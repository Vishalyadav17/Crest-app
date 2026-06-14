"""
Market-data refresh jobs: price snapshots, breadth, sector heatmap, gainers/losers,
indices EMA, RS universe, bhavcopy, MF NAVs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone as tz

from jobs import _is_market_hours, _IST
from jobs.snapshots import _upsert_daily_snap

log = logging.getLogger(__name__)


# ── Job: refresh price snapshots (every 60s, market hours only) ───────────────

def _gather_price_syms(db) -> set[str]:
    from models import SwingTrade, ScanPick, ScanRun, WatchlistItem, PriceBand
    syms: set[str] = set()
    for s in db.query(SwingTrade).filter(SwingTrade.status == "active").all():
        syms.add(s.sym)
    for p in (db.query(ScanPick)
              .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
              .filter(ScanPick.scan_result.is_(None)).all()):
        syms.add(p.symbol)
    for w in db.query(WatchlistItem).all():
        syms.add(w.sym)
    for b in db.query(PriceBand).filter(PriceBand.is_active == True).all():
        syms.add(b.sym)
    return syms


def _any_kite_session(db) -> str | None:
    """Any user's saved Kite session id (snapshots are shared, keyed by symbol not user)."""
    from models import UserPreference
    row = (db.query(UserPreference)
           .filter(UserPreference.key == "kite_session_id", UserPreference.value.isnot(None))
           .first())
    return row.value if row else None


async def job_refresh_price_snapshots() -> None:
    if not _is_market_hours():
        return
    # Kite first (accurate, free with a session) — writes ltp+ohlc straight into price_snapshots
    # via sync_quotes; yfinance then fills only the symbols Kite didn't return.
    kite_done: set[str] = set()
    try:
        from database import SessionLocal
        db = SessionLocal()
        try:
            syms = _gather_price_syms(db)
            sid = _any_kite_session(db)
            if sid and syms:
                from services.kite_mcp.client import call_tool
                res = await call_tool(sid, "get_quotes", {"instruments": [f"NSE:{s}" for s in syms]})
                if isinstance(res, dict) and res:
                    from crud.kite import sync_quotes
                    kite_done = set(sync_quotes(db, res))
                    log.debug("kite snapshot: %d symbols via Kite", len(kite_done))
        finally:
            db.close()
    except Exception:
        log.debug("kite snapshot path failed — yfinance will cover all", exc_info=True)

    try:
        await asyncio.to_thread(_sync_refresh_price_snapshots, kite_done)
    except Exception:
        log.exception("job_refresh_price_snapshots failed")


def _sync_refresh_price_snapshots(skip: set[str] | None = None) -> None:
    from database import SessionLocal
    from models import PriceSnapshot
    import yfinance as yf
    import pandas as pd

    skip = skip or set()
    db = SessionLocal()
    try:
        syms = _gather_price_syms(db) - skip
        if not syms:
            return

        ns_syms = [s + ".NS" for s in syms]
        raw = yf.download(
            ns_syms, period="2d", auto_adjust=True, progress=False,
            group_by="ticker", timeout=45
        )
        if raw is None or raw.empty:
            return

        now = datetime.now(tz.utc)
        ws_batch: dict = {}

        for sym in syms:
            ns = sym + ".NS"
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    close_col = raw["Close"][ns] if ns in raw["Close"].columns else None
                    if close_col is None:
                        continue
                    close = close_col.dropna()
                else:
                    close = raw["Close"].dropna()

                if len(close) < 1:
                    continue

                ltp = round(float(close.iloc[-1]), 4)
                prev_close = round(float(close.iloc[-2]), 4) if len(close) >= 2 else ltp
                day_change_pct = round((ltp - prev_close) / prev_close * 100, 4) if prev_close else 0

                row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == sym).first()
                if row is None:
                    row = PriceSnapshot(sym=sym)
                    db.add(row)

                row.ltp            = ltp
                row.prev_close     = prev_close
                row.day_change_pct = day_change_pct
                row.fetched_at     = now
                # day high/low from last candle in 2d daily download
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        dh = raw["High"][ns].dropna()
                        dl = raw["Low"][ns].dropna()
                    else:
                        dh = raw["High"].dropna()
                        dl = raw["Low"].dropna()
                    if len(dh) >= 1:
                        row.day_high = round(float(dh.iloc[-1]), 4)
                    if len(dl) >= 1:
                        row.day_low = round(float(dl.iloc[-1]), 4)
                except Exception:
                    pass
                ws_batch[sym] = {
                    "ltp":        ltp,
                    "chg_pct":    day_change_pct,
                    "prev_close": prev_close,
                    "fetched_at": now.isoformat(),
                }
            except Exception:
                pass

        db.commit()
        log.debug("price_snapshots refreshed for %d symbols", len(syms))
        if ws_batch:
            from shared.price_channel import enqueue_price_update
            enqueue_price_update(ws_batch)
    finally:
        db.close()


