"""원문 수집의 성공·실패와 시점을 보존한다."""
from alembic import op
import sqlalchemy as sa

revision = "l1c2e3f4a567"
down_revision = "k0b1d2e3f456"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("listing_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("requested_at", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.Float(), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False))
    op.create_index("ix_listing_observation_owner", "listing_observations", ["user_id", "external_id", "fetched_at"])


def downgrade():
    op.drop_table("listing_observations")
