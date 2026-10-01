"""매수 케이스의 최종 후보와 선택 근거를 저장한다.

Revision ID: h7e9a1b3c456
Revises: g6d8f0a2b345
"""
from alembic import op
import sqlalchemy as sa

revision = "h7e9a1b3c456"
down_revision = "g6d8f0a2b345"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_cases", sa.Column("selected_property_id", sa.Integer(), nullable=True))
    op.add_column("purchase_cases", sa.Column("decision_reason", sa.Text(), nullable=False, server_default=""))
    op.add_column("purchase_cases", sa.Column("decided_at", sa.String(32), nullable=True))
    op.create_index("ix_purchase_cases_selected_property_id", "purchase_cases", ["selected_property_id"])
    op.create_foreign_key(
        "fk_purchase_cases_selected_property_id", "purchase_cases", "case_properties",
        ["selected_property_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_purchase_cases_selected_property_id", "purchase_cases", type_="foreignkey")
    op.drop_index("ix_purchase_cases_selected_property_id", table_name="purchase_cases")
    op.drop_column("purchase_cases", "decided_at")
    op.drop_column("purchase_cases", "decision_reason")
    op.drop_column("purchase_cases", "selected_property_id")
