"""
One-time cleanup for Alpha Scanner vault data.

Fixes two issues:
  1. Duplicate ScanPick rows sharing (scan_run_id, symbol) — keep highest composite_score,
     re-point child scan_outcomes / pick_analysis to the survivor, delete the loser pick.
  2. Multiple ScanRun rows in the same Sunday-week (rolling weekly basket should be ONE folder)
     — keep the latest run as the week basket, re-point other runs' picks into it, then dedupe.

Idempotent. Defaults to DRY RUN; pass --apply to commit.

    python -m scripts.cleanup_scan_dedupe            # dry run
    python -m scripts.cleanup_scan_dedupe --apply    # commit
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from database import SessionLocal
from models import ScanRun, ScanPick, ScanOutcome, PickAnalysis
from jobs.scan_jobs import _month_key


def _composite(p: ScanPick) -> float:
    return p.composite_score if p.composite_score is not None else (p.total_score or -1.0)


def _repoint_children(db, loser_id: int, winner_id: int) -> None:
    # scan_outcomes: no unique constraint — safe to repoint all
    db.query(ScanOutcome).filter(ScanOutcome.scan_pick_id == loser_id).update(
        {ScanOutcome.scan_pick_id: winner_id}, synchronize_session=False)
    # pick_analysis: unique (scan_pick_id, kind) — drop loser rows whose kind the winner already has
    winner_kinds = {
        k for (k,) in db.query(PickAnalysis.kind)
        .filter(PickAnalysis.scan_pick_id == winner_id).all()
    }
    for a in db.query(PickAnalysis).filter(PickAnalysis.scan_pick_id == loser_id).all():
        if a.kind in winner_kinds:
            db.delete(a)
        else:
            a.scan_pick_id = winner_id
            winner_kinds.add(a.kind)
    db.flush()


def _dedupe_run(db, run_id: int, apply: bool) -> int:
    """Within one run, collapse duplicate symbols. Returns #picks deleted."""
    picks = db.query(ScanPick).filter(ScanPick.scan_run_id == run_id).all()
    by_sym: dict[str, list[ScanPick]] = defaultdict(list)
    for p in picks:
        by_sym[p.symbol].append(p)

    deleted = 0
    for sym, group in by_sym.items():
        if len(group) < 2:
            continue
        group.sort(key=_composite, reverse=True)
        winner = group[0]
        losers = group[1:]
        print(f"    dup {sym}: keep pick#{winner.id} (comp={_composite(winner)}), "
              f"drop {[l.id for l in losers]}")
        for loser in losers:
            if apply:
                _repoint_children(db, loser.id, winner.id)
                db.delete(loser)
            deleted += 1
    return deleted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit changes (default: dry run)")
    args = ap.parse_args()
    apply = args.apply

    db = SessionLocal()
    try:
        runs = db.query(ScanRun).order_by(ScanRun.user_id, ScanRun.scanned_at).all()

        # 1) collapse same Sunday-week runs per user → keep latest run id
        groups: dict[tuple[int, str], list[ScanRun]] = defaultdict(list)
        for r in runs:
            if not r.scanned_at:
                continue
            groups[(r.user_id, _month_key(r.scanned_at))].append(r)

        merged_run_ids: set[int] = set()
        for (user_id, week), wk_runs in groups.items():
            if len(wk_runs) < 2:
                continue
            wk_runs.sort(key=lambda r: r.scanned_at)
            keep = wk_runs[-1]
            others = wk_runs[:-1]
            print(f"week {week} user {user_id}: keep run#{keep.id} "
                  f"({keep.scanned_at:%Y-%m-%d}), merge {[r.id for r in others]}")
            for other in others:
                moved = db.query(ScanPick).filter(ScanPick.scan_run_id == other.id).all()
                print(f"    move {len(moved)} picks from run#{other.id} → run#{keep.id}")
                if apply:
                    db.query(ScanPick).filter(ScanPick.scan_run_id == other.id).update(
                        {ScanPick.scan_run_id: keep.id}, synchronize_session=False)
                    db.delete(other)  # scan_reviews cascade
            merged_run_ids.add(keep.id)

        if apply:
            db.flush()

        # 2) dedupe symbols within every (possibly-merged) run
        total_deleted = 0
        run_ids = [r.id for r in db.query(ScanRun.id).all()] if apply else \
            sorted({r.id for r in runs} | merged_run_ids)
        for rid in run_ids:
            if db.query(ScanRun).filter(ScanRun.id == rid).first() is None:
                continue
            print(f"run#{rid}: dedupe symbols")
            total_deleted += _dedupe_run(db, rid, apply)

        print(f"\n{'APPLIED' if apply else 'DRY RUN'} — picks deleted: {total_deleted}, "
              f"week-merges: {sum(1 for v in groups.values() if len(v) > 1)}")
        if apply:
            db.commit()
            print("committed.")
        else:
            print("re-run with --apply to commit.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
