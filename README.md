# Multiverse Global Records — Backend

Flask + SQLite backend for registrations, donations (Flutterwave + Coinbase
Commerce), comments, community posts, admin/developer access, and email
notifications.

## Deploying (Render.com — free tier, works well with Flask)

1. Push this `mgr_backend` folder to its own GitHub repo (same phone workflow
   you just used for the frontend — new repo, upload files, commit).
2. Go to **render.com**, sign up, connect your GitHub account.
3. **New +** → **Web Service** → pick that repo.
4. Render auto-detects Python. Set:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `gunicorn app:app`
5. Under **Environment**, add every variable from `.env.example` with your
   real values (Flutterwave keys, Coinbase keys, SMTP, Cloudinary, etc.) —
   whatever you don't have yet, leave out; that feature just logs a warning
   instead of crashing.
6. **Important**: Render's free tier wipes the filesystem on every redeploy,
   which means a SQLite file (`mgr.db`) gets erased each time you push an
   update. For anything beyond a first test, add a free **Render Postgres**
   database instead (Render's dashboard → New + → PostgreSQL), then set
   `DATABASE_URL` to the connection string Render gives you. SQLite is fine
   only for the very first "does this work at all" test.
7. Deploy. Render gives you a live URL like `https://mgr-backend.onrender.com`.
8. Open the **Shell** tab on your Render service and run:
   ```
   flask --app app init-db
   flask --app app create-admin
   ```
   (enter `mdmasterdan@gmail.com` when it asks for the developer email)

Once you have that live URL, send it back and the frontend's registration,
donation, and login forms get pointed at it instead of just simulating
everything in the browser.

## Local setup (for testing before you deploy)

```bash
cd mgr_backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then fill in your real keys
flask --app app init-db         # creates the SQLite tables
flask --app app create-admin    # create your developer account (see below)
flask --app app run             # starts on http://localhost:5000
```

## Access control — read this before creating any accounts

There are two roles:

- **Developer** — exactly one account, permanently locked to
  `mdmasterdan@gmail.com`. This is enforced in code (`models.DEVELOPER_EMAIL`),
  not just convention — the CLI and the API both refuse to let any other
  email hold this role, and refuse to create a second developer account.
  The developer can see and manage everything, both frontend and backend:
  registrations, pledges, comments, admin accounts, platform settings,
  homepage content.

- **Admin** — up to 10 accounts (`models.MAX_ADMINS`), each created *by the
  developer only* (`POST /api/admin/admins`, or `flask create-admin` on the
  server). Every admin account requires a `verified_note` — a short record
  of how you confirmed that person actually works for you (e.g. "Verified
  by phone call, 2026-08-10"). This is stored, not enforced by the software
  itself — the software just refuses to create the account without one.

When you run `flask create-admin` the first time, enter
`mdmasterdan@gmail.com` to create the developer account. Every time after
that, entering a different email creates a regular admin (and will ask for
the verification note).

## Google Sheet / sister-site links

`GET/POST /api/admin/settings` stores free-text values for:
- `google_sheet_url`
- `mea_site_url`, `msa_site_url`, `mta_site_url`
- `notify_email`

These are admin-only and never exposed on the public frontend. Note this
does **not** sync data into the sheet automatically — it just stores the
link. Live two-way sync with Google Sheets requires a Google Cloud service
account and the Sheets API, which needs your own Google credentials to set
up; ask if you want that built once you're ready to create the credentials.

## Community posts

Schools, teachers, students, and supporters can post (image/meme/video/text)
and like posts **only once their registration status is `verified`**
(`POST /api/admin/registrations/<id>/status` with `{"status":"verified"}`
sets that). Posts start `pending` and need `POST
/api/admin/posts/<id>/moderate` before they're publicly visible.

Note: this backend stores a `media_url` string for posts and homepage
content — it does not yet handle the actual file upload/storage. You'll
need a place to host the files themselves (e.g. an S3 bucket or Cloudinary)
before real image/video uploads can work end-to-end; ask if you want that
wired in.

## Email notifications

Set `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` in `.env` and every new
registration, pledge, comment, and admin account triggers an email to
`NOTIFY_EMAIL` (defaults to mdmasterdan@gmail.com). If SMTP isn't
configured, notifications are just logged to the console instead of
sending — nothing breaks.

## Connecting the frontend

The `index.html` site is currently a self-contained static file and does
**not** call any of these endpoints yet — it simulates registration/payment
forms client-side. Once this backend is deployed somewhere with a real URL,
the frontend's `fetch()` calls need to be pointed at it. That's the next
concrete step once you're ready to host this.
