"""
Sends the developer (mdmasterdan@gmail.com) an email whenever something
happens on the platform: new registration, new pledge, new comment, new
admin added, etc.

Uses plain SMTP so it works with Gmail, Outlook, or any provider — set the
SMTP_* variables in .env. If they aren't set, notifications are silently
skipped (logged to console) rather than crashing the request that triggered
them; a notification failure should never block a user's registration.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "mdmasterdan@gmail.com")


def notify(subject: str, body: str):
    """Fire-and-forget email notification. Never raises — logs and returns."""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD):
        print(f"[notify skipped — no SMTP configured] {subject}\n{body}\n")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[MGR] {subject}"
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        # Never let a notification failure break the actual request.
        print(f"[notify FAILED] {subject}: {e}")


# ---- convenience wrappers for each event type ----

def notify_new_registration(reg):
    notify(
        f"New {reg.reg_type} registration — {reg.name}",
        f"Type: {reg.reg_type}\nName: {reg.name}\nOrganization: {reg.organization or '-'}\n"
        f"Email: {reg.email}\nPhone: {reg.phone}\nSubmitted: {reg.created_at}\n",
    )


def notify_new_pledge(pledge):
    notify(
        f"New pledge — ${pledge.amount} via {pledge.method}",
        f"Name: {pledge.name or 'Anonymous'}\nEmail: {pledge.email or '-'}\n"
        f"Amount: {pledge.amount} {pledge.currency}\nPillar: {pledge.pillar or '-'}\n"
        f"Method: {pledge.method}\nReference: {pledge.reference}\nStatus: {pledge.status}\n",
    )


def notify_pledge_paid(pledge):
    notify(
        f"Pledge CONFIRMED PAID — ${pledge.amount}",
        f"Reference {pledge.reference} from {pledge.name or 'Anonymous'} ({pledge.email or '-'}) "
        f"just cleared via {pledge.method}.\n",
    )


def notify_new_comment(comment):
    notify(
        f"New comment on {comment.pillar}",
        f"From: {comment.name or 'Anonymous'}\nPillar: {comment.pillar}\n\n{comment.body}\n",
    )


def notify_new_admin(admin_user, added_by_email):
    notify(
        f"New admin account created — {admin_user.email}",
        f"Email: {admin_user.email}\nName: {admin_user.name}\nRole: {admin_user.role}\n"
        f"Created by: {added_by_email}\nVerification note: {admin_user.verified_note or '(none logged)'}\n",
    )
