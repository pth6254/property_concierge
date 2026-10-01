"""add legal_regions hierarchy

Revision ID: c2f4d6a8b901
Revises: b7e42562ca36
Create Date: 2026-08-29 00:00:00.000000

행정안전부 10자리 법정동코드를 이름이 아닌 코드 기준으로 저장한다.
기존 region_codes는 현재 시세추정 경로가 사용하므로 변경하지 않는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2f4d6a8b901"
down_revision: Union[str, None] = "b7e42562ca36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """전국 법정동 계층 마스터를 추가한다."""
    op.create_table(
        "legal_regions",
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("parent_code", sa.String(length=10), nullable=True),
        sa.Column("sido_code", sa.String(length=2), nullable=False),
        sa.Column("sigungu_code", sa.String(length=3), nullable=False),
        sa.Column("eup_myeon_dong_code", sa.String(length=3), nullable=False),
        sa.Column("ri_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("lawd_code", sa.String(length=5), nullable=True),
        sa.Column("resident_code", sa.String(length=10), nullable=False),
        sa.Column("cadastral_code", sa.String(length=10), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.String(length=8), nullable=True),
        sa.Column("abolished_date", sa.String(length=8), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("synced_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index("ix_legal_regions_parent_code", "legal_regions", ["parent_code"])
    op.create_index("ix_legal_regions_full_name", "legal_regions", ["full_name"])
    op.create_index("ix_legal_regions_lawd_code", "legal_regions", ["lawd_code"])
    op.create_index("ix_legal_regions_is_active", "legal_regions", ["is_active"])
    op.create_index(
        "idx_legal_regions_parent_active",
        "legal_regions",
        ["parent_code", "is_active"],
    )


def downgrade() -> None:
    """법정동 계층 마스터만 제거한다."""
    op.drop_index("idx_legal_regions_parent_active", table_name="legal_regions")
    op.drop_index("ix_legal_regions_is_active", table_name="legal_regions")
    op.drop_index("ix_legal_regions_lawd_code", table_name="legal_regions")
    op.drop_index("ix_legal_regions_full_name", table_name="legal_regions")
    op.drop_index("ix_legal_regions_parent_code", table_name="legal_regions")
    op.drop_table("legal_regions")
