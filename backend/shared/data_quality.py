"""
Data-quality guard — CAPITAL PROTECTION.

Every price series feeding a real-money recommendation passes through here.
A series that fails is skipped (never ranked / never weighted into an MCW index),
so stale, gappy, or corrupt data cannot produce a trade signal.

yfinance is fetched with auto_adjust=True (splits/dividends already applied),
so we do NOT need to handle raw split jumps — but we still flag implausible moves.
"""
from __future__ import annotations
from datetime import datetime, timezone
import pandas as pd

# Conservative defaults; scanner overrides from config.json.
MIN_ROWS          = 60      # need ~3 months minimum to say anything
MAX_STALE_DAYS    = 5       # latest bar must be within 5 calendar days (covers a long weekend)
MAX_DAILY_MOVE    = 0.60    # |single-day return| above this is implausible for an adjusted series
MAX_NAN_FRAC      = 0.05    # >5% NaN in the recent window = unreliable


def check_series(
    df: pd.DataFrame | None,
    *,
    min_rows: int = MIN_ROWS,
    max_stale_days: int = MAX_STALE_DAYS,
    asof: datetime | None = None,
) -> tuple[bool, list[str]]:
    """
    Returns (ok, reasons). ok=False means DO NOT use this series for any signal.
    `asof` lets callers pin "now" (e.g. backtest); defaults to current UTC date.
    """
    reasons: list[str] = []

    if df is None or df.empty:
        return False, ["empty"]
    if "Close" not in df.columns:
        return False, ["no Close column"]

    close = df["Close"]
    n = int(close.dropna().shape[0])
    if n < min_rows:
        reasons.append(f"insufficient history ({n} < {min_rows})")

    # Staleness — last bar must be recent.
    try:
        last_date = pd.to_datetime(close.dropna().index[-1]).to_pydatetime()
        ref = (asof or datetime.now(timezone.utc)).replace(tzinfo=None)
        last_naive = last_date.replace(tzinfo=None)
        stale_days = (ref - last_naive).days
        if stale_days > max_stale_days:
            reasons.append(f"stale ({stale_days}d > {max_stale_days}d)")
    except Exception:
        reasons.append("unparseable date index")

    # Sanity — no non-positive prices in the usable window.
    recent = close.dropna().tail(max(min_rows, 60))
    if (recent <= 0).any():
        reasons.append("non-positive price")

    # NaN density in the recent window.
    window = close.tail(max(min_rows, 60))
    if len(window) > 0:
        nan_frac = float(window.isna().mean())
        if nan_frac > MAX_NAN_FRAC:
            reasons.append(f"NaN-heavy ({nan_frac:.0%})")

    # Implausible single-day move (auto_adjust already handles splits/divs).
    rets = recent.pct_change().abs()
    if not rets.empty and float(rets.max()) > MAX_DAILY_MOVE:
        reasons.append(f"implausible daily move ({rets.max():.0%})")

    return (len(reasons) == 0), reasons


def is_ok(df: pd.DataFrame | None, **kw) -> bool:
    ok, _ = check_series(df, **kw)
    return ok
