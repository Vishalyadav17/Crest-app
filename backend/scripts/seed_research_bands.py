"""
Upsert PriceBand rows with research-updated entry zones (2026-06-13).
Values reflect current price action vs. older ideal/acceptable ranges in seed_price_bands.py.

Run: .venv/bin/python -m scripts.seed_research_bands [user_id]
Idempotent — upserts by (user, sym, category); existing rows updated, others untouched.
"""
from __future__ import annotations
import sys

from database import SessionLocal
from crud.price_bands import upsert

# (sym, name, ideal_lo, ideal_hi, accept_lo, accept_hi, note)
RESEARCH_BANDS = [
    ("CCL",       "CCL Products",           950,  1050, 1050, 1130, "FY26 re-rated; old 700-900 zone stale; 200DMA 991"),
    ("QPOWER",    "Quality Power",           950,  1050, 1050, 1150, "Sangli Jul-Aug 2026 catalyst; don't chase >1300 pre-Q1FY27"),
    ("HBLENGINE", "HBL Power Systems",       580,   650,  650,  750, "in old acceptable zone now; downtrend — stagger"),
    ("GRSE",      "Garden Reach Ship",      2000,  2400, 2300, 2550, "200DMA 2547 confluence"),
    ("GRAVITA",   "Gravita India",          1200,  1350, 1380, 1500, "falling into zone; watch RMI execution"),
    ("PICCADIL",  "Piccadily Agro",          450,   550,  500,  575, "averaging zone active; half position from 593"),
    ("KPL",       "Kwality Pharma",         1900,  2100, 2100, 2250, "at ATH 2493; tiny float; only on pullback + valuation recheck"),
    ("CARTRADE",  "CarTrade Tech",          1800,  2000, 2100, 2250, "holding from 1825; volatile"),
    ("APOLLO",    "Apollo Micro Systems",    320,   345,  345,  370, "extended +20% over 50DMA; add on retest"),
    ("SUPREMEPWR","Supreme Power Equipment", 200,   220,  220,  235, "post-Q4 confirm"),
    ("ITC",       "ITC",                     260,   290,  290,  320, "AT ideal bottom now (282) — active"),
    ("HCG",       "HealthCare Global",       570,   610,  610,  640, "active zone"),
    ("NH",        "Narayana Hrudayalaya",   1600,  1750, 1750, 1800, "wait <1750"),
    ("IEX",       "Indian Energy Exch",      100,   110,  110,  120, "structural headwind — cautious"),
]


def main(user_id: int) -> None:
    db = SessionLocal()
    try:
        n = 0
        for sym, name, ilo, ihi, alo, ahi, note in RESEARCH_BANDS:
            upsert(
                db, user_id, sym, "long_term",
                name=name, ideal_lo=ilo, ideal_hi=ihi,
                accept_lo=alo, accept_hi=ahi, sl=None, target=None,
                source="research_2026", note=note, is_active=True,
            )
            n += 1
        print(f"upserted {n} research bands for user {user_id}")
    finally:
        db.close()


if __name__ == "__main__":
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    main(uid)
