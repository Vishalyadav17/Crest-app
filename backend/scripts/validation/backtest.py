"""
Indicative backtest — SANITY CHECK ONLY, NOT A PROFIT PROMISE.

Walk-forward replay of a REDUCED composite (SEPA + breakout + universe-relative RS)
on strictly trailing, point-in-time windows: at each rebalance date t the score for a
stock uses ONLY bars up to t, top-N are selected, and the forward return is measured
over the next `hold_weeks` using bars after t. No bar from the future ever informs a
selection — no look-ahead.

CAVEATS (read before trusting any number here):
  • SURVIVORSHIP BIAS: the universe is today's index membership. Names that delisted or
    fell out are absent, biasing returns upward.
  • REDUCED SIGNAL: the live sector-momentum component (CSV ranks + RRG) cannot be
    reconstructed point-in-time (we only have a current CSV snapshot), so it is dropped.
    This backtest therefore approximates, not reproduces, the live composite.
  • Use it to rank weight configs and sniff-test that "higher score → better forward
    return," never as an expected-return estimate. The trusted metric is forward_track.py.

CLI:
  python backend/scripts/validation/backtest.py
  python backend/scripts/validation/backtest.py --universe-cap 150 --hold-weeks 4 --top-n 10
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_BACKEND = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from shared.tickers import nse
from shared.yfinance_client import get_bulk_daily
from shared.sepa import score_sepa
from shared.breakout import score_breakout

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

_OUT_DIR = _BACKEND / "data" / "validation"

# Reduced-composite weights (no sector component available point-in-time).
_W_RS, _W_SEPA, _W_BRK = 0.40, 0.35, 0.25
_MIN_ROWS_AT_T = 120


def _universe(db, cap: int) -> list[str]:
    from models import IndexMembership, StockMaster
    broad = [m[0] for m in db.query(IndexMembership.sym)
             .filter(IndexMembership.index_type == "broad").distinct().all()]
    if not broad:
        broad = [r[0] for r in db.query(StockMaster.sym)
                 .filter((StockMaster.yf_ok.is_(True)) | (StockMaster.yf_ok.is_(None))).all()]
    bad = {r[0] for r in db.query(StockMaster.sym)
           .filter((StockMaster.yf_ok.is_(False)) | (StockMaster.is_etf.is_(True))).all()}
    syms = sorted(s for s in set(broad) - bad if "BEES" not in s.upper())
    return syms[:cap]


def _ret(close: pd.Series, days: int) -> float:
    c = close.dropna()
    if len(c) < days:
        return 0.0
    a, b = float(c.iloc[-days]), float(c.iloc[-1])
    return (b - a) / a * 100.0 if a else 0.0


def _rs_ranks(closes: dict[str, pd.Series]) -> dict[str, float]:
    raw = {}
    for sym, c in closes.items():
        c = c.dropna()
        if len(c) < 63:
            continue
        raw[sym] = 0.4 * _ret(c, 63) + 0.2 * _ret(c, 126) + 0.2 * _ret(c, 189) + 0.2 * _ret(c, 252)
    if not raw:
        return {}
    s = pd.Series(raw)
    return {k: float(v) for k, v in (s.rank(pct=True) * 100).items()}


def _truncate(hist: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame | None:
    idx = hist.index
    naive = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
    sub = hist[naive <= t]
    return sub if len(sub) >= _MIN_ROWS_AT_T else None


def _fwd_return(close: pd.Series, t: pd.Timestamp, hold_days: int) -> float | None:
    naive = close.index.tz_localize(None) if getattr(close.index, "tz", None) is not None else close.index
    at_t = close[naive <= t]
    fut = close[naive >= (t + pd.Timedelta(days=hold_days))]
    if at_t.empty or fut.empty:
        return None
    p0, p1 = float(at_t.iloc[-1]), float(fut.iloc[0])
    return round((p1 - p0) / p0 * 100, 2) if p0 else None


def run_backtest(db=None, *, universe_cap: int = 200, hold_weeks: int = 4,
                 step_weeks: int = 4, lookback_weeks: int = 40, top_n: int = 10) -> dict:
    own_db = db is None
    if own_db:
        from database import SessionLocal
        db = SessionLocal()
    try:
        syms = _universe(db, universe_cap)
        log.info("Backtest universe: %d symbols", len(syms))
        bulk = get_bulk_daily([nse(s) for s in syms], period="2y")

        hists: dict[str, pd.DataFrame] = {}
        for s in syms:
            h = bulk.get(nse(s))
            if h is not None and not h.empty and "Close" in h.columns:
                hists[s] = h

        now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
        hold_days = hold_weeks * 7
        # rebalance dates: oldest first, each must leave room for the hold window.
        dates = [now - pd.Timedelta(weeks=w)
                 for w in range(lookback_weeks, hold_weeks - 1, -step_weeks)]

        rebalances = []
        all_returns: list[float] = []
        for t in dates:
            closes_t: dict[str, pd.Series] = {}
            trunc: dict[str, pd.DataFrame] = {}
            for s, h in hists.items():
                ht = _truncate(h, t)
                if ht is not None:
                    trunc[s] = ht
                    closes_t[s] = ht["Close"].dropna()
            if len(closes_t) < top_n:
                continue
            rs = _rs_ranks(closes_t)

            scored = []
            for s, ht in trunc.items():
                sepa = score_sepa(s, ht, rs.get(s))
                brk = score_breakout(s, ht)
                comp = _W_RS * rs.get(s, 0.0) + _W_SEPA * sepa["total"] + _W_BRK * brk["score"]
                scored.append((s, round(comp, 1)))
            scored.sort(key=lambda x: x[1], reverse=True)
            picks = scored[:top_n]

            rets = []
            for s, _c in picks:
                r = _fwd_return(hists[s]["Close"].dropna(), t, hold_days)
                if r is not None:
                    rets.append(r)
            if not rets:
                continue
            sr = pd.Series(rets)
            all_returns.extend(rets)
            rebalances.append({
                "date": t.strftime("%Y-%m-%d"),
                "picks": [s for s, _ in picks],
                "n_with_return": len(rets),
                "hit_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
                "avg_return": round(float(sr.mean()), 2),
            })

        overall = None
        if all_returns:
            s = pd.Series(all_returns)
            overall = {
                "n": len(all_returns),
                "hit_rate": round(sum(1 for r in all_returns if r > 0) / len(all_returns) * 100, 1),
                "avg_return": round(float(s.mean()), 2),
                "median_return": round(float(s.median()), 2),
            }

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "INDICATIVE_ONLY": "Survivorship + reduced-signal biased. Not a profit promise. "
                               "Trusted metric = forward_track.py.",
            "params": {"universe_cap": universe_cap, "hold_weeks": hold_weeks,
                       "step_weeks": step_weeks, "lookback_weeks": lookback_weeks,
                       "top_n": top_n, "weights": {"rs": _W_RS, "sepa": _W_SEPA, "breakout": _W_BRK}},
            "rebalances": rebalances,
            "overall": overall,
        }
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = _OUT_DIR / f"backtest_{datetime.now().strftime('%Y%m%d')}.json"
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        log.info("Backtest report → %s", path.name)
        return report
    finally:
        if own_db:
            db.close()


def _print_summary(rep: dict) -> None:
    print("\n=== INDICATIVE BACKTEST (NOT A PROFIT PROMISE) ===")
    print(rep["INDICATIVE_ONLY"])
    p = rep["params"]
    print(f"\nuniverse={p['universe_cap']} hold={p['hold_weeks']}w step={p['step_weeks']}w "
          f"top_n={p['top_n']} weights={p['weights']}")
    print(f"\n{len(rep['rebalances'])} rebalances (point-in-time):")
    for r in rep["rebalances"]:
        print(f"  {r['date']}: hit={r['hit_rate']}%  avg={r['avg_return']:+}%  n={r['n_with_return']}")
    o = rep.get("overall")
    if o:
        print(f"\nOVERALL: hit={o['hit_rate']}%  avg={o['avg_return']:+}%  "
              f"median={o['median_return']:+}%  n={o['n']}")
    else:
        print("\nNo rebalances produced returns (insufficient history).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Indicative walk-forward backtest")
    ap.add_argument("--universe-cap", type=int, default=200)
    ap.add_argument("--hold-weeks", type=int, default=4)
    ap.add_argument("--step-weeks", type=int, default=4)
    ap.add_argument("--lookback-weeks", type=int, default=40)
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = run_backtest(universe_cap=args.universe_cap, hold_weeks=args.hold_weeks,
                       step_weeks=args.step_weeks, lookback_weeks=args.lookback_weeks,
                       top_n=args.top_n)
    print(json.dumps(rep, indent=2, default=str)) if args.json else _print_summary(rep)
