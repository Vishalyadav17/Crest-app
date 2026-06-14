from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import MFHolding, MFWatchpoint


def _mf_display_name(r) -> str:
    """Prefer the full fund name; never surface the raw ISIN (stored in `short`)."""
    name = (r.name or "").strip()
    if name:
        # Trim common plan suffixes for a tighter label without losing identity.
        for suffix in (" - DIRECT PLAN", " - DIRECT  PLAN", " - GROWTH", " - DIRECT", " - REGULAR PLAN"):
            if name.upper().endswith(suffix):
                name = name[: -len(suffix)].rstrip(" -")
        return name
    return (r.short or "").strip() or "—"


def _mf_infer_type(r) -> str | None:
    """Derive a coarse fund type from the name when the source didn't set one."""
    if r.type:
        return r.type
    n = (r.name or "").upper()
    if "ELSS" in n or "TAX SAVER" in n:
        return "ELSS"
    if "INDEX" in n or "NIFTY" in n or "SENSEX" in n:
        return "Index"
    if not n:
        return None
    return "Active"


def get_mf_holdings(db: Session, user_id: int) -> list[dict]:
    rows = db.query(MFHolding).filter(MFHolding.user_id == user_id).all()
    out = []
    for r in rows:
        invested = float(r.invested) if r.invested is not None else None
        current  = float(r.current_value) if r.current_value is not None else None
        # Kite MF sync stores pnl=0; recover it on read from invested/current.
        pnl = float(r.pnl) if r.pnl not in (None, 0) else (
            round(current - invested, 2) if (current is not None and invested is not None) else None
        )
        pnl_pct = float(r.pnl_pct) if r.pnl_pct is not None else (
            round(pnl / invested * 100, 2) if (pnl is not None and invested) else None
        )
        out.append({
            "id":            r.id,
            "name":          _mf_display_name(r),
            "full_name":     r.name,
            "short":         r.short,
            "amc":           r.amc,
            "type":          _mf_infer_type(r),
            "category":      r.category,
            "scheme_code":   r.scheme_code,
            "units":         float(r.units) if r.units is not None else None,
            "avg":           float(r.avg_nav) if r.avg_nav is not None else None,
            "nav":           float(r.current_nav or r.avg_nav) if (r.current_nav or r.avg_nav) else None,
            "source":        r.source,
            "invested":      invested,
            "current":       current,
            "pnl":           pnl,
            "pnl_pct":       pnl_pct,
            "weight_pct":    None,  # computed by route
        })
    return out


def upsert_cas_holdings(db: Session, user_id: int, holdings: list[dict]) -> None:
    """Replace only source='cas' rows; leave kite/manual rows untouched."""
    db.query(MFHolding).filter(
        MFHolding.user_id == user_id,
        MFHolding.source == "cas",
    ).delete()
    now = datetime.now(timezone.utc)
    for h in holdings:
        units   = h.get("units")
        avg_nav = h.get("avg_nav") or h.get("avg")
        cur_nav = h.get("current_nav") or h.get("nav") or avg_nav
        invested    = round(float(h["invested"]), 4) if h.get("invested") is not None else (
            round(float(units) * float(avg_nav), 4) if (units and avg_nav) else None
        )
        cur_val     = round(float(h["current_value"]), 4) if h.get("current_value") is not None else (
            round(float(units) * float(cur_nav), 4) if (units and cur_nav) else None
        )
        pnl         = round(cur_val - invested, 4) if (cur_val is not None and invested is not None) else None
        pnl_pct     = round(pnl / invested * 100, 4) if (pnl is not None and invested) else None
        db.add(MFHolding(
            user_id=user_id,
            name=h["name"],
            short=h.get("short"),
            amc=h.get("amc"),
            category=h.get("category"),
            type=h.get("type"),
            scheme_code=h.get("scheme_code"),
            folio_number=h.get("folio_number"),
            units=units,
            avg_nav=avg_nav,
            current_nav=cur_nav,
            invested=invested,
            current_value=cur_val,
            pnl=pnl,
            pnl_pct=pnl_pct,
            source="cas",
            imported_at=now,
            updated_at=now,
        ))
    db.commit()
    from services.portfolio_service import recompute_portfolio_snapshot
    recompute_portfolio_snapshot(user_id, db)


def upsert_mf_holdings(db: Session, user_id: int, holdings: list[dict]) -> None:
    db.query(MFHolding).filter(MFHolding.user_id == user_id).delete()
    now = datetime.now(timezone.utc)
    for h in holdings:
        units    = h.get("units")
        avg_nav  = h.get("avg_nav") or h.get("avg")
        cur_nav  = h.get("current_nav") or h.get("nav") or avg_nav
        invested     = round(float(units) * float(avg_nav), 4) if (units and avg_nav) else None
        current_val  = round(float(units) * float(cur_nav), 4) if (units and cur_nav) else None
        pnl          = round(current_val - invested, 4) if (current_val is not None and invested is not None) else None
        pnl_pct      = round(pnl / invested * 100, 4) if (pnl is not None and invested) else None
        db.add(MFHolding(
            user_id=user_id,
            name=h["name"],
            short=h.get("short"),
            amc=h.get("amc"),
            category=h.get("category"),
            type=h.get("type"),
            units=units,
            avg_nav=avg_nav,
            current_nav=cur_nav,
            invested=invested,
            current_value=current_val,
            pnl=pnl,
            pnl_pct=pnl_pct,
            source=h.get("source", "manual"),
            imported_at=now,
            updated_at=now,
        ))
    db.commit()
    from services.portfolio_service import recompute_portfolio_snapshot
    recompute_portfolio_snapshot(user_id, db)


def get_mf_watchpoints(db: Session, user_id: int) -> list[dict]:
    rows = db.query(MFWatchpoint).filter(MFWatchpoint.user_id == user_id).all()
    return [{"fund_key": r.fund_key, "note": r.note} for r in rows]


def upsert_mf_watchpoints(db: Session, user_id: int, watchpoints) -> None:
    db.query(MFWatchpoint).filter(MFWatchpoint.user_id == user_id).delete()
    items: list[dict] = []
    if isinstance(watchpoints, dict):
        items = [{"fund_key": k, "note": v} for k, v in watchpoints.items()]
    elif isinstance(watchpoints, list):
        for i, wp in enumerate(watchpoints):
            if isinstance(wp, dict):
                items.append(wp)
            elif isinstance(wp, str):
                # Plain string — store as a numbered note
                items.append({"fund_key": f"note_{i+1}", "note": wp})
    for wp in items:
        db.add(MFWatchpoint(user_id=user_id, fund_key=wp["fund_key"], note=wp.get("note")))
    db.commit()