# ── Job: refresh market breadth (every 4h, also EOD) ─────────────────────────

async def job_refresh_market_breadth() -> None:
    try:
        await asyncio.to_thread(_sync_refresh_market_breadth)
    except Exception:
        log.exception("job_refresh_market_breadth failed")


def _sync_refresh_market_breadth() -> None:
    from modules.market_monitor.breadth import compute_breadth_fresh
    from shared.cache import cache_set

    result = compute_breadth_fresh()
    cache_set("market_breadth_v2", result, ttl_seconds=14400)

    today = date.today().isoformat()
    _upsert_daily_snap(today, breadth_json=result)
    log.info("market breadth refreshed")


# ── Job: refresh sector heatmap (every 15m) ───────────────────────────────────

async def job_refresh_sector_heatmap() -> None:
    try:
        await asyncio.to_thread(_sync_refresh_sector_heatmap)
    except Exception:
        log.exception("job_refresh_sector_heatmap failed")


def _sync_refresh_sector_heatmap() -> None:
    from modules.market_monitor.sector_heatmap import _fetch_sector, _fetch_nse_only_sectors, _load_sector_stocks
    from shared.tickers import SECTOR_TICKERS, NSE_ONLY_SECTORS
    from shared.cache import cache_set

    sector_stocks = _load_sector_stocks()
    sectors = []
    for name, sym in SECTOR_TICKERS.items():
        data = _fetch_sector(name, sym)
        if data:
            data["stocks"] = sector_stocks.get(name, [])
            sectors.append(data)
    for data in _fetch_nse_only_sectors(NSE_ONLY_SECTORS):
        data["stocks"] = sector_stocks.get(data["name"], [])
        sectors.append(data)

    sectors.sort(key=lambda x: x["chg_pct"], reverse=True)
    result = {
        "sectors": sectors,
        "momentum_count": sum(1 for s in sectors if s["in_momentum"]),
        "total": len(sectors),
    }
    cache_set("sector_heatmap", result, ttl_seconds=900)

    today = date.today().isoformat()
    _upsert_daily_snap(today, sector_heatmap_json=result)
    log.info("sector heatmap refreshed (%d sectors)", len(sectors))


# ── Job: refresh gainers / losers (every 15m, market hours) ──────────────────

async def job_refresh_gainers_losers() -> None:
    if not _is_market_hours():
        return
    try:
        await asyncio.to_thread(_sync_refresh_gainers_losers)
    except Exception:
        log.exception("job_refresh_gainers_losers failed")


def _sync_refresh_gainers_losers() -> None:
    from modules.market_monitor.gainers_losers import _from_nse, _from_yfinance, _TOP_N
    from shared.cache import cache_set

    result = _from_nse(_TOP_N) or _from_yfinance(_TOP_N)
    cache_set(f"gainers_losers|{_TOP_N}", result, ttl_seconds=300)

    today = date.today().isoformat()
    _upsert_daily_snap(today, top_gainers_json=result)
    log.info("gainers/losers refreshed")


# ── Job: refresh indices (every 5m, market hours) ────────────────────────────

async def job_refresh_indices() -> None:
    if not _is_market_hours():
        return
    try:
        await asyncio.to_thread(_sync_refresh_indices)
    except Exception:
        log.exception("job_refresh_indices failed")


