"""scan_pick_is_ipo

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-06-14

Stock-level recent-IPO flag on scan_picks, distinct from is_ipo_pick (which only marks picks
that came from the IPO sub-scan bucket). Lets a normal-scan pick whose underlying stock is a
recent IPO (e.g. BELRISE) be clearly tagged as an IPO.
"""
from alembic import op
import sqlalchemy as sa

revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scan_picks", sa.Column("is_ipo", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Backfill from stock_master.is_ipo (match full symbol then series-stripped base)
    op.execute("""
        UPDATE scan_picks sp SET is_ipo = TRUE
        FROM stock_master sm
        WHERE sm.is_ipo IS TRUE
          AND (sm.sym = sp.symbol OR sm.sym = split_part(sp.symbol, '-', 1))
    """)


def downgrade():
    op.drop_column("scan_picks", "is_ipo")
