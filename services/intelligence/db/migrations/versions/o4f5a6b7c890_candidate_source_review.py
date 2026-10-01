"""원본 매물 변경을 후보에 반영한 이력을 보존한다."""
from alembic import op
import sqlalchemy as sa

revision = "o4f5a6b7c890"
down_revision = "n3e4f5a6b789"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("candidate_source_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("case_properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_snapshot", sa.JSON(), nullable=False),
        sa.Column("applied_snapshot", sa.JSON(), nullable=False),
        sa.Column("previous_decision", sa.JSON(), nullable=True),
        sa.Column("invalidated_analyses", sa.JSON(), nullable=False),
        sa.Column("previous_analyses", sa.JSON(), nullable=False),
        sa.Column("previous_execution", sa.JSON(), nullable=False),
        sa.Column("created", sa.String(32), nullable=False))
    op.create_index("ix_candidate_source_reviews_case_id", "candidate_source_reviews", ["case_id"])
    op.create_index("ix_candidate_source_reviews_property_id", "candidate_source_reviews", ["property_id"])


def downgrade():
    op.drop_index("ix_candidate_source_reviews_property_id", table_name="candidate_source_reviews")
    op.drop_index("ix_candidate_source_reviews_case_id", table_name="candidate_source_reviews")
    op.drop_table("candidate_source_reviews")
