"""후보 매물 분석과 검토 체크리스트를 추가한다.

Revision ID: g6d8f0a2b345
Revises: f5c7a9e1b234
"""
from alembic import op
import sqlalchemy as sa

revision = "g6d8f0a2b345"
down_revision = "f5c7a9e1b234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("analysis_type", sa.String(30), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("analyzed_at", sa.String(32), nullable=True),
        sa.Column("expires_at", sa.String(32), nullable=True),
        sa.Column("created", sa.String(32), nullable=False),
        sa.Column("updated", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["purchase_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["case_properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_analyses_case_id", "candidate_analyses", ["case_id"])
    op.create_index("ix_candidate_analyses_property_id", "candidate_analyses", ["property_id"])
    op.create_index("uq_candidate_analysis_type", "candidate_analyses", ["property_id", "analysis_type"], unique=True)
    op.create_table(
        "candidate_checklist_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="todo"),
        sa.Column("source", sa.String(30), nullable=False, server_default="system"),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.String(32), nullable=True),
        sa.Column("created", sa.String(32), nullable=False),
        sa.Column("updated", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["purchase_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["case_properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_checklist_items_case_id", "candidate_checklist_items", ["case_id"])
    op.create_index("ix_candidate_checklist_items_property_id", "candidate_checklist_items", ["property_id"])
    op.create_index("uq_candidate_checklist_item", "candidate_checklist_items", ["property_id", "category", "title"], unique=True)


def downgrade() -> None:
    op.drop_table("candidate_checklist_items")
    op.drop_table("candidate_analyses")