def _sync_refresh_indices() -> None:
    from modules.market_monitor.market_overview import _fetch_index, _fetch_nse_only_indices, _INDEX_META
    from shared.cache import cache_set
    from shared.tickers import SECTOR_TICKERS
    from shared.yfinance_client import get_bulk_daily

    result: dict = {}
    for sym, meta in _INDEX_META.items():
        data = _fetch_index(sym)
        if data:
            result[meta["short"]] = {**meta, **data, "symbol": sym}

    result.update(_fetch_nse_only_indices())

    # Bulk-download 8 sector ETFs in one call (replaces 8 serial yf.download calls)
    sector_syms = list(SECTOR_TICKERS.values())[:8]
    bulk = get_bulk_daily(sector_syms, period="3mo")

    sector_above = sector_total = 0
    for tsym in sector_syms:
        df = bulk.get(tsym)
        if df is None or df.empty:
            continue
        try:
            close = df["Close"].dropna() if "Close" in df.columns else df.iloc[:, 0].dropna()
            if len(close) >= 50:
                sector_total += 1
                ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
                if float(close.iloc[-1]) > ema50:
                    sector_above += 1
        except Exception:
            pass

    bscore = sector_above / sector_total if sector_total else 0
    result["market_signal"] = {
        "sectors_above_ema50": sector_above,
        "sectors_checked":     sector_total,
        "breakout_likely":     bscore >= 0.6,
        "signal":              "BULLISH" if bscore >= 0.6 else ("NEUTRAL" if bscore >= 0.4 else "CAUTION"),
    }

    cache_set("market_overview|indices", result, ttl_seconds=900)

    today = date.today().isoformat()
    _upsert_daily_snap(today, indices_json=result)
    log.debug("indices refreshed")


# ── Job: refresh RS universe (daily 17:00) ────────────────────────────────────

async def job_refresh_rs_universe() -> None:
    try:
        await asyncio.to_thread(_sync_refresh_rs_universe)
    except Exception:
        log.exception("job_refresh_rs_universe failed")


def _sync_refresh_rs_universe() -> None:
    from shared.rs_universe import compute_universe
    import pandas as pd
    from pathlib import Path

    csv = Path(__file__).parent.parent / "data" / "nifty500.csv"
    if not csv.exists():
        log.warning("nifty500.csv not found — skipping RS universe refresh")
        return
    df = pd.read_csv(csv).dropna(subset=["symbol"])
    syms = df["symbol"].drop_duplicates().tolist()
    result = compute_universe(syms)

    today = date.today().isoformat()
    _upsert_daily_snap(today, rs_universe_json=result)
    log.info("RS universe refreshed (%d stocks)", len(result) if isinstance(result, list) else 0)


# ── Job: ingest NSE bhavcopy (daily 17:30) ────────────────────────────────────

async def job_ingest_bhavcopy() -> None:
    try:
        await asyncio.to_thread(_sync_ingest_bhavcopy)
    except Exception:
        log.exception("job_ingest_bhavcopy failed")


def _sync_ingest_bhavcopy() -> None:
    from shared.nse_bhavcopy import fetch_bhavcopy, upsert_bhavcopy_to_db
    df = fetch_bhavcopy()
    if not df.empty:
        upsert_bhavcopy_to_db(df)
        log.info("bhavcopy ingested: %d rows", len(df))
        # Fresh prices in — refresh every custom index off them.
        from database import SessionLocal
        from services.custom_index_compute import recompute_all
        db = SessionLocal()
        try:
            recompute_all(db)
        finally:
            db.close()
    else:
        log.warning("bhavcopy fetch returned empty DataFrame")


# ── Job: refresh MF NAVs (daily 21:00) ────────────────────────────────────────

async def job_refresh_mf_navs() -> None:
    try:
        await asyncio.to_thread(_sync_refresh_mf_navs)
    except Exception:
        log.exception("job_refresh_mf_navs failed")


