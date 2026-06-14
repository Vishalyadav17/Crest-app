from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import SwingTrade, SwingSummary, ScanPick
from crud.stock import upsert_stock
from crud.prefs import get_pref, set_pref


def get_swing_budget(db: Session, user_id: int) -> int:
    return int(get_pref(db, user_id, "swing_budget", "100000"))


def _recompute_swing_summary(user_id: int, db: Session) -> None:
    rows = db.query(SwingTrade).filter(SwingTrade.user_id == user_id).all()

    total_invested = sum(float(r.invested) for r in rows if r.status == "active" and r.invested is not None)
    open_count     = sum(1 for r in rows if r.status == "active")
    closed_rows    = [r for r in rows if r.status != "active"]
    closed_count   = len(closed_rows)
    closed_pl      = sum(float(r.realized_pnl) for r in closed_rows if r.realized_pnl is not None)
    # Win-rate is a scanner metric — manual trades are excluded.
    scan_closed    = [r for r in closed_rows if r.trade_type != "manual"]
    wins           = sum(1 for r in scan_closed if (r.realized_pnl or 0) > 0)
    win_rate       = round(wins / len(scan_closed) * 100) if scan_closed else None
    win_rate_class = ("green" if (win_rate or 0) >= 60 else "gold-c" if (win_rate or 0) > 0 else "")

    summary = db.query(SwingSummary).filter(SwingSummary.user_id == user_id).first()
    if summary is None:
        summary = SwingSummary(user_id=user_id)
        db.add(summary)

    summary.total_invested  = round(total_invested, 4)
    summary.open_count      = open_count
    summary.closed_count    = closed_count
    summary.wins            = wins
    summary.win_rate        = win_rate
    summary.win_rate_class  = win_rate_class
    summary.closed_pl       = round(closed_pl, 4)
    summary.updated_at      = datetime.now(timezone.utc)
    db.commit()


def get_swing_trades(db: Session, user_id: int) -> dict:
    rows = db.query(SwingTrade).filter(SwingTrade.user_id == user_id).all()
    active, closed = [], []
    for r in rows:
        if r.status == "active":
            active.append({
                "id":         r.id,
                "sym":        r.sym,
                "name":       r.name or r.sym,
                "sector":     r.sector,
                "qty":        float(r.qty) if r.qty is not None else None,
                "avg":        float(r.avg_price) if r.avg_price is not None else None,
                "ltp":        float(r.ltp or r.avg_price) if (r.ltp or r.avg_price) else None,
                "sl":         float(r.sl) if r.sl is not None else None,
                "target":     float(r.target) if r.target is not None else None,
                "exit_rule":     r.exit_rule,
                "trade_type":    r.trade_type,
                "invested":      float(r.invested) if r.invested is not None else None,
                "hold_long_term": r.hold_long_term,
                "note":          r.note,
            })
        else:
            closed.append({
                "id":           r.id,
                "sym":          r.sym,
                "name":         r.name or r.sym,
                "sector":       r.sector,
                "qty":          float(r.qty) if r.qty is not None else None,
                "avg":          float(r.avg_price) if r.avg_price is not None else None,
                "exit":         float(r.exit_price) if r.exit_price is not None else None,
                "exit_date":    r.exit_date,
                "realized_pnl": float(r.realized_pnl) if r.realized_pnl is not None else None,
                "return_pct":   float(r.return_pct) if r.return_pct is not None else None,
                "note":         r.note,
                "trade_type":   r.trade_type,
            })

    summary_row = db.query(SwingSummary).filter(SwingSummary.user_id == user_id).first()
    if summary_row:
        summary = {
            "total_invested": float(summary_row.total_invested) if summary_row.total_invested is not None else 0,
            "closed_pl":      float(summary_row.closed_pl) if summary_row.closed_pl is not None else 0,
            "win_rate":       summary_row.win_rate,
            "win_rate_class": summary_row.win_rate_class or "",
            "open_count":     summary_row.open_count,
            "closed_count":   summary_row.closed_count,
        }
    else:
        summary = {
            "total_invested": 0,
            "closed_pl":      0,
            "win_rate":       None,
            "win_rate_class": "",
            "open_count":     len(active),
            "closed_count":   len(closed),
        }

    return {
        "active":  active,
        "closed":  closed,
        "budget":  get_swing_budget(db, user_id),
        "summary": summary,
    }


