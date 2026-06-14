"""
Scanner v2 — Momentum Discovery Engine (Crest / Module 3) — PRODUCTION.

Real-money pipeline. Picks drive manual Kite trades, so capital protection,
auditability and honest validation are first-class:

  0. Data-quality guard on every price series (shared.data_quality).
  1. Broad-market regime (Nifty index trend + leader breadth).
  2. Sector momentum rank (CSV blend + live MCW) — shared.sector_momentum.
  3. Universe = constituents of leading industries ∪ custom idx ∪ microcap idx.
  4. Live recompute per stock: SEPA + RS(over the candidate universe) + Leadership
     + Breakout quality — one bulk OHLC download, everything derived from it.
  5. Composite Momentum Opportunity Score (config weights).
  6. TRADEABILITY/RISK GATE (shared.tradeability) — hard-exclude un-tradeable names.
  7. Key levels + R:R + RISK SIZING (shared.position_sizing) → top N.
  8. IPO sub-scan (is_ipo universe) → top 2.
  9. Persist + AUDIT SNAPSHOT (crud.scan.save_scan_run) — fully reconstructable.

Recommend-only: emits copy-ready Kite order params; never places an order.
Extends — does not replace — scanner.py (legacy two-pass remains available).

CLI:
  python backend/modules/swing_detector/scanner_v2.py --dry-run
  python backend/modules/swing_detector/scanner_v2.py --dry-run --explain HFCL
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_BACKEND = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from shared.tickers import nse
from shared.yfinance_client import get_bulk_daily
from shared import data_quality as dq
from shared.sepa import score_sepa
from shared.leadership import score_leadership
from shared.breakout import score_breakout
from shared.sector_momentum import rank_sectors
from shared.mcw_index import compute_mcw_index
from shared.tradeability import evaluate as evaluate_tradeability, EXCLUDED
from shared.position_sizing import size_position
from modules.swing_detector.key_levels import compute_key_levels

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

_DATA_DIR     = _BACKEND / "data"
_LAST_RUN     = _DATA_DIR / "last_scan_v2.json"
_SCAN_HISTORY = _DATA_DIR / "scan_history_v2"
_CONFIG       = _BACKEND / "config.json"

_BROAD_TIERS  = ["NIFTY 50", "NIFTY 500", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250"]


# ── config ────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    with open(_CONFIG) as f:
        return json.load(f).get("scanner_v2", {})


# ── inline relative strength over the candidate universe ───────────────────────
# (NOT shared.rs_universe.compute_universe — that one caches under a fixed N500 key
#  and would both pollute and be polluted by the legacy scan. We rank over the true
#  candidate universe, reusing the bulk OHLC already in memory — no extra download.)

def _ret(close: pd.Series, days: int) -> float:
    c = close.dropna()
    if len(c) < days:
        return 0.0
    a, b = float(c.iloc[-days]), float(c.iloc[-1])
    return (b - a) / a * 100.0 if a else 0.0


def _rs_ranks(closes: dict[str, pd.Series]) -> dict[str, float]:
    raw: dict[str, float] = {}
    for sym, c in closes.items():
        c = c.dropna()
        if len(c) < 63:
            continue
        raw[sym] = 0.4 * _ret(c, 63) + 0.2 * _ret(c, 126) + 0.2 * _ret(c, 189) + 0.2 * _ret(c, 252)
    if not raw:
        return {}
    s = pd.Series(raw)
    return {k: round(float(v), 1) for k, v in (s.rank(pct=True) * 100).items()}


def _sector_series(syms: list[str], closes: dict[str, pd.Series]) -> pd.Series | None:
    """Equal-weight rebased mean close of an industry's constituents — leadership ref."""
    valid = [closes[s] for s in syms if s in closes]
    if len(valid) < 2:
        return None
    frame = pd.DataFrame({i: c for i, c in enumerate(valid)}).sort_index().ffill().dropna()
    if len(frame) < 60:
        return None
    return (frame / frame.iloc[0] * 100.0).mean(axis=1)


