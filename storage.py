"""
Real file storage for uploads (photos, logos, memes, short videos) via
Cloudinary — a straightforward REST API with a generous free tier, so this
works without you having to run your own file server.

Setup (you'll need to do this once you're ready):
  1. Create a free account at https://cloudinary.com
  2. Dashboard shows CLOUD_NAME, API_KEY, API_SECRET — put them in .env
  3. That's it — no SDK install needed, this uses plain REST + signed uploads.

Docs: https://cloudinary.com/documentation/upload_images
"""
import hashlib
import os
import time

import requests

CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

UPLOAD_URL = f"https://api.cloudinary.com/v1_1/{CLOUD_NAME}/auto/upload"

ALLOWED_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/quicktime", "video/webm",
}
MAX_FILE_BYTES = 25 * 1024 * 1024  # 25MB


class StorageError(Exception):
    pass


def _signature(params: dict) -> str:
    """Cloudinary signed-upload signature: sort params, join as k=v&k=v,
    append the API secret, SHA1 it."""
    to_sign = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.sha1((to_sign + API_SECRET).encode()).hexdigest()


def upload_file(file_storage, folder="mgr_uploads"):
    """file_storage is a Flask request.files[...] object (Werkzeug FileStorage).
    Returns the hosted URL on success."""
    if not (CLOUD_NAME and API_KEY and API_SECRET):
        raise StorageError("Cloudinary is not configured on the server (CLOUDINARY_* env vars missing)")

    content_type = file_storage.mimetype
    if content_type not in ALLOWED_TYPES:
        raise StorageError(f"File type not allowed: {content_type}")

    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_FILE_BYTES:
        raise StorageError(f"File too large — max {MAX_FILE_BYTES // (1024*1024)}MB")

    timestamp = int(time.time())
    params_to_sign = {"folder": folder, "timestamp": timestamp}
    signature = _signature(params_to_sign)

    try:
        resp = requests.post(
            UPLOAD_URL,
            data={
                "api_key": API_KEY,
                "timestamp": timestamp,
                "folder": folder,
                "signature": signature,
            },
            files={"file": (file_storage.filename, file_storage.stream, content_type)},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        raise StorageError(f"Could not reach file storage provider: {e}")

    try:
        data = resp.json()
    except ValueError:
        raise StorageError(f"Storage provider returned an unexpected response (HTTP {resp.status_code})")

    if resp.status_code >= 400:
        raise StorageError(data.get("error", {}).get("message", "Upload failed"))

    return data["secure_url"]
