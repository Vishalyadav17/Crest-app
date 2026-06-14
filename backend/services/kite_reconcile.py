"""
Kite → trades reconciliation.

Maps live Kite holdings + positions onto SwingTrade rows so the Alpha Scanner
"My Trades" view stays in sync with the broker automatically.

Truth model (Kite Connect exposes no historical-trade date range — get_trades is
today-only): current holdings + positions (incl. T+1 settlement qty) define what
is held *now*. A tracked trade whose base symbol is no longer held is closed,
using the last recorded SELL price as exit (falling back to LTP / avg).

  - scanner pick now held in Kite      → auto-create a SwingTrade (trade_type='scanner')
  - active trade still held            → refresh qty / avg / ltp
  - active trade no longer held        → close it (evidence-based, see below)

Evidence-based close: scanner trades and any symbol with Kite trade history are
Kite-managed and closed on absence. Pure off-Kite manual holds are left alone
(unless qty has hit 0). NSE series suffixes (-BE etc.) are normalised so
STLTECH and STLTECH-BE are treated as one underlying.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

_SCANNER_TYPES = ("scanner", "scanner_promoted")
_SERIES_SUFFIXES = ("-BE", "-BZ", "-BL", "-SM", "-ST", "-GB", "-GS", "-IL", "-IQ")


def _base_sym(sym: str | None) -> str:
    """Strip NSE series suffix so STLTECH-BE == STLTECH (same underlying)."""
    s = (sym or "").upper().strip()
    for suf in _SERIES_SUFFIXES:
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def _last_sell_price(db: Session, user_id: int, base: str) -> float | None:
    from models import KiteTrade

    rows = (
        db.query(KiteTrade)
        .filter(
            KiteTrade.user_id == user_id,
            KiteTrade.transaction_type == "SELL",
        )
        .order_by(KiteTrade.fill_timestamp.desc().nullslast())
        .all()
    )
    for r in rows:
        if _base_sym(r.tradingsymbol) == base and r.average_price:
            return float(r.average_price)
    return None


def _kite_traded_bases(db: Session, user_id: int) -> set[str]:
    """Base symbols that have any Kite trade fill — proof they were Kite-managed."""
    from models import KiteTrade

    return {
        _base_sym(r.tradingsymbol)
        for r in db.query(KiteTrade.tradingsymbol).filter(KiteTrade.user_id == user_id).all()
    }


def _kite_held_map(db: Session, user_id: int) -> dict[str, dict]:
    """base_sym -> {qty, avg, ltp, kind} from Kite holdings (delivery, incl. T+1)
    + positions (intraday/F&O). Same-base rows are merged (qty summed, avg weighted)."""
    from models import EquityHolding, KitePosition

    held: dict[str, dict] = {}

    def _add(base: str, qty: float, avg: float, ltp: float, kind: str) -> None:
        if not base or qty <= 0:
            return
        prev = held.get(base)
        if prev:
            tot = prev["qty"] + qty
            prev["avg"] = (prev["avg"] * prev["qty"] + avg * qty) / tot if tot else avg
            prev["qty"] = tot
            prev["ltp"] = ltp or prev["ltp"]
        else:
            held[base] = {"qty": qty, "avg": avg, "ltp": ltp or avg, "kind": kind}

    for h in db.query(EquityHolding).filter(
        EquityHolding.user_id == user_id, EquityHolding.source == "kite"
    ).all():
        q = float(h.qty or 0) + float(h.t1_quantity or 0)  # T+1 = bought, not yet settled
        _add(_base_sym(h.sym), q, float(h.avg_price or 0), float(h.ltp or h.avg_price or 0), "holding")

    for p in db.query(KitePosition).filter(KitePosition.user_id == user_id).all():
        q = float(p.quantity or 0)
        _add(_base_sym(p.tradingsymbol), q, float(p.average_price or 0),
             float(p.last_price or p.average_price or 0), "position")

    return held


def _merge_series_dupes(user_id: int, db: Session) -> list[str]:
    """Collapse active trades that share a base symbol (e.g. STLTECH + STLTECH-BE)
    into one row, and normalise every active trade's sym to its base. Returns the
    list of dropped duplicate symbols."""
    from models import ScanPick, SwingTrade

    active = db.query(SwingTrade).filter(
        SwingTrade.user_id == user_id, SwingTrade.status == "active"
    ).all()

    groups: dict[str, list] = defaultdict(list)
    for t in active:
        groups[_base_sym(t.sym)].append(t)

    dropped: list[str] = []
    for base, rows in groups.items():
        if len(rows) > 1:
            # Keeper: row carrying SL/target wins, else lowest id (oldest).
            rows.sort(key=lambda r: (0 if (r.sl or r.target) else 1, r.id))
            keeper, dups = rows[0], rows[1:]
            for dup in dups:
                db.query(ScanPick).filter(ScanPick.promoted_to_trade_id == dup.id).update(
                    {ScanPick.promoted_to_trade_id: keeper.id}, synchronize_session=False
                )
                dropped.append(dup.sym)
                db.delete(dup)
            keep = keeper
        else:
            keep = rows[0]
        if keep.sym != base:
            keep.sym = base  # STLTECH-BE -> STLTECH (also fixes yfinance price lookups)

    if dropped or groups:
        db.flush()
    return dropped


def reconcile_trades(user_id: int, db: Session, allow_close: bool = True) -> dict:
    from models import ScanPick, ScanRun, SwingTrade
    from crud.stock import upsert_stock
    from crud.swings import _recompute_swing_summary

    now = datetime.now(timezone.utc)

    merged = _merge_series_dupes(user_id, db)
    held = _kite_held_map(db, user_id)
    traded = _kite_traded_bases(db, user_id)

    created: list[str] = []
    updated: list[str] = []
    closed: list[str] = []

    # 1. Auto-create scanner picks that are now held in Kite (latest run, not yet promoted).
    run = (
        db.query(ScanRun)
        .filter(ScanRun.user_id == user_id)
        .order_by(ScanRun.scanned_at.desc())
        .first()
    )
    if run:
        for pick in db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all():
            base = _base_sym(pick.symbol)
            if base not in held or pick.promoted_to_trade_id:
                continue
            existing = (
                db.query(SwingTrade)
                .filter(
                    SwingTrade.user_id == user_id,
                    SwingTrade.sym == base,
                    SwingTrade.status == "active",
                )
                .first()
            )
            if existing:
                pick.promoted_to_trade_id = existing.id
                pick.is_holding = True
                continue
            info = held[base]
            levels = pick.levels or {}
            trade = SwingTrade(
                user_id=user_id,
                sym=base,
                name=pick.name or base,
                sector=pick.sector,
                mcap_cr=pick.mcap_cr,
                qty=info["qty"],
                avg_price=info["avg"],
                ltp=info["ltp"],
                sl=levels.get("sl"),
                target=levels.get("target"),
                invested=round(info["avg"] * info["qty"], 4) if info["avg"] and info["qty"] else None,
                trade_type="scanner",
                status="active",
                note="Auto-added from Kite (scanner pick)",
                created_at=now,
                updated_at=now,
            )
            db.add(trade)
            db.flush()
            pick.promoted_to_trade_id = trade.id
            pick.is_holding = True
            upsert_stock(db, base, pick.name or base, sector=pick.sector)
            created.append(base)

    # 2. Refresh live, or close sold. All trade types are reconciled, but a pure
    #    off-Kite manual hold (no scanner origin, no Kite trade history) is never
    #    auto-closed — unless its qty has already hit 0.
    active = (
        db.query(SwingTrade)
        .filter(SwingTrade.user_id == user_id, SwingTrade.status == "active")
        .all()
    )
    for t in active:
        base = _base_sym(t.sym)
        if base in held:
            info = held[base]
            t.sym = base
            t.qty = info["qty"]
            t.avg_price = info["avg"]
            t.ltp = info["ltp"]
            t.invested = round(info["avg"] * info["qty"], 4) if info["avg"] and info["qty"] else None
            t.updated_at = now
            updated.append(base)
            continue

        # Not held. Only close when we have a trustworthy snapshot (holdings fetched
        # ok and non-empty) to avoid wiping everything on a flaky/empty fetch.
        if not (allow_close and held):
            continue

        kite_managed = t.trade_type in _SCANNER_TYPES or base in traded
        qty_zero = float(t.qty or 0) <= 0
        if not (kite_managed or qty_zero):
            continue  # genuine off-Kite manual hold — leave active

        avg = float(t.avg_price or 0)
        qty = float(t.qty or 0)
        exit_price = _last_sell_price(db, user_id, base) or (float(t.ltp) if t.ltp else avg)
        t.status = "closed"
        t.exit_price = exit_price
        t.exit_date = now.date().isoformat()
        t.realized_pnl = round((exit_price - avg) * qty, 2) if avg and qty else None
        t.return_pct = round((exit_price - avg) / avg * 100, 4) if avg else None
        t.invested = None
        t.updated_at = now
        closed.append(base)

    # 3. Sync scanner picks ↔ My Trades: populate ScanOutcome (qty/entry) for every held
    #    scanner pick across ALL baskets, and resurrect a CHURNED pick the user actually holds.
    resurrected = _sync_scan_outcomes(db, user_id, held, now)

    db.commit()
    _recompute_swing_summary(user_id, db)
    from services.portfolio_service import recompute_portfolio_snapshot
    recompute_portfolio_snapshot(user_id, db)

    unclassified = _find_unclassified(user_id, db)
    return {"created": created, "updated": updated, "closed": closed,
            "merged": merged, "resurrected": resurrected, "unclassified": unclassified}


def _sync_scan_outcomes(db: Session, user_id: int, held: dict, now) -> list[str]:
    """F + G: for every scanner pick (any basket) whose symbol the user now holds in Kite,
    populate an open ScanOutcome (was_traded, qty, entry_price) so Scanner/Vault/My-Trades show
    one truth; and un-churn (resurrect) a CHURNED pick that's actually being held."""
    from models import ScanPick, ScanRun, ScanOutcome

    resurrected: list[str] = []
    picks = (db.query(ScanPick)
             .join(ScanRun, ScanRun.id == ScanPick.scan_run_id)
             .options(joinedload(ScanPick.outcomes))
             .filter(ScanRun.user_id == user_id).all())
    for p in picks:
        base = _base_sym(p.symbol)
        if base not in held:
            continue
        if p.scan_result in ("SL_HIT", "TARGET_HIT"):
            continue
        if any(o.exit_price for o in (p.outcomes or [])):
            continue  # already closed — don't reopen

        if p.scan_result == "CHURNED":   # G — resurrect a held churned pick
            p.scan_result = None
            p.tracking_json = {**(p.tracking_json or {}), "strength_status": "enterable", "resurrected": True}
            resurrected.append(base)

        p.is_holding = True
        info = held[base]
        oc = next((o for o in (p.outcomes or []) if o.user_id == user_id), None)
        if oc is None:
            oc = ScanOutcome(scan_pick_id=p.id, user_id=user_id, created_at=now)
            db.add(oc)
        oc.was_traded = True
        if info.get("qty"):
            oc.qty = info["qty"]
        if info.get("avg"):
            oc.entry_price = info["avg"]
    return resurrected