def _benchmark_close() -> pd.Series | None:
    """Nifty 500 (^CRSLDX) daily close for leadership; fall back to Nifty 50."""
    import yfinance as yf
    for tk in ("^CRSLDX", "^NSEI"):
        try:
            df = yf.download(tk, period="1y", interval="1d",
                             auto_adjust=True, progress=False, timeout=20)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                c = df["Close"].dropna()
                if len(c) >= 63:
                    return c
        except Exception:
            continue
    return None


def _turnover_cr(hist: pd.DataFrame, days: int = 20) -> float | None:
    try:
        v = (hist["Close"] * hist["Volume"]).dropna().tail(days)
        return float(v.mean()) / 1e7 if not v.empty else None  # ₹ → cr
    except Exception:
        return None


# ── broad-market regime ────────────────────────────────────────────────────────

def _broad_regime(db, leader_count: int) -> dict:
    import yfinance as yf
    nifty_up = False
    try:
        df = yf.download("^NSEI", period="6mo", interval="1d",
                         auto_adjust=True, progress=False, timeout=20)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            close = df["Close"].dropna()
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            nifty_up = float(close.iloc[-1]) > ema50
    except Exception as e:
        log.warning("broad_regime nifty EMA check failed: %s", e)

    tiers = {}
    healthy = 0
    for name in _BROAD_TIERS:
        try:
            sig = compute_mcw_index(name, "broad", db)
        except Exception:
            sig = None
        if sig:
            tiers[name] = {"trend_template": sig["trend_template"],
                           "pct_from_52wh": sig["pct_from_52wh"],
                           "breadth_above_ema50": sig["breadth_above_ema50"]}
            if sig["trend_template"]:
                healthy += 1

    signal = "BULLISH" if (nifty_up and leader_count >= 6) else (
             "NEUTRAL" if leader_count >= 3 else "CAUTION")
    return {
        "signal": signal,
        "nifty_above_ema50": nifty_up,
        "leader_sectors": leader_count,
        "broad_tiers_healthy": healthy,
        "tiers": tiers,
    }


# ── universe assembly ──────────────────────────────────────────────────────────

def _leader_universe(db, leader_names: set[str]) -> list[str]:
    from models import IndexMembership, StockMaster
    syms: set[str] = set()
    if leader_names:
        for m in db.query(IndexMembership.sym).filter(IndexMembership.index_name.in_(leader_names)).all():
            syms.add(m[0])
    # ∪ microcap-index ∪ custom-index constituents (always momentum-eligible)
    for row in db.query(StockMaster.sym).filter(
        (StockMaster.is_microcap_idx.is_(True)) | (StockMaster.is_custom_idx.is_(True))
    ).all():
        syms.add(row[0])
    # drop yf-unresolvable + ETFs
    bad = {r[0] for r in db.query(StockMaster.sym).filter(
        (StockMaster.yf_ok.is_(False)) | (StockMaster.is_etf.is_(True))).all()}
    return sorted(s for s in syms - bad if "BEES" not in s.upper())


def _stock_meta(db, syms: list[str]) -> dict[str, dict]:
    from models import StockMaster
    out: dict[str, dict] = {}
    for r in db.query(
        StockMaster.sym, StockMaster.name, StockMaster.basic_industry,
        StockMaster.mcap_cr, StockMaster.is_ipo, StockMaster.listing_date,
    ).filter(StockMaster.sym.in_(syms)).all():
        out[r[0]] = {
            "name": r[1] or r[0], "basic_industry": r[2],
            "mcap_cr": float(r[3]) if r[3] is not None else None,
            "is_ipo": bool(r[4]), "listing_date": r[5],
        }
    return out


def _surveillance_map(db, syms: list[str]) -> dict:
    from models import StockSurveillance
    return {
        r.sym: r for r in
        db.query(StockSurveillance).filter(StockSurveillance.sym.in_(syms)).all()
    }


# ── per-stock scoring over a prefetched bulk ───────────────────────────────────

