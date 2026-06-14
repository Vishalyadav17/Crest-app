"""
Build the nightly scan Telegram report (HTML) from a re-checked basket.

Layout: a short summary header, then one monospace <pre> table per non-empty
group (Enterable / Weak-Missed / Closed / IPO). Telegram renders <pre> in a
fixed-width font and lets it scroll horizontally, so columns stay aligned.
Telegram HTML supports only <b>/<i>/<code>/<pre>/<a>; escape < > & in text.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))

# column widths for the aligned tables
_W = {"tk": 12, "comp": 5, "st": 5, "cmp": 9, "zone": 17, "sl": 9, "tgt": 9, "rr": 5}

_ST = {"in_band": "in", "approaching": "wait", "extended": "ext"}


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _n(v, dec=2) -> str:
    try:
        return f"{float(v):.{dec}f}"
    except (TypeError, ValueError):
        return "-"


def _ticker(p) -> str:
    t = p.symbol + ("*" if p.tradeability_status == "FLAGGED" else "")
    return t


def _row(cols) -> str:
    tk, comp, st, cmp_, zone, sl, tgt, rr = cols
    return (f"{tk:<{_W['tk']}}{comp:<{_W['comp']}}{st:<{_W['st']}}"
            f"{cmp_:>{_W['cmp']}}  {zone:<{_W['zone']}}{sl:>{_W['sl']}}"
            f"{tgt:>{_W['tgt']}}{rr:>{_W['rr']}}")


_HEADER = _row(("TICKER", "COMP", "ST", "CMP", "ENTRY ZONE", "SL", "TGT", "RR"))


def _open_table(items) -> str:
    lines = [_HEADER]
    for it in items:
        p = it["pick"]; t = it["tracking"]; lvl = p.levels or {}
        comp = t.get("composite_live") or p.composite_score
        st = _ST.get(t.get("band_state"), "")
        if t.get("strength_status") == "weak":
            st = "weak"
        zone = f"{_n(lvl.get('entry_lo'))}-{_n(lvl.get('entry_hi'))}"
        lines.append(_row((
            _ticker(p), _n(comp, 1), st, _n(t.get("cmp")), zone,
            _n(lvl.get("sl")), _n(lvl.get("target")),
            _n(lvl.get("rr"), 1) if lvl.get("rr") else "-")))
    return "<pre>" + _esc("\n".join(lines)) + "</pre>"


def _closed_table(items) -> str:
    head = f"{'TICKER':<12}{'RESULT':<9}{'RET%':>7}  {'ENTRY':>9}{'EXIT':>10}"
    lines = [head]
    for it in items:
        p = it["pick"]; t = it["tracking"]; lvl = p.levels or {}
        res = "TARGET" if t.get("close_result") == "TARGET_HIT" else "SL"
        ret = t.get("return_pct")
        rets = (f"{'+' if (ret or 0) >= 0 else ''}{_n(ret, 1)}") if ret is not None else "-"
        lines.append(f"{_ticker(p):<12}{res:<9}{rets:>7}  "
                     f"{_n(lvl.get('entry')):>9}{_n(t.get('close_level')):>10}")
    return "<pre>" + _esc("\n".join(lines)) + "</pre>"


def build_caption(run, groups, *, basket_date=None, day_n=None, kind="track") -> str:
    """Short HTML caption for the table image (Telegram caption limit 1024)."""
    enter = groups.get("enterable", [])
    wm = groups.get("missed", []) + groups.get("weak", [])
    closed = groups.get("closed", [])
    ipo = groups.get("ipo", [])
    total = len(enter) + len(wm) + len(closed) + len(ipo)
    signal = (run.market_summary or {}).get("signal", "NEUTRAL")
    now_ist = datetime.now(_IST)
    title = "🆕 <b>Fresh Basket</b>" if kind == "establish" else "🌙 <b>Nightly Scan</b>"
    sub = " · ".join(filter(None, [
        f"week of {basket_date}" if basket_date else None,
        f"Day {day_n}" if day_n else None, signal]))
    parts = [f"{title} — {now_ist.strftime('%a %d %b, %-I %p')}", f"<i>{sub}</i>",
             f"<b>{total} fixed</b> · {len(enter)} enterable · {len(wm)} weak/missed · "
             f"{len(closed)} closed · {len(ipo)} IPO"]
    if closed:
        wins = sum(1 for c in closed if c["tracking"].get("close_result") == "TARGET_HIT")
        parts.append(f"Scorecard: {wins}/{len(closed)} hit target")
    parts.append("<i>Recommend-only — place manually on Kite.</i>")
    return "\n".join(parts)


def build_report(run, groups, *, basket_date=None, day_n=None, kind="track") -> str:
    counts = groups.get("counts", {})
    ms = run.market_summary or {}
    signal = ms.get("signal", "NEUTRAL")
    now_ist = datetime.now(_IST)
    title = "🆕 <b>Fresh Basket</b>" if kind == "establish" else "🌙 <b>Nightly Scan</b>"

    enter = groups.get("enterable", [])
    wm = groups.get("missed", []) + groups.get("weak", [])
    closed = groups.get("closed", [])
    ipo = groups.get("ipo", [])
    total = len(enter) + len(wm) + len(closed) + len(ipo)

    sub = []
    if basket_date:
        sub.append(f"week of {basket_date}")
    if day_n:
        sub.append(f"Day {day_n}")
    sub.append(signal)

    out = [
        f"{title} — {now_ist.strftime('%a %d %b, %-I %p')}",
        "<i>" + " · ".join(sub) + "</i>",
        f"<b>{total} fixed</b> · {len(enter)} enterable · {len(wm)} weak/missed · "
        f"{len(closed)} closed · {len(ipo)} IPO",
    ]

    if enter:
        out += ["", f"✅ <b>ENTERABLE ({len(enter)})</b>", _open_table(enter)]
    if wm:
        out += ["", f"⚠️ <b>WEAK / MISSED ({len(wm)})</b> — zone blown / faded", _open_table(wm)]
    if closed:
        wins = sum(1 for c in closed if c["tracking"].get("close_result") == "TARGET_HIT")
        out += ["", f"🔒 <b>CLOSED ({len(closed)})</b> — {wins}/{len(closed)} hit target",
                _closed_table(closed)]
    if ipo:
        out += ["", f"🚀 <b>IPO ({len(ipo)})</b> — informational", _open_table(ipo)]

    out += ["", "<i>ST: in=in zone · wait=approaching · ext=extended · weak=composite&lt;70 · "
                "* = surveillance flag. Recommend-only — place manually on Kite.</i>"]
    return "\n".join(out)
