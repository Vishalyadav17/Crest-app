from __future__ import annotations

from sqlalchemy.orm import Session


def user_has_llm(db: Session, user_id: int) -> bool:
    from models import ProviderCredential
    count = db.query(ProviderCredential).filter(
        ProviderCredential.user_id == user_id,
        ProviderCredential.status == "active",
    ).count()
    return count > 0
