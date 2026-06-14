"""
Module 2 — Market Monitor API routes.
All routes require authentication (enforced by main.py middleware).
All sync I/O (yfinance, requests) is wrapped in asyncio.to_thread().
"""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from shared.sepa import score_sepa
from shared.yfinance_client import get_daily, get_bulk_daily
from shared.tickers import nse
from shared.rs_universe import get_rs_universe
from shared.cache import cache_get, cache_set

from modules.market_monitor.market_overview import get_indices, get_ad_ratio
from modules.market_monitor.gainers_losers import get_gainers_losers
from modules.market_monitor.sector_heatmap import get_sector_heatmap
from modules.market_monitor.breadth import get_market_breadth
from modules.market_monitor.news import get_news

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_SECTOR_STOCKS_TTL = 900

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["market_monitor"])


@router.get("/overview")
async def market_overview():
    """Index snapshot + breakout signal. Cached 15 min."""
    return await asyncio.to_thread(get_indices)


@router.get("/ad-ratio")
async def ad_ratio():
    """Advance/Decline ratio using 30-stock large-cap proxy. Cached 15 min."""
    return await asyncio.to_thread(get_ad_ratio)


@router.get("/gainers-losers")
async def gainers_losers(n: int = Query(10, ge=3, le=20)):
    """Top N gainers and losers from Nifty 500 universe. Cached 5 min."""
    return await asyncio.to_thread(get_gainers_losers, n)


@router.get("/sectors")
async def sectors():
    """Sector index heatmap with momentum flag + constituent stock list. Cached 15 min."""
    return await asyncio.to_thread(get_sector_heatmap)


@router.get("/sectors/{name}/stocks")
async def sector_stocks(name: str):
    """
    Constituent stocks for a sector with today's price and % change.
    name: sector key e.g. METAL, DEFENCE (case-insensitive).
    Cached 15 min.
    """
    name = name.upper()
    cache_key = f"sector_stocks_{name}"
    cached = cache_get(cache_key, _SECTOR_STOCKS_TTL)
    if cached:
        return cached

    sectors_path = _DATA_DIR / "sectors.json"
    if not sectors_path.exists():
        raise HTTPException(status_code=503, detail="sectors.json not found — run refresh_sectors.py")
    with open(sectors_path) as f:
        all_sectors = json.load(f)

    symbols = all_sectors.get(name)
    if not symbols:
        payload = {"sector": name, "stocks": [], "total": 0, "no_data": True}
        cache_set(cache_key, payload)
        return payload

    nse_syms = [nse(s) for s in symbols]
    bulk = await asyncio.to_thread(get_bulk_daily, nse_syms, "5d")

    result = []
    for sym in symbols:
        sym_ns = nse(sym)
        try:
            df = bulk.get(sym_ns, pd.DataFrame()).dropna(how="all")
            if len(df) < 2:
                continue
            price   = float(df["Close"].iloc[-1])
            prev    = float(df["Close"].iloc[-2])
            chg_pct = round((price - prev) / prev * 100, 2) if prev else 0.0
            result.append({"symbol": sym, "price": round(price, 2), "chg_pct": chg_pct})
        except (KeyError, IndexError, ValueError, TypeError) as e:
            log.warning("sector stocks parse skip %s: %s", sym, e)
            continue

    result.sort(key=lambda x: x["chg_pct"], reverse=True)
    payload = {"sector": name, "stocks": result, "total": len(result)}
    cache_set(cache_key, payload)
    return payload


@router.get("/breadth")
async def breadth():
    """% of N500 stocks above 20/50/200 DMA. Cached 4h."""
    return await asyncio.to_thread(get_market_breadth)


@router.get("/news")
async def news():
    """Latest market news from ET, Moneycontrol, BS, Mint. Cached 30 min."""
    return await asyncio.to_thread(get_news)


@router.get("/available-indices")
async def available_indices():
    """Ordered list of market index keys used for rendering the index tape in M2."""
    return {
        "order": ["N50", "BNIFTY", "MIDCAP100", "SC100", "USDINR"],
        "meta": {
            "N50":      {"label": "NIFTY 50",     "short": "N50"},
            "BNIFTY":   {"label": "BANK NIFTY",   "short": "BNIFTY"},
            "MIDCAP100":{"label": "MIDCAP 100",   "short": "MIDCAP100"},
            "SC100":    {"label": "SMALLCAP 100", "short": "SC100"},
            "USDINR":   {"label": "USD/INR",       "short": "USDINR"},
        },
    }


@router.get("/crypto-symbols")
async def crypto_symbols():
    """Symbols that should be routed to the Hyperliquid data source (not yfinance)."""
    return {
        "symbols": sorted([
            "BTC","ETH","SOL","AVAX","ARB","OP","LINK","DOGE",
            "PEPE","WIF","SUI","TIA","SEI","XRP","MATIC","NEAR","AAVE","UNI",
        ])
    }


@router.get("/sepa/{ticker}")
async def sepa_score(ticker: str):
    """
    Full SEPA analysis for a single NSE ticker.
    ticker: NSE symbol (e.g. POLYCAB). .NS suffix added automatically.
    """
    ticker = ticker.upper().strip()
    sym = nse(ticker)
    hist = await asyncio.to_thread(get_daily, sym, "1y")
    if hist is None or hist.empty:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}")

    try:
        rs_uni = await asyncio.to_thread(get_rs_universe)
        rs_pct = rs_uni.get(ticker, None)
    except (OSError, ValueError, KeyError) as e:
        log.warning("rs_universe fetch failed for %s: %s", ticker, e)
        rs_pct = None

    return score_sepa(ticker, hist, rs_pct)
