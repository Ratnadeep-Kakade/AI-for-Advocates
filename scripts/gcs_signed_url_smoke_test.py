"""End-to-end GCS signed URL smoke test executed on Modal.

Run from the backend project root:
    uv run modal run scripts/gcs_signed_url_smoke_test.py::gcs_signed_url_smoke_test

The Modal function is deliberately named ``fastapi_app`` because the existing
Workload Identity Provider condition restricts tokens to:
    app_name=cicero-backend, function_name=fastapi_app
"""
from __future__ import annotations

import json

import modal

app = modal.App("cicero-backend")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "google-auth>=2.35,<3.0",
        "google-cloud-storage>=3.0,<4.0",
        "httpx>=0.27,<1.0",
        "pydantic-settings>=2.6,<3.0",
    )
    .add_local_python_source("cicero")
)

database_secret = modal.Secret.from_name(
    "cicero-database",
    required_keys=[
        "CICERO_DATABASE_WIF_PROJECT_NUMBER",
        "CICERO_DATABASE_WIF_POOL_ID",
        "CICERO_DATABASE_WIF_PROVIDER_ID",
        "CICERO_DATABASE_WIF_SERVICE_ACCOUNT_EMAIL",
    ],
)


@app.function(
    image=image,
    secrets=[database_secret],
    name="fastapi_app",
    timeout=180,
)
def gcs_signed_url_smoke_test() -> dict[str, str | int | bool]:
    """Exercise WIF, signBlob, signed PUT/GET, metadata read and object deletion."""
    from uuid import uuid4

    import httpx

    from cicero.config import Settings
    from cicero.storage.manager import StorageManager

    settings = Settings(_env_file=None)
    manager = StorageManager(settings)

    payload = b"Cicero GCS signed URL end-to-end smoke test.\n"
    object_name = f"smoke-tests/{uuid4().hex}/probe.txt"
    upload_verified = False
    download_verified = False
    metadata_verified = False
    cleanup_verified = False

    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as http:
            # Generates the V4 signature through the impersonated service
            # account. This exercises IAM Credentials signBlob via Modal WIF.
            upload = manager.generate_upload_url(
                object_name,
                content_type="text/plain",
            )

            put_response = http.put(
                upload.url,
                content=payload,
                headers=upload.required_headers,
            )
            if put_response.status_code not in (200, 201):
                raise RuntimeError(
                    "Signed GCS PUT failed with HTTP "
                    f"{put_response.status_code}: {put_response.text[:500]}"
                )
            upload_verified = True

            metadata = manager.get_object_metadata(object_name)
            metadata_verified = (
                metadata.size_bytes == len(payload)
                and metadata.content_type == "text/plain"
                and metadata.generation is not None
            )
            if not metadata_verified:
                raise RuntimeError(
                    "Uploaded object metadata did not match the expected size, "
                    "content type, and generation."
                )

            download = manager.generate_download_url(
                object_name,
                generation=metadata.generation,
            )
            get_response = http.get(download.url)
            if get_response.status_code != 200:
                raise RuntimeError(
                    "Signed GCS GET failed with HTTP "
                    f"{get_response.status_code}: {get_response.text[:500]}"
                )
            download_verified = get_response.content == payload
            if not download_verified:
                raise RuntimeError("Downloaded bytes did not match the uploaded payload.")

        return {
            "status": "SUCCESS",
            "bucket": settings.gcs_bucket_name,
            "upload_verified": upload_verified,
            "metadata_verified": metadata_verified,
            "download_verified": download_verified,
            "object_size_bytes": len(payload),
            "object_generation": int(metadata.generation),
        }
    finally:
        # Best-effort cleanup, followed by an explicit verification.
        try:
            if manager.object_exists(object_name):
                manager.delete_object(object_name)
            cleanup_verified = not manager.object_exists(object_name)
        finally:
            manager.close()

        if not cleanup_verified:
            raise RuntimeError(
                "Smoke test object could not be confirmed deleted: "
                f"{object_name}"
            )

@app.local_entrypoint()
def main():
    result = gcs_signed_url_smoke_test.remote()

    print("\n===== GCS SMOKE TEST RESULTS =====")
    print(json.dumps(result, indent=2))