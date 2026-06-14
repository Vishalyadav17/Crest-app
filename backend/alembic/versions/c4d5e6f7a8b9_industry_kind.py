"""industry_kind

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-09

Add industry_master.kind (basic_industry | sector | broad) so the MCW momentum
engine ranks chartmaze basic-industries and official NSE indices uniformly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('industry_master',
                  sa.Column('kind', sa.String(), nullable=True, server_default='basic_industry'))


def downgrade() -> None:
    op.drop_column('industry_master', 'kind')
