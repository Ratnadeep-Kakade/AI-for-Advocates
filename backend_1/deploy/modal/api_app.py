"""Modal deployment entrypoint for Cicero."""

import modal

app = modal.App("cicero-backend")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "fastapi>=0.115,<1.0",
        "pydantic-settings>=2.6,<3.0",
    )
    .add_local_python_source("cicero")
)


@app.function(image=image)
@modal.asgi_app()
def fastapi_app():
    from cicero.api.app import create_app

    return create_app()