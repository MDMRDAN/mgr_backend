"""
Live sync of registrations and pledges into a real Google Sheet.

Setup (one-time, on your end — this needs your own Google Cloud project):
  1. Go to https://console.cloud.google.com -> create a project (free)
  2. Enable the "Google Sheets API" for that project
  3. Create a Service Account -> generate a JSON key -> download it
  4. Save that file as `service_account.json` in this backend folder
     (already in .gitignore-equivalent — never commit this file)
  5. Open your Google Sheet, click Share, and share it with the service
     account's email address (looks like xxx@xxx.iam.gserviceaccount.com —
     found inside the JSON file), giving it Editor access
  6. Set GOOGLE_SHEET_ID in .env (the long ID in the sheet's URL, between
     /d/ and /edit)
  7. pip install gspread google-auth (already in requirements.txt)

Without steps 1-6 done, every function here raises SheetsError with a clear
message rather than crashing — registrations/pledges still save to the
database either way, the sheet is a mirror, not the source of truth.
"""
import os

SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

_client = None
_sheet = None


class SheetsError(Exception):
    pass


def _get_sheet():
    global _client, _sheet
    if _sheet is not None:
        return _sheet

    if not SHEET_ID:
        raise SheetsError("GOOGLE_SHEET_ID is not set in .env")
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise SheetsError(
            f"{SERVICE_ACCOUNT_FILE} not found — follow the setup steps at the top of sheets.py"
        )

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise SheetsError("gspread / google-auth not installed — run: pip install gspread google-auth")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
        _client = gspread.authorize(creds)
        _sheet = _client.open_by_key(SHEET_ID)
    except Exception as e:
        raise SheetsError(f"Could not connect to Google Sheets: {e}")

    return _sheet


def _get_or_create_worksheet(sheet, title, header_row):
    try:
        ws = sheet.worksheet(title)
    except Exception:
        ws = sheet.add_worksheet(title=title, rows=1000, cols=len(header_row))
        ws.append_row(header_row)
    return ws


def sync_registration(registration):
    """Appends one row to the 'Registrations' tab. Safe to call repeatedly —
    each registration is only ever appended once by the caller (see app.py)."""
    sheet = _get_sheet()
    ws = _get_or_create_worksheet(
        sheet, "Registrations",
        ["ID", "Type", "Name", "Organization", "Email", "Phone", "Status", "Created At"],
    )
    ws.append_row([
        registration.id, registration.reg_type, registration.name,
        registration.organization or "", registration.email, registration.phone,
        registration.status, registration.created_at.isoformat(),
    ])


def sync_pledge(pledge):
    """Appends one row to the 'Pledges' tab."""
    sheet = _get_sheet()
    ws = _get_or_create_worksheet(
        sheet, "Pledges",
        ["ID", "Name", "Email", "Amount", "Currency", "Pillar", "Method", "Status", "Reference", "Created At"],
    )
    ws.append_row([
        pledge.id, pledge.name or "", pledge.email or "", pledge.amount, pledge.currency,
        pledge.pillar or "", pledge.method, pledge.status, pledge.reference,
        pledge.created_at.isoformat(),
    ])


def safe_sync(fn, *args, **kwargs):
    """Wraps a sync_* call so a Sheets outage never breaks the actual
    request that triggered it — logs and moves on, same philosophy as
    notify.py."""
    try:
        fn(*args, **kwargs)
    except SheetsError as e:
        print(f"[sheets sync skipped] {e}")
    except Exception as e:
        print(f"[sheets sync FAILED] {e}")
