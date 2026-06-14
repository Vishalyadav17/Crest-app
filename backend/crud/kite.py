"""
Kite → DB sync functions.

Each sync_<type> persists Kite MCP tool output into the mapped table.
Full-replace strategy for snapshot tables; upsert by id for mutable tables.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models import (
    EquityHolding, KiteGTT, KiteMargin, KiteOrder, KitePosition,
    KiteTrade, MFHolding, PortfolioMeta, PriceSnapshot,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Holdings (equity) ──────────────────────────────────────────────────────────

def sync_holdings(db: Session, user_id: int, raw: list[dict]) -> list[dict]:
    """Kite is the source of truth for equity. Upsert by (user_id, sym) so a Kite
    holding UPDATES the existing row instead of adding a duplicate. Manual-only
    holdings (not in Kite) are left untouched."""
    incoming = raw or []
    incoming_syms = [s for s in {item.get("tradingsymbol", "") for item in incoming} if s]

    # Drop prior Kite rows whose symbol is no longer in the account (sold).
    db.query(EquityHolding).filter(
        EquityHolding.user_id == user_id,
        EquityHolding.source == "kite",
        ~EquityHolding.sym.in_(incoming_syms or [""]),
    ).delete(synchronize_session=False)

    rows = []
    for item in incoming:
        sym = item.get("tradingsymbol", "")
        if not sym:
            continue
        row = db.query(EquityHolding).filter(
            EquityHolding.user_id == user_id,
            EquityHolding.sym == sym,
        ).first()
        if row is None:
            row = EquityHolding(user_id=user_id, sym=sym)
            db.add(row)
        row.name             = row.name or sym
        row.is_etf           = "BEES" in sym.upper()
        row.qty              = item.get("quantity", 0)
        row.avg_price        = item.get("average_price", 0)
        row.ltp              = item.get("last_price")
        row.broker           = "kite"
        row.source           = "kite"
        row.isin             = item.get("isin")
        row.instrument_token = item.get("instrument_token")
        row.exchange         = item.get("exchange")
        row.product          = item.get("product")
        row.t1_quantity      = item.get("t1_quantity")
        row.close_price      = item.get("close_price")
        row.pnl              = item.get("pnl")
        row.day_change       = item.get("day_change")
        row.day_change_pct   = item.get("day_change_percentage")
        row.updated_at       = _now()
        if row.imported_at is None:
            row.imported_at = _now()
        rows.append(item)
    db.commit()
    return rows


# ── MF Holdings ────────────────────────────────────────────────────────────────

def sync_mf_holdings(db: Session, user_id: int, raw: list[dict]) -> list[dict]:
    db.query(MFHolding).filter(
        MFHolding.user_id == user_id,
        MFHolding.source == "kite",
    ).delete(synchronize_session=False)

    rows = []
    for item in (raw or []):
        units = item.get("quantity") or 0
        avg_nav = item.get("average_price") or 0
        current_nav = item.get("last_price") or 0
        invested = float(units) * float(avg_nav) if units and avg_nav else None
        current_value = float(units) * float(current_nav) if units and current_nav else None
        pnl = item.get("pnl")
        pnl_pct = (float(pnl) / float(invested) * 100) if pnl and invested else None

        row = MFHolding(
            user_id=user_id,
            name=item.get("fund", item.get("tradingsymbol", "")),
            short=item.get("tradingsymbol"),
            folio_number=item.get("folio"),
            tradingsymbol=item.get("tradingsymbol"),
            units=units,
            avg_nav=avg_nav,
            current_nav=current_nav,
            invested=invested,
            current_value=current_value,
            pnl=pnl,
            pnl_pct=pnl_pct,
            last_price_date=item.get("last_price_date"),
            pledged_quantity=item.get("pledged_quantity"),
            source="kite",
            imported_at=_now(),
            updated_at=_now(),
        )
        db.add(row)
        rows.append(item)
    db.commit()
    return rows


# ── Positions (full-replace) ───────────────────────────────────────────────────

def sync_positions(db: Session, user_id: int, raw: Any) -> list[dict]:
    db.query(KitePosition).filter(KitePosition.user_id == user_id).delete(synchronize_session=False)

    items = []
    if isinstance(raw, dict):
        items = raw.get("net", []) + raw.get("day", [])
    elif isinstance(raw, list):
        items = raw

    for item in items:
        row = KitePosition(
            user_id=user_id,
            tradingsymbol=item.get("tradingsymbol"),
            exchange=item.get("exchange"),
            instrument_token=item.get("instrument_token"),
            product=item.get("product"),
            quantity=item.get("quantity"),
            overnight_quantity=item.get("overnight_quantity"),
            multiplier=item.get("multiplier"),
            average_price=item.get("average_price"),
            last_price=item.get("last_price"),
            close_price=item.get("close_price"),
            value=item.get("value"),
            pnl=item.get("pnl"),
            m2m=item.get("m2m"),
            unrealised=item.get("unrealised"),
            realised=item.get("realised"),
            buy_quantity=item.get("buy_quantity"),
            buy_price=item.get("buy_price"),
            buy_value=item.get("buy_value"),
            sell_quantity=item.get("sell_quantity"),
            sell_price=item.get("sell_price"),
            sell_value=item.get("sell_value"),
            day_buy_quantity=item.get("day_buy_quantity"),
            day_buy_price=item.get("day_buy_price"),
            day_sell_quantity=item.get("day_sell_quantity"),
            day_sell_price=item.get("day_sell_price"),
            fetched_at=_now(),
        )
        db.add(row)
    db.commit()
    return items


# ── Orders (upsert) ────────────────────────────────────────────────────────────

def sync_orders(db: Session, user_id: int, raw: list[dict]) -> list[dict]:
    for item in (raw or []):
        oid = str(item.get("order_id", ""))
        if not oid:
            continue
        row = db.query(KiteOrder).filter(
            KiteOrder.user_id == user_id,
            KiteOrder.order_id == oid,
        ).first()
        if not row:
            row = KiteOrder(user_id=user_id, order_id=oid)
            db.add(row)
        row.parent_order_id = item.get("parent_order_id")
        row.exchange_order_id = item.get("exchange_order_id")
        row.placed_by = item.get("placed_by")
        row.variety = item.get("variety")
        row.status = item.get("status")
        row.status_message = item.get("status_message")
        row.tradingsymbol = item.get("tradingsymbol")
        row.exchange = item.get("exchange")
        row.instrument_token = item.get("instrument_token")
        row.transaction_type = item.get("transaction_type")
        row.order_type = item.get("order_type")
        row.product = item.get("product")
        row.validity = item.get("validity")
        row.price = item.get("price")
        row.quantity = item.get("quantity")
        row.trigger_price = item.get("trigger_price")
        row.average_price = item.get("average_price")
        row.pending_quantity = item.get("pending_quantity")
        row.filled_quantity = item.get("filled_quantity")
        row.disclosed_quantity = item.get("disclosed_quantity")
        row.cancelled_quantity = item.get("cancelled_quantity")
        row.order_timestamp = str(item.get("order_timestamp", "")) or None
        row.exchange_timestamp = str(item.get("exchange_timestamp", "")) or None
        row.tag = item.get("tag")
        row.fetched_at = _now()
    db.commit()
    return raw or []


# ── Trades (upsert) ────────────────────────────────────────────────────────────

def sync_trades(db: Session, user_id: int, raw: list[dict]) -> list[dict]:
    for item in (raw or []):
        tid = str(item.get("trade_id", ""))
        if not tid:
            continue
        row = db.query(KiteTrade).filter(
            KiteTrade.user_id == user_id,
            KiteTrade.trade_id == tid,
        ).first()
        if not row:
            row = KiteTrade(user_id=user_id, trade_id=tid)
            db.add(row)
        row.order_id = str(item.get("order_id", "")) or None
        row.exchange_order_id = item.get("exchange_order_id")
        row.exchange = item.get("exchange")
        row.tradingsymbol = item.get("tradingsymbol")
        row.instrument_token = item.get("instrument_token")
        row.product = item.get("product")
        row.average_price = item.get("average_price")
        row.quantity = item.get("quantity")
        row.transaction_type = item.get("transaction_type")
        row.fill_timestamp = str(item.get("fill_timestamp", "")) or None
        row.order_timestamp = str(item.get("order_timestamp", "")) or None
        row.exchange_timestamp = str(item.get("exchange_timestamp", "")) or None
        row.fetched_at = _now()
    db.commit()
    return raw or []


# ── Margins (full-replace + mirror to portfolio_meta.cash) ────────────────────

def sync_margins(db: Session, user_id: int, raw: dict) -> dict:
    db.query(KiteMargin).filter(KiteMargin.user_id == user_id).delete(synchronize_session=False)

    for segment_name in ("equity", "commodity"):
        seg = raw.get(segment_name, {})
        if not seg:
            continue
        row = KiteMargin(
            user_id=user_id,
            segment=segment_name,
            enabled=seg.get("enabled"),
            net=seg.get("net"),
            available_json=seg.get("available"),
            utilised_json=seg.get("utilised"),
            fetched_at=_now(),
        )
        db.add(row)

    equity_net = raw.get("equity", {}).get("net")
    if equity_net is not None:
        meta = db.query(PortfolioMeta).filter(PortfolioMeta.user_id == user_id).first()
        if meta:
            meta.cash = equity_net
        else:
            db.add(PortfolioMeta(user_id=user_id, cash=equity_net))

    db.commit()
    return raw


# ── GTTs (full-replace) ────────────────────────────────────────────────────────

def sync_gtts(db: Session, user_id: int, raw: list[dict]) -> list[dict]:
    db.query(KiteGTT).filter(KiteGTT.user_id == user_id).delete(synchronize_session=False)

    for item in (raw or []):
        row = KiteGTT(
            user_id=user_id,
            trigger_id=item.get("id"),
            type=item.get("type"),
            status=item.get("status"),
            tradingsymbol=(item.get("condition") or {}).get("tradingsymbol") or item.get("tradingsymbol"),
            exchange=(item.get("condition") or {}).get("exchange") or item.get("exchange"),
            instrument_token=(item.get("condition") or {}).get("instrument_token") or item.get("instrument_token"),
            trigger_values_json=(item.get("condition") or {}).get("trigger_values"),
            last_price=(item.get("condition") or {}).get("last_price"),
            orders_json=item.get("orders"),
            created_at_kite=str(item.get("created_at", "")) or None,
            updated_at_kite=str(item.get("updated_at", "")) or None,
            expires_at=str(item.get("expires_at", "")) or None,
            fetched_at=_now(),
        )
        db.add(row)
    db.commit()
    return raw or []


# ── Price snapshots (upsert) ───────────────────────────────────────────────────

def sync_quotes(db: Session, raw: dict) -> list[str]:
    syms = []
    for key, data in (raw or {}).items():
        if not isinstance(data, dict):
            continue
        sym = key.split(":")[-1] if ":" in key else key
        row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == sym).first()
        if not row:
            row = PriceSnapshot(sym=sym)
            db.add(row)
        row.ltp = data.get("last_price")
        ohlc = data.get("ohlc", {})
        row.prev_close = ohlc.get("close")
        row.day_high = ohlc.get("high")
        row.day_low = ohlc.get("low")
        net = data.get("net_change")
        if net is None and row.ltp and row.prev_close and row.prev_close != 0:
            net = (row.ltp - row.prev_close) / row.prev_close * 100
        row.day_change_pct = net
        row.ohlc_today_json = ohlc
        row.fetched_at = _now()
        syms.append(sym)
    db.commit()
    return syms
