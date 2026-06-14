from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models import ProviderCredential
from services.llm.providers import PROVIDERS


def add_credential(
    db: Session, user_id: int, provider: str, key_label: str, plaintext: str
) -> ProviderCredential:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    from services.llm.crypto import encrypt
    ciphertext = encrypt(plaintext)
    row = ProviderCredential(
        user_id=user_id,
        provider=provider,
        key_label=key_label,
        ciphertext=ciphertext,
        status="active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_credentials(db: Session, user_id: int) -> list[dict]:
    from services.llm.crypto import decrypt, mask
    rows = db.query(ProviderCredential).filter(
        ProviderCredential.user_id == user_id
    ).order_by(ProviderCredential.created_at).all()
    result = []
    for r in rows:
        try:
            plain = decrypt(r.ciphertext)
            masked = mask(plain)
        except Exception:
            masked = "****"
        result.append({
            "id": r.id,
            "provider": r.provider,
            "key_label": r.key_label,
            "key_masked": masked,
            "status": r.status,
            "last_used": r.last_used.isoformat() if r.last_used else None,
            "rl_cooldown_until": r.rl_cooldown_until.isoformat() if r.rl_cooldown_until else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


def delete_credential(db: Session, user_id: int, cred_id: int) -> bool:
    row = db.query(ProviderCredential).filter(
        ProviderCredential.id == cred_id,
        ProviderCredential.user_id == user_id,
    ).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def get_active(db: Session, user_id: int, provider: str) -> list[tuple[int, str]]:
    from services.llm.crypto import decrypt
    now = datetime.now(timezone.utc)
    rows = db.query(ProviderCredential).filter(
        ProviderCredential.user_id == user_id,
        ProviderCredential.provider == provider,
        ProviderCredential.status == "active",
    ).all()
    result = []
    for r in rows:
        if r.rl_cooldown_until and r.rl_cooldown_until > now:
            continue
        try:
            plain = decrypt(r.ciphertext)
            result.append((r.id, plain))
        except Exception:
            continue
    return result


def mark_used(db: Session, cred_id: int) -> None:
    row = db.query(ProviderCredential).filter(ProviderCredential.id == cred_id).first()
    if row:
        row.last_used = datetime.now(timezone.utc)
        db.commit()


def mark_rate_limited(db: Session, cred_id: int, until: datetime) -> None:
    row = db.query(ProviderCredential).filter(ProviderCredential.id == cred_id).first()
    if row:
        row.status = "rate_limited"
        row.rl_cooldown_until = until
        db.commit()