def upsert_active_swings(db: Session, user_id: int, active: list[dict]) -> None:
    db.query(SwingTrade).filter(
        SwingTrade.user_id == user_id,
        SwingTrade.status == "active",
    ).delete()
    now = datetime.now(timezone.utc)
    for s in active:
        sym = s["sym"]
        name = s.get("name", sym)
        avg  = s.get("avg_price") or s.get("avg")
        qty  = s.get("qty")
        invested = round(float(avg) * float(qty), 4) if (avg and qty) else None
        db.add(SwingTrade(
            user_id=user_id,
            sym=sym,
            name=name,
            sector=s.get("sector"),
            mcap_cr=s.get("mcap_cr"),
            qty=qty,
            avg_price=avg,
            ltp=s.get("ltp"),
            sl=s.get("sl"),
            target=s.get("target"),
            exit_rule=s.get("exit_rule"),
            trade_type=s.get("trade_type", "technical"),
            status="active",
            invested=invested,
            created_at=now,
            updated_at=now,
        ))
        upsert_stock(db, sym, name, sector=s.get("sector"))
    db.commit()
    _recompute_swing_summary(user_id, db)


def upsert_closed_swings(db: Session, user_id: int, closed: list[dict]) -> None:
    db.query(SwingTrade).filter(
        SwingTrade.user_id == user_id,
        SwingTrade.status != "active",
    ).delete()
    now = datetime.now(timezone.utc)
    for s in closed:
        sym  = s["sym"]
        name = s.get("name", sym)
        avg  = s.get("avg_price") or s.get("avg")
        exit = s.get("exit_price") or s.get("exit")
        ret  = round((float(exit) - float(avg)) / float(avg) * 100, 4) if (avg and exit and float(avg)) else None
        db.add(SwingTrade(
            user_id=user_id,
            sym=sym,
            name=name,
            sector=s.get("sector"),
            qty=s.get("qty"),
            avg_price=avg,
            exit_price=exit,
            exit_date=s.get("exit_date"),
            realized_pnl=s.get("realized_pnl"),
            return_pct=ret,
            note=s.get("note"),
            trade_type=s.get("trade_type", "technical"),
            status="closed",
            created_at=now,
            updated_at=now,
        ))
        upsert_stock(db, sym, name, sector=s.get("sector"))
    db.commit()
    _recompute_swing_summary(user_id, db)


def add_swing(db: Session, user_id: int, data: dict) -> SwingTrade:
    sym  = data["sym"]
    name = data.get("name", sym)
    avg  = data.get("avg_price") or data.get("avg")
    qty  = data.get("qty")
    invested = round(float(avg) * float(qty), 4) if (avg and qty) else None
    now = datetime.now(timezone.utc)
    trade = SwingTrade(
        user_id=user_id,
        sym=sym,
        name=name,
        sector=data.get("sector"),
        mcap_cr=data.get("mcap_cr"),
        qty=qty,
        avg_price=avg,
        ltp=data.get("ltp"),
        sl=data.get("sl"),
        target=data.get("target"),
        exit_rule=data.get("exit_rule"),
        trade_type=data.get("trade_type", "manual"),
        status="active",
        invested=invested,
        note=data.get("note"),
        created_at=now,
        updated_at=now,
    )
    db.add(trade)
    upsert_stock(db, sym, name, sector=data.get("sector"))
    db.commit()
    db.refresh(trade)
    _recompute_swing_summary(user_id, db)
    return trade


