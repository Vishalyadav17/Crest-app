from __future__ import annotations
import csv
import io
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_BACKUP_DIR = Path(__file__).parent.parent / "data" / "backups"

_USER_TABLES = [
    "equity_holdings",
    "global_holdings",
    "crypto_holdings",
    "mf_holdings",
    "mf_watchpoints",
    "investment_thesis",
    "swing_trades",
    "watchlists",
    "watchlist_items",
    "price_alerts",
    "price_bands",
    "scan_runs",
    "scan_picks",
    "scan_outcomes",
    "portfolio_meta",
    "portfolio_snapshots",
    "user_preferences",
]


def _rows_for_table(db: Session, user_id: int, table: str) -> list[dict]:
    from sqlalchemy import text
    try:
        # Check if table has user_id column
        has_user = db.execute(
            text(f"SELECT column_name FROM information_schema.columns WHERE table_name=:t AND column_name='user_id'"),
            {"t": table},
        ).fetchone()
        if has_user:
            rows = db.execute(text(f"SELECT * FROM {table} WHERE user_id = :uid"), {"uid": user_id}).mappings().all()
        else:
            # join through scan_runs for scan_picks/outcomes
            if table == "scan_picks":
                rows = db.execute(
                    text("SELECT sp.* FROM scan_picks sp JOIN scan_runs sr ON sr.id=sp.scan_run_id WHERE sr.user_id=:uid"),
                    {"uid": user_id},
                ).mappings().all()
            elif table == "scan_outcomes":
                rows = db.execute(
                    text("SELECT so.* FROM scan_outcomes so JOIN scan_picks sp ON sp.id=so.pick_id JOIN scan_runs sr ON sr.id=sp.scan_run_id WHERE sr.user_id=:uid"),
                    {"uid": user_id},
                ).mappings().all()
            elif table == "watchlist_items":
                rows = db.execute(
                    text("SELECT wi.* FROM watchlist_items wi JOIN watchlists w ON w.id=wi.watchlist_id WHERE w.user_id=:uid"),
                    {"uid": user_id},
                ).mappings().all()
            else:
                rows = []
    except Exception as e:
        log.warning("backup: error reading %s: %s", table, e)
        return []
    return [dict(r) for r in rows]


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def run_backup(user_id: int, db: Session) -> tuple[str, str]:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir  = _BACKUP_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    all_data: dict[str, list[dict]] = {}
    for table in _USER_TABLES:
        rows = _rows_for_table(db, user_id, table)
        all_data[table] = rows
        if not rows:
            continue
        # JSON
        (out_dir / f"{table}.json").write_text(
            json.dumps(rows, default=_serialize, indent=2), encoding="utf-8"
        )
        # CSV
        keys = list(rows[0].keys())
        csv_buf = io.StringIO()
        writer  = csv.DictWriter(csv_buf, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _serialize(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for k, v in row.items()})
        (out_dir / f"{table}.csv").write_text(csv_buf.getvalue(), encoding="utf-8")

    # Combined JSON
    (out_dir / "all_tables.json").write_text(
        json.dumps(all_data, default=_serialize, indent=2), encoding="utf-8"
    )

    # Zip
    zip_path = _BACKUP_DIR / f"crest-backup-{date_str}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in out_dir.iterdir():
            zf.write(f, arcname=f.name)

    log.info("backup: wrote %s tables to %s", len(_USER_TABLES), zip_path)
    return str(zip_path), date_str


def list_backups() -> list[dict]:
    if not _BACKUP_DIR.exists():
        return []
    items = []
    for d in sorted(_BACKUP_DIR.iterdir(), reverse=True):
        if d.is_dir():
            zip_f = _BACKUP_DIR / f"crest-backup-{d.name}.zip"
            items.append({
                "date":     d.name,
                "size_kb":  round(zip_f.stat().st_size / 1024, 1) if zip_f.exists() else None,
                "has_zip":  zip_f.exists(),
            })
    return items[:20]


def get_backup_zip(date_str: str) -> str | None:
    p = _BACKUP_DIR / f"crest-backup-{date_str}.zip"
    return str(p) if p.exists() else None


def job_backup_data() -> None:
    """Weekly backup job — Sun 02:00 IST."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        from crud.prefs import get_all_prefs
        from models import User
        users = db.query(User).all()
        for u in users:
            try:
                run_backup(u.id, db)
            except Exception as e:
                log.warning("backup: user %s failed: %s", u.id, e)
    finally:
        db.close()
