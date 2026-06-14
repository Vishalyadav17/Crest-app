import asyncio
import io
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Query, Depends, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import is_authenticated
from database import get_db
from deps import get_current_user_id
from models import PortfolioSnapshot
from modules.portfolio.quotes import get_random_quote
from modules.portfolio.allocation import get_concentration_from_holdings
from modules.portfolio.alpha import compute_alpha
from crud.portfolio import get_holdings, get_portfolio_meta
from crud.mf import get_mf_holdings, get_mf_watchpoints
from crud.swings import get_swing_trades, get_swing_budget, add_swing, update_swing, close_swing
from services.portfolio_service import recompute_portfolio_snapshot

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio")


def _auth_check(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


@router.get("/overview")
async def overview(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err

    user_id = get_current_user_id(request, db)

    snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == user_id).first()
    if snap is None:
        snap = recompute_portfolio_snapshot(user_id, db)

    from services.portfolio_service import asset_bucket
    from models import MFHolding

    holdings = get_holdings(db, user_id)
    t0 = [h for h in holdings if h.get("hold_type") == "t_plus_0"]
    meta = get_portfolio_meta(db, user_id)

    # ── Equity buckets computed directly from holdings (no subtraction) ──────────
    eq = {b: {"invested": 0.0, "value": 0.0, "holdings": []} for b in ("stocks", "gold", "etf")}
    _map = {"stock": "stocks", "gold": "gold", "etf": "etf"}
    for h in holdings:
        if h.get("hold_type") != "long":
            continue
        q = float(h.get("qty") or 0)
        a = float(h.get("avg") or 0)
        l = float(h.get("ltp") or a)
        b = eq[_map[asset_bucket(h["sym"], h.get("is_etf"))]]
        b["invested"] += q * a
        b["value"] += q * l
        b["holdings"].append(h)

    mf_rows = db.query(MFHolding).filter(MFHolding.user_id == user_id).all()
    mf_inv  = float(sum(float(m.units) * float(m.avg_nav) for m in mf_rows if m.units and m.avg_nav))
    mf_val  = float(sum(float(m.units) * float(m.current_nav or m.avg_nav) for m in mf_rows if m.units and (m.current_nav or m.avg_nav)))
    cash    = float(meta.get("cash") or 0)

    def _box(inv, val):
        pnl = val - inv
        return {
            "invested": round(inv),
            "value": round(val),
            "pnl": round(pnl),
            "pnl_pct": round(pnl / inv * 100, 1) if inv else 0,
        }

    buckets = {
        "stocks":    {**_box(eq["stocks"]["invested"], eq["stocks"]["value"]), "count": len(eq["stocks"]["holdings"])},
        "gold":      {**_box(eq["gold"]["invested"], eq["gold"]["value"]), "count": len(eq["gold"]["holdings"])},
        "etf":       {**_box(eq["etf"]["invested"], eq["etf"]["value"]), "count": len(eq["etf"]["holdings"])},
        "mf":        {**_box(mf_inv, mf_val), "count": len(mf_rows)},
        "cash":      {"value": round(cash)},
        "crypto":    {"invested": 0, "value": 0, "pnl": 0, "pnl_pct": 0, "count": 0},
        "us_equity": {"invested": 0, "value": 0, "pnl": 0, "pnl_pct": 0, "count": 0},
    }

    total_invested = eq["stocks"]["invested"] + eq["gold"]["invested"] + eq["etf"]["invested"] + mf_inv
    total_value    = eq["stocks"]["value"] + eq["gold"]["value"] + eq["etf"]["value"] + mf_val
    total_wealth   = total_value + cash
    total_pnl      = total_value - total_invested

    return {
        "first_trade_date": snap.first_trade_date,
        "as_of":            snap.as_of,
        "total_wealth":     round(total_wealth),
        "total_invested":   round(total_invested),
        "total_pnl":        round(total_pnl),
        "total_pnl_pct":    round(total_pnl / total_invested * 100, 1) if total_invested else 0,
        "cagr":             round(float(snap.cagr), 1) if snap.cagr is not None else None,
        "cash":             round(cash),
        "buckets":          buckets,
        # legacy keys kept for any older consumers
        "stocks_invested":  buckets["stocks"]["invested"],
        "stocks_value":     buckets["stocks"]["value"],
        "stocks_pnl":       buckets["stocks"]["pnl"],
        "stocks_pnl_pct":   buckets["stocks"]["pnl_pct"],
        "mf_invested":      buckets["mf"]["invested"],
        "mf_value":         buckets["mf"]["value"],
        "mf_pnl":           buckets["mf"]["pnl"],
        "mf_pnl_pct":       buckets["mf"]["pnl_pct"],
        "stocks_pct":       round(total_value and eq["stocks"]["value"] / total_wealth * 100, 1) if total_wealth else 0,
        "mf_pct":           round(mf_val / total_wealth * 100, 1) if total_wealth else 0,
        "cash_pct":         round(cash / total_wealth * 100, 1) if total_wealth else 0,
        "t_plus_0_count":   len(t0),
        "t_plus_0":         t0,
        "holdings":         eq["stocks"]["holdings"],
        "score":            meta.get("score") or {},
    }


@router.post("/classify")
async def classify_holdings(request: Request, db: Session = Depends(get_db)):
    """Place untracked Kite holdings: {classifications: {SYM: 'long_term'|'swing'|'manual'}}.
    swing/manual also creates a SwingTrade (My Trades) from the live Kite position."""
    user_id = get_current_user_id(request, db)
    data = await request.json()
    classifications = data.get("classifications") or {}
    from crud.portfolio import set_track_class
    from models import EquityHolding, SwingTrade

    created = 0
    for sym, cls in classifications.items():
        if cls not in ("long_term", "swing", "manual"):
            continue
        set_track_class(db, user_id, sym, cls)
        if cls in ("swing", "manual"):
            exists = db.query(SwingTrade).filter(
                SwingTrade.user_id == user_id, SwingTrade.sym == sym, SwingTrade.status == "active"
            ).first()
            if exists:
                continue
            h = db.query(EquityHolding).filter(
                EquityHolding.user_id == user_id, EquityHolding.sym == sym, EquityHolding.source == "kite"
            ).first()
            if not h:
                continue
            qty = float(h.qty or 0)
            avg = float(h.avg_price or 0)
            add_swing(db, user_id, {
                "sym": sym, "name": h.name or sym, "sector": h.sector,
                "qty": qty, "avg_price": avg, "ltp": float(h.ltp or avg),
                "trade_type": "scanner" if cls == "swing" else "manual",
                "note": "Classified from Kite refresh",
            })
            created += 1
    db.commit()
    return {"ok": True, "trades_created": created}


@router.get("/long-term")
async def long_term_holdings(request: Request, db: Session = Depends(get_db)):
    """Indian Equity page: stock holdings the user marked long-term."""
    user_id = get_current_user_id(request, db)
    from crud.portfolio import get_track_map
    from services.portfolio_service import asset_bucket

    track = get_track_map(db, user_id)
    rows = []
    inv_t = val_t = 0.0
    for h in get_holdings(db, user_id):
        if h.get("hold_type") != "long":
            continue
        if asset_bucket(h["sym"], h.get("is_etf")) != "stock":
            continue
        if track.get(h["sym"]) != "long_term":
            continue
        qty = float(h.get("qty") or 0)
        avg = float(h.get("avg") or 0)
        ltp = float(h.get("ltp") or avg)
        inv = qty * avg
        val = qty * ltp
        inv_t += inv
        val_t += val
        rows.append({
            "sym": h["sym"], "name": h.get("name") or h["sym"], "sector": h.get("sector"),
            "qty": qty, "avg": round(avg, 2), "ltp": round(ltp, 2),
            "invested": round(inv), "value": round(val),
            "pnl": round(val - inv), "pnl_pct": round((val - inv) / inv * 100, 1) if inv else 0,
        })
    rows.sort(key=lambda r: r["value"], reverse=True)
    for r in rows:
        r["weight"] = round(r["value"] / val_t * 100, 1) if val_t else 0
    pnl = val_t - inv_t
    return {
        "holdings": rows,
        "summary": {
            "count": len(rows), "invested": round(inv_t), "value": round(val_t),
            "pnl": round(pnl), "pnl_pct": round(pnl / inv_t * 100, 1) if inv_t else 0,
        },
    }


@router.get("/alpha")
async def alpha(request: Request, index: str = Query("N50", pattern="^(N50|N500)$"),
                db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    try:
        return compute_alpha(index)
    except Exception as e:
        log.error("alpha computation failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/allocation")
async def allocation(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)

    snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == user_id).first()
    if snap is None:
        snap = recompute_portfolio_snapshot(user_id, db)

    # Concentration still reads live holdings (no snapshot column for it)
    holdings = get_holdings(db, user_id)

    return {
        "sectors":       snap.allocation_sector_json or {"total_equity": 0, "sectors": []},
        "mcap":          snap.allocation_mcap_json   or {"total_equity": 0, "buckets": []},
        "concentration": get_concentration_from_holdings(holdings),
    }


@router.get("/swings")
async def swings(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err

    user_id = get_current_user_id(request, db)
    data    = get_swing_trades(db, user_id)

    budget  = data["budget"]
    active  = data["active"]
    closed  = data["closed"]
    summary = data["summary"]

    deployed = sum(s["invested"] or 0 for s in active if s.get("invested") is not None)

    for s in active:
        ltp = s.get("ltp") or 0
        avg = s.get("avg") or 0
        qty = s.get("qty") or 0
        s["weight_pct"] = round(qty * ltp / budget * 100, 1) if budget else 0
        s["pnl"]        = round((ltp - avg) * qty, 2)
        s["pnl_pct"]    = round((ltp - avg) / avg * 100, 2) if avg else 0

    return {
        "budget":         budget,
        "deployed":       round(deployed),
        "deployed_pct":   round(deployed / budget * 100, 1) if budget else 0,
        "over_budget":    deployed > budget,
        "over_by":        round(deployed - budget) if deployed > budget else 0,
        "realized_pnl":   round(summary.get("closed_pl") or 0),
        "active":         active,
        "closed":         closed,
        "summary":        summary,
    }


@router.post("/swings")
async def add_swing_trade(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    data = await request.json()
    trade = add_swing(db, user_id, data)
    return {"id": trade.id, "ok": True}


@router.patch("/swings/{swing_id}")
async def edit_swing_trade(swing_id: int, request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    data = await request.json()
    trade = update_swing(db, user_id, swing_id, data)
    if not trade:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"ok": True}


@router.post("/swings/{swing_id}/close")
async def close_swing_trade(swing_id: int, request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    data = await request.json()
    exit_price = float(data.get("exit_price", 0))
    exit_date = data.get("exit_date", "")
    note = data.get("note")
    trade = close_swing(db, user_id, swing_id, exit_price, exit_date, note=note)
    if not trade:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"ok": True, "realized_pnl": trade.realized_pnl}


def _is_market_hours() -> bool:
    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 555 <= t <= 930   # 09:15–15:30 IST


async def _get_or_fetch_price(sym: str, db: Session) -> float | None:
    """Read from price_snapshots; fall back to yfinance on miss/stale, then write to DB."""
    from models import PriceSnapshot
    staleness = 120 if _is_market_hours() else 300

    row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == sym).first()
    if row and row.fetched_at:
        age = (datetime.now(timezone.utc) - row.fetched_at).total_seconds()
        if age < staleness and row.ltp:
            return float(row.ltp)

    # Fallback: fetch from yfinance off the hot path
    import yfinance as yf

    def _fetch():
        try:
            ticker = sym + ".NS"
            # Always use 5m intraday — daily candles lag on yfinance (current day often NaN)
            raw = yf.download(ticker, period="1d", interval="5m", auto_adjust=True, progress=False)
            if raw is None or raw.empty:
                return None
            # Flatten MultiIndex columns (yfinance single-ticker download quirk)
            if hasattr(raw.columns, "levels"):
                raw.columns = [col[0] for col in raw.columns]
            col = raw["Close"].dropna()
            return round(float(col.iloc[-1]), 2) if not col.empty else None
        except Exception:
            return None

    ltp = await asyncio.to_thread(_fetch)
    if ltp is not None:
        now = datetime.now(timezone.utc)
        if row is None:
            row = PriceSnapshot(sym=sym)
            db.add(row)
        row.ltp        = ltp
        row.fetched_at = now
        try:
            db.commit()
        except Exception:
            db.rollback()
    return ltp


@router.get("/swings/unrealised")
async def swings_unrealised(request: Request, db: Session = Depends(get_db)):
    """Live CMP for active swings from price_snapshots (yfinance fallback)."""
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    data    = get_swing_trades(db, user_id)
    active  = [s for s in data["active"] if s.get("avg") and s.get("qty")]
    if not active:
        return {"positions": []}

    positions = []
    for s in active:
        cmp = await _get_or_fetch_price(s["sym"], db)
        unrealised_pl  = round((cmp - s["avg"]) * s["qty"], 2) if cmp else None
        unrealised_pct = round((cmp - s["avg"]) / s["avg"] * 100, 2) if (cmp and s["avg"]) else None
        positions.append({
            "id":             s["id"],
            "sym":            s["sym"],
            "cmp":            cmp,
            "unrealised_pl":  unrealised_pl,
            "unrealised_pct": unrealised_pct,
        })
    return {"positions": positions}


@router.get("/cmp")
async def get_cmp(symbols: str, request: Request, db: Session = Depends(get_db)):
    """CMP lookup for NSE symbols (comma-separated) from price_snapshots."""
    err = _auth_check(request)
    if err:
        return err
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return {"prices": {}}
    prices = {}
    for sym in sym_list:
        ltp = await _get_or_fetch_price(sym, db)
        if ltp is not None:
            prices[sym] = ltp
    return {"prices": prices}


@router.get("/mf")
async def mutual_funds(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err

    user_id     = get_current_user_id(request, db)
    holdings    = get_mf_holdings(db, user_id)
    watchpoints = get_mf_watchpoints(db, user_id)

    mf_total_invested = sum(f["invested"] or 0 for f in holdings if f.get("invested") is not None)
    mf_total_value    = sum(f["current"]  or 0 for f in holdings if f.get("current") is not None)

    for f in holdings:
        current = f.get("current") or 0
        f["weight_pct"] = round(current / mf_total_value * 100, 1) if mf_total_value else 0
        if f.get("pnl") is not None:
            f["pnl"]     = round(f["pnl"])
        if f.get("invested") is not None:
            f["invested"] = round(f["invested"])
        if f.get("current") is not None:
            f["current"] = round(f["current"])

    wp_dict = {wp["fund_key"]: wp["note"] for wp in watchpoints}

    return {
        "summary": {
            "total_invested": round(mf_total_invested),
            "total_value":    round(mf_total_value),
            "total_pnl":      round(mf_total_value - mf_total_invested),
            "total_pnl_pct":  round((mf_total_value - mf_total_invested) / mf_total_invested * 100, 1) if mf_total_invested else 0,
            "fund_count":     len(holdings),
        },
        "holdings":    sorted(holdings, key=lambda f: -(f.get("current") or 0)),
        "overlap":     {},
        "watchpoints": wp_dict,
    }


@router.get("/quote")
async def quote(request: Request):
    return get_random_quote()


# ── CSV Import ─────────────────────────────────────────────────────────────────

def _parse_csv_holdings(content: str) -> tuple[str, list[dict]]:
    """Detect broker format and return (broker_name, list of holding dicts)."""
    import csv
    reader = csv.DictReader(io.StringIO(content))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]

    rows = []
    broker = "unknown"

    # Kite Console: "instrument", "qty.", "avg. cost"
    if any("instrument" in h for h in headers) and any("qty" in h for h in headers):
        broker = "kite"
        sym_col = next(h for h in reader.fieldnames if "instrument" in h.lower())
        qty_col = next(h for h in reader.fieldnames if "qty" in h.lower())
        avg_col = next(h for h in reader.fieldnames if "avg" in h.lower() and "cost" in h.lower())
        ltp_col = next((h for h in reader.fieldnames if "ltp" in h.lower()), None)
        for row in reader:
            sym = row.get(sym_col, "").strip()
            if not sym:
                continue
            try:
                rows.append({
                    "sym": sym,
                    "qty": float(row[qty_col].replace(",", "")),
                    "avg": float(row[avg_col].replace(",", "").replace("₹", "")),
                    "ltp": float(row[ltp_col].replace(",", "").replace("₹", "")) if ltp_col and row.get(ltp_col) else None,
                })
            except (ValueError, KeyError):
                continue

    # Groww: "company", "quantity", "average buy price"
    elif any("company" in h for h in headers) and any("quantity" in h for h in headers):
        broker = "groww"
        sym_col = next(h for h in reader.fieldnames if "company" in h.lower())
        qty_col = next(h for h in reader.fieldnames if "quantity" in h.lower())
        avg_col = next(h for h in reader.fieldnames if "average" in h.lower() and ("buy" in h.lower() or "price" in h.lower()))
        ltp_col = next((h for h in reader.fieldnames if "ltp" in h.lower() or "current price" in h.lower()), None)
        for row in reader:
            sym = row.get(sym_col, "").strip()
            if not sym:
                continue
            try:
                rows.append({
                    "sym": sym,
                    "qty": float(row[qty_col].replace(",", "")),
                    "avg": float(row[avg_col].replace(",", "").replace("₹", "")),
                    "ltp": float(row[ltp_col].replace(",", "").replace("₹", "")) if ltp_col and row.get(ltp_col) else None,
                })
            except (ValueError, KeyError):
                continue

    # Generic fallback: symbol/ticker + quantity/qty + price/avg
    else:
        broker = "generic"
        sym_col = next((h for h in reader.fieldnames if h.lower() in ("symbol","ticker","scrip","stock")), None)
        qty_col = next((h for h in reader.fieldnames if "qty" in h.lower() or "quantity" in h.lower()), None)
        avg_col = next((h for h in reader.fieldnames if "avg" in h.lower() or "price" in h.lower() or "cost" in h.lower()), None)
        if sym_col and qty_col and avg_col:
            for row in reader:
                sym = row.get(sym_col, "").strip()
                if not sym:
                    continue
                try:
                    rows.append({
                        "sym": sym,
                        "qty": float(row[qty_col].replace(",", "")),
                        "avg": float(row[avg_col].replace(",", "").replace("₹", "")),
                        "ltp": None,
                    })
                except (ValueError, KeyError):
                    continue

    return broker, rows


@router.post("/import/csv")
async def import_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)

    content = (await file.read()).decode("utf-8", errors="replace")
    broker, rows = _parse_csv_holdings(content)

    if not rows:
        return JSONResponse({"error": "no_rows_parsed", "broker": broker}, status_code=422)

    from crud.portfolio import upsert_holdings
    holdings = [{
        "sym": r["sym"],
        "qty": r["qty"],
        "avg": r["avg"],
        "ltp": r.get("ltp"),
        "broker": broker,
    } for r in rows]
    upsert_holdings(db, user_id, holdings)

    return {"ok": True, "broker": broker, "imported": len(rows)}


@router.post("/holdings/manual")
async def save_manual_holdings(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    data = await request.json()
    from crud.portfolio import upsert_holdings
    upsert_holdings(db, user_id, data.get("holdings", []))
    return {"ok": True}


@router.post("/mf/manual")
async def save_manual_mf(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    data = await request.json()
    from crud.mf import upsert_mf_holdings
    upsert_mf_holdings(db, user_id, data.get("funds", []))
    return {"ok": True}


@router.put("/mf/{holding_id}/scheme-code")
async def link_mf_scheme_code(holding_id: int, request: Request, db: Session = Depends(get_db)):
    """Link a scheme_code to an MF holding and backfill NAV history from mfapi.in."""
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from models import MFHolding, MFNavHistory
    h = db.query(MFHolding).filter(MFHolding.id == holding_id, MFHolding.user_id == user_id).first()
    if not h:
        return JSONResponse({"error": "not_found"}, status_code=404)
    data = await request.json()
    scheme_code = str(data.get("scheme_code", "")).strip()
    if not scheme_code:
        return JSONResponse({"error": "scheme_code required"}, status_code=422)
    h.scheme_code = scheme_code
    db.commit()

    # Backfill nav history from mfapi.in in background
    async def _backfill(sc: str, fkey: str):
        import urllib.request, json as _json
        try:
            url = f"https://api.mfapi.in/mf/{sc}"
            with urllib.request.urlopen(url, timeout=15) as r:
                payload = _json.loads(r.read())
            navs = payload.get("data", [])  # [{date, nav}]
            from database import SessionLocal
            from models import MFNavHistory as _MFNHist
            _db = SessionLocal()
            try:
                inserted = 0
                for entry in navs:
                    nav_date = _iso_navdate(entry.get("date", ""))
                    try:
                        nav_val = float(entry.get("nav", "0"))
                    except (ValueError, TypeError):
                        continue
                    if not nav_date or not nav_val:
                        continue
                    exists = _db.query(_MFNHist).filter(
                        _MFNHist.fund_key == fkey, _MFNHist.nav_date == nav_date
                    ).first()
                    if not exists:
                        _db.add(_MFNHist(fund_key=fkey, nav_date=nav_date, nav_value=nav_val))
                        inserted += 1
                _db.commit()
                log.info("MF backfill scheme=%s: %d rows inserted", sc, inserted)
            finally:
                _db.close()
        except Exception as e:
            log.warning("MF backfill failed scheme=%s: %s", sc, e)

    fkey = scheme_code
    asyncio.create_task(_backfill(scheme_code, fkey))
    return {"ok": True, "scheme_code": scheme_code, "backfill": "started"}


@router.get("/mf/{holding_id}/nav-history")
async def mf_nav_history(holding_id: int, request: Request, db: Session = Depends(get_db),
                          days: int = 365):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from models import MFHolding, MFNavHistory
    h = db.query(MFHolding).filter(MFHolding.id == holding_id, MFHolding.user_id == user_id).first()
    if not h:
        return JSONResponse({"error": "not_found"}, status_code=404)
    fkey = h.scheme_code or h.name or str(h.id)
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = (db.query(MFNavHistory)
              .filter(MFNavHistory.fund_key == fkey, MFNavHistory.nav_date >= cutoff)
              .order_by(MFNavHistory.nav_date)
              .all())
    return {
        "holding_id": holding_id,
        "scheme_code": h.scheme_code,
        "name": h.name,
        "history": [{"date": r.nav_date, "nav": float(r.nav_value)} for r in rows],
    }


@router.get("/mf/picks")
async def mf_picks(request: Request, db: Session = Depends(get_db)):
    """Serve curated MF picks from data/mf_picks.json joined with latest NAV."""
    err = _auth_check(request)
    if err:
        return err
    import json, os
    from models import MFNavHistory
    picks_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mf_picks.json")
    picks_path = os.path.normpath(picks_path)
    try:
        with open(picks_path) as f:
            categories = json.load(f)
    except FileNotFoundError:
        return {"categories": [], "hint": "data/mf_picks.json not found"}

    # Join latest NAV + 1y return for each scheme_code
    for cat in categories:
        for fund in cat.get("funds", []):
            sc = fund.get("scheme_code")
            if not sc:
                continue
            latest = (db.query(MFNavHistory)
                        .filter(MFNavHistory.fund_key == sc)
                        .order_by(MFNavHistory.nav_date.desc())
                        .first())
            if latest:
                fund["latest_nav"] = float(latest.nav_value)
                fund["nav_date"] = latest.nav_date
            yr_ago_row = (db.query(MFNavHistory)
                           .filter(MFNavHistory.fund_key == sc, MFNavHistory.nav_date >= _year_ago())
                           .order_by(MFNavHistory.nav_date)
                           .first())
            if yr_ago_row and latest:
                yr_nav = float(yr_ago_row.nav_value)
                if yr_nav > 0:
                    fund["return_1y"] = round((float(latest.nav_value) - yr_nav) / yr_nav * 100, 2)
    return {"categories": categories}


def _year_ago() -> str:
    from datetime import date, timedelta
    return (date.today() - timedelta(days=365)).isoformat()


def _iso_navdate(raw: str) -> str:
    """mfapi.in returns dates as DD-MM-YYYY; normalize to ISO so range/sort queries work."""
    raw = (raw or "").strip()
    if len(raw) == 10 and raw[2] == "-" and raw[5] == "-":
        d, m, y = raw.split("-")
        return f"{y}-{m}-{d}"
    return raw


# ── Helpers shared by global + crypto routes ──────────────────────────────────

def _get_fx_rate() -> float:
    from services.fx import get_fx_rate
    return get_fx_rate()


def _snapshot_ltp(db, sym_key: str) -> float | None:
    from models import PriceSnapshot
    row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == sym_key).first()
    if row and row.ltp:
        return float(row.ltp)
    return None


# ── Global (US) Holdings ─────────────────────────────────────────────────────

@router.get("/global")
async def list_global_holdings(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from models import GlobalHolding
    rows = db.query(GlobalHolding).filter(
        GlobalHolding.user_id == user_id,
        GlobalHolding.status == "active",
    ).all()
    fx = _get_fx_rate()
    result = []
    total_invested_inr = 0.0
    total_value_inr = 0.0
    for h in rows:
        ltp_usd = _snapshot_ltp(db, f"US:{h.sym}") or float(h.avg_price_usd)
        invested_inr = float(h.qty) * float(h.avg_price_usd) * fx
        value_inr = float(h.qty) * ltp_usd * fx
        pnl_inr = value_inr - invested_inr
        pnl_pct = round(pnl_inr / invested_inr * 100, 2) if invested_inr else 0
        total_invested_inr += invested_inr
        total_value_inr += value_inr
        result.append({
            "id": h.id, "sym": h.sym, "name": h.name, "exchange": h.exchange,
            "asset_type": h.asset_type, "qty": float(h.qty),
            "avg_price_usd": float(h.avg_price_usd), "ltp_usd": round(ltp_usd, 4),
            "invested_inr": round(invested_inr, 2), "value_inr": round(value_inr, 2),
            "pnl_inr": round(pnl_inr, 2), "pnl_pct": pnl_pct,
            "broker": h.broker, "note": h.note,
        })
    total_pnl_inr = total_value_inr - total_invested_inr
    total_pnl_pct = round(total_pnl_inr / total_invested_inr * 100, 2) if total_invested_inr else 0
    return {
        "holdings": result,
        "summary": {
            "count": len(result),
            "invested_inr": round(total_invested_inr, 2),
            "value_inr": round(total_value_inr, 2),
            "pnl_inr": round(total_pnl_inr, 2),
            "pnl_pct": total_pnl_pct,
            "fx_rate": fx,
        },
    }


@router.post("/global")
async def add_global_holding(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    data = await request.json()
    sym = (data.get("sym") or "").strip().upper()
    qty = float(data.get("qty") or 0)
    avg_price_usd = float(data.get("avg_price_usd") or 0)
    if not sym or qty <= 0 or avg_price_usd <= 0:
        return JSONResponse({"error": "sym, qty, avg_price_usd required"}, status_code=422)

    # Validate symbol exists on yfinance
    def _validate_us(s: str):
        try:
            import yfinance as yf
            t = yf.Ticker(s)
            info = t.fast_info
            return info.last_price is not None and info.last_price > 0
        except Exception:
            return False

    valid = await asyncio.to_thread(_validate_us, sym)
    if not valid:
        return JSONResponse({"error": f"Symbol '{sym}' not found on US markets"}, status_code=422)

    from models import GlobalHolding
    h = GlobalHolding(
        user_id=user_id, sym=sym, qty=qty, avg_price_usd=avg_price_usd,
        name=data.get("name"), exchange=data.get("exchange", "NYSE/NASDAQ"),
        asset_type=data.get("asset_type", "stock"),
        broker=data.get("broker"), note=data.get("note"), status="active",
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    recompute_portfolio_snapshot(user_id, db)
    return {"ok": True, "id": h.id}


@router.post("/global/{holding_id}/close")
async def close_global_holding(holding_id: int, request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from models import GlobalHolding
    h = db.query(GlobalHolding).filter(
        GlobalHolding.id == holding_id, GlobalHolding.user_id == user_id
    ).first()
    if not h:
        return JSONResponse({"error": "not_found"}, status_code=404)
    h.status = "closed"
    h.closed_at = datetime.now(timezone.utc)
    db.commit()
    recompute_portfolio_snapshot(user_id, db)
    return {"ok": True}


# ── Crypto Holdings ───────────────────────────────────────────────────────────

@router.get("/crypto")
async def list_crypto_holdings(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from models import CryptoHolding
    rows = db.query(CryptoHolding).filter(
        CryptoHolding.user_id == user_id,
        CryptoHolding.status == "active",
    ).all()
    fx = _get_fx_rate()
    result = []
    total_invested_inr = 0.0
    total_value_inr = 0.0
    for h in rows:
        cg_id = h.coingecko_id or h.sym.lower()
        ltp_usd = _snapshot_ltp(db, f"CRYPTO:{cg_id}") or float(h.avg_price_usd)
        invested_inr = float(h.qty) * float(h.avg_price_usd) * fx
        value_inr = float(h.qty) * ltp_usd * fx
        pnl_inr = value_inr - invested_inr
        pnl_pct = round(pnl_inr / invested_inr * 100, 2) if invested_inr else 0
        total_invested_inr += invested_inr
        total_value_inr += value_inr
        result.append({
            "id": h.id, "sym": h.sym, "coingecko_id": cg_id,
            "name": h.name, "qty": float(h.qty),
            "avg_price_usd": float(h.avg_price_usd), "ltp_usd": round(ltp_usd, 4),
            "invested_inr": round(invested_inr, 2), "value_inr": round(value_inr, 2),
            "pnl_inr": round(pnl_inr, 2), "pnl_pct": pnl_pct,
            "wallet_or_exchange": h.wallet_or_exchange, "note": h.note,
        })
    total_pnl_inr = total_value_inr - total_invested_inr
    total_pnl_pct = round(total_pnl_inr / total_invested_inr * 100, 2) if total_invested_inr else 0
    return {
        "holdings": result,
        "summary": {
            "count": len(result),
            "invested_inr": round(total_invested_inr, 2),
            "value_inr": round(total_value_inr, 2),
            "pnl_inr": round(total_pnl_inr, 2),
            "pnl_pct": total_pnl_pct,
            "fx_rate": fx,
        },
    }


@router.post("/crypto")
async def add_crypto_holding(request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    data = await request.json()
    sym = (data.get("sym") or "").strip().upper()
    coingecko_id = (data.get("coingecko_id") or sym.lower()).strip().lower()
    qty = float(data.get("qty") or 0)
    avg_price_usd = float(data.get("avg_price_usd") or 0)
    if not sym or qty <= 0 or avg_price_usd <= 0:
        return JSONResponse({"error": "sym, qty, avg_price_usd required"}, status_code=422)

    # Validate via CoinGecko simple/price
    def _validate_crypto(cg_id: str):
        try:
            import urllib.request, json as _json
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
            with urllib.request.urlopen(url, timeout=8) as r:
                d = _json.loads(r.read())
            return cg_id in d and d[cg_id].get("usd", 0) > 0
        except Exception:
            return False

    valid = await asyncio.to_thread(_validate_crypto, coingecko_id)
    if not valid:
        return JSONResponse(
            {"error": f"CoinGecko id '{coingecko_id}' not found. Pass coingecko_id (e.g. 'bitcoin') explicitly."},
            status_code=422,
        )

    from models import CryptoHolding
    h = CryptoHolding(
        user_id=user_id, sym=sym, coingecko_id=coingecko_id,
        qty=qty, avg_price_usd=avg_price_usd,
        name=data.get("name"), wallet_or_exchange=data.get("wallet_or_exchange"),
        note=data.get("note"), status="active",
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    recompute_portfolio_snapshot(user_id, db)
    return {"ok": True, "id": h.id}


@router.post("/crypto/{holding_id}/close")
async def close_crypto_holding(holding_id: int, request: Request, db: Session = Depends(get_db)):
    err = _auth_check(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from models import CryptoHolding
    h = db.query(CryptoHolding).filter(
        CryptoHolding.id == holding_id, CryptoHolding.user_id == user_id
    ).first()
    if not h:
        return JSONResponse({"error": "not_found"}, status_code=404)
    h.status = "closed"
    h.closed_at = datetime.now(timezone.utc)
    db.commit()
    recompute_portfolio_snapshot(user_id, db)
    return {"ok": True}
