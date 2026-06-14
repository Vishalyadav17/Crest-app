"""scan_pick_added_at

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-06-14

Per-pick basket-entry timestamp. The monthly basket grows via daily merge, so a pick added
mid-month must track SL/target/return from when IT was added — not from the run's establish
date. Backfills existing picks to their run's scanned_at.
"""
from alembic import op
import sqlalchemy as sa

revision = "o5p6q7r8s9t0"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scan_picks", sa.Column("added_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        UPDATE scan_picks sp SET added_at = r.scanned_at
        FROM scan_runs r WHERE r.id = sp.scan_run_id AND sp.added_at IS NULL
    """)


def downgrade():
    op.drop_column("scan_picks", "added_at")
