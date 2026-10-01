"""실거래 상세 필드와 월별 수집 상태를 추가한다.

Revision ID: d3a5e7c9f012
Revises: c2f4d6a8b901
"""

from alembic import op
import sqlalchemy as sa

revision = "d3a5e7c9f012"
down_revision = "c2f4d6a8b901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column in [
        ("deal_day", sa.String(10)), ("bjdong_code", sa.String(10)),
        ("property_detail", sa.String(30)), ("building_area_sqm", sa.Float()),
        ("land_area_sqm", sa.Float()), ("building_use", sa.String(100)),
        ("jimok", sa.String(50)), ("transaction_type", sa.String(30)),
        ("cancellation_date", sa.String(8)),
    ]:
        op.add_column("transactions", sa.Column(name, column, nullable=True))
    op.add_column("transactions", sa.Column("is_cancelled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_transactions_bjdong_code", "transactions", ["bjdong_code"])

    op.add_column("ingest_log", sa.Column("status", sa.String(20), nullable=False, server_default="completed"))
    op.add_column("ingest_log", sa.Column("started_at", sa.Float(), nullable=True))
    op.add_column("ingest_log", sa.Column("completed_at", sa.Float(), nullable=True))
    op.add_column("ingest_log", sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingest_log", sa.Column("error_message", sa.Text(), nullable=True))
    op.create_index("ix_ingest_log_status", "ingest_log", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ingest_log_status", table_name="ingest_log")
    for name in ["error_message", "page_count", "completed_at", "started_at", "status"]:
        op.drop_column("ingest_log", name)
    op.drop_index("ix_transactions_bjdong_code", table_name="transactions")
    for name in ["is_cancelled", "cancellation_date", "transaction_type", "jimok", "building_use",
                 "land_area_sqm", "building_area_sqm", "property_detail", "bjdong_code", "deal_day"]:
        op.drop_column("transactions", name)
