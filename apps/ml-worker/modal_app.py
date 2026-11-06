"""Modal T4 GPU deployment for Cicero's RAG worker.

This is the primary compute deployment for document intelligence ingestion and
retrieval: Docling parsing, BGE-M3 embeddings and BGE reranking run on an
NVIDIA T4 (Google Cloud now holds only PostgreSQL/pgvector and GCS storage).

Two entrypoints share one app/image:

* ``process_document`` — long-running ingestion (up to the 3600s function
  ceiling) invoked via ``.spawn`` so Pub/Sub's 600s ack deadline never applies.
* ``fastapi_app`` — HTTPS surface: ``/pubsub/push`` (GCP Pub/Sub with OIDC,
  enqueues ``process_document``), ``/retrieve`` (EvidencePack retrieval for the
  Modal backend/agents), ``/healthz`` and ``/readyz``.

Prerequisites (Modal dashboard or CLI):
* Secret ``cicero-database`` with the Cloud SQL/WIF keys (shared with the API).
* Secret ``cicero-rag`` with CICERO_GCS_PROJECT_ID, CICERO_GCS_BUCKET_NAME,
  CICERO_RAG_SERVICE_TOKEN, CICERO_PUBSUB_PUSH_AUDIENCE (this app's URL) and
  CICERO_PUBSUB_PUSH_SERVICE_ACCOUNT.
* The backend's CICERO_RAG_WORKER_URL must point at this app's URL.

Deploy from ``backend_3_1``:  ``modal deploy deploy/modal/rag_worker_app.py``
"""

import modal

app = modal.App("cicero-rag-worker")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("poppler-utils", "libgl1", "libglib2.0-0", "libgomp1")
    .uv_pip_install(
        # Backend/storage dependencies (mirrors pyproject.toml).
        "asyncpg>=0.30,<1.0",
        "cloud-sql-python-connector[asyncpg]>=1.18,<2.0",
        "fastapi>=0.115,<1.0",
        "google-auth>=2.35,<3.0",
        "google-cloud-storage>=3.0,<4.0",
        "httpx>=0.27,<1.0",
        "pgvector>=0.3,<1.0",
        "pydantic-settings>=2.6,<3.0",
        "sqlalchemy[asyncio]>=2.0.36,<3.0",
        # RAG dependencies (mirrors requirements-rag.txt); torch resolves to
        # Modal's CUDA build so Docling/BGE run on the T4.
        "torch>=2.4,<3.0",
        "docling>=2.15,<3.0",
        "pdfplumber>=0.11,<1.0",
        "python-docx>=1.1,<2.0",
        "pandas>=2.2,<3.0",
        "numpy>=1.26,<3.0",
        "transformers>=4.45,<5.0",
        "FlagEmbedding>=1.3.5,<2.0",
        "dateparser>=1.2.0,<2.0",
        "reportlab>=4.2,<5.0",
        "requests>=2.31,<3.0",
        "uvicorn[standard]>=0.30,<1.0",
    )
    .add_local_python_source("cicero")
)

database_secret = modal.Secret.from_name(
    "cicero-database",
    required_keys=[
        "CICERO_DATABASE_INSTANCE_CONNECTION_NAME",
        "CICERO_DATABASE_NAME",
        "CICERO_DATABASE_USER",
        "CICERO_DATABASE_PASSWORD",
        "CICERO_DATABASE_WIF_PROJECT_NUMBER",
        "CICERO_DATABASE_WIF_POOL_ID",
        "CICERO_DATABASE_WIF_PROVIDER_ID",
        "CICERO_DATABASE_WIF_SERVICE_ACCOUNT_EMAIL",
    ],
)
rag_secret = modal.Secret.from_name(
    "cicero-rag",
    required_keys=[
        "CICERO_GCS_PROJECT_ID",
        "CICERO_GCS_BUCKET_NAME",
        "CICERO_RAG_SERVICE_TOKEN",
        "CICERO_PUBSUB_PUSH_AUDIENCE",
        "CICERO_PUBSUB_PUSH_SERVICE_ACCOUNT",
    ],
)


@app.function(
    image=image,
    gpu="T4",
    cpu=4.0,
    memory=32768,
    secrets=[database_secret, rag_secret],
    timeout=3600,
    scaledown_window=10 * 60,
)
def process_document(payload: dict) -> dict:
    """Ingest one document version (spawned; Modal manages the lifecycle)."""
    import asyncio

    from cicero.config import get_settings
    from cicero.rag_worker.service import ProcessingAlreadyRunning, RagWorker

    worker = RagWorker(get_settings())

    async def _run() -> dict:
        await worker.start()
        try:
            return await worker.process_message(payload)
        except ProcessingAlreadyRunning:
            raise
        except Exception as exc:
            # Without this the run stays "processing" in the DB forever even
            # though this spawned function has already failed.
            await worker.mark_failed(payload, exc)
            raise
        finally:
            await worker.close()

    return asyncio.run(_run())


@app.function(
    image=image,
    gpu="T4",
    cpu=2.0,
    memory=8192,
    secrets=[database_secret, rag_secret],
    timeout=1500,
    scaledown_window=15 * 60,
)
@modal.asgi_app()
def fastapi_app():
    import base64
    import json
    import logging
    from typing import Annotated, Any

    from fastapi import FastAPI, Header, HTTPException, Request

    from cicero.config import get_settings
    from cicero.rag_worker.service import (
        RagWorker,
        verify_pubsub_identity,
        verify_service_token,
    )

    logger = logging.getLogger("cicero.rag_worker.modal")
    settings = get_settings()
    worker = RagWorker(settings)
    app = FastAPI(title="Cicero RAG Worker (Modal)", version="1.0.0")

    @app.on_event("startup")
    async def startup() -> None:
        await worker.start()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await worker.close()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"service": "cicero-rag-worker", "status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        if not worker.database.is_started:
            raise HTTPException(status_code=503, detail="Cloud SQL is not ready")
        try:
            await worker.database.ping()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Cloud SQL is unavailable") from exc
        return {"service": "cicero-rag-worker", "status": "ready"}

    @app.post("/ingest")
    async def ingest(
        payload: dict[str, Any],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_service_token(authorization)
        await process_document.spawn.aio(payload)
        return {"ok": True, "accepted": True}

    @app.post("/pubsub/push")
    async def pubsub_push(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_pubsub_identity(authorization, settings)
        envelope = await request.json()
        try:
            message = envelope["message"]
            payload = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
        except Exception:
            logger.exception("Malformed Pub/Sub envelope; dropping message")
            return {"ok": False, "dropped": True}
        # Ingestion runs in the spawned GPU function (3600s ceiling), fully
        # decoupled from Pub/Sub's 600s ack deadline and HTTP timeouts.
        await process_document.spawn.aio(payload)
        return {"ok": True, "accepted": True}

    @app.post("/retrieve")
    async def retrieve(
        payload: dict[str, Any],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_service_token(authorization)
        try:
            return await worker.retrieve(payload)
        except Exception as exc:
            logger.exception("RAG retrieval failed")
            raise HTTPException(status_code=500, detail="RAG retrieval failed") from exc

    return app
