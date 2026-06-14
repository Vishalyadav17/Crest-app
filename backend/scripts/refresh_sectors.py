"""
CLI: refresh backend/data/sectors.json from live NSE index constituents.

Usage:
  python backend/scripts/refresh_sectors.py            # refresh all
  python backend/scripts/refresh_sectors.py --merge    # keep existing + add new
  python backend/scripts/refresh_sectors.py DEFENCE MNC  # specific sectors only
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from shared.tickers import INDEX_CONSTITUENTS_MAP
from shared.index_constituents import fetch_index_constituents

_SECTORS_FILE = _BACKEND / "data" / "sectors.json"


def refresh(targets: list[str] | None = None, merge: bool = False) -> dict[str, list[str]]:
    existing: dict[str, list[str]] = {}
    if merge and _SECTORS_FILE.exists():
        with open(_SECTORS_FILE) as f:
            existing = json.load(f)

    result: dict[str, list[str]] = dict(existing) if merge else {}
    ok, fail = 0, 0

    mapping = INDEX_CONSTITUENTS_MAP
    if targets:
        # targets can be sector names (e.g. DEFENCE) or index_ids (e.g. niftyindiadefence)
        target_set = {t.upper() for t in targets}
        mapping = {
            idx_id: sector_name
            for idx_id, sector_name in INDEX_CONSTITUENTS_MAP.items()
            if sector_name.upper() in target_set or idx_id.upper() in target_set
        }

    for index_id, sector_name in mapping.items():
        print(f"  Fetching {sector_name:18} ({index_id}) ...", end=" ", flush=True)
        records = fetch_index_constituents(index_id)
        if records:
            syms = [r["symbol"] for r in records if r.get("symbol")]
            result[sector_name] = syms
            print(f"{len(syms)} stocks")
            ok += 1
        else:
            print("FAILED")
            fail += 1

    _SECTORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_SECTORS_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nDone: {ok} succeeded, {fail} failed → {_SECTORS_FILE}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("sectors", nargs="*", help="Sector names or index_ids to refresh (default: all)")
    parser.add_argument("--merge", action="store_true", help="Keep existing sectors, only update fetched ones")
    args = parser.parse_args()
    refresh(targets=args.sectors or None, merge=args.merge)
