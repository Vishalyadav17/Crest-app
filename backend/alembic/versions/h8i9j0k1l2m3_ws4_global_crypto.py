"""ws4_global_crypto

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-06-13

WS4: GlobalHolding.status + closed_at;
     CryptoHolding.coingecko_id + status + closed_at.
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("global_holdings", sa.Column("status",    sa.String(), nullable=False, server_default="active"))
    op.add_column("global_holdings", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("crypto_holdings", sa.Column("coingecko_id", sa.String(), nullable=True))
    op.add_column("crypto_holdings", sa.Column("status",       sa.String(), nullable=False, server_default="active"))
    op.add_column("crypto_holdings", sa.Column("closed_at",    sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("global_holdings", "status")
    op.drop_column("global_holdings", "closed_at")

    op.drop_column("crypto_holdings", "coingecko_id")
    op.drop_column("crypto_holdings", "status")
    op.drop_column("crypto_holdings", "closed_at")
