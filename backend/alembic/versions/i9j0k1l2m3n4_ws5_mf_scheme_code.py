"""ws5_mf_scheme_code

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-06-13

WS5: MFHolding.scheme_code (indexed, nullable).
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mf_holdings", sa.Column("scheme_code", sa.String(), nullable=True))
    op.create_index("idx_mf_scheme_code", "mf_holdings", ["scheme_code"])


def downgrade() -> None:
    op.drop_index("idx_mf_scheme_code", table_name="mf_holdings")
    op.drop_column("mf_holdings", "scheme_code")