def _score_universe(
    syms: list[str], bulk: dict, meta: dict,
    sector_scores: dict[str, float], benchmark: pd.Series | None,
    weights: dict, *, asof: datetime | None = None,
) -> tuple[list[dict], dict[str, pd.Series]]:
    # 1) data-quality pass → closes for RS + sector series
    closes: dict[str, pd.Series] = {}
    for sym in syms:
        hist = bulk.get(nse(sym))
        ok, _ = dq.check_series(hist, asof=asof)
        if ok:
            closes[sym] = hist["Close"].dropna()

    rs_ranks = _rs_ranks(closes)

    # 2) per-industry leadership reference series
    by_ind: dict[str, list[str]] = {}
    for sym in closes:
        ind = (meta.get(sym) or {}).get("basic_industry")
        if ind:
            by_ind.setdefault(ind, []).append(sym)
    sector_series = {ind: _sector_series(ss, closes) for ind, ss in by_ind.items()}

    w_sec  = weights.get("sector", 0.30)
    w_rsl  = weights.get("rs_leadership", 0.30)
    w_sepa = weights.get("sepa", 0.25)
    w_brk  = weights.get("breakout", 0.15)

    out: list[dict] = []
    for sym in closes:
        hist = bulk.get(nse(sym))
        m = meta.get(sym, {})
        ind = m.get("basic_industry")
        rs_pct = rs_ranks.get(sym)

        sepa = score_sepa(sym, hist, rs_pct)
        lead = score_leadership(sym, hist, benchmark_close=benchmark,
                                sector_close=sector_series.get(ind))
        brk  = score_breakout(sym, hist, bench_close=benchmark)
        sec_score = sector_scores.get(ind, 0.0) if ind else 0.0

        rs_lead = ((rs_pct or 0.0) + lead["score"]) / 2.0
        composite = round(
            w_sec * sec_score + w_rsl * rs_lead +
            w_sepa * sepa["total"] + w_brk * brk["score"], 1)

        out.append({
            "symbol": sym, "name": m.get("name", sym), "sector": ind,
            "mcap_cr": m.get("mcap_cr"),
            "sepa": sepa, "leadership": lead, "breakout": brk,
            "rs_pct": rs_pct, "sector_momentum_score": round(sec_score, 1),
            "composite_score": composite,
            "turnover_cr": _turnover_cr(hist),
            "is_ipo": m.get("is_ipo", False),
        })

    out.sort(key=lambda x: x["composite_score"], reverse=True)
    return out, closes


# ── finalisation: gate + levels + sizing ───────────────────────────────────────

