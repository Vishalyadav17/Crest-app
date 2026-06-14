"""
Seed price_bands from research memory entry ranges.
Long-term core + 9-slot picks — valuation-based ideal/acceptable entry zones.
No target (long-term convention); SL left blank to be set from charts later.

Run: .venv/bin/python -m scripts.seed_price_bands [user_id]
Idempotent — re-running upserts by (user, sym, category).
"""
from __future__ import annotations
import sys

from database import SessionLocal
from crud.price_bands import upsert

# (sym, name, ideal_lo, ideal_hi, accept_lo, accept_hi, source, note)
LONG_TERM = [
    ("ITC",        "ITC",                280,  320,  320,  340,  "lt_entry_ranges", "Low-end of hist PE 20-21x. Add now."),
    ("SJS",        "SJS Enterprises",    1650, 1800, 1800, 1900, "lt_entry_ranges", "At research model entry. FY27 target 2687."),
    ("LT",         "Larsen & Toubro",    3400, 3700, 3700, 4000, "lt_entry_ranges", "Slightly above mean PE. Add small."),
    ("NUVAMA",     "Nuvama Wealth",      1280, 1380, 1380, 1480, "lt_entry_ranges", "6% PAT growth weak. Half now, rest on dip."),
    ("HCG",        "HealthCare Global",   570,  620,  620,  655, "lt_entry_ranges", "KKR re-rating thesis. Base case 542-602."),
    ("NH",         "Narayana Hrudayalaya",1600,1750, 1750, 1870, "lt_entry_ranges", "Long-term hospital. No SL. Dip buckets 1800-1820 / 1720-1750."),
    ("ATHERENERG", "Ather Energy",        800,  870,  870,  930, "lt_entry_ranges", "Loss-making. Existing 16 sh @676. Don't add high."),
    ("ADANIPORTS", "Adani Ports",        1450, 1650, 1650, 1750, "lt_entry_ranges", "EV/EBITDA 21% above hist. Wait for dip."),
    ("IEX",        "Indian Energy Exch",  100,  115,  115,  130, "lt_entry_ranges", "Contra bet. RTM/MBED risk. Add 140-150 cautiously."),
    # 9-slot research shortlist
    ("CCL",        "CCL Products",        700,  900, None, None, "entry_watchlist", "Tier 1. Wait for dip, ~24% above."),
    ("HBLENGINE",  "HBL Engineering",     490,  650,  650,  780, "entry_watchlist", "Tier 1. Kavach. Borderline above ideal."),
    ("QPOWER",     "QPower",              800,  950,  950, 1100, "entry_watchlist", "HVDC/STATCOM moat. At top of acceptable."),
    ("GRSE",       "Garden Reach Ship",  2000, 2400, 2400, 2700, "entry_watchlist", "Defence shipbuilder. Top of acceptable."),
    ("GRAVITA",    "Gravita India",      1200, 1500, None, None, "entry_watchlist", "Tier 2 recycler. ~13% above, wait."),
    ("PICCADIL",   "Piccadily Agro",      350,  550,  550,  700, "entry_watchlist", "Indri whisky. In acceptable zone."),
    ("KPL",        "Kwality Pharma",      900, 1166, None, None, "entry_watchlist", "Re-rated post NSE listing. Wait <1300."),
    ("CARTRADE",   "CarTrade Tech",      1400, 1800, 1800, 2200, "entry_watchlist", "FY26 PAT +68%. In acceptable zone."),
]


def main(user_id: int) -> None:
    db = SessionLocal()
    try:
        n = 0
        for sym, name, ilo, ihi, alo, ahi, src, note in LONG_TERM:
            upsert(
                db, user_id, sym, "long_term",
                name=name, ideal_lo=ilo, ideal_hi=ihi,
                accept_lo=alo, accept_hi=ahi, sl=None, target=None,
                source=src, note=note, is_active=True,
            )
            n += 1
        print(f"seeded {n} price bands for user {user_id}")
    finally:
        db.close()


if __name__ == "__main__":
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    main(uid)
