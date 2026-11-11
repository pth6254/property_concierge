"""실거래 행에 최초 수집 시각을 추가한다. 기존 거래·벡터 데이터는 변경하지 않으며 기존 행은 NULL(기록 시작 전)로 둔다."""
from alembic import op
import sqlalchemy as sa

revision = "u0d1e2f3a456"
down_revision = "t9c0d1e2f345"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("transactions")}
    # 테스트·직접 기동의 create_all 경로와 정식 마이그레이션 경로를 함께 지원한다.
    if "first_seen_at" not in columns:
        op.add_column("transactions", sa.Column("first_seen_at", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("transactions", "first_seen_at")
