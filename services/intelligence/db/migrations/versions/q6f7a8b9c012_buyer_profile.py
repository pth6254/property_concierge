"""케이스별 매수 조건을 영속화한다."""
from alembic import op
import sqlalchemy as sa

revision = "q6f7a8b9c012"
down_revision = "p5e6f7a8b901"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("purchase_cases", sa.Column("buyer_profile", sa.JSON(), nullable=False, server_default="{}"))
    op.alter_column("purchase_cases", "buyer_profile", server_default=None)


def downgrade():
    op.drop_column("purchase_cases", "buyer_profile")
