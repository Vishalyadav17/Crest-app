from __future__ import annotations
import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.environ.get("FERNET_KEY", "").strip()
    if not key:
        raise RuntimeError("FERNET_KEY not set in environment")
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def mask(plaintext: str) -> str:
    if len(plaintext) <= 8:
        return "****"
    return plaintext[:4] + "…" + plaintext[-4:]
