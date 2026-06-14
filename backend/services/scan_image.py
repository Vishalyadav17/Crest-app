"""
Render the nightly basket as a dark-theme PNG table — mobile Telegram wraps
<pre>, so we send an image instead. Looks like the Crest scanner.
"""
from __future__ import annotations
import logging
import tempfile

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# palette (matches Crest)
BG = (11, 19, 38); SURF = (23, 31, 51); BORDER = (51, 65, 85)
TEXT = (218, 226, 253); MUTED = (141, 144, 159); MUTED2 = (195, 198, 213)
GREEN = (16, 185, 129); GOLD = (245, 158, 11); PURPLE = (144, 80, 232)
RED = (239, 68, 68); BLUE = (177, 197, 255)

_MONO = "/System/Library/Fonts/Menlo.ttc"
_SANS = "/System/Library/Fonts/HelveticaNeue.ttc"


def _font(path, size, idx=0):
    try:
        return ImageFont.truetype(path, size, index=idx)
    except Exception:
        return ImageFont.load_default()


# Menlo.ttc: 0 regular, 1 bold;  HelveticaNeue.ttc: 0 regular, used for headers
F_ROW   = _font(_MONO, 26, 0)
F_ROWB  = _font(_MONO, 26, 1)
F_HEAD  = _font(_MONO, 22, 1)
F_TITLE = _font(_SANS, 30)
F_SUB   = _font(_SANS, 22)

PAD = 30
ROWH = 42
# (key, x, align)  align: l=left start, r=right edge
COLS = [
    ("TICKER", PAD, "l"),
    ("COMP", PAD + 250, "l"),
    ("ST", PAD + 345, "l"),
    ("CMP", PAD + 590, "r"),
    ("ENTRY ZONE", PAD + 610, "l"),
    ("SL", PAD + 1020, "r"),
    ("TGT", PAD + 1160, "r"),
    ("RR", PAD + 1260, "r"),
]
WIDTH = PAD + 1290


def _n(v, dec=2):
    try:
        return f"{float(v):.{dec}f}"
    except (TypeError, ValueError):
        return "-"


def _draw_cell(d, x, y, text, font, color, align):
    if align == "r":
        d.text((x, y), text, font=font, fill=color, anchor="ra")
    else:
        d.text((x, y), text, font=font, fill=color, anchor="la")


def _open_row(d, y, it):
    p = it["pick"]; t = it["tracking"]; lvl = p.levels or {}
    comp = t.get("composite_live") or p.composite_score or 0
    band = t.get("band_state"); status = t.get("strength_status")
    st_txt, st_col = {"in_band": ("in", GREEN), "approaching": ("wait", BLUE),
                      "extended": ("ext", GOLD)}.get(band, ("", MUTED))
    if status == "weak":
        st_txt, st_col = ("weak", GOLD)
    tk = p.symbol + ("*" if p.tradeability_status == "FLAGGED" else "")
    comp_col = GREEN if comp >= 70 else GOLD
    vals = {
        "TICKER": (tk, F_ROWB, TEXT),
        "COMP": (_n(comp, 1), F_ROW, comp_col),
        "ST": (st_txt, F_ROW, st_col),
        "CMP": (_n(t.get("cmp")), F_ROW, TEXT),
        "ENTRY ZONE": (f"{_n(lvl.get('entry_lo'))}-{_n(lvl.get('entry_hi'))}", F_ROW, MUTED2),
        "SL": (_n(lvl.get("sl")), F_ROW, RED),
        "TGT": (_n(lvl.get("target")), F_ROW, GREEN),
        "RR": (f"{_n(lvl.get('rr'), 1)}" if lvl.get("rr") else "-", F_ROW, MUTED2),
    }
    for key, x, align in COLS:
        txt, font, col = vals[key]
        _draw_cell(d, x, y, txt, font, col, align)