def _parse_amfi_navall(text: str) -> tuple[dict[str, float], dict[str, float], list[dict]]:
    """
    Returns:
      code_map  {scheme_code: nav}
      name_map  {fund_name_upper: nav}
      scheme_list [{scheme_code, name, isin, nav}] — for scheme-search cache
    """
    code_map: dict[str, float] = {}
    name_map: dict[str, float] = {}
    scheme_list: list[dict] = []
    for line in text.splitlines():
        parts = line.split(";")
        if len(parts) >= 5:
            code = parts[0].strip()
            name = parts[3].strip()
            nav_str = parts[4].strip()
            try:
                nav = float(nav_str)
            except ValueError:
                continue
            if code.isdigit():
                code_map[code] = nav
            name_map[name.upper()] = nav
            scheme_list.append({"scheme_code": code, "name": name, "isin": parts[1].strip(), "nav": nav})
    return code_map, name_map, scheme_list


def _sync_refresh_mf_navs() -> None:
    import requests
    from database import SessionLocal
    from models import MFHolding, MFNavHistory
    from shared.cache import cache_set

    AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

    try:
        r = requests.get(AMFI_URL, timeout=30)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        log.warning("AMFI NAV fetch failed: %s", e)
        return

    code_map, name_map, scheme_list = _parse_amfi_navall(text)
    # Cache parsed scheme list for scheme-search endpoint (24h TTL)
    cache_set("amfi_scheme_list", scheme_list, ttl_seconds=86400)

    db = SessionLocal()
    today_str = date.today().isoformat()
    try:
        holdings = db.query(MFHolding).all()
        updated = 0
        for h in holdings:
            nav = None
            # Prefer scheme_code match (exact, reliable)
            if h.scheme_code and h.scheme_code in code_map:
                nav = code_map[h.scheme_code]
            else:
                # Fuzzy name fallback
                name_upper = (h.name or "").upper()
                nav = name_map.get(name_upper)
                if nav is None:
                    for k, v in name_map.items():
                        if name_upper in k or k in name_upper:
                            nav = v
                            break
                if nav is None:
                    log.warning("MF NAV fuzzy match failed for name=%s (add scheme_code to fix)", h.name)
                    continue
                else:
                    log.warning("MF NAV fuzzy match used for name=%s — link scheme_code for accuracy", h.name)

            h.current_nav = nav
            if h.units and h.avg_nav:
                h.current_value = round(float(h.units) * nav, 4)
                h.pnl           = round(h.current_value - float(h.units) * float(h.avg_nav), 4)
                h.pnl_pct       = round(h.pnl / (float(h.units) * float(h.avg_nav)) * 100, 4) if h.avg_nav else 0

            # Use scheme_code as fund_key if available, else name
            fkey = h.scheme_code or h.name or str(h.id)
            existing = db.query(MFNavHistory).filter(
                MFNavHistory.fund_key == fkey,
                MFNavHistory.nav_date == today_str,
            ).first()
            if existing is None:
                db.add(MFNavHistory(fund_key=fkey, nav_date=today_str, nav_value=nav))
            updated += 1

        db.commit()
        log.info("MF NAVs refreshed: %d funds updated", updated)
    finally:
        db.close()


# ── Job: refresh US equity prices (every 30m during US session 19:00–01:35 IST) ──

async def job_refresh_us_prices() -> None:
    now = datetime.now(_IST)
    # US session IST gate: 19:00–01:35 (next day), Mon–Fri only
    weekday = now.weekday()
    hour, minute = now.hour, now.minute
    in_session = (
        (weekday < 5 and hour >= 19) or
        (weekday < 6 and hour == 0) or
        (weekday < 6 and hour == 1 and minute <= 35)
    )
    if not in_session:
        return
    try:
        await asyncio.to_thread(_sync_refresh_us_prices)
    except Exception:
        log.exception("job_refresh_us_prices failed")


