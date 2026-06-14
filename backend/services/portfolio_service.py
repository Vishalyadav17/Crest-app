from __future__ import annotations
import logging
from datetime import date, datetime, timezone
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)
from models import (
    EquityHolding, MFHolding, GlobalHolding, CryptoHolding,
    PortfolioMeta, PortfolioSnapshot,
)
from modules.portfolio.allocation import (
    get_sector_allocation_from_holdings,
    get_mcap_allocation_from_holdings,
)


def _mcap_bucket(mcap_cr: float | None) -> str | None:
    """Market-cap bucket from ₹-crore market cap (SEBI-ish absolute thresholds)."""
    if not mcap_cr:
        return None
    if mcap_cr >= 50000:
        return "Large"
    if mcap_cr >= 15000:
        return "Mid"
    if mcap_cr >= 1000:
        return "Small"
    return "Micro"


def _base_sym(sym: str) -> str:
    """Strip NSE series suffix (-BE/-BZ/-BL...) for KB lookups."""
    return (sym or "").split("-")[0]


def asset_bucket(sym: str, is_etf: bool = False) -> str:
    """Classify an equity holding into stock | gold | etf."""
    u = (sym or "").upper()
    if "GOLD" in u or "SILVER" in u:
        return "gold"
    if is_etf or "BEES" in u or "ETF" in u or "IETF" in u:
        return "etf"
    return "stock"


