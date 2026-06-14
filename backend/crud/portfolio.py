from __future__ import annotations
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import EquityHolding, PortfolioMeta
from crud.stock import upsert_stock

# Per-user map of equity symbol -> 'long_term' | 'swing' | 'manual'
_TRACK_PREF = "holding_track_map"


def get_track_map(db: Session, user_id: int) -> dict:
    from crud.prefs import get_pref
    try:
        return json.loads(get_pref(db, user_id, _TRACK_PREF, "{}")) or {}
    except Exception:
        return {}


def set_track_class(db: Session, user_id: int, sym: str, cls: str) -> None:
    from crud.prefs import set_pref
    m = get_track_map(db, user_id)
    m[sym] = cls
    set_pref(db, user_id, _TRACK_PREF, json.dumps(m))


def get_holdings(db: Session, user_id: int) -> list[dict]:
    from models import StockMaster
    from services.portfolio_service import _mcap_bucket, _base_sym

    rows = db.query(EquityHolding).filter(EquityHolding.user_id == user_id).all()
    # Enrich null sector/mcap (Kite import doesn't supply them) from the stock_master KB,
    # matching full symbol then series-stripped base (e.g. STLTECH-BE → STLTECH).
    lookup = {r.sym for r in rows} | {_base_sym(r.sym) for r in rows}
    sm_map = {s.sym: s for s in db.query(StockMaster).filter(StockMaster.sym.in_(lookup)).all()} if lookup else {}

    def _sm(sym):
        return sm_map.get(sym) or sm_map.get(_base_sym(sym))

    out = []
    for r in rows:
        sm = _sm(r.sym)
        mcap_cr = r.mcap_cr if r.mcap_cr else (sm.mcap_cr if sm and sm.mcap_cr else None)
        out.append({
            "sym":         r.sym,
            "name":        r.name or r.sym,
            "sector":      r.sector or (sm.sector if sm else None) or (sm.basic_industry if sm else None),
            "mcap_bucket": r.mcap_bucket or (sm.mcap_bucket if sm and sm.mcap_bucket else None) or _mcap_bucket(float(mcap_cr) if mcap_cr else None),
            "mcap_cr":     mcap_cr,
            "qty":         r.qty,
            "avg":         r.avg_price,   # keep legacy field name for API compat
            "ltp":         r.ltp or r.avg_price,
            "is_etf":      r.is_etf,
            "hold_type":   r.hold_type,
            "note":        r.note,
        })
    return out


def upsert_holdings(db: Session, user_id: int, holdings: list[dict]) -> None:
    db.query(EquityHolding).filter(EquityHolding.user_id == user_id).delete()
    now = datetime.now(timezone.utc)
    for h in holdings:
        sym = h["sym"]
        name = h.get("name", sym)
        db.add(EquityHolding(
            user_id=user_id,
            sym=sym,
            name=name,
            sector=h.get("sector"),
            mcap_bucket=h.get("mcap_bucket"),
            mcap_cr=h.get("mcap_cr"),
            qty=h["qty"],
            avg_price=h.get("avg_price") or h.get("avg", 0),
            ltp=h.get("ltp"),
            is_etf=bool(h.get("is_etf", False)),
            hold_type=h.get("hold_type", "long"),
            broker=h.get("broker"),
            note=h.get("note"),
            imported_at=now,
            updated_at=now,
        ))
        upsert_stock(db, sym, name,
                     sector=h.get("sector"),
                     mcap_bucket=h.get("mcap_bucket"),
                     mcap_cr=h.get("mcap_cr"),
                     is_etf=bool(h.get("is_etf", False)))
    db.commit()
    from services.portfolio_service import recompute_portfolio_snapshot
    recompute_portfolio_snapshot(user_id, db)


def get_portfolio_meta(db: Session, user_id: int) -> dict:
    row = db.query(PortfolioMeta).filter(PortfolioMeta.user_id == user_id).first()
    if not row:
        return {"first_trade_date": None, "as_of": None, "cash": 0, "health_score": None, "score": None}
    return {
        "first_trade_date": row.first_trade_date,
        "as_of":            row.as_of,
        "cash":             float(row.cash) if row.cash is not None else 0,
        "health_score":     row.health_score,
        "score":            row.score_json,
    }


def upsert_portfolio_meta(db: Session, user_id: int, **kwargs) -> None:
    row = db.query(PortfolioMeta).filter(PortfolioMeta.user_id == user_id).first()
    if row:
        for k, v in kwargs.items():
            if hasattr(row, k):
                setattr(row, k, v)
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(PortfolioMeta(user_id=user_id, updated_at=datetime.now(timezone.utc), **kwargs))
    db.commit()
