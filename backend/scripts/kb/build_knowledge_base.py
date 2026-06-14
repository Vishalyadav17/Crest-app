"""
Scanner v2 knowledge-base builder — orchestrates all KB ingestion (idempotent).

Usage:
  python -m scripts.kb.build_knowledge_base --dry-run        # counts only, no writes
  python -m scripts.kb.build_knowledge_base                  # full build
  python -m scripts.kb.build_knowledge_base --skip-surveillance --skip-yf
  python -m scripts.kb.build_knowledge_base --source-dir /path/to/index_scans

Order matters: industries + chartmaze (sets basic_industry) before nse_indices
(enriches momentum, never basic_industry); network steps (surveillance, yf) last.
"""
from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from database import SessionLocal
from scripts.kb import (
    common,
    ingest_industry_analytics,
    ingest_chartmaze,
    ingest_nse_indices,
    ingest_recent_ipos,
    ingest_broad_indices,
    ingest_custom_indices,
    ingest_surveillance,
    resolve_yf,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("kb.build")


def build(source_dir: Path, dry_run: bool, skip_surveillance: bool, skip_yf: bool) -> dict:
    db = SessionLocal()
    summary: dict = {}
    try:
        summary["industry_analytics"] = ingest_industry_analytics.ingest(db, source_dir, dry_run)
        summary["chartmaze"]          = ingest_chartmaze.ingest(db, source_dir, dry_run)
        summary["nse_indices"]        = ingest_nse_indices.ingest(db, source_dir, dry_run)
        summary["recent_ipos"]        = ingest_recent_ipos.ingest(db, source_dir, dry_run)
        summary["broad_indices"]      = ingest_broad_indices.ingest(db, dry_run)
        summary["custom_indices"]     = ingest_custom_indices.ingest(db, source_dir, dry_run)
        if not skip_surveillance:
            summary["surveillance"] = ingest_surveillance.ingest(db, dry_run)
        if not skip_yf:
            summary["resolve_yf"] = resolve_yf.ingest(db, dry_run)
    finally:
        db.close()
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Scanner v2 knowledge base")
    ap.add_argument("--dry-run", action="store_true", help="counts only, no DB writes")
    ap.add_argument("--source-dir", default=str(common.KB_SOURCE_DIR))
    ap.add_argument("--skip-surveillance", action="store_true", help="skip NSE network fetch")
    ap.add_argument("--skip-yf", action="store_true", help="skip yfinance resolution")
    args = ap.parse_args()

    summary = build(Path(args.source_dir), args.dry_run, args.skip_surveillance, args.skip_yf)

    print("\n=== KB BUILD SUMMARY%s ===" % (" (DRY RUN)" if args.dry_run else ""))
    for step, res in summary.items():
        print(f"  {step:20} {res}")


if __name__ == "__main__":
    main()
