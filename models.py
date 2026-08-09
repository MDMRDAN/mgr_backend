from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# The one and only email allowed to hold the "developer" role.
# Enforced in code (see app.py) wherever an AdminUser is created or promoted —
# never trust a role field alone for something this sensitive.
DEVELOPER_EMAIL = "mdmasterdan@gmail.com"
MAX_ADMINS = 10  # not counting the developer account


class AdminUser(db.Model):
    __tablename__ = "admin_users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120))
    role = db.Column(db.String(20), default="admin")  # "developer" | "admin"
    # Free-text note on how this admin's employment was confirmed
    # (e.g. "Verified by phone call, 2026-08-10" or "Verified by email thread")
    verified_note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "verified_note": self.verified_note,
            "created_at": self.created_at.isoformat(),
        }


class Setting(db.Model):
    """Simple key/value store for admin-configurable platform settings —
    Google Sheet link, sister-site URLs, notification email, etc.
    Never exposed on the public frontend, admin-only."""
    __tablename__ = "settings"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Post(db.Model):
    """A community post — image, meme, short video, or text — from a
    verified school, teacher, student, or supporter. Grouped by pillar."""
    __tablename__ = "posts"
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey("registrations.id"), nullable=False)
    pillar = db.Column(db.String(60))
    post_type = db.Column(db.String(20), default="text")  # text | image | meme | video
    caption = db.Column(db.Text)
    media_url = db.Column(db.String(500))  # populated once real file storage exists
    likes_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="pending")  # pending | approved | rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "registration_id": self.registration_id,
            "pillar": self.pillar,
            "post_type": self.post_type,
            "caption": self.caption,
            "media_url": self.media_url,
            "likes_count": self.likes_count,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


class PostLike(db.Model):
    """One row per (post, registration) like — prevents double-liking."""
    __tablename__ = "post_likes"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    registration_id = db.Column(db.Integer, db.ForeignKey("registrations.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("post_id", "registration_id", name="uq_post_liker"),)


class HomepageContent(db.Model):
    """Images/results the developer or an admin uploads to feature on the
    public homepage billboard."""
    __tablename__ = "homepage_content"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180))
    media_url = db.Column(db.String(500))
    link_url = db.Column(db.String(500))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "media_url": self.media_url,
            "link_url": self.link_url,
            "active": self.active,
            "created_at": self.created_at.isoformat(),
        }


class Registration(db.Model):
    __tablename__ = "registrations"
    id = db.Column(db.Integer, primary_key=True)
    reg_type = db.Column(db.String(20), nullable=False)  # school | teacher | student | supporter
    name = db.Column(db.String(180), nullable=False)
    organization = db.Column(db.String(180))
    email = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending")  # pending | verified | rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.reg_type,
            "name": self.name,
            "organization": self.organization,
            "email": self.email,
            "phone": self.phone,
            "message": self.message,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


class Pledge(db.Model):
    __tablename__ = "pledges"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180))
    email = db.Column(db.String(180))
    amount = db.Column(db.Float, nullable=False)  # minimum enforced at API level: 1
    currency = db.Column(db.String(10), default="USD")
    pillar = db.Column(db.String(60))
    method = db.Column(db.String(20))  # flutterwave | coinbase
    status = db.Column(db.String(20), default="pending")  # pending | paid | failed
    reference = db.Column(db.String(120), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "amount": self.amount,
            "currency": self.currency,
            "pillar": self.pillar,
            "method": self.method,
            "status": self.status,
            "reference": self.reference,
            "created_at": self.created_at.isoformat(),
        }


class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    pillar = db.Column(db.String(60), nullable=False)
    name = db.Column(db.String(120))
    body = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "pillar": self.pillar,
            "name": self.name or "Anonymous",
            "body": self.body,
            "created_at": self.created_at.isoformat(),
        }


class Record(db.Model):
    """A logged achievement / record entry shown on the admin dashboard."""
    __tablename__ = "records"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    record_type = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending | verified
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "type": self.record_type,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }
