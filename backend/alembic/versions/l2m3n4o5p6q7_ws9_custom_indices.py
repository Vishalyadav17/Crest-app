"""ws9_custom_indices

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-06-13

WS9: Custom indices on Wavesight.
  - custom_indices: new table
  - custom_index_members: new table
  - custom_index_history: new table
"""
from alembic import op
import sqlalchemy as sa

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "custom_indices",
        sa.Column("id",          sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("user_id",     sa.Integer(),  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name",        sa.String(),   nullable=False),
        sa.Column("kind",        sa.String(),   nullable=False, server_default="user"),
        sa.Column("weight_mode", sa.String(),   nullable=False, server_default="mcap"),
        sa.Column("base_date",   sa.String(),   nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "name", name="uq_custom_index_user_name"),
    )
    op.create_index("idx_custom_indices_user_id", "custom_indices", ["user_id"])

    op.create_table(
        "custom_index_members",
        sa.Column("id",              sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("custom_index_id", sa.Integer(), sa.ForeignKey("custom_indices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sym",             sa.String(),  nullable=False),
        sa.UniqueConstraint("custom_index_id", "sym", name="uq_custom_index_member"),
    )
    op.create_index("idx_custom_index_members_idx_id", "custom_index_members", ["custom_index_id"])

    op.create_table(
        "custom_index_history",
        sa.Column("id",              sa.Integer(),          primary_key=True, autoincrement=True),
        sa.Column("custom_index_id", sa.Integer(),          sa.ForeignKey("custom_indices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date",            sa.String(),           nullable=False),
        sa.Column("value",           sa.Numeric(18, 4),     nullable=False),
        sa.UniqueConstraint("custom_index_id", "date", name="uq_custom_index_history"),
    )
    op.create_index("idx_custom_index_history_idx_id", "custom_index_history", ["custom_index_id"])
    op.create_index("idx_custom_index_history_date",   "custom_index_history", ["date"])


def downgrade():
    op.drop_table("custom_index_history")
    op.drop_table("custom_index_members")
    op.drop_table("custom_indices")
