# Cicero integrated legal RAG subsystem

This patch adds a Cloud Run-hosted RAG ingestion and retrieval subsystem while
keeping Modal as the user-facing API/agent orchestrator. It vendors the supplied
Argon parser, structural reconstruction, legal hierarchy, definitions,
cross-reference, date, table, and hierarchical chunking implementations. Cicero
uses its existing Cloud SQL document/extraction/chunk tables; Argon's standalone
Postgres schema/store is deliberately not installed.

## End-to-end flow

1. Browser uploads the PDF directly to the existing private GCS bucket.
2. Existing Modal `/complete` registers document/version/processing-run records.
3. A FastAPI background task publishes a Pub/Sub message (when
   `CICERO_PUBSUB_DOCUMENT_TOPIC` is configured).
4. An authenticated Pub/Sub push subscription invokes the Cloud Run worker.
5. The worker claims the run with a 70-minute lease, downloads the GCS object,
   parses/OCRs it with Docling, runs Argon's legal structure pipeline, chunks it,
   generates 1024-d BGE-M3 embeddings, and persists results to Cloud SQL.
6. The worker updates the existing processing run to `completed` or `failed`.
7. Trusted Cicero agents call the worker's `/retrieve` endpoint through `RagClient`.

## RAG capabilities

- Docling PDF parsing with OCR enabled and page/table extraction.
- Logical-unit reconstruction and legal hierarchy extraction.
- Definitions, cross-reference resolution, and temporal/date extraction.
- Table dual representation and cell-level provenance from Argon.
- Hierarchical parent/child chunking and contextual embedding text.
- BGE-M3 dense embeddings (1024 dimensions).
- PostgreSQL full-text lexical retrieval, exact legal identifier routing,
  Reciprocal Rank Fusion (k=60), and BGE reranking.
- Parent-node context expansion, matching definitions/cross-references, and
  source-span verification before evidence is returned.
- JSONL retrieval evaluation harness reporting Recall@k and MRR.

The lexical channel is PostgreSQL FTS, not BGE-M3 neural sparse vectors. The
retrieval diagnostics report this explicitly.

## Local checks

From the backend root in Windows CMD:

```cmd
uv sync
uv run ruff check src/cicero/config.py src/cicero/api/routes/documents.py src/cicero/rag src/cicero/rag_worker migrations/versions/20261104_0002_legal_rag.py deploy/modal/api_app.py
uv run pytest
```

Vendored Argon source is excluded from Ruff because it is preserved upstream
code; Cicero adapter/worker code remains linted. The Cloud Run-only ML/parser
dependencies are in `requirements-rag.txt` and are intentionally not installed
into the Modal API image.

## Database migration

Run the migration only after confirming the Cloud SQL PostgreSQL instance has
the `vector` extension available:

```cmd
uv run alembic upgrade head
```

This creates pgvector indexes and legal intelligence tables in the existing
`intelligence` schema, and extends `documents.document_chunks`. It does not
replace existing tables. If `CREATE EXTENSION vector` is denied, the database
user needs the Cloud SQL-supported extension privilege; do not drop or recreate
the existing database.

## Cloud Run deployment

Use the repository root as the source/build context and
`deploy/cloud_run/Dockerfile` as the Dockerfile path. Deploy as an authenticated
Cloud Run service with:

- 4 vCPU, 16 GiB RAM
- request timeout: 3600 seconds
- concurrency: 1
- maximum instances: 2 initially
- runtime service account: `cicero-backend@project-d05a24bb-cf47-4351-b6e.iam.gserviceaccount.com`

Grant that service account Cloud SQL Client, Storage Object Viewer (or the
existing bucket-level Storage Object User role), and Secret Manager Secret
Accessor for the RAG service token. Cloud Run uses its attached service account
through ADC; Modal WIF environment variables are not required in Cloud Run.

Set the environment variables documented in `deploy/cloud_run/README.md`.
Store the database password and RAG service token in Secret Manager, not as
plain-text deployment values.

## Pub/Sub setup

Create topic `cicero-document-processing`. Grant the Modal backend service
account Pub/Sub Publisher on that topic. Create a push subscription targeting
`https://<CLOUD_RUN_SERVICE_URL>/pubsub/push`, with OIDC authentication enabled.
Set the OIDC audience to the Cloud Run service URL and configure the same push
service account email in `CICERO_PUBSUB_PUSH_SERVICE_ACCOUNT`. Grant the Pub/Sub
service agent permission to mint OIDC tokens for that push service account. The
worker verifies this token itself; `/retrieve` is separately protected by the
shared RAG service token.
Set the push acknowledgement deadline to 600 seconds and configure retries.

Add these values to the existing Modal `cicero-database` secret:

- `CICERO_PUBSUB_DOCUMENT_TOPIC=projects/project-d05a24bb-cf47-4351-b6e/topic/cicero-document-processing`
- `CICERO_RAG_WORKER_URL=https://<CLOUD_RUN_SERVICE_URL>`
- `CICERO_RAG_SERVICE_TOKEN=<same Secret Manager token used by Cloud Run>`

Then redeploy the Modal API. If the Pub/Sub topic is not configured, uploads keep
the current database-only behavior and remain pending.

## Retrieval API

The Cloud Run worker exposes an authenticated service-to-service endpoint:

```json
{
  "organization_id": "<organization UUID>",
  "case_id": "<case UUID>",
  "query": "What are the termination rights under clause 8.2?",
  "top_k": 8
}
```

POST `/retrieve` with `Authorization: Bearer <CICERO_RAG_SERVICE_TOKEN>`. Optional
fields: `token_budget` (default 3000, clamped 500-12000), `document_ids` (restrict
to specific documents), and `ablation` (`{dense, lexical, exact, reranker}`
booleans for evaluation).

The response is a verified **EvidencePack** following the prototype pipeline:
the query is classified (exact clause / defined term / cross-reference /
temporal / table / semantic / multi-document), deterministic routes answer
structured lookups without vector search, semantic queries run dense (pgvector)
+ lexical (PostgreSQL FTS) with exact-identifier boosting fused by RRF (k=60)
and BGE reranking, then parent expansion, definition injection and
cross-reference resolution feed token-budget context packing. Every item is
strictly validated against its extraction source span (table summaries are
retrieval aids only; raw tables are returned instead) and carries an evidence
ID, page, character offsets, retrieval reason and verification status. When
nothing verifies, the pack returns `insufficient_evidence: true` rather than
guessing.

In Modal-side code, instantiate `RagClient(settings)` and call its async
`retrieve(...)` method, or call `POST /api/cases/{case_id}/evidence` on the
Modal API (case-authorized; keeps the service token server-side). This is the
tool boundary the agents use: Document Intelligence (Muse Spark) consumes the
pack directly.

## Operational caveats

- First model initialization downloads Docling/BGE weights. Expect a cold-start
  delay; warm the service before the demo and keep one minimum instance if budget
  permits.
- Documents run to 500-600 pages: `/pubsub/push` acknowledges immediately and
  ingestion runs as a background task (Cloud Run must use CPU-always-allocated;
  see `deploy/cloud_run/README.md`). A 120-minute heartbeat-extended lease and
  idempotent persistence (re-processing replaces the version's index) make
  duplicates and crashes safe. Very long production ingestion should still move
  to a Cloud Run Job per document. Uploads are capped at 200 MiB
  (`CICERO_GCS_MAX_FILE_SIZE_BYTES`) for large scans.
- This patch provides a hackathon-ready service boundary, not production legal
  security certification. Keep Cloud Run authenticated, use a strong service
  token, restrict IAM, and do not expose `/retrieve` directly to the browser.
