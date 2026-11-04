# Processing Repository

`ProcessingRepository` persists document-processing runs, extraction records and
text chunks using the existing `documents` schema. It does not parse documents,
perform OCR, split text, generate embeddings, or read/write Google Cloud Storage.
Those operations belong to ingestion services and their adapters.

## Scope and transactions

All read methods that return processing data require `organization_id`, either
directly or alongside the document/extraction identifier. The repository provides
query scoping, not user authorization; the service layer must authorize the
request before invoking a write or returning data. Repository methods stage
changes in the supplied `AsyncSession` and never commit or roll back.

## Processing runs

- `create_run()` stages a pending run linked to a document version.
- `get_run()` and `get_run_for_document()` retrieve runs within an organization.
- `list_runs_for_document()` returns a document's processing history.
- `list_by_status()` supports organization-scoped worker polling.
- `set_status()` validates the schema's four supported statuses and maintains
  `started_at`, `completed_at`, and `error_message` consistently.

The repository does not enforce a strict transition graph. The existing database
schema only constrains the set of status values; workflow policy belongs in the
processing service. Concurrent worker claiming/locking is also intentionally not
implemented here and should be designed with the worker orchestration layer.

## Extractions and chunks

- `create_extraction()` stages extracted text and JSONB metadata.
- `get_extraction()` and `list_extractions_for_document()` are organization-scoped.
- `create_chunk()` and `create_chunks()` stage chunk content and source coordinates.
- `list_chunks_for_extraction()` and `list_chunks_for_document()` return chunks in
  stable chunk-index order, optionally scoped to a version or extraction.

No embedding or full-text fields are written because the current live schema does
not yet contain them. Those will be introduced through a separately reviewed
schema migration when the RAG persistence design is ready.