def _finalise(
    ranked: list[dict], bulk: dict, surv_map: dict, cfg: dict,
    holdings: set[str], top_n: int, *, is_ipo_bucket: bool = False,
    db=None,
) -> list[dict]:
    from shared.earnings_calendar import get_next_earnings, sessions_until_earnings
    risk = cfg.get("risk", {})
    liq  = cfg.get("liquidity", {})
    picks: list[dict] = []
    # Only fetch earnings for the top ~40 finalists to respect rate limits
    earnings_budget = 40

    for c in ranked:
        if len(picks) >= top_n:
            break
        sym = c["symbol"]
        hist = bulk.get(nse(sym))

        gate = evaluate_tradeability(
            sym, surv_map.get(sym), turnover_cr=c.get("turnover_cr"),
            min_turnover_cr=liq.get("min_turnover_cr", 1.0),
            hist=hist)
        if gate["status"] == EXCLUDED:
            log.info("EXCLUDED %s: %s", sym, "; ".join(gate["hard"]))
            continue

        levels = compute_key_levels(sym, hist)  # None if R:R < 2
        if levels is None:
            continue

        # High-confidence (composite ≥ threshold) → 10% slot (₹10k); else 5% (₹5k)
        _hc_thresh = risk.get("high_confidence_composite", 90)
        _slot = (risk.get("slot_size_high", 10000)
                 if (c.get("composite_score") or 0) >= _hc_thresh
                 else risk.get("slot_size", 5000))
        sizing = size_position(
            levels["entry"], levels["sl"], levels["target"],
            capital=risk.get("capital", 100000),
            risk_pct=risk.get("risk_pct_per_trade", 0.01),
            max_pct=risk.get("max_pct_per_position", 0.10),
            mcap_cr=c.get("mcap_cr"),
            mcap_ceiling_cr=risk.get("mcap_fit_ceiling_cr", 30000),
            slot_size=_slot,
            symbol=sym)

        # Earnings proximity: only for top earnings_budget finalists
        earnings_flag: str | None = None
        next_earnings = None
        if earnings_budget > 0 and db is not None:
            try:
                next_earnings = get_next_earnings(sym, db)
                sessions = sessions_until_earnings(next_earnings)
                if sessions is not None and sessions <= 5:
                    earnings_flag = "earnings_soon"
                    gate["flags"].append("earnings_soon")
                    if gate["status"] == OK:
                        gate["status"] = FLAGGED
            except Exception as e:
                log.debug("earnings lookup %s: %s", sym, e)
            earnings_budget -= 1

        # Fetch kb_as_of from industry_master if available
        kb_as_of: str | None = None
        if db is not None and c.get("sector"):
            try:
                from models import IndustryMaster
                row = db.query(IndustryMaster).filter(IndustryMaster.name == c["sector"]).first()
                if row and row.kb_as_of:
                    kb_as_of = row.kb_as_of.isoformat()
            except Exception:
                pass

        # Earnings-setup score (compute from cached QTD order flow)
        earnings_setup: dict | None = None
        if db is not None:
            try:
                from services.earnings_setup import get_or_compute_setup
                setup = get_or_compute_setup(db, sym)
                earnings_setup = setup
                # EARNINGS_SETUP positive badge when strong; upgrades earnings_soon amber → green
                if setup["score"] == "strong":
                    if earnings_flag == "earnings_soon":
                        earnings_flag = "earnings_setup_strong"  # green replaces amber
                    gate["flags"].append("earnings_setup_strong")
                elif setup["score"] == "building" and "earnings_setup_building" not in gate["flags"]:
                    gate["flags"].append("earnings_setup_building")
            except Exception as e:
                log.debug("earnings_setup %s: %s", sym, e)

        audit = {
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "sub_scores": {
                "sepa_total": c["sepa"]["total"],
                "rs_pct": c["rs_pct"],
                "leadership": c["leadership"]["score"],
                "breakout": c["breakout"]["score"],
                "sector_momentum": c["sector_momentum_score"],
                "breakout_components": c["breakout"].get("components", {}),
            },
            "composite_weights": cfg.get("composite_weights", {}),
            "gate": gate,
            "sizing_inputs": sizing.get("inputs"),
            "levels": levels,
            "kb_as_of": kb_as_of,
            "next_earnings": next_earnings.isoformat() if next_earnings else None,
            "earnings_setup": earnings_setup,
        }

        flags = gate["flags"]
        picks.append({
            "symbol": sym, "name": c["name"], "sector": c["sector"],
            "total": c["sepa"]["total"], "grade": c["sepa"]["grade"],
            "criteria": c["sepa"]["criteria"],
            "pullback_signal": c["sepa"].get("pullback_signal"),
            "from_pass": "IPO" if is_ipo_bucket else "v2",
            "levels": levels,
            "mcap_cr": c.get("mcap_cr"),
            "is_holding": sym.upper() in holdings,
            "is_portfolio_fit": bool(sizing.get("mcap_fit")),
            "is_microcap": False,
            "sector_momentum_score": c["sector_momentum_score"],
            "leadership_score": c["leadership"]["score"],
            "breakout_score": c["breakout"]["score"],
            "composite_score": c["composite_score"],
            "is_ipo_pick": is_ipo_bucket,
            "is_ipo": bool(c.get("is_ipo")),  # stock is a recent IPO (independent of which bucket picked it)
            "tradeability_status": gate["status"],
            "tradeability_flags": flags,
            "earnings_flag": earnings_flag,
            "position_size_json": sizing,
            "audit_json": audit,
        })
    return picks


