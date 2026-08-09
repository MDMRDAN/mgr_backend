"""
Payment provider integrations.

Flutterwave  -> global + Nigeria/Ghana card, bank transfer, mobile money
Coinbase Commerce -> BTC / ETH / USDT crypto donations

Both are called with plain `requests` calls against their REST APIs.
Docs:
  Flutterwave: https://developer.flutterwave.com/docs
  Coinbase Commerce: https://commerce.coinbase.com/docs/api/
"""
import hashlib
import hmac
import os
import uuid

import requests

FLW_SECRET_KEY = os.environ.get("FLUTTERWAVE_SECRET_KEY", "")
FLW_BASE_URL = "https://api.flutterwave.com/v3"

CB_API_KEY = os.environ.get("COINBASE_COMMERCE_API_KEY", "")
CB_WEBHOOK_SECRET = os.environ.get("COINBASE_COMMERCE_WEBHOOK_SECRET", "")
CB_BASE_URL = "https://api.commerce.coinbase.com"

MIN_DONATION_USD = 1  # enforced here so it can never be bypassed by the frontend
SUPPORTED_CURRENCIES = {"USD", "NGN", "GHS"}


class PaymentError(Exception):
    pass


def new_reference(prefix="mgr"):
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _post_json(url, **kwargs):
    """requests.post wrapper that turns network/HTTP failures into PaymentError
    instead of letting an unhandled exception or a JSONDecodeError crash the
    request — a payment provider being briefly down should return a clean
    error to the user, not a 500."""
    try:
        resp = requests.post(url, **kwargs)
    except requests.exceptions.RequestException as e:
        raise PaymentError(f"Could not reach payment provider: {e}")
    try:
        data = resp.json()
    except ValueError:
        raise PaymentError(f"Payment provider returned an unexpected response (HTTP {resp.status_code})")
    if resp.status_code >= 500:
        raise PaymentError("Payment provider is currently unavailable — please try again shortly")
    return resp, data


def _get_json(url, **kwargs):
    try:
        resp = requests.get(url, **kwargs)
    except requests.exceptions.RequestException as e:
        raise PaymentError(f"Could not reach payment provider: {e}")
    try:
        data = resp.json()
    except ValueError:
        raise PaymentError(f"Payment provider returned an unexpected response (HTTP {resp.status_code})")
    return resp, data


# ---------------- Flutterwave ----------------

def flutterwave_initiate(amount, email, name, redirect_url, currency="USD", pillar=None):
    """Create a Flutterwave standard payment link. Returns (reference, payment_link)."""
    if amount < MIN_DONATION_USD:
        raise PaymentError(f"Minimum donation is ${MIN_DONATION_USD}")
    if not FLW_SECRET_KEY:
        raise PaymentError("FLUTTERWAVE_SECRET_KEY is not configured on the server")
    currency = (currency or "USD").upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise PaymentError(f"Unsupported currency: {currency}")

    tx_ref = new_reference("flw")
    payload = {
        "tx_ref": tx_ref,
        "amount": str(amount),
        "currency": currency,
        "redirect_url": redirect_url,
        "customer": {"email": email, "name": name},
        "customizations": {
            "title": "Multiverse Global Records",
            "description": f"Support for {pillar or 'MGR'}",
        },
        "meta": {"pillar": pillar or ""},
    }
    resp, data = _post_json(
        f"{FLW_BASE_URL}/payments",
        json=payload,
        headers={"Authorization": f"Bearer {FLW_SECRET_KEY}"},
        timeout=15,
    )
    if data.get("status") != "success":
        raise PaymentError(data.get("message", "Flutterwave initiation failed"))
    return tx_ref, data["data"]["link"]


def flutterwave_verify(transaction_id):
    """Verify a completed transaction by Flutterwave's transaction id.
    Always re-check with Flutterwave directly here — never trust amount/status
    from a webhook body alone, since that's spoofable without this step."""
    resp, data = _get_json(
        f"{FLW_BASE_URL}/transactions/{transaction_id}/verify",
        headers={"Authorization": f"Bearer {FLW_SECRET_KEY}"},
        timeout=15,
    )
    if data.get("status") != "success":
        raise PaymentError("Could not verify transaction")
    return data["data"]  # includes status, amount, currency, tx_ref, customer


def flutterwave_verify_webhook_signature(request_headers, expected_hash):
    """Flutterwave sends the hash you configured in the dashboard back in 'verif-hash'."""
    sig = request_headers.get("verif-hash", "")
    return sig and expected_hash and hmac.compare_digest(sig, expected_hash)


# ---------------- Coinbase Commerce ----------------

def coinbase_create_charge(amount, name, email, pillar=None):
    if amount < MIN_DONATION_USD:
        raise PaymentError(f"Minimum donation is ${MIN_DONATION_USD}")
    if not CB_API_KEY:
        raise PaymentError("COINBASE_COMMERCE_API_KEY is not configured on the server")

    reference = new_reference("cb")
    payload = {
        "name": f"MGR Support — {pillar or 'General'}",
        "description": f"Donation from {name or 'a supporter'}",
        "pricing_type": "fixed_price",
        "local_price": {"amount": str(amount), "currency": "USD"},
        "metadata": {"reference": reference, "email": email or "", "pillar": pillar or ""},
    }
    resp, data = _post_json(
        f"{CB_BASE_URL}/charges",
        json=payload,
        headers={
            "X-CC-Api-Key": CB_API_KEY,
            "X-CC-Version": "2018-03-22",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    if "data" not in data:
        raise PaymentError(data.get("error", {}).get("message", "Coinbase charge creation failed"))
    return reference, data["data"]["hosted_url"], data["data"]["code"]


def coinbase_verify_webhook_signature(raw_body: bytes, signature: str):
    if not CB_WEBHOOK_SECRET:
        return False
    computed = hmac.new(CB_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature or "")
