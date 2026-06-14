from __future__ import annotations
from datetime import datetime, timedelta, timezone


def cache_get(key: str, ttl_seconds: int) -> dict | None:
    from database import SessionLocal
    from models import MarketCache
    db = SessionLocal()
    try:
        row = db.query(MarketCache).filter(MarketCache.key == key).first()
        if not row:
            return None
        if row.expires_at and row.expires_at < datetime.now(timezone.utc):
            return None
        return row.data_json
    finally:
        db.close()


def cache_set(key: str, data, ttl_seconds: int = 900) -> None:
    from database import SessionLocal
    from models import MarketCache
    db = SessionLocal()
    try:
        now     = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        row = db.query(MarketCache).filter(MarketCache.key == key).first()
        if row:
            row.data_json   = data
            row.ttl_seconds = ttl_seconds
            row.expires_at  = expires
            row.updated_at  = now
        else:
            db.add(MarketCache(
                key=key,
                data_json=data,
                ttl_seconds=ttl_seconds,
                expires_at=expires,
                updated_at=now,
            ))
        db.commit()
    finally:
        db.close()


def cache_clear_stale(max_age_seconds: int = 86400 * 7) -> int:
    from database import SessionLocal
    from models import MarketCache
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        deleted = db.query(MarketCache).filter(MarketCache.updated_at < cutoff).delete()
        db.commit()
        return deleted
    finally:
        db.close()
