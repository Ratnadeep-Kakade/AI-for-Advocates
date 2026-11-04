# Cicero Cloud RAG worker deployment

> **Current primary deployment:** Modal T4 GPU — see
> `deploy/modal/rag_worker_app.py`. This Cloud Run guide remains the CPU
> fallback topology; the worker code is identical, only the host differs.

## Runtime layout

- Modal remains the user-facing API and agent orchestrator.
- The Modal API publishes a Pub/Sub event after document registration.
- This Cloud Run service downloads the private GCS object, parses it with Docling,
  extracts legal structure using the supplied Argon components, creates BGE-M3
  embeddings, and writes extraction/chunks/legal metadata to Cloud SQL.
- `/retrieve` exposes case-scoped hybrid retrieval to trusted Cicero services.

## Required Cloud Run settings

Deploy `deploy/cloud_run/Dockerfile` with the **`backend_3_1` directory as the
build context** (the Dockerfile copies `.` and pip-installs the project).
Use 4 vCPU, 16 GiB memory, request timeout 3600 seconds, concurrency 1, and start
with maximum instances 2. **Enable CPU always allocated (`--no-cpu-throttling`)**:
`/pubsub/push` acknowledges immediately and ingestion continues in the
background, which only works when CPU is not throttled after the response.
Keep minimum instances at 0 to save credit; set it to 1 only to warm the demo
(model weights load on first use). Enable unauthenticated invocation at the Cloud Run IAM
layer because Pub/Sub push uses OIDC that is verified inside `/pubsub/push`, and
`/retrieve` uses its own bearer token. Do not expose the retrieval token to the
browser. Configure the Cloud Run runtime service account with:

- Cloud SQL Client
- Storage Object Viewer on `cicero-legal-documents-1575`
- Secret Manager Secret Accessor for `CICERO_RAG_SERVICE_TOKEN`

Environment variables (use the same database values already used by the Modal
backend, but do not configure Modal WIF variables on Cloud Run):

- `CICERO_ENVIRONMENT=development` (or staging/production as appropriate)
- `CICERO_DATABASE_INSTANCE_CONNECTION_NAME`
- `CICERO_DATABASE_NAME=legal_ai`
- `CICERO_DATABASE_USER`
- `CICERO_DATABASE_PASSWORD` (Secret Manager)
- `CICERO_DATABASE_IP_TYPE=public` (or private if configured)
- `CICERO_GCS_PROJECT_ID=project-d05a24bb-cf47-4351-b6e`
- `CICERO_GCS_BUCKET_NAME=cicero-legal-documents-1575`
- `CICERO_RAG_SERVICE_TOKEN` (Secret Manager; a long random value)
- `CICERO_PUBSUB_PUSH_AUDIENCE=https://<CLOUD_RUN_SERVICE_URL>`
- `CICERO_PUBSUB_PUSH_SERVICE_ACCOUNT=<Pub/Sub push authentication service account email>`

Cloud Run uses its attached service account through ADC. Do not copy Modal's
`MODAL_IDENTITY_TOKEN` or WIF executable settings into this service.

## Pub/Sub

Create topic `cicero-document-processing`. Create a push subscription targeting
`https://<CLOUD_RUN_URL>/pubsub/push`, enable OIDC authentication, and select a
push service account. Set the OIDC audience to the Cloud Run service URL and set
`CICERO_PUBSUB_PUSH_SERVICE_ACCOUNT` to that exact service account email. Grant
the Pub/Sub service agent (`service-116460390489@gcp-sa-pubsub.iam.gserviceaccount.com`)
`Service Account Token Creator` on the push service account. Set acknowledgement
deadline to 600 seconds and configure retry/backoff. Add a dead-letter topic after
initial smoke testing.

Documents run to 500-600 pages, so ingestion regularly exceeds both the 600s
ack deadline and the Cloud Run request timeout. `/pubsub/push` therefore
returns HTTP 200 immediately and processes in the background: a processing
lease (120 minutes, heartbeat-extended) plus idempotent persistence make
duplicate deliveries and crashed runs safe. Failures mark the processing run
`failed` in the database (visible via the documents list API) instead of
relying on Pub/Sub redelivery. If a run is ever left stuck in `processing`
after an instance restart, wait for the lease to expire, then republish the
same message payload to re-drive it. The production follow-up is a Cloud Run
Job per document; the background-task design is the hackathon-pragmatic step.

Set Modal secret `cicero-database` with the additional variable:
`CICERO_PUBSUB_DOCUMENT_TOPIC=projects/project-d05a24bb-cf47-4351-b6e/topic/cicero-document-processing`.
The publisher service account must have Pub/Sub Publisher on that topic. Generate
a long random service token locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Store it as Secret Manager secret `CICERO_RAG_SERVICE_TOKEN`, then add the same
value to the existing Modal `cicero-database` secret. Do not paste the token into
source code or commit it.

## Database migration

Apply Alembic revision `20261104_0002` after confirming Cloud SQL supports the
`vector` extension. It extends `documents.document_chunks` and creates legal
structure tables in the existing `intelligence` schema. It does not replace
existing tables or create a second database.

## Retrieval request

POST `/retrieve` with `Authorization: Bearer <CICERO_RAG_SERVICE_TOKEN>`:

```json
{
  "organization_id": "<organization UUID>",
  "case_id": "<case UUID>",
  "query": "What are the termination rights under clause 8.2?",
  "top_k": 8
}
```

The response contains evidence quotes with document/version IDs, page and
character offsets, plus retrieval diagnostics. Only use it after the worker
health endpoint and the ingestion smoke test pass.
