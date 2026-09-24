"""사용자별 제공 매물과 갱신 이력 저장소를 추가한다."""
from alembic import op
import sqlalchemy as sa

revision = "k0b1d2e3f456"
down_revision = "j9a0c1d2e345"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("imported_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_name", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("legal_region_code", sa.String(10)),
        sa.Column("property_type", sa.String(30), nullable=False),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("area_sqm", sa.Float(), nullable=False),
        sa.Column("confirmed_at", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False))
    op.create_index("uq_imported_listing_source", "imported_listings", ["user_id", "source_name", "external_id"], unique=True)
    op.create_index("ix_imported_listing_search", "imported_listings", ["user_id", "legal_region_code", "status"])
    op.create_table("listing_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("imported_listings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("imported_at", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False))
    op.create_index("ix_listing_revisions_listing_id", "listing_revisions", ["listing_id"])


def downgrade():
    op.drop_table("listing_revisions")
    op.drop_table("imported_listings")
