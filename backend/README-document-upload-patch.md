# Cicero document upload API patch

This patch adds the first backend slice of document ingestion. It does not replace
existing database tables and does not add a migration.

## What it adds

- `POST /api/cases/{case_id}/documents/upload-url`
  - Requires the configured demo identity to be a member of the organization and case.
  - Accepts PDF only, 1 byte through the configured 50 MiB maximum.
  - Creates a server-generated document/version UUID and a short-lived V4 signed
    GCS PUT URL with `Content-Type: application/pdf` and create-only generation
    precondition.
- Browser uploads bytes directly to private GCS.
- `POST /api/cases/{case_id}/documents/complete`
  - Re-authorizes case access.
  - Verifies that the exact expected object exists, is marked as PDF, and is
    within the configured size limit.
  - Registers `documents.documents`, `documents.document_versions`, and a
    `pending` `documents.document_processing_runs` row in one DB transaction.
- `GET /api/cases/{case_id}/documents` lists registered active documents and
  their latest version and processing status.

No DB migration is required because the patch uses the existing ORM mappings and
repositories. The pending run is marked with `extraction_method=docling`, but
this patch does not execute Docling yet.

## Apply

Copy the `src` and `tests` directories from this patch into the backend root,
preserving the directory structure and allowing the two existing files to be
updated:
- `src/cicero/api/app.py`
- `src/cicero/api/routes/documents.py` (new)
- `tests/test_document_upload_api.py` (new)

Then run from the backend root:

```cmd
uv run ruff check src/cicero/api/app.py src/cicero/api/routes/documents.py tests/test_document_upload_api.py
uv run pytest
```

## Required GCS bucket CORS

FastAPI CORS and GCS bucket CORS are separate. Browser PUT requests go directly
to GCS, so the bucket must allow the browser origins. A matching
`gcs-cors.json` is included in this patch.

Apply it to bucket `cicero-legal-documents-1575` using Google Cloud CLI:

```cmd
gcloud storage buckets update gs://cicero-legal-documents-1575 --cors-file=gcs-cors.json
```

Run this from the directory containing `gcs-cors.json`, with the correct Google
Cloud project selected. This changes bucket CORS only; it does not make objects
public.

## Deploy

The API uses the existing `cicero-database` and `cicero-model-gateway` Modal
secrets. Keep `CICERO_CORS_ALLOWED_ORIGINS` set to both browser origins:

```text
https://ai-for-advocates-xi.vercel.app,http://localhost:5173
```

Deploy:

```cmd
uv run modal deploy deploy/modal/api_app.py
```

## API sequence

1. Call upload-url with `filename`, `content_type: application/pdf`, and `file_size`.
2. PUT the raw file bytes to the returned `upload_url`, including the returned
   `required_headers` exactly.
3. Call complete with the returned `document_id`, `version_id`, original
   `filename`, and `content_type: application/pdf`.
4. GET the case documents endpoint to confirm the registered record.

The signed PUT endpoint cannot enforce maximum body size by itself. The API
pre-checks the browser-declared size and verifies the actual GCS object size at
completion before inserting database metadata. A failed DB commit after a
successful object upload can leave an unregistered private object; lifecycle
cleanup/reconciliation is a later hardening task.

The current demo identity is a single-tenant hackathon mechanism, not production
authentication. Do not expose this configuration as a production authorization
system.
