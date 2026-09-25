"""후보가 참조한 매물 버전과 당시 값을 보존한다."""
from alembic import op
import sqlalchemy as sa

revision = "m2d3e4f5a678"
down_revision = "l1c2e3f4a567"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("case_properties", sa.Column("source_listing_id", sa.Integer(), nullable=True))
    op.add_column("case_properties", sa.Column("source_snapshot", sa.JSON(), nullable=True))
    op.create_foreign_key("fk_case_properties_source_listing", "case_properties", "imported_listings",
                          ["source_listing_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_case_properties_source_listing_id", "case_properties", ["source_listing_id"])


def downgrade():
    op.drop_index("ix_case_properties_source_listing_id", table_name="case_properties")
    op.drop_constraint("fk_case_properties_source_listing", "case_properties", type_="foreignkey")
    op.drop_column("case_properties", "source_snapshot")
    op.drop_column("case_properties", "source_listing_id")