# ── orchestrator ───────────────────────────────────────────────────────────────

def run_scan_v2(db=None, *, dry_run: bool = False, explain: str | None = None,
                persist: bool = True, user_id: int | None = None) -> dict:
    if user_id is None:
        from deps import _get_default_user_id
        user_id = _get_default_user_id()
    start = time.time()
    cfg = _load_config()
    weights = cfg.get("composite_weights", {})
    threshold = cfg.get("sector_score_threshold", 60)
    top_n = cfg.get("top_n", 10)
    ipo_top_n = cfg.get("ipo_top_n", 2)

    import json as _json
    with open(_CONFIG) as f:
        full_cfg = _json.load(f)
    holdings = {h.upper() for h in full_cfg.get("my_holdings", [])}

    own_db = db is None
    if own_db:
        from database import SessionLocal
        db = SessionLocal()

    try:
        log.info("=== Scanner v2 started ===")

        # 2. Sector momentum rank → leaders
        log.info("Ranking sectors")
        ranked_sectors = rank_sectors(db)
        leaders = [s for s in ranked_sectors if (s["score"] or 0) >= threshold]
        leader_names = {s["name"] for s in leaders}
        sector_scores = {s["name"]: (s["score"] or 0.0) for s in ranked_sectors}
        log.info("%d/%d sectors qualify (>=%s)", len(leaders), len(ranked_sectors), threshold)

        # 1. Broad regime
        regime = _broad_regime(db, len(leaders))

        # 3. Universe
        universe = _leader_universe(db, leader_names)
        log.info("Universe = %d candidates", len(universe))
        meta = _stock_meta(db, universe)
        surv_map = _surveillance_map(db, universe)

        # 4. One bulk download
        log.info("Bulk downloading %d symbols (1y)", len(universe))
        bulk = get_bulk_daily([nse(s) for s in universe], period="1y")
        benchmark = _benchmark_close()

        # 4-5. Score + composite
        ranked, _closes = _score_universe(
            universe, bulk, meta, sector_scores, benchmark, weights)

        # 6-7. Gate + levels + sizing → top N
        picks = _finalise(ranked, bulk, surv_map, cfg, holdings, top_n, db=db)

        # 8. IPO sub-scan
        ipo_picks: list[dict] = []
        from models import StockMaster
        ipo_syms = [r[0] for r in db.query(StockMaster.sym).filter(
            StockMaster.is_ipo.is_(True),
            (StockMaster.yf_ok.is_(True)) | (StockMaster.yf_ok.is_(None))).all()]
        ipo_syms = [s for s in ipo_syms if "BEES" not in s.upper()]
        if ipo_syms:
            log.info("IPO sub-scan: %d candidates", len(ipo_syms))
            ipo_meta = _stock_meta(db, ipo_syms)
            ipo_surv = _surveillance_map(db, ipo_syms)
            ipo_bulk = get_bulk_daily([nse(s) for s in ipo_syms], period="1y")
            # IPOs are young → emphasise RS+breakout, relax sector dependency.
            ipo_weights = {"sector": 0.15, "rs_leadership": 0.35, "sepa": 0.20, "breakout": 0.30}
            ipo_ranked, _ = _score_universe(
                ipo_syms, ipo_bulk, ipo_meta, sector_scores, benchmark, ipo_weights)
            ipo_picks = _finalise(ipo_ranked, ipo_bulk, ipo_surv, cfg, holdings,
                                  ipo_top_n, is_ipo_bucket=True, db=db)

        elapsed = round(time.time() - start, 1)
        result = {
            "picks": picks,
            "ipo_picks": ipo_picks,
            "market_summary": regime,
            "sector_ranking": [
                {"name": s["name"], "kind": s["kind"], "score": s["score"]}
                for s in ranked_sectors[:15]
            ],
            "scan_time": datetime.now().strftime("%H:%M"),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "top_n": top_n,
            "min_score": threshold,
            "scanner_version": "v2",
            "universe_size": len(universe),
            "pass1_candidates": len(universe),
            "total_qualified": len(picks),
        }

        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_LAST_RUN, "w") as f:
            json.dump(result, f, indent=2, default=str)
        _SCAN_HISTORY.mkdir(parents=True, exist_ok=True)
        wk = datetime.now().strftime("week_%Y-W%W")
        with open(_SCAN_HISTORY / f"{wk}.json", "w") as f:
            json.dump(result, f, indent=2, default=str)

        if persist and not dry_run:
            try:
                from crud.scan import save_scan_run
                run_id = save_scan_run(db, user_id, {**result, "picks": picks + ipo_picks})
                result["run_id"] = run_id
                log.info("Persisted scan run #%s", run_id)
            except Exception as e:
                log.error("persist failed: %s", e)

        if explain:
            sym = explain.upper()
            match = next((p for p in picks + ipo_picks if p["symbol"] == sym), None)
            if match:
                print(json.dumps(match, indent=2, default=str))
            else:
                cand = next((c for c in ranked if c["symbol"] == sym), None)
                if cand:
                    print(f"{sym} scored but dropped (gate/R:R/top-N).")
                    print(json.dumps({k: cand[k] for k in
                          ("composite_score", "rs_pct", "sector_momentum_score")}, indent=2))
                else:
                    print(f"{sym} not in candidate universe.")

        log.info("Scanner v2 complete: %d picks + %d IPO in %.1fs",
                 len(picks), len(ipo_picks), elapsed)

        if dry_run:
            _print_dry_run(result)
        return result
    finally:
        if own_db:
            db.close()


