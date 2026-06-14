from __future__ import annotations
from sqlalchemy.orm import Session
from models import User


def get_or_create_default_user(db: Session, email: str, name: str | None = None) -> int:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user.id
    user = User(email=email, name=name or email.split("@")[0], tier="pro")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id
