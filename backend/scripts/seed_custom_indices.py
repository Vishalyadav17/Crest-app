"""
Idempotent upsert of seeded custom indices from data/custom_indices_seed.json.
Owner = resolved dev user (lowest id).

Usage:
    backend/.venv/bin/python scripts/seed_custom_indices.py [--dry-run]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

# Allow running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal
from models import CustomIndex, CustomIndexMember, User

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "custom_indices_seed.json"


def _resolve_user(db) -> int:
    user = db.query(User).order_by(User.id).first()
    if not user:
        raise RuntimeError("No users in DB — run the app first to seed a user")
    return user.id


def seed(dry_run: bool = False) -> dict:
    db = SessionLocal()
    try:
        user_id = _resolve_user(db)
        data = json.loads(SEED_FILE.read_text())

        # Last element may be the unresolved dict — skip it
        entries = [e for e in data if "name" in e]
        unresolved_block = next((e for e in data if "unresolved" in e), None)

        created = updated = skipped = 0
        total_members = 0

        for entry in entries:
            name = entry["name"]
            syms = entry.get("symbols", [])
            if not syms:
                print(f"  SKIP (no symbols): {name}")
                skipped += 1
                continue

            existing = (
                db.query(CustomIndex)
                .filter(CustomIndex.user_id == user_id, CustomIndex.name == name)
                .one_or_none()
            )

            if existing is None:
                idx = CustomIndex(user_id=user_id, name=name, kind="seeded", weight_mode="mcap")
                if not dry_run:
                    db.add(idx)
                    db.flush()
                created += 1
            else:
                idx = existing
                updated += 1

            if not dry_run:
                # Replace members idempotently
                db.query(CustomIndexMember).filter(CustomIndexMember.custom_index_id == idx.id).delete()
                for sym in syms:
                    db.add(CustomIndexMember(custom_index_id=idx.id, sym=sym))
                total_members += len(syms)

        if not dry_run:
            db.commit()

        if unresolved_block:
            ur = unresolved_block.get("unresolved", [])
            print(f"\nUnresolved symbols ({len(ur)}) — not seeded, edit seed JSON to fix:")
            for item in ur:
                print(f"  {item['sym']:20s}  [{item['index']}]  reason: {item['reason']}")

        print(f"\nSeed complete: {created} created, {updated} updated, {skipped} skipped, {total_members} members total")
        return {"created": created, "updated": updated, "total_members": total_members}
    finally:
        db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    seed(dry_run=dry)
