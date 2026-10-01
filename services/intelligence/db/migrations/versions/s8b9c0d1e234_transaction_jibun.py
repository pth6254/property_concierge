"""실거래 원문의 지번을 보존한다. 기존 거래·벡터 데이터는 변경하지 않는다."""
from alembic import op
import sqlalchemy as sa

revision = "s8b9c0d1e234"
down_revision = "r7a8b9c0d123"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("transactions")}
    # 테스트·직접 기동의 create_all 경로와 정식 마이그레이션 경로를 함께 지원한다.
    if "jibun" not in columns:
        op.add_column("transactions", sa.Column("jibun", sa.String(50), nullable=True))


def downgrade():
    op.drop_column("transactions", "jibun")
