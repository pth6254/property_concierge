"""단지 기준정보를 API 캐시와 분리해 보관한다."""
from alembic import op
import sqlalchemy as sa

revision = "p5e6f7a8b901"
down_revision = "o4f5a6b7c890"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("complex_catalog",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lawd_code", sa.String(5), nullable=False),
        sa.Column("dong", sa.String(50), nullable=False),
        sa.Column("canonical_name", sa.String(150), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("region", sa.String(150), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("address", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("checked_at", sa.Float(), nullable=False))
    op.create_index("uq_complex_catalog_identity", "complex_catalog", ["lawd_code", "dong", "canonical_name"], unique=True)


def downgrade():
    op.drop_table("complex_catalog")