def _sync_refresh_us_prices() -> None:
    import yfinance as yf
    import pandas as pd
    from database import SessionLocal
    from models import GlobalHolding, PriceSnapshot

    db = SessionLocal()
    try:
        syms = list({h.sym for h in db.query(GlobalHolding).filter(
            GlobalHolding.status == "active"
        ).all()})
        if not syms:
            return

        raw = yf.download(syms, period="2d", auto_adjust=True, progress=False, group_by="ticker", timeout=30)
        if raw is None or raw.empty:
            return

        now = datetime.now(tz.utc)
        for sym in syms:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    col = raw["Close"][sym].dropna() if sym in raw["Close"].columns else None
                else:
                    col = raw["Close"].dropna()
                if col is None or len(col) < 1:
                    continue
                ltp = round(float(col.iloc[-1]), 4)
                prev = round(float(col.iloc[-2]), 4) if len(col) >= 2 else ltp
                chg = round((ltp - prev) / prev * 100, 4) if prev else 0
                key = f"US:{sym}"
                row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == key).first()
                if row is None:
                    row = PriceSnapshot(sym=key)
                    db.add(row)
                row.ltp = ltp
                row.prev_close = prev
                row.day_change_pct = chg
                row.fetched_at = now
            except Exception as e:
                log.warning("US price skip %s: %s", sym, e)
        db.commit()
    finally:
        db.close()


# ── Job: refresh crypto prices (hourly 24/7) ──────────────────────────────────

async def job_refresh_crypto_prices() -> None:
    try:
        await asyncio.to_thread(_sync_refresh_crypto_prices)
    except Exception:
        log.exception("job_refresh_crypto_prices failed")


def _sync_refresh_crypto_prices() -> None:
    import urllib.request
    import json as _json
    from database import SessionLocal
    from models import CryptoHolding, PriceSnapshot

    db = SessionLocal()
    try:
        rows = db.query(CryptoHolding).filter(CryptoHolding.status == "active").all()
        if not rows:
            return

        ids = list({(h.coingecko_id or h.sym.lower()) for h in rows})
        ids_param = ",".join(ids)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_param}&vs_currencies=usd,inr"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                prices = _json.loads(r.read())
        except Exception as e:
            log.warning("CoinGecko fetch failed: %s", e)
            return

        now = datetime.now(tz.utc)
        for cg_id in ids:
            data = prices.get(cg_id, {})
            usd = data.get("usd")
            if not usd:
                continue
            key = f"CRYPTO:{cg_id}"
            row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == key).first()
            if row is None:
                row = PriceSnapshot(sym=key)
                db.add(row)
            row.ltp = round(float(usd), 4)
            row.fetched_at = now
        db.commit()
    finally:
        db.close()


# ── Job: refresh USD/INR FX rate (daily 18:00 IST) ───────────────────────────

async def job_refresh_fx() -> None:
    try:
        await asyncio.to_thread(_sync_refresh_fx)
    except Exception:
        log.exception("job_refresh_fx failed")


def _sync_refresh_fx() -> None:
    import yfinance as yf
    from shared.cache import cache_set

    try:
        raw = yf.download("USDINR=X", period="2d", auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            return
        col = raw["Close"].dropna()
        if col.empty:
            return
        rate = round(float(col.iloc[-1]), 4)
        cache_set("fx_usdinr", {"rate": rate}, ttl_seconds=86400)
        log.info("FX USD/INR refreshed: %.4f", rate)
    except Exception as e:
        log.warning("FX refresh failed: %s", e)


# ── Job: compute all custom indices (nightly 22:00 IST) ──────────────────────

async def job_compute_custom_indices() -> None:
    try:
        await asyncio.to_thread(_sync_compute_custom_indices)
    except Exception:
        log.exception("job_compute_custom_indices failed")


def _sync_compute_custom_indices() -> None:
    from database import SessionLocal
    from models import CustomIndex
    from services.custom_index_compute import compute_and_persist

    db = SessionLocal()
    try:
        indices = db.query(CustomIndex).all()
        log.info("compute_custom_indices: %d indices", len(indices))
        for idx in indices:
            try:
                n = compute_and_persist(db, idx.id)
                log.info("  idx %d (%s): %d rows", idx.id, idx.name, n)
            except Exception as e:
                log.warning("  idx %d (%s) failed: %s", idx.id, idx.name, e)
    finally:
        db.close()
