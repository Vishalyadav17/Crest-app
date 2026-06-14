"""
Shared helpers for Scanner v2 knowledge-base ingestion (scripts/kb/).

Paths, DB session, idempotent upserts, CSV normalisation.
"""
from __future__ import annotations
import sys
import math
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from database import SessionLocal  # noqa: E402
from models import (  # noqa: E402
    StockMaster, IndustryMaster, IndexMembership, StockSurveillance,
)

# Source data lives outside backend/ — configurable via build_knowledge_base.
KB_SOURCE_DIR = Path("/Users/vishal/Documents/grow/index_scans")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean_num(v) -> float | None:
    """Parse a CSV numeric cell; '', None, NaN → None."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip().replace(",", "")
    if s == "" or s.lower() in ("nan", "na", "-", "none"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def clean_int(v) -> int | None:
    f = clean_num(v)
    return int(f) if f is not None else None


def industry_from_filename(path: Path) -> str:
    """'Stocks Data_Telecom - Infrastructure.csv' -> 'Telecom - Infrastructure'."""
    stem = path.stem
    prefix = "Stocks Data_"
    return stem[len(prefix):].strip() if stem.startswith(prefix) else stem.strip()


def norm_sym(raw: str) -> str:
    """Normalise an NSE trading symbol from a CSV cell."""
    return str(raw).strip().upper()


# ── Idempotent upserts (ORM, DB-agnostic) ──────────────────────────────────────

def upsert_industry(db, name: str, **fields) -> IndustryMaster:
    row = db.query(IndustryMaster).filter(IndustryMaster.name == name).one_or_none()
    if row is None:
        row = IndustryMaster(name=name)
        db.add(row)
    for k, v in fields.items():
        setattr(row, k, v)
    return row


def upsert_stock(db, sym: str, **fields) -> StockMaster:
    row = db.query(StockMaster).filter(StockMaster.sym == sym).one_or_none()
    if row is None:
        # name is NOT NULL — default to symbol until a better name is known
        row = StockMaster(sym=sym, name=fields.get("name") or sym)
        db.add(row)
    for k, v in fields.items():
        if k == "name" and not v:
            continue
        setattr(row, k, v)
    return row


def upsert_membership(db, sym: str, index_name: str, index_type: str) -> None:
    exists = (
        db.query(IndexMembership.id)
        .filter(
            IndexMembership.sym == sym,
            IndexMembership.index_name == index_name,
            IndexMembership.index_type == index_type,
        )
        .first()
    )
    if not exists:
        db.add(IndexMembership(sym=sym, index_name=index_name, index_type=index_type))


def upsert_surveillance(db, sym: str, **fields) -> StockSurveillance:
    row = db.query(StockSurveillance).filter(StockSurveillance.sym == sym).one_or_none()
    if row is None:
        row = StockSurveillance(sym=sym)
        db.add(row)
    for k, v in fields.items():
        setattr(row, k, v)
    row.updated_at = now_utc()
    return row
