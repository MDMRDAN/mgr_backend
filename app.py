import os
from functools import wraps

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, request, jsonify, session
from flask_cors import CORS

from models import (
    db, AdminUser, Registration, Pledge, Comment, Record,
    Setting, Post, PostLike, HomepageContent,
    DEVELOPER_EMAIL, MAX_ADMINS,
)
from payments import (
    flutterwave_initiate, flutterwave_verify, flutterwave_verify_webhook_signature,
    coinbase_create_charge, coinbase_verify_webhook_signature,
    PaymentError, MIN_DONATION_USD,
)
import notify
import sheets
from storage import upload_file, StorageError, ALLOWED_TYPES as UPLOAD_ALLOWED_TYPES


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///mgr.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SESSION_COOKIE_SAMESITE"] = "None"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"

    frontend_url = os.environ.get("FRONTEND_URL", "*")
    CORS(app, supports_credentials=True, origins=[frontend_url] if frontend_url != "*" else "*")

    db.init_app(app)

    # fail loud, not silent — missing payment keys should be obvious at
    # startup, not discovered when a real donor's payment breaks
    if app.config["SECRET_KEY"] == "dev-change-me" and os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("SECRET_KEY is still the dev default — set a real one in production")
    for key in ("FLUTTERWAVE_SECRET_KEY", "COINBASE_COMMERCE_API_KEY"):
        if not os.environ.get(key):
            print(f"[startup warning] {key} is not set — that payment method will return errors until it is.")
    if not os.environ.get("SMTP_HOST"):
        print("[startup warning] SMTP not configured — activity notifications will only log to console.")

    # ---------------------------------------------------------------
    # helpers
    # ---------------------------------------------------------------
    def admin_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("admin_id"):
                return jsonify({"error": "unauthorized"}), 401
            return fn(*a, **kw)
        return wrapper

    def developer_required(fn):
        """Only the single developer account (mdmasterdan@gmail.com) may pass."""
        @wraps(fn)
        def wrapper(*a, **kw):
            if session.get("admin_role") != "developer":
                return jsonify({"error": "developer access only"}), 403
            return fn(*a, **kw)
        return wrapper

    # ---------------------------------------------------------------
    # health
    # ---------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "mgr-backend"}

    # ---------------------------------------------------------------
    # file uploads (photos, logos, memes, short videos) — real storage
    # via Cloudinary, used by registration forms, posts, sponsor logos,
    # and homepage content
    # ---------------------------------------------------------------
    @app.post("/api/upload")
    def upload():
        if "file" not in request.files:
            return jsonify({"error": "no file provided (expected multipart field 'file')"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "empty filename"}), 400
        try:
            url = upload_file(f)
        except StorageError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True, "url": url})

    # ---------------------------------------------------------------
    # registrations (school / teacher / student / supporter)
    # ---------------------------------------------------------------
    @app.post("/api/register")
    def register():
        data = request.get_json(force=True, silent=True) or {}
        required = ["type", "name", "email", "phone"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400
        if data["type"] not in ("school", "teacher", "student", "supporter"):
            return jsonify({"error": "invalid type"}), 400

        r = Registration(
            reg_type=data["type"],
            name=data["name"],
            organization=data.get("organization"),
            email=data["email"],
            phone=data["phone"],
            message=data.get("message"),
        )
        db.session.add(r)
        db.session.commit()
        notify.notify_new_registration(r)
        sheets.safe_sync(sheets.sync_registration, r)
        return jsonify({"ok": True, "registration": r.to_dict()}), 201

    # ---------------------------------------------------------------
    # comments / advice per pillar — grouped and displayed under each
    # pillar's own comment thread on the frontend
    # ---------------------------------------------------------------
    @app.post("/api/comment")
    def add_comment():
        data = request.get_json(force=True, silent=True) or {}
        if not data.get("pillar") or not data.get("body"):
            return jsonify({"error": "pillar and body are required"}), 400
        c = Comment(pillar=data["pillar"], name=data.get("name"), body=data["body"])
        db.session.add(c)
        db.session.commit()
        notify.notify_new_comment(c)
        return jsonify({"ok": True, "comment": c.to_dict()}), 201

    @app.get("/api/comments/<pillar>")
    def list_comments(pillar):
        rows = (
            Comment.query.filter_by(pillar=pillar, approved=True)
            .order_by(Comment.created_at.desc())
            .limit(100)
            .all()
        )
        return jsonify([c.to_dict() for c in rows])

    # ---------------------------------------------------------------
    # donations — Flutterwave (cards / bank / mobile money)
    # ---------------------------------------------------------------
    @app.post("/api/pledge/flutterwave/initiate")
    def flw_initiate():
        data = request.get_json(force=True, silent=True) or {}
        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid amount"}), 400
        if amount < MIN_DONATION_USD:
            return jsonify({"error": f"minimum donation is ${MIN_DONATION_USD}"}), 400

        redirect_url = data.get("redirect_url") or os.environ.get("FRONTEND_URL", "") + "/thank-you"
        try:
            tx_ref, link = flutterwave_initiate(
                amount=amount,
                email=data.get("email", ""),
                name=data.get("name", ""),
                redirect_url=redirect_url,
                currency=data.get("currency", "USD"),
                pillar=data.get("pillar"),
            )
        except PaymentError as e:
            return jsonify({"error": str(e)}), 400

        p = Pledge(
            name=data.get("name"), email=data.get("email"), amount=amount,
            currency=data.get("currency", "USD"), pillar=data.get("pillar"),
            method="flutterwave", status="pending", reference=tx_ref,
        )
        db.session.add(p)
        db.session.commit()
        notify.notify_new_pledge(p)
        sheets.safe_sync(sheets.sync_pledge, p)
        return jsonify({"ok": True, "reference": tx_ref, "payment_link": link})

    @app.post("/api/pledge/flutterwave/webhook")
    def flw_webhook():
        expected_hash = os.environ.get("FLUTTERWAVE_WEBHOOK_HASH", "")
        if not flutterwave_verify_webhook_signature(request.headers, expected_hash):
            return jsonify({"error": "invalid signature"}), 401

        payload = request.get_json(force=True, silent=True) or {}
        tx_data = payload.get("data", {})
        tx_ref = tx_data.get("tx_ref")
        transaction_id = tx_data.get("id")
        if not tx_ref or not transaction_id:
            return jsonify({"error": "malformed payload"}), 400

        try:
            verified = flutterwave_verify(transaction_id)
        except PaymentError as e:
            return jsonify({"error": str(e)}), 400

        pledge = Pledge.query.filter_by(reference=tx_ref).first()
        # idempotent: Flutterwave may retry webhook delivery — only act, and
        # only notify, the first time this pledge actually flips to paid
        if pledge and pledge.status != "paid" and verified.get("status") == "successful":
            pledge.status = "paid"
            db.session.commit()
            notify.notify_pledge_paid(pledge)
        return jsonify({"ok": True})

    # ---------------------------------------------------------------
    # donations — Coinbase Commerce (crypto)
    # ---------------------------------------------------------------
    @app.post("/api/pledge/coinbase/charge")
    def cb_charge():
        data = request.get_json(force=True, silent=True) or {}
        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid amount"}), 400
        if amount < MIN_DONATION_USD:
            return jsonify({"error": f"minimum donation is ${MIN_DONATION_USD}"}), 400

        try:
            reference, hosted_url, code = coinbase_create_charge(
                amount=amount, name=data.get("name"), email=data.get("email"),
                pillar=data.get("pillar"),
            )
        except PaymentError as e:
            return jsonify({"error": str(e)}), 400

        p = Pledge(
            name=data.get("name"), email=data.get("email"), amount=amount,
            currency="USD", pillar=data.get("pillar"),
            method="coinbase", status="pending", reference=reference,
        )
        db.session.add(p)
        db.session.commit()
        notify.notify_new_pledge(p)
        sheets.safe_sync(sheets.sync_pledge, p)
        return jsonify({"ok": True, "reference": reference, "checkout_url": hosted_url, "charge_code": code})

    @app.post("/api/pledge/coinbase/webhook")
    def cb_webhook():
        signature = request.headers.get("X-CC-Webhook-Signature", "")
        raw_body = request.get_data()
        if not coinbase_verify_webhook_signature(raw_body, signature):
            return jsonify({"error": "invalid signature"}), 401

        payload = request.get_json(force=True, silent=True) or {}
        event = payload.get("event", {})
        event_type = event.get("type", "")
        metadata = event.get("data", {}).get("metadata", {})
        reference = metadata.get("reference")

        if reference and event_type == "charge:confirmed":
            pledge = Pledge.query.filter_by(reference=reference).first()
            # idempotent: Coinbase retries webhooks — only notify on first flip
            if pledge and pledge.status != "paid":
                pledge.status = "paid"
                db.session.commit()
                notify.notify_pledge_paid(pledge)
        elif reference and event_type in ("charge:failed", "charge:delayed"):
            pledge = Pledge.query.filter_by(reference=reference).first()
            if pledge and pledge.status == "pending":
                pledge.status = "failed"
                db.session.commit()

        return jsonify({"ok": True})

    # ---------------------------------------------------------------
    # admin auth
    # ---------------------------------------------------------------
    @app.post("/api/admin/login")
    def admin_login():
        data = request.get_json(force=True, silent=True) or {}
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        user = AdminUser.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            return jsonify({"error": "invalid credentials"}), 401
        session["admin_id"] = user.id
        session["admin_role"] = user.role
        return jsonify({"ok": True, "name": user.name, "email": user.email, "role": user.role})

    @app.post("/api/admin/logout")
    def admin_logout():
        session.pop("admin_id", None)
        session.pop("admin_role", None)
        return jsonify({"ok": True})

    @app.get("/api/admin/me")
    def admin_me():
        if not session.get("admin_id"):
            return jsonify({"authenticated": False})
        user = AdminUser.query.get(session["admin_id"])
        return jsonify({"authenticated": True, "email": user.email, "name": user.name, "role": user.role})

    # ---------------------------------------------------------------
    # admin management — developer-only. Enforces:
    #   - the "developer" role can only ever belong to DEVELOPER_EMAIL
    #   - at most MAX_ADMINS (10) admin accounts exist at once
    # ---------------------------------------------------------------
    @app.get("/api/admin/admins")
    @developer_required
    def list_admins():
        rows = AdminUser.query.order_by(AdminUser.created_at.asc()).all()
        return jsonify([u.to_dict() for u in rows])

    @app.post("/api/admin/admins")
    @developer_required
    def create_admin_account():
        data = request.get_json(force=True, silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        name = (data.get("name") or "").strip()
        password = data.get("password") or ""
        verified_note = (data.get("verified_note") or "").strip()

        if not email or not name or not password:
            return jsonify({"error": "email, name and password are required"}), 400
        if email == DEVELOPER_EMAIL:
            return jsonify({"error": "that email is reserved for the developer account"}), 400
        if AdminUser.query.filter_by(email=email).first():
            return jsonify({"error": "an account with that email already exists"}), 400
        if not verified_note:
            return jsonify({"error": "verified_note is required — log how you confirmed this person's employment"}), 400

        current_admin_count = AdminUser.query.filter_by(role="admin").count()
        if current_admin_count >= MAX_ADMINS:
            return jsonify({"error": f"maximum of {MAX_ADMINS} admin accounts reached"}), 400

        user = AdminUser(email=email, name=name, role="admin", verified_note=verified_note)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        notify.notify_new_admin(user, added_by_email=DEVELOPER_EMAIL)
        return jsonify({"ok": True, "admin": user.to_dict()}), 201

    @app.post("/api/admin/admins/<int:admin_id>/revoke")
    @developer_required
    def revoke_admin(admin_id):
        user = AdminUser.query.get_or_404(admin_id)
        if user.role == "developer":
            return jsonify({"error": "cannot revoke the developer account"}), 400
        db.session.delete(user)
        db.session.commit()
        return jsonify({"ok": True})

    # ---------------------------------------------------------------
    # platform settings — Google Sheet link, sister-site URLs, etc.
    # admin-only, never exposed on the public frontend
    # ---------------------------------------------------------------
    SETTING_KEYS = {
        "google_sheet_url", "mea_site_url", "msa_site_url", "mta_site_url",
        "notify_email",
    }

    @app.get("/api/admin/settings")
    @admin_required
    def get_settings():
        rows = Setting.query.all()
        result = {k: None for k in SETTING_KEYS}
        for row in rows:
            if row.key in SETTING_KEYS:
                result[row.key] = row.value
        return jsonify(result)

    @app.post("/api/admin/settings")
    @admin_required
    def update_settings():
        data = request.get_json(force=True, silent=True) or {}
        updated = {}
        for key, value in data.items():
            if key not in SETTING_KEYS:
                continue
            row = Setting.query.get(key)
            if row is None:
                row = Setting(key=key, value=value)
                db.session.add(row)
            else:
                row.value = value
            updated[key] = value
        db.session.commit()
        return jsonify({"ok": True, "updated": updated})

    # ---------------------------------------------------------------
    # homepage content (billboard) — developer/admin uploads,
    # publicly readable so the frontend billboard can display it
    # ---------------------------------------------------------------
    @app.get("/api/homepage-content")
    def public_homepage_content():
        rows = (
            HomepageContent.query.filter_by(active=True)
            .order_by(HomepageContent.created_at.desc())
            .limit(30)
            .all()
        )
        return jsonify([r.to_dict() for r in rows])

    @app.post("/api/admin/homepage-content")
    @admin_required
    def add_homepage_content():
        data = request.get_json(force=True, silent=True) or {}
        if not data.get("media_url"):
            return jsonify({"error": "media_url is required"}), 400
        item = HomepageContent(
            title=data.get("title"), media_url=data["media_url"], link_url=data.get("link_url"),
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({"ok": True, "item": item.to_dict()}), 201

    @app.post("/api/admin/homepage-content/<int:item_id>/toggle")
    @admin_required
    def toggle_homepage_content(item_id):
        item = HomepageContent.query.get_or_404(item_id)
        item.active = not item.active
        db.session.commit()
        return jsonify({"ok": True, "item": item.to_dict()})

    # ---------------------------------------------------------------
    # community posts — verified schools/teachers/students/supporters
    # can post images, memes, short videos, and comments; anyone can like
    # ---------------------------------------------------------------
    @app.post("/api/posts")
    def create_post():
        data = request.get_json(force=True, silent=True) or {}
        reg_id = data.get("registration_id")
        reg = Registration.query.get(reg_id) if reg_id else None
        if not reg:
            return jsonify({"error": "registration_id not found"}), 400
        if reg.status != "verified":
            return jsonify({"error": "only verified registrations can post"}), 403

        post = Post(
            registration_id=reg.id,
            pillar=data.get("pillar"),
            post_type=data.get("post_type", "text"),
            caption=data.get("caption"),
            media_url=data.get("media_url"),
        )
        db.session.add(post)
        db.session.commit()
        return jsonify({"ok": True, "post": post.to_dict()}), 201

    @app.get("/api/posts/<pillar>")
    def list_posts(pillar):
        rows = (
            Post.query.filter_by(pillar=pillar, status="approved")
            .order_by(Post.created_at.desc())
            .limit(100)
            .all()
        )
        return jsonify([p.to_dict() for p in rows])

    @app.post("/api/posts/<int:post_id>/like")
    def like_post(post_id):
        data = request.get_json(force=True, silent=True) or {}
        reg_id = data.get("registration_id")
        reg = Registration.query.get(reg_id) if reg_id else None
        if not reg or reg.status != "verified":
            return jsonify({"error": "only verified registrations can like posts"}), 403

        post = Post.query.get_or_404(post_id)
        existing = PostLike.query.filter_by(post_id=post_id, registration_id=reg_id).first()
        if existing:
            return jsonify({"error": "already liked"}), 400

        db.session.add(PostLike(post_id=post_id, registration_id=reg_id))
        post.likes_count = (post.likes_count or 0) + 1
        db.session.commit()
        return jsonify({"ok": True, "likes_count": post.likes_count})

    @app.post("/api/admin/posts/<int:post_id>/moderate")
    @admin_required
    def moderate_post(post_id):
        data = request.get_json(force=True, silent=True) or {}
        status = data.get("status")
        if status not in ("pending", "approved", "rejected"):
            return jsonify({"error": "invalid status"}), 400
        post = Post.query.get_or_404(post_id)
        post.status = status
        db.session.commit()
        return jsonify({"ok": True, "post": post.to_dict()})

    # ---------------------------------------------------------------
    # admin dashboard data
    # ---------------------------------------------------------------
    @app.get("/api/admin/stats")
    @admin_required
    def admin_stats():
        return jsonify({
            "total_registrations": Registration.query.count(),
            "pledges_raised": db.session.query(db.func.coalesce(db.func.sum(Pledge.amount), 0))
                .filter(Pledge.status == "paid").scalar(),
            "records_logged": Record.query.count(),
            "pending_registrations": Registration.query.filter_by(status="pending").count(),
        })

    @app.get("/api/admin/registrations")
    @admin_required
    def admin_registrations():
        rows = Registration.query.order_by(Registration.created_at.desc()).limit(200).all()
        return jsonify([r.to_dict() for r in rows])

    @app.post("/api/admin/registrations/<int:reg_id>/status")
    @admin_required
    def admin_update_registration(reg_id):
        data = request.get_json(force=True, silent=True) or {}
        status = data.get("status")
        if status not in ("pending", "verified", "rejected"):
            return jsonify({"error": "invalid status"}), 400
        reg = Registration.query.get_or_404(reg_id)
        reg.status = status
        db.session.commit()
        return jsonify({"ok": True, "registration": reg.to_dict()})

    @app.get("/api/admin/pledges")
    @admin_required
    def admin_pledges():
        rows = Pledge.query.order_by(Pledge.created_at.desc()).limit(200).all()
        return jsonify([p.to_dict() for p in rows])

    @app.get("/api/admin/records")
    @admin_required
    def admin_list_records():
        rows = Record.query.order_by(Record.created_at.desc()).limit(200).all()
        return jsonify([r.to_dict() for r in rows])

    @app.post("/api/admin/records")
    @admin_required
    def admin_add_record():
        data = request.get_json(force=True, silent=True) or {}
        required = ["name", "category", "type"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400
        rec = Record(name=data["name"], category=data["category"], record_type=data["type"])
        db.session.add(rec)
        db.session.commit()
        return jsonify({"ok": True, "record": rec.to_dict()}), 201

    # ---------------------------------------------------------------
    # CLI commands
    # ---------------------------------------------------------------
    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        print("Database tables created.")

    @app.cli.command("create-admin")
    def create_admin():
        """Create the developer account or an admin account.
        Only DEVELOPER_EMAIL (mdmasterdan@gmail.com) can ever get role='developer' —
        this is enforced here, not just in the API, so it holds even for
        whoever has server/CLI access.
        """
        import getpass
        email = input("Email: ").strip().lower()
        name = input("Name: ").strip()
        password = getpass.getpass("Password: ")

        if AdminUser.query.filter_by(email=email).first():
            print("An account with that email already exists.")
            return

        if email == DEVELOPER_EMAIL:
            if AdminUser.query.filter_by(role="developer").first():
                print("A developer account already exists. Only one is allowed.")
                return
            role = "developer"
            verified_note = "Developer — platform founder"
        else:
            current_admin_count = AdminUser.query.filter_by(role="admin").count()
            if current_admin_count >= MAX_ADMINS:
                print(f"Maximum of {MAX_ADMINS} admin accounts already reached.")
                return
            role = "admin"
            verified_note = input("How was this person's employment verified? (required): ").strip()
            if not verified_note:
                print("A verification note is required for admin accounts.")
                return

        user = AdminUser(email=email, name=name, role=role, verified_note=verified_note)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"{role.capitalize()} account created for {email}.")

    return app


app = create_app()
@app.route('/setup-db-init')
def setup_db_init():
    try:
        db.create_all()
        return "Database initialized successfully!", 200
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/setup-admin-create')
def setup_admin_create():
    try:
        email = "mdmasterdan@gmail.com"
        if AdminUser.query.filter_by(email=email).first():
            return "Admin account already exists!", 200
        
        user = AdminUser(
            email=email,
            name="Developer Admin",
            role="developer",
            verified_note="Developer - platform founder"
        )
        # Set your default initial password here
        user.set_password("ChangeMe123!")
        
        db.session.add(user)
        db.session.commit()
        return f"Admin account created for {email}!", 200
    except Exception as e:
        return f"Error: {str(e)}", 500
        
if __name__ == "__main__":
    app.run(debug=True, port=5000)
