from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_
from models import StockMaster


def upsert_stock(
    db: Session,
    sym: str,
    name: str,
    exchange: str = "NSE",
    asset_class: str = "equity",
    sector: str | None = None,
    mcap_bucket: str | None = None,
    mcap_cr: float | None = None,
    is_etf: bool = False,
) -> None:
    existing = db.query(StockMaster).filter(StockMaster.sym == sym).first()
    if existing:
        # Only upgrade the name — never overwrite a descriptive name with just the ticker
        if name and name != sym and existing.name == sym:
            existing.name = name
        elif name and name != sym and existing.name == existing.sym:
            existing.name = name
        if sector:
            existing.sector = sector
        if mcap_bucket:
            existing.mcap_bucket = mcap_bucket
        if mcap_cr is not None:
            existing.mcap_cr = mcap_cr
        existing.last_updated = datetime.now(timezone.utc)
    else:
        db.add(StockMaster(
            sym=sym, name=name, exchange=exchange, asset_class=asset_class,
            sector=sector, mcap_bucket=mcap_bucket, mcap_cr=mcap_cr,
            is_etf=is_etf, last_updated=datetime.now(timezone.utc),
        ))
    db.commit()


def search_stocks(db: Session, query: str, limit: int = 10) -> list[dict]:
    q = query.upper().strip()
    if not q:
        return []

    # Exact prefix match on sym first, then name contains
    prefix_results = (
        db.query(StockMaster)
        .filter(StockMaster.sym.like(f"{q}%"))
        .order_by(StockMaster.mcap_cr.desc().nulls_last())
        .limit(limit)
        .all()
    )
    seen = {r.sym for r in prefix_results}

    # Name contains match
    name_results = (
        db.query(StockMaster)
        .filter(
            StockMaster.sym.notin_(seen),
            or_(
                StockMaster.name.ilike(f"%{query}%"),
                StockMaster.sym.ilike(f"%{q}%"),
            )
        )
        .order_by(StockMaster.mcap_cr.desc().nulls_last())
        .limit(limit - len(prefix_results))
        .all()
    ) if len(prefix_results) < limit else []

    return [
        {"sym": r.sym, "name": r.name, "sector": r.sector, "mcap_cr": r.mcap_cr, "is_etf": r.is_etf}
        for r in prefix_results + name_results
    ]


def get_name_map(db: Session) -> dict[str, str]:
    rows = db.query(StockMaster.sym, StockMaster.name).all()
    return {sym: name for sym, name in rows}


def seed_from_csv(db: Session, csv_path: Path) -> int:
    import pandas as pd
    if not csv_path.exists():
        return 0
    df = pd.read_csv(csv_path).dropna(subset=["symbol"])
    # Get all existing syms in one query
    existing_syms = {r.sym for r in db.query(StockMaster.sym).all()}
    seen_in_batch: set[str] = set()
    count = 0
    for _, row in df.iterrows():
        sym = str(row["symbol"]).strip()
        if sym in existing_syms or sym in seen_in_batch:
            continue
        name = str(row.get("name", sym)).strip()
        sector = str(row.get("sector", "")) or None
        mcap_cr = float(row["mcap_cr"]) if "mcap_cr" in row and row["mcap_cr"] == row["mcap_cr"] else None
        db.add(StockMaster(sym=sym, name=name, sector=sector, mcap_cr=mcap_cr,
                           last_updated=datetime.now(timezone.utc)))
        seen_in_batch.add(sym)
        count += 1
    db.commit()
    return count
