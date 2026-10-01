"""매수 검토 케이스와 후보 부동산을 추가한다.

Revision ID: e4b6f8d0a123
Revises: d3a5e7c9f012
"""
from alembic import op
import sqlalchemy as sa

revision = "e4b6f8d0a123"
down_revision = "d3a5e7c9f012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_cases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="exploring"),
        sa.Column("purpose", sa.String(20), nullable=False, server_default="purchase"),
        sa.Column("budget_min", sa.BigInteger(), nullable=True),
        sa.Column("budget_max", sa.BigInteger(), nullable=True),
        sa.Column("target_regions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created", sa.String(32), nullable=False),
        sa.Column("updated", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_cases_user_id", "purchase_cases", ["user_id"])
    op.create_index("ix_purchase_cases_status", "purchase_cases", ["status"])
    op.create_index("ix_purchase_cases_created", "purchase_cases", ["created"])
    op.create_table(
        "case_properties",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(30), nullable=False, server_default=""),
        sa.Column("asking_price", sa.BigInteger(), nullable=True),
        sa.Column("area_sqm", sa.Float(), nullable=True),
        sa.Column("legal_region_code", sa.String(10), nullable=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(20), nullable=False, server_default="reviewing"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("history_id", sa.Integer(), nullable=True),
        sa.Column("created", sa.String(32), nullable=False),
        sa.Column("updated", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["purchase_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["history_id"], ["history.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_properties_case_id", "case_properties", ["case_id"])
    op.create_index("ix_case_properties_history_id", "case_properties", ["history_id"])
    op.create_index("ix_case_properties_legal_region_code", "case_properties", ["legal_region_code"])
    op.create_index("idx_case_properties_case_status", "case_properties", ["case_id", "status"])


def downgrade() -> None:
    op.drop_table("case_properties")
    op.drop_table("purchase_cases")
