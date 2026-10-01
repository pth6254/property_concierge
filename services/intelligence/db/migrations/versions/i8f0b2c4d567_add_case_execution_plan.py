"""거래 준비 실행 계획과 작업을 추가한다.

Revision ID: i8f0b2c4d567
Revises: h7e9a1b3c456
"""
from alembic import op
import sqlalchemy as sa

revision = "i8f0b2c4d567"
down_revision = "h7e9a1b3c456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_execution_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("contract_planned_date", sa.String(10), nullable=True),
        sa.Column("closing_planned_date", sa.String(10), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="preparing"),
        sa.Column("created", sa.String(32), nullable=False),
        sa.Column("updated", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["purchase_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["case_properties.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("case_id"),
    )
    op.create_index("ix_case_execution_plans_case_id", "case_execution_plans", ["case_id"], unique=True)
    op.create_index("ix_case_execution_plans_property_id", "case_execution_plans", ["property_id"])
    op.create_table(
        "case_execution_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("template_key", sa.String(80), nullable=True),
        sa.Column("phase", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor_type", sa.String(30), nullable=False, server_default="self"),
        sa.Column("status", sa.String(30), nullable=False, server_default="scheduled"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("due_date", sa.String(10), nullable=True),
        sa.Column("completed_at", sa.String(32), nullable=True),
        sa.Column("checked_by", sa.String(150), nullable=False, server_default=""),
        sa.Column("outcome", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("follow_up", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False, server_default="system"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.String(32), nullable=False),
        sa.Column("updated", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["case_execution_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["purchase_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["case_properties.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_execution_tasks_plan_id", "case_execution_tasks", ["plan_id"])
    op.create_index("ix_case_execution_tasks_case_id", "case_execution_tasks", ["case_id"])
    op.create_index("ix_case_execution_tasks_property_id", "case_execution_tasks", ["property_id"])
    op.create_index("ix_case_execution_tasks_due_date", "case_execution_tasks", ["due_date"])
    op.create_index("uq_case_execution_task_template", "case_execution_tasks", ["plan_id", "template_key"], unique=True)


def downgrade() -> None:
    op.drop_table("case_execution_tasks")
    op.drop_table("case_execution_plans")
