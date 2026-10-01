"""매수 검토 케이스에 관심 지역과 판단 당시 통계를 저장한다.

Revision ID: f5c7a9e1b234
Revises: e4b6f8d0a123
"""
from alembic import op
import sqlalchemy as sa

revision = "f5c7a9e1b234"
down_revision = "e4b6f8d0a123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_regions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(10), nullable=False),
        sa.Column("region_name", sa.String(255), nullable=False),
        sa.Column("source", sa.String(30), nullable=False, server_default="market_explorer"),
        sa.Column("property_type", sa.String(30), nullable=False, server_default="all"),
        sa.Column("budget_max_won", sa.BigInteger(), nullable=True),
        sa.Column("period_from", sa.String(6), nullable=True),
        sa.Column("period_to", sa.String(6), nullable=True),
        sa.Column("stats_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["purchase_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["region_code"], ["legal_regions.code"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_regions_case_id", "case_regions", ["case_id"])
    op.create_index("ix_case_regions_region_code", "case_regions", ["region_code"])
    op.create_index("uq_case_regions_case_region", "case_regions", ["case_id", "region_code"], unique=True)


def downgrade() -> None:
    op.drop_table("case_regions")
