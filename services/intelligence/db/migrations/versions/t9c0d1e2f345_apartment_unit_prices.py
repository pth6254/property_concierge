"""공동주택 공시가격(호별)과 필지·연도별 수집 상태 테이블을 추가한다. 기존 거래·벡터 데이터는 변경하지 않는다."""
from alembic import op
import sqlalchemy as sa

revision = "t9c0d1e2f345"
down_revision = "s8b9c0d1e234"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    # 테스트·직접 기동의 create_all 경로와 정식 마이그레이션 경로를 함께 지원한다.
    if "apartment_unit_prices" not in tables:
        op.create_table(
            "apartment_unit_prices",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("pnu", sa.String(19), nullable=False),
            sa.Column("stdr_year", sa.Integer(), nullable=False),
            sa.Column("aphus_code", sa.String(20), nullable=False),
            sa.Column("aphus_name", sa.String(100), nullable=True),
            sa.Column("dong_name", sa.String(50), nullable=False, server_default=""),
            sa.Column("ho_name", sa.String(50), nullable=False, server_default=""),
            sa.Column("floor_name", sa.String(20), nullable=True),
            sa.Column("exclusive_area", sa.Float(), nullable=True),
            sa.Column("official_price", sa.BigInteger(), nullable=False),
            sa.Column("ld_code", sa.String(10), nullable=True),
            sa.Column("lot_number", sa.String(20), nullable=True),
            sa.Column("source_updated", sa.String(20), nullable=True),
            sa.Column("fetched_at", sa.Float(), nullable=False),
        )
        op.create_index("uq_apt_unit_price", "apartment_unit_prices", ["pnu", "stdr_year", "aphus_code", "dong_name", "ho_name"], unique=True)
        op.create_index("idx_apt_unit_price_pnu_year", "apartment_unit_prices", ["pnu", "stdr_year"])
    if "apartment_unit_price_fetches" not in tables:
        op.create_table(
            "apartment_unit_price_fetches",
            sa.Column("pnu", sa.String(19), primary_key=True),
            sa.Column("stdr_year", sa.Integer(), primary_key=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("fetched_at", sa.Float(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_apartment_unit_price_fetches_status", "apartment_unit_price_fetches", ["status"])


def downgrade():
    op.drop_index("ix_apartment_unit_price_fetches_status", table_name="apartment_unit_price_fetches")
    op.drop_table("apartment_unit_price_fetches")
    op.drop_index("idx_apt_unit_price_pnu_year", table_name="apartment_unit_prices")
    op.drop_index("uq_apt_unit_price", table_name="apartment_unit_prices")
    op.drop_table("apartment_unit_prices")