def _closed_row(d, y, it):
    p = it["pick"]; t = it["tracking"]; lvl = p.levels or {}
    win = t.get("close_result") == "TARGET_HIT"
    ret = t.get("return_pct")
    rets = (f"{'+' if (ret or 0) >= 0 else ''}{_n(ret, 1)}%") if ret is not None else "-"
    tk = p.symbol + ("*" if p.tradeability_status == "FLAGGED" else "")
    cells = [
        ("TICKER", tk, F_ROWB, MUTED2),
        ("COMP", _n(t.get("composite_live") or p.composite_score, 1), F_ROW, MUTED),
        ("ST", "TARGET" if win else "SL", F_ROW, GREEN if win else RED),
        ("CMP", _n(t.get("close_level")), F_ROW, MUTED2),
        ("ENTRY ZONE", f"entry {_n(lvl.get('entry'))}", F_ROW, MUTED),
        ("RR", rets, F_ROWB, GREEN if win else RED),
    ]
    cmap = {k: (x, a) for k, x, a in COLS}
    for key, txt, font, col in cells:
        x, align = cmap[key]
        _draw_cell(d, x, y, txt, font, col, align)


def render_basket_image(run, groups, *, basket_date=None, day_n=None, kind="track") -> str:
    enter = groups.get("enterable", [])
    wm = groups.get("missed", []) + groups.get("weak", [])
    closed = groups.get("closed", [])
    ipo = groups.get("ipo", [])

    sections = []  # (label, color, items, closed_style)
    if enter:  sections.append(("ACTIVE - ENTERABLE", GREEN, enter, False))
    if wm:     sections.append(("WEAK / MISSED - zone blown", GOLD, wm, False))
    if closed: sections.append(("CLOSED - scorecard", MUTED, closed, True))
    if ipo:    sections.append(("IPO - informational", PURPLE, ipo, False))

    # height: title(2 lines) + per section (subheader + header + rows) + footer
    h = PAD + 90
    for _, _, items, _c in sections:
        h += 52 + ROWH + len(items) * ROWH + 16
    h += 70

    img = Image.new("RGB", (WIDTH, h), BG)
    d = ImageDraw.Draw(img)
    y = PAD

    title = "Fresh Basket" if kind == "establish" else "Nightly Scan"
    sub = " · ".join(filter(None, [
        f"week of {basket_date}" if basket_date else None,
        f"Day {day_n}" if day_n else None,
        (run.market_summary or {}).get("signal", "NEUTRAL"),
        f"{len(enter)+len(wm)+len(closed)+len(ipo)} fixed"]))
    d.text((PAD, y), title, font=F_TITLE, fill=TEXT, anchor="la"); y += 40
    d.text((PAD, y), sub, font=F_SUB, fill=MUTED, anchor="la"); y += 46

    for label, color, items, closed_style in sections:
        # subheader bar
        d.rectangle([(PAD - 8, y - 4), (WIDTH - PAD + 8, y + 34)], fill=SURF)
        d.rectangle([(PAD - 8, y - 4), (PAD - 4, y + 34)], fill=color)
        d.text((PAD + 6, y + 2), f"{label}  ({len(items)})", font=F_SUB, fill=color, anchor="la")
        y += 50
        # column header
        for key, x, align in COLS:
            _draw_cell(d, x, y, key, F_HEAD, MUTED, align)
        y += ROWH
        d.line([(PAD, y - 8), (WIDTH - PAD, y - 8)], fill=BORDER, width=1)
        for it in items:
            (_closed_row if closed_style else _open_row)(d, y, it)
            y += ROWH
        y += 16

    d.text((PAD, h - 50),
           "in=in zone · approaching · extended · weak=composite<70 · * = surveillance flag",
           font=_font(_SANS, 18), fill=MUTED, anchor="la")
    d.text((PAD, h - 28), "Recommend-only — place manually on Kite.",
           font=_font(_SANS, 18), fill=MUTED, anchor="la")

    path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    img.save(path)
    return path