def update_swing(db: Session, user_id: int, swing_id: int, data: dict) -> SwingTrade | None:
    trade = db.query(SwingTrade).filter(
        SwingTrade.id == swing_id,
        SwingTrade.user_id == user_id,
    ).first()
    if not trade:
        return None
    for k in ("ltp", "sl", "target", "exit_rule", "qty", "note", "trade_type"):
        if k in data:
            setattr(trade, k, data[k])
    if "avg_price" in data or "avg" in data:
        trade.avg_price = data.get("avg_price") or data.get("avg")
    # recompute invested from current qty + avg_price
    if trade.avg_price and trade.qty:
        trade.invested = round(float(trade.avg_price) * float(trade.qty), 4)
    trade.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trade)
    _recompute_swing_summary(user_id, db)
    return trade


def close_swing(db: Session, user_id: int, swing_id: int,
                exit_price: float, exit_date: str,
                realized_pnl: float | None = None, note: str | None = None) -> SwingTrade | None:
    trade = db.query(SwingTrade).filter(
        SwingTrade.id == swing_id,
        SwingTrade.user_id == user_id,
    ).first()
    if not trade:
        return None
    trade.status = "closed"
    trade.exit_price = exit_price
    trade.exit_date = exit_date
    if realized_pnl is not None:
        trade.realized_pnl = realized_pnl
    elif trade.avg_price and trade.qty:
        trade.realized_pnl = round((exit_price - float(trade.avg_price)) * float(trade.qty), 2)
    if trade.avg_price:
        trade.return_pct = round((exit_price - float(trade.avg_price)) / float(trade.avg_price) * 100, 4)
    trade.invested = None
    if note:
        trade.note = note
    trade.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trade)
    _recompute_swing_summary(user_id, db)
    from services.portfolio_service import recompute_portfolio_snapshot
    recompute_portfolio_snapshot(user_id, db)
    return trade


def set_hold_long_term(db: Session, user_id: int, swing_id: int, value: bool) -> SwingTrade | None:
    trade = db.query(SwingTrade).filter(
        SwingTrade.id == swing_id,
        SwingTrade.user_id == user_id,
    ).first()
    if not trade:
        return None
    trade.hold_long_term = value
    trade.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trade)
    return trade


def promote_pick_to_trade(db: Session, user_id: int, pick_id: int) -> SwingTrade | None:
    """
    Copy a ScanPick into a new SwingTrade (hold_long_term=True, source='scanner_promoted').
    Marks pick.promoted_to_trade_id. Returns the new SwingTrade, or None if already promoted.
    """
    pick = db.query(ScanPick).filter(ScanPick.id == pick_id).first()
    if not pick:
        return None
    if pick.promoted_to_trade_id:
        return db.query(SwingTrade).filter(SwingTrade.id == pick.promoted_to_trade_id).first()

    levels = pick.levels or {}
    sl     = levels.get("sl")
    target = levels.get("target")
    entry  = levels.get("entry_mid") or levels.get("price") or levels.get("entry_lo")

    now = datetime.now(timezone.utc)
    trade = SwingTrade(
        user_id=user_id,
        sym=pick.symbol,
        name=pick.name or pick.symbol,
        sector=pick.sector,
        mcap_cr=pick.mcap_cr,
        sl=sl,
        target=target,
        avg_price=entry,
        trade_type="scanner_promoted",
        status="active",
        hold_long_term=True,
        note=f"Promoted from scanner pick #{pick.id}",
        created_at=now,
        updated_at=now,
    )
    db.add(trade)
    db.flush()

    pick.promoted_to_trade_id = trade.id
    upsert_stock(db, pick.symbol, pick.name or pick.symbol, sector=pick.sector)
    db.commit()
    db.refresh(trade)
    _recompute_swing_summary(user_id, db)
    return trade
