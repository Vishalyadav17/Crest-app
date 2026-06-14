import time
import logging

import httpx
from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import is_authenticated
from database import get_db
from deps import get_current_user_id
from models import InvestmentThesis
from modules.charts import data_source
from crud.stock import search_stocks, get_name_map, upsert_stock

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/charts", tags=["charts"])

_VALID_TF  = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}
_VALID_SRC = {"yfinance", "hyperliquid"}

# ── In-process TTL cache ──────────────────────────────────────────────────────
_cache: dict[str, tuple[float, object]] = {}
_HISTORY_TTL = 60   # seconds
_QUOTE_TTL   = 10


def _cache_get(key: str, ttl: int):
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < ttl:
        return entry[1]
    return None


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (time.time(), value)


def _auth(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/history")
def history(
    request: Request,
    symbol: str = Query(...),
    timeframe: str = Query("1d"),
    source: str = Query("yfinance"),
):
    err = _auth(request)
    if err:
        return err

    symbol    = symbol.strip().upper()
    timeframe = timeframe.strip().lower()
    source    = source.strip().lower()

    if not symbol:
        return JSONResponse({"error": "missing_param", "detail": "symbol required"}, status_code=400)
    if timeframe not in _VALID_TF:
        return JSONResponse({"error": "invalid_param",
                             "detail": f"timeframe must be one of {sorted(_VALID_TF)}"}, status_code=400)
    if source not in _VALID_SRC:
        return JSONResponse({"error": "invalid_param",
                             "detail": f"source must be one of {sorted(_VALID_SRC)}"}, status_code=400)

    cache_key = f"hist|{source}|{symbol}|{timeframe}"
    cached = _cache_get(cache_key, _HISTORY_TTL)
    if cached is not None:
        return cached

    try:
        candles = data_source.get_history(symbol, timeframe, source)
    except Exception as e:
        _log.exception("history error %s %s %s", symbol, timeframe, source)
        return JSONResponse({"error": "internal", "detail": str(e)}, status_code=500)

    if not candles:
        return JSONResponse(
            {"error": "no_data", "detail": f"No candles for {symbol}/{timeframe}/{source}"},
            status_code=404,
        )

    result = {"symbol": symbol, "timeframe": timeframe, "source": source, "candles": candles}
    _cache_set(cache_key, result)
    return result


@router.get("/quote")
def quote(
    request: Request,
    symbol: str = Query(...),
    source: str = Query("yfinance"),
):
    err = _auth(request)
    if err:
        return err

    symbol = symbol.strip().upper()
    source = source.strip().lower()

    if not symbol:
        return JSONResponse({"error": "missing_param", "detail": "symbol required"}, status_code=400)
    if source not in _VALID_SRC:
        return JSONResponse({"error": "invalid_param",
                             "detail": f"source must be one of {sorted(_VALID_SRC)}"}, status_code=400)

    cache_key = f"quote|{source}|{symbol}"
    cached = _cache_get(cache_key, _QUOTE_TTL)
    if cached is not None:
        return cached

    try:
        result = data_source.get_live_price(symbol, source)
    except Exception as e:
        _log.exception("quote error %s %s", symbol, source)
        return JSONResponse({"error": "internal", "detail": str(e)}, status_code=500)

    _cache_set(cache_key, result)
    return result


@router.get("/sources")
def sources(request: Request):
    err = _auth(request)
    if err:
        return err
    return {"sources": data_source.list_sources()}


@router.get("/namemap")
def namemap(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    cache_key = "namemap"
    cached = _cache_get(cache_key, 3600)
    if cached is not None:
        return cached
    # Serve from stock_master DB (comprehensive — all stocks ever seen, not just nifty500)
    result = {"names": get_name_map(db)}
    _cache_set(cache_key, result)
    return result


@router.get("/search")
def stock_search(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, le=20),
    db: Session = Depends(get_db),
):
    """Search stock_master for autocomplete — faster and more comprehensive than CSV."""
    err = _auth(request)
    if err:
        return err
    results = search_stocks(db, q, limit=limit)
    return {"results": results}


@router.get("/stock-info")
def stock_info(
    request: Request,
    symbol: str = Query(...),
    include_news: bool = Query(False, description="When true, append news[] to response"),
    db: Session = Depends(get_db),
):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    symbol = symbol.strip().upper()
    base = symbol.replace(".NS", "").replace("^", "")
    cache_key = f"stock_info|{symbol}"
    cached = _cache_get(cache_key, 3600)
    if cached is not None:
        result = dict(cached)
        if include_news and "news" not in result:
            result["news"] = _fetch_stock_news(symbol)
        result["thesis"] = _get_thesis(db, user_id, base)
        return result
    try:
        result = data_source.get_stock_info(symbol)
    except Exception as e:
        _log.exception("stock_info error %s", symbol)
        return JSONResponse({"error": "internal", "detail": str(e)}, status_code=500)
    _cache_set(cache_key, result)
    # Auto-index this stock in stock_master so future searches find it
    name = result.get("name") or base
    if base and name:
        try:
            upsert_stock(db, base, name,
                         sector=result.get("sector"),
                         mcap_cr=result.get("market_cap_cr"))
            _cache.pop("namemap", None)
        except Exception as e:
            _log.warning("upsert_stock failed %s: %s", base, e)
    result = dict(result)
    if include_news:
        result["news"] = _fetch_stock_news(symbol)
    result["thesis"] = _get_thesis(db, user_id, base)
    return result


def _get_thesis(db: Session, user_id: int, sym: str) -> dict | None:
    row = (
        db.query(InvestmentThesis)
        .filter(
            InvestmentThesis.user_id == user_id,
            InvestmentThesis.asset_type == "equity",
            InvestmentThesis.sym == sym,
        )
        .first()
    )
    if row is None:
        return None
    return {
        "name":          row.name,
        "why_holding":   row.why_holding,
        "entry_trigger": row.entry_trigger,
        "exit_trigger":  row.exit_trigger,
        "conviction":    row.conviction,
        "review_date":   row.review_date,
    }


def _google_news_items(base: str) -> list[dict]:
    """Latest Google RSS news for a ticker — recency-filtered, newest first."""
    import urllib.parse
    from email.utils import parsedate_to_datetime
    from xml.etree import ElementTree as ET

    def _fetch(qsuffix: str) -> list[dict]:
        query = urllib.parse.quote(f"{base} NSE stock India {qsuffix}".strip())
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        resp = httpx.get(url, timeout=10, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible)"})
        root = ET.fromstring(resp.text)
        out = []
        for item in root.findall(".//item"):
            raw_title = item.findtext("title", "")
            src_el = item.find("source")
            pub = item.findtext("pubDate", "")
            try:
                ts = parsedate_to_datetime(pub).timestamp() if pub else 0
            except Exception:
                ts = 0
            out.append({
                "title": raw_title.split(" - ")[0].strip(),
                "url": item.findtext("link", ""),
                "source": src_el.text if src_el is not None else "",
                "pub": pub,
                "_ts": ts,
            })
        return out

    # Prefer last-30-day window; fall back to unrestricted if that's empty.
    items = _fetch("when:30d") or _fetch("")
    items.sort(key=lambda x: x["_ts"], reverse=True)
    items = items[:8]
    for it in items:
        it.pop("_ts", None)
    return items


def _fetch_stock_news(symbol: str) -> list[dict]:
    """Fetch fresh Google RSS news for symbol. Cached 10 min."""
    base = symbol.replace(".NS", "").replace("^", "")
    cache_key = f"news|{base}"
    cached = _cache_get(cache_key, 600)
    if cached is not None:
        return cached.get("items", [])
    try:
        items = _google_news_items(base)
        _cache_set(cache_key, {"symbol": base, "items": items})
        return items
    except Exception as e:
        _log.warning("_fetch_stock_news %s: %s", symbol, e)
        return []


@router.get("/news")
def stock_news(
    request: Request,
    symbol: str = Query(...),
):
    err = _auth(request)
    if err:
        return err
    symbol = symbol.strip().upper().replace(".NS", "").replace("^", "")
    cache_key = f"news|{symbol}"
    cached = _cache_get(cache_key, 600)
    if cached is not None:
        return cached
    try:
        result = {"symbol": symbol, "items": _google_news_items(symbol)}
    except Exception as e:
        _log.warning("news error %s: %s", symbol, e)
        result = {"symbol": symbol, "items": []}
    _cache_set(cache_key, result)
    return result


@router.post("/hl-proxy")
async def hl_proxy(request: Request):
    """Transparent proxy to Hyperliquid /info for cases where the browser needs it."""
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post("https://api.hyperliquid.xyz/info", json=body)
        return JSONResponse(resp.json(), status_code=resp.status_code)
    except Exception as e:
        _log.warning("hl_proxy error: %s", e)
        return JSONResponse({"error": "proxy_error", "detail": str(e)}, status_code=502)


@router.get("/indicator-config")
async def indicator_config():
    """
    Algorithm parameters for FE chart indicators.
    FE reads these instead of hardcoding — single source of truth in backend.
    """
    return {
        "ppv_lookback":  10,
        "dry_frac":       5,
        "vol_ma_period": 50,
        "volume_colors": {
            "ppv":          "#2196F3",
            "down_heavy":   "#EF5350",
            "up_strong":    "#26A69A",
            "dry":          "#FF9800",
            "noise":        "#555555",
        },
        "ema_periods": [20, 50, 200],
    }
