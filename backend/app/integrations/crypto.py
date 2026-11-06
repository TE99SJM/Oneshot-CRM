"""Encrypt integration credentials at rest with a key derived from SECRET_KEY."""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(f"integrations:{settings.secret_key}".encode()).digest())
    return Fernet(key)


def encrypt_secrets(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode() if data else ""


def decrypt_secrets(token: str) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as e:
        raise ValueError("Saved credentials can't be decrypted (SECRET_KEY changed?). Re-enter them.") from e
