"""ws2_research_workbench

Revision ID: g7h8i9j0k1l2
Revises: d5e6f7a8b9c0
Create Date: 2026-06-13

WS2: pick_analysis.detail_json + conviction_score;
     scan_reviews.kind column + unique constraint swap.
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pick_analysis: add detail_json + conviction_score
    op.add_column("pick_analysis", sa.Column("detail_json", sa.JSON(), nullable=True))
    op.add_column("pick_analysis", sa.Column("conviction_score", sa.Integer(), nullable=True))

    # scan_reviews: add kind column
    op.add_column("scan_reviews", sa.Column("kind", sa.String(), nullable=False, server_default="auto"))

    # scan_reviews: drop old unique on scan_run_id, add composite unique (scan_run_id, kind)
    op.drop_constraint("scan_reviews_scan_run_id_key", "scan_reviews", type_="unique")
    op.create_unique_constraint("uq_scan_review_run_kind", "scan_reviews", ["scan_run_id", "kind"])


def downgrade() -> None:
    op.drop_constraint("uq_scan_review_run_kind", "scan_reviews", type_="unique")
    op.create_unique_constraint("scan_reviews_scan_run_id_key", "scan_reviews", ["scan_run_id"])
    op.drop_column("scan_reviews", "kind")
    op.drop_column("pick_analysis", "conviction_score")
    op.drop_column("pick_analysis", "detail_json")