def _find_unclassified(user_id: int, db) -> list[dict]:
    """Kite stock holdings not tracked anywhere yet (no class, no active trade) —
    user decides Long-term / Swing / Manual in a post-refresh popup."""
    from models import EquityHolding, ScanPick, ScanRun, SwingTrade
    from crud.portfolio import get_track_map
    from services.portfolio_service import asset_bucket

    track = get_track_map(db, user_id)
    track_bases = {_base_sym(s) for s in track}
    active_bases = {
        _base_sym(t.sym) for t in db.query(SwingTrade).filter(
            SwingTrade.user_id == user_id, SwingTrade.status == "active"
        ).all()
    }
    run = (
        db.query(ScanRun).filter(ScanRun.user_id == user_id)
        .order_by(ScanRun.scanned_at.desc()).first()
    )
    pick_bases = (
        {_base_sym(p.symbol) for p in db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()}
        if run else set()
    )

    out = []
    for h in db.query(EquityHolding).filter(
        EquityHolding.user_id == user_id,
        EquityHolding.source == "kite",
        EquityHolding.hold_type == "long",
    ).all():
        if asset_bucket(h.sym, h.is_etf) != "stock":
            continue
        base = _base_sym(h.sym)
        if base in track_bases or base in active_bases:
            continue
        out.append({
            "sym": h.sym,
            "name": h.name or h.sym,
            "qty": float(h.qty or 0),
            "avg": float(h.avg_price or 0),
            "ltp": float(h.ltp or h.avg_price or 0),
            "suggested": "swing" if base in pick_bases else "long_term",
        })
    return out