def recompute_portfolio_snapshot(user_id: int, db: Session) -> PortfolioSnapshot:
    equity_rows = db.query(EquityHolding).filter(EquityHolding.user_id == user_id).all()
    mf_rows     = db.query(MFHolding).filter(MFHolding.user_id == user_id).all()
    meta        = db.query(PortfolioMeta).filter(PortfolioMeta.user_id == user_id).first()

    # Equity value/wealth includes gold + ETFs; sector/mcap allocation uses pure stocks only.
    long_equity = [h for h in equity_rows if h.hold_type == "long"]
    stocks      = [h for h in long_equity if asset_bucket(h.sym, h.is_etf) == "stock"]

    # Kite import leaves sector/mcap_bucket null — enrich from the stock_master KB
    # (match on full symbol then series-stripped base, e.g. STLTECH-BE → STLTECH).
    from models import StockMaster
    _lookup = {_base_sym(h.sym) for h in stocks} | {h.sym for h in stocks}
    sm_rows = db.query(StockMaster).filter(StockMaster.sym.in_(_lookup)).all() if _lookup else []
    sm_map = {r.sym: r for r in sm_rows}

    def _sm(sym):
        return sm_map.get(sym) or sm_map.get(_base_sym(sym))

    holdings_dicts = []
    for h in stocks:
        sm = _sm(h.sym)
        mcap_cr = float(h.mcap_cr) if h.mcap_cr else (float(sm.mcap_cr) if sm and sm.mcap_cr else None)
        sector = h.sector or (sm.sector if sm else None) or (sm.basic_industry if sm else None)
        bucket = h.mcap_bucket or (sm.mcap_bucket if sm and sm.mcap_bucket else None) or _mcap_bucket(mcap_cr)
        holdings_dicts.append({
            "sym":         h.sym,
            "name":        h.name or h.sym,
            "sector":      sector,
            "mcap_bucket": bucket,
            "mcap_cr":     mcap_cr,
            "qty":         float(h.qty),
            "avg":         float(h.avg_price),
            "ltp":         float(h.ltp or h.avg_price),
            "is_etf":      h.is_etf,
            "hold_type":   h.hold_type,
        })

    equity_inv   = sum(float(h.qty) * float(h.avg_price) for h in long_equity)
    equity_value = sum(float(h.qty) * float(h.ltp or h.avg_price) for h in long_equity)

    # Mutual funds
    mf_inv   = sum(float(h.units) * float(h.avg_nav) for h in mf_rows if h.units and h.avg_nav)
    mf_value = sum(float(h.units) * float(h.current_nav or h.avg_nav) for h in mf_rows if h.units and (h.current_nav or h.avg_nav))

    cash = float(meta.cash or 0) if meta else 0

    total_invested = equity_inv + mf_inv
    total_pnl      = (equity_value + mf_value) - total_invested
    total_wealth   = equity_value + mf_value + cash

    total_pnl_pct = round(total_pnl / total_invested * 100, 2) if total_invested else 0

    cagr = None
    first_trade = (meta.first_trade_date if meta else None)
    if first_trade and total_pnl_pct is not None:
        try:
            start = date.fromisoformat(str(first_trade)[:10])
            years = ((date.today() - start).days) / 365.25
            if years > 0.1:
                cagr = round(((1 + total_pnl_pct / 100) ** (1 / years) - 1) * 100, 2)
        except Exception as e:
            log.warning("CAGR compute failed: %s", e)

    stocks_pct = round(equity_value / total_wealth * 100, 2) if total_wealth else 0
    mf_pct     = round(mf_value    / total_wealth * 100, 2) if total_wealth else 0
    cash_pct   = max(0, round(100 - stocks_pct - mf_pct, 2))

    alloc_sector = get_sector_allocation_from_holdings(holdings_dicts)
    alloc_mcap   = get_mcap_allocation_from_holdings(holdings_dicts)

    now = datetime.now(timezone.utc)
    snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == user_id).first()
    if snap is None:
        snap = PortfolioSnapshot(user_id=user_id)
        db.add(snap)

    # Global + crypto values from price_snapshots × FX
    from models import GlobalHolding, CryptoHolding, PriceSnapshot
    from services.fx import get_fx_rate
    fx = get_fx_rate()

    global_rows = db.query(GlobalHolding).filter(
        GlobalHolding.user_id == user_id, GlobalHolding.status == "active"
    ).all()
    global_value = 0.0
    for h in global_rows:
        snap_row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == f"US:{h.sym}").first()
        ltp_usd = float(snap_row.ltp) if snap_row and snap_row.ltp else float(h.avg_price_usd)
        global_value += float(h.qty) * ltp_usd * fx

    crypto_rows = db.query(CryptoHolding).filter(
        CryptoHolding.user_id == user_id, CryptoHolding.status == "active"
    ).all()
    crypto_value = 0.0
    for h in crypto_rows:
        cg_id = h.coingecko_id or h.sym.lower()
        snap_row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == f"CRYPTO:{cg_id}").first()
        ltp_usd = float(snap_row.ltp) if snap_row and snap_row.ltp else float(h.avg_price_usd)
        crypto_value += float(h.qty) * ltp_usd * fx

    total_wealth_full = equity_value + mf_value + cash + global_value + crypto_value
    global_pct = round(global_value / total_wealth_full * 100, 2) if total_wealth_full else 0
    crypto_pct = round(crypto_value / total_wealth_full * 100, 2) if total_wealth_full else 0
    stocks_pct = round(equity_value / total_wealth_full * 100, 2) if total_wealth_full else 0
    mf_pct = round(mf_value / total_wealth_full * 100, 2) if total_wealth_full else 0
    cash_pct = max(0, round(100 - stocks_pct - mf_pct - global_pct - crypto_pct, 2))

    snap.as_of                  = date.today().isoformat()
    snap.total_wealth           = round(total_wealth_full, 4)
    snap.equity_value           = round(equity_value, 4)
    snap.mf_value               = round(mf_value, 4)
    snap.global_value           = round(global_value, 4)
    snap.crypto_value           = round(crypto_value, 4)
    snap.cash                   = round(cash, 4)
    snap.total_invested         = round(total_invested, 4)
    snap.total_pnl              = round(total_pnl, 4)
    snap.total_pnl_pct          = total_pnl_pct
    snap.cagr                   = cagr
    snap.stocks_pct             = stocks_pct
    snap.mf_pct                 = mf_pct
    snap.cash_pct               = cash_pct
    snap.global_pct             = global_pct
    snap.crypto_pct             = crypto_pct
    snap.allocation_sector_json = alloc_sector
    snap.allocation_mcap_json   = alloc_mcap
    snap.first_trade_date       = first_trade
    snap.computed_at            = now

    db.commit()
    db.refresh(snap)
    return snap
