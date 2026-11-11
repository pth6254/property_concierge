"""변화 알림함 테이블을 추가한다. 기존 업무·실거래·RAG 테이블은 변경하지 않는다."""
from alembic import op
import sqlalchemy as sa

revision = "v1e2f3a4b567"
down_revision = "u0d1e2f3a456"
branch_labels = None
depends_on = None


def upgrade():
    # 테스트·직접 기동의 create_all 경로가 먼저 만들었을 수 있다.
    if "user_notifications" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("subject_key", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(300), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("case_properties.id", ondelete="CASCADE"), nullable=True),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("imported_listings.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created", sa.String(32), nullable=False),
        sa.Column("read_at", sa.String(32), nullable=True),
        sa.Column("resolved_at", sa.String(32), nullable=True),
    )
    op.create_index("uq_user_notification_condition", "user_notifications",
                    ["user_id", "kind", "subject_key", "fingerprint"], unique=True)
    op.create_index("ix_user_notification_open", "user_notifications", ["user_id", "resolved_at", "read_at"])
    op.create_index("ix_user_notifications_case_id", "user_notifications", ["case_id"])
    op.create_index("ix_user_notifications_property_id", "user_notifications", ["property_id"])
    op.create_index("ix_user_notifications_listing_id", "user_notifications", ["listing_id"])


def downgrade():
    op.drop_table("user_notifications")
