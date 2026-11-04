"""Add structure-aware legal RAG indexes to existing Cicero document tables.

Revision ID: 20261104_0002
Revises: 20261104_0001
"""
from alembic import op

revision = "20261104_0002"
down_revision = "20261104_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS intelligence")
    op.execute("""ALTER TABLE documents.document_chunks
        ADD COLUMN IF NOT EXISTS embedding vector(1024)""")
    op.execute("ALTER TABLE documents.document_chunks ADD COLUMN IF NOT EXISTS embedding_text text")
    op.execute("""ALTER TABLE documents.document_chunks
        ADD COLUMN IF NOT EXISTS parent_chunk_key text""")
    op.execute("""ALTER TABLE documents.document_chunks
        ADD COLUMN IF NOT EXISTS chunk_type text NOT NULL DEFAULT 'clause'""")
    op.execute("""ALTER TABLE documents.document_chunks
        ADD COLUMN IF NOT EXISTS section_path text[] NOT NULL DEFAULT ARRAY[]::text[]""")
    op.execute("""ALTER TABLE documents.document_chunks
        ADD COLUMN IF NOT EXISTS legal_identifiers text[] NOT NULL DEFAULT ARRAY[]::text[]""")
    op.execute("""ALTER TABLE documents.document_chunks
        ADD COLUMN IF NOT EXISTS chunk_metadata jsonb NOT NULL DEFAULT '{}'::jsonb""")
    op.execute("""ALTER TABLE documents.document_chunks
        ADD COLUMN IF NOT EXISTS search_vector tsvector""")
    op.execute("""
        CREATE OR REPLACE FUNCTION documents.refresh_chunk_search_vector() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            NEW.search_vector := to_tsvector('english', coalesce(NEW.content, ''));
            RETURN NEW;
        END $$
    """)
    op.execute("""DROP TRIGGER IF EXISTS trg_document_chunks_search_vector
        ON documents.document_chunks""")
    op.execute("""
        CREATE TRIGGER trg_document_chunks_search_vector
        BEFORE INSERT OR UPDATE OF content ON documents.document_chunks
        FOR EACH ROW EXECUTE FUNCTION documents.refresh_chunk_search_vector()
    """)
    op.execute("""UPDATE documents.document_chunks
        SET search_vector = to_tsvector('english', coalesce(content, ''))
        WHERE search_vector IS NULL""")
    op.execute("""CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
        ON documents.document_chunks USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL""")
    op.execute("""CREATE INDEX IF NOT EXISTS idx_document_chunks_search_gin
        ON documents.document_chunks USING gin (search_vector)""")
    op.execute("""CREATE INDEX IF NOT EXISTS idx_document_chunks_identifiers_gin
        ON documents.document_chunks USING gin (legal_identifiers)""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS intelligence.legal_hierarchy_nodes (
            node_id text NOT NULL,
            organization_id uuid NOT NULL,
            case_id uuid NOT NULL,
            document_id uuid NOT NULL,
            version_id uuid NOT NULL,
            extraction_id uuid NOT NULL,
            parent_node_id text,
            level text NOT NULL,
            label text NOT NULL,
            page_start integer,
            page_end integer,
            char_start integer,
            char_end integer,
            node_data jsonb NOT NULL,
            PRIMARY KEY (organization_id, version_id, node_id)
        )
    """)
    op.execute("""CREATE INDEX IF NOT EXISTS idx_legal_nodes_document
        ON intelligence.legal_hierarchy_nodes (organization_id, document_id, version_id)""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS intelligence.legal_definitions (
            definition_id bigserial PRIMARY KEY,
            organization_id uuid NOT NULL,
            case_id uuid NOT NULL,
            document_id uuid NOT NULL,
            version_id uuid NOT NULL,
            extraction_id uuid NOT NULL,
            term text NOT NULL,
            verbatim_definition text NOT NULL,
            normalized_meaning text,
            page integer,
            char_start integer,
            char_end integer,
            definition_data jsonb NOT NULL DEFAULT '{}'::jsonb
        )
    """)
    op.execute("""CREATE INDEX IF NOT EXISTS idx_legal_definitions_term
        ON intelligence.legal_definitions (organization_id, case_id, lower(term))""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS intelligence.legal_cross_references (
            edge_id text NOT NULL,
            organization_id uuid NOT NULL,
            case_id uuid NOT NULL,
            document_id uuid NOT NULL,
            version_id uuid NOT NULL,
            extraction_id uuid NOT NULL,
            from_node_id text,
            to_node_id text,
            target_label text,
            normalized_reference text,
            resolution_status text NOT NULL,
            source_provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            edge_data jsonb NOT NULL,
            PRIMARY KEY (organization_id, version_id, edge_id)
        )
    """)
    op.execute("""CREATE INDEX IF NOT EXISTS idx_legal_xrefs_target
        ON intelligence.legal_cross_references (organization_id, case_id, normalized_reference)""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS intelligence.legal_tables (
            table_id text NOT NULL,
            organization_id uuid NOT NULL,
            case_id uuid NOT NULL,
            document_id uuid NOT NULL,
            version_id uuid NOT NULL,
            extraction_id uuid NOT NULL,
            page integer,
            caption text,
            table_data jsonb NOT NULL,
            PRIMARY KEY (organization_id, version_id, table_id)
        )
    """)
    op.execute("""CREATE INDEX IF NOT EXISTS idx_legal_tables_document
        ON intelligence.legal_tables (organization_id, document_id, version_id)""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS intelligence.legal_dates (
            date_id text NOT NULL,
            organization_id uuid NOT NULL,
            case_id uuid NOT NULL,
            document_id uuid NOT NULL,
            version_id uuid NOT NULL,
            extraction_id uuid NOT NULL,
            normalized_date date,
            raw_date text NOT NULL,
            date_role text NOT NULL,
            page integer,
            char_start integer,
            char_end integer,
            ambiguous boolean NOT NULL DEFAULT false,
            date_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (organization_id, version_id, date_id)
        )
    """)
    op.execute("""CREATE INDEX IF NOT EXISTS idx_legal_dates_document
        ON intelligence.legal_dates (organization_id, document_id, version_id)""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS intelligence.legal_dates")
    op.execute("DROP TABLE IF EXISTS intelligence.legal_tables")
    op.execute("DROP TABLE IF EXISTS intelligence.legal_cross_references")
    op.execute("DROP TABLE IF EXISTS intelligence.legal_definitions")
    op.execute("DROP TABLE IF EXISTS intelligence.legal_hierarchy_nodes")
    op.execute("DROP INDEX IF EXISTS documents.idx_document_chunks_identifiers_gin")
    op.execute("DROP INDEX IF EXISTS documents.idx_document_chunks_search_gin")
    op.execute("DROP INDEX IF EXISTS documents.idx_document_chunks_embedding_hnsw")
    op.execute("""DROP TRIGGER IF EXISTS trg_document_chunks_search_vector
        ON documents.document_chunks""")
    op.execute("DROP FUNCTION IF EXISTS documents.refresh_chunk_search_vector()")
    op.execute("ALTER TABLE documents.document_chunks DROP COLUMN IF EXISTS search_vector")
    op.execute("ALTER TABLE documents.document_chunks DROP COLUMN IF EXISTS chunk_metadata")
    op.execute("ALTER TABLE documents.document_chunks DROP COLUMN IF EXISTS legal_identifiers")
    op.execute("ALTER TABLE documents.document_chunks DROP COLUMN IF EXISTS section_path")
    op.execute("ALTER TABLE documents.document_chunks DROP COLUMN IF EXISTS chunk_type")
    op.execute("ALTER TABLE documents.document_chunks DROP COLUMN IF EXISTS parent_chunk_key")
    op.execute("ALTER TABLE documents.document_chunks DROP COLUMN IF EXISTS embedding_text")
    op.execute("ALTER TABLE documents.document_chunks DROP COLUMN IF EXISTS embedding")
