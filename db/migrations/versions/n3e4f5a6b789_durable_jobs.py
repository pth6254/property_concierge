"""재실행된 작업의 이력과 수집 기록을 중복 저장하지 않는다."""
from alembic import op
import sqlalchemy as sa

revision = "n3e4f5a6b789"
down_revision = "m2d3e4f5a678"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("history", sa.Column("job_id", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_history_job_id", "history", ["job_id"])
    op.add_column("listing_observations", sa.Column("job_id", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_listing_observations_job_id", "listing_observations", ["job_id"])


def downgrade():
    op.drop_constraint("uq_listing_observations_job_id", "listing_observations", type_="unique")
    op.drop_column("listing_observations", "job_id")
    op.drop_constraint("uq_history_job_id", "history", type_="unique")
    op.drop_column("history", "job_id")