def _print_dry_run(result: dict) -> None:
    r = result["market_summary"]
    print("\n=== SCANNER v2 DRY RUN ===")
    print(f"Regime: {r['signal']} | Nifty>EMA50={r['nifty_above_ema50']} | "
          f"leader sectors={r['leader_sectors']} | universe={result['universe_size']}")
    print("\nTop sectors:")
    for s in result["sector_ranking"][:8]:
        print(f"  {s['score']:>5} {s['name']} ({s['kind']})")
    print(f"\nTop {len(result['picks'])} picks:")
    for i, p in enumerate(result["picks"], 1):
        lvl, sz = p.get("levels") or {}, p.get("position_size_json") or {}
        tag = "[HOLD] " if p["is_holding"] else ""
        tag += "[FLAG] " if p["tradeability_status"] == "FLAGGED" else ""
        print(f"{i:2}. {p['symbol']:12} {tag}Comp={p['composite_score']:>5} "
              f"SEPA={p['total']:>3} RSlead={p.get('leadership_score'):>5} "
              f"Brk={p.get('breakout_score'):>5} Sec={p['sector_momentum_score']:>5} | "
              f"Entry=₹{lvl.get('entry','?')} SL=₹{lvl.get('sl','?')} "
              f"Tgt=₹{lvl.get('target','?')} R:R={lvl.get('rr','?')} | "
              f"qty={sz.get('qty','?')} risk=₹{sz.get('risk_amount','?')}")
    if result["ipo_picks"]:
        print("\nIPO Breakouts (Top 2):")
        for p in result["ipo_picks"]:
            lvl = p.get("levels") or {}
            print(f"  {p['symbol']:12} Comp={p['composite_score']:>5} "
                  f"Entry=₹{lvl.get('entry','?')} R:R={lvl.get('rr','?')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scanner v2 — momentum discovery engine")
    ap.add_argument("--dry-run", action="store_true", help="Print results, skip persist")
    ap.add_argument("--explain", metavar="TICKER", help="Full breakdown for a ticker")
    ap.add_argument("--no-persist", action="store_true", help="Skip DB persistence")
    args = ap.parse_args()
    run_scan_v2(dry_run=args.dry_run, explain=args.explain, persist=not args.no_persist)
