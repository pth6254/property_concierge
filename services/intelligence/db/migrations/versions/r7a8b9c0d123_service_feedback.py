"""사용자 문제 신고를 계정별로 보관한다."""
from alembic import op
import sqlalchemy as sa

revision = "r7a8b9c0d123"
down_revision = "q6f7a8b9c012"
branch_labels = None
depends_on = None


def upgrade():
    # 개발용 create_all 안전망이 이미 생성했으면 기존 테이블을 유지한다.
    inspector=sa.inspect(op.get_bind())
    if inspector.has_table("service_feedback"):
        expected={"id","user_id","feature","category","message","status","created"}
        if {column["name"] for column in inspector.get_columns("service_feedback")} != expected:
            raise RuntimeError("service_feedback 스키마가 마이그레이션과 다릅니다")
        return
    op.create_table("service_feedback", sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("feature",sa.String(30),nullable=False),sa.Column("category",sa.String(30),nullable=False),
        sa.Column("message",sa.Text(),nullable=False),sa.Column("status",sa.String(20),nullable=False),
        sa.Column("created",sa.String(32),nullable=False))
    op.create_index("ix_service_feedback_user_id","service_feedback",["user_id"])


def downgrade():
    op.drop_table("service_feedback")
