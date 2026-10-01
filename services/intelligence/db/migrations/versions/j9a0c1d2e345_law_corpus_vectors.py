"""법령 원문 전용 pgvector 저장소를 추가한다."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "j9a0c1d2e345"
down_revision = "i8f0b2c4d567"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("law_corpus_documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("law_id", sa.String(30), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("model_digest", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False))
    op.create_index("ix_law_corpus_documents_law_id", "law_corpus_documents", ["law_id"])
    op.create_table("law_corpus_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.String(64), sa.ForeignKey("law_corpus_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("embedding", Vector(2560), nullable=False))
    op.create_index("ix_law_corpus_chunks_document_id", "law_corpus_chunks", ["document_id"])


def downgrade():
    op.drop_table("law_corpus_chunks")
    op.drop_table("law_corpus_documents")
