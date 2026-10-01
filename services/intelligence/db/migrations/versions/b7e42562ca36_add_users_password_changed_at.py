"""add users.password_changed_at

Revision ID: b7e42562ca36
Revises: 44e30fbeb985
Create Date: 2026-08-09 22:17:12.595464

비밀번호 변경 시 기존 JWT 세션을 무효화하기 위한 컬럼.
JWT 는 stateless 라 서버가 발급된 토큰을 폐기할 수 없으므로, 이 값을
토큰 클레임(pwd_at)에 함께 넣고 검증 때 대조한다.

주의 — autogenerate 원본에서 아래 구문을 제거했다:
    op.drop_table('langchain_pg_collection')
    op.drop_table('langchain_pg_embedding')
    op.drop_table('real_estate_docs')
    op.drop_index('real_estate_docs_embedding_idx', ...)
이 셋은 docker/init.sql 이 만드는 RAG 벡터스토어 테이블로, SQLAlchemy
모델(db/models.py)에는 없다. autogenerate 는 모델에 없으면 "삭제된 것"으로
간주하므로 그대로 두면 배포 시 RAG 데이터가 전부 사라진다.
앞으로 마이그레이션을 생성할 때도 이 세 테이블에 대한 drop 이 섞여 들어오면
반드시 지울 것.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e42562ca36'
down_revision: Union[str, None] = '44e30fbeb985'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('password_changed_at', sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'password_changed_at')
