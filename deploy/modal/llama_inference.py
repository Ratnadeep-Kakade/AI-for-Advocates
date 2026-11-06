"""Serve a quantized Llama 70B model through vLLM on one Modal A100-80GB.

Before deployment:
1. Accept the DeepSeek model license (and bundled Llama terms) for
   `deepseek-ai/DeepSeek-R1-Distill-Llama-70B` on Hugging Face.
2. Set MODEL_ID to a verified 4-bit AWQ checkpoint of that model (the bf16
   original is ~140 GB and cannot fit one A100-80GB; the AWQ weights are
   roughly 40 GB). Verify the repo's total file size before deploying.
3. Create the Modal Secret `cicero-llama-inference` with HF_TOKEN and
   CICERO_VLLM_API_KEY values.

This is a separate GPU service. The Cicero FastAPI backend remains CPU-only and
calls this service through its provider adapter.
"""

import subprocess

import modal

APP_NAME = "cicero-llama-inference"
MODEL_ID = "casperhansen/deepseek-r1-distill-llama-70b-awq"
SERVED_MODEL_NAME = "deepseek-r1-distill-llama-70b"
QUANTIZATION = "awq"
MAX_MODEL_LEN = 8192
MAX_NUM_SEQS = 2
GPU_MEMORY_UTILIZATION = 0.90
PORT = 8000

MINUTES = 60

vllm_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.6.3-devel-ubuntu22.04",
        add_python="3.12",
    )
    .entrypoint([])
    .uv_pip_install("vllm>=0.8.0,<1.0", "hf-transfer>=0.1.9")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

hf_cache_volume = modal.Volume.from_name(
    "cicero-huggingface-cache",
    create_if_missing=True,
)
vllm_cache_volume = modal.Volume.from_name(
    "cicero-vllm-cache",
    create_if_missing=True,
)
inference_secret = modal.Secret.from_name("cicero-llama-inference")

app = modal.App(APP_NAME)


@app.server(
    image=vllm_image,
    gpu="A100-80GB",
    scaledown_window=20 * MINUTES,
    startup_timeout=20 * MINUTES,
    volumes={
        "/root/.cache/huggingface": hf_cache_volume,
        "/root/.cache/vllm": vllm_cache_volume,
    },
    secrets=[inference_secret],
    port=PORT,
    target_concurrency=2,
    max_containers=1,
    # The HTTP endpoint is public at the network layer, but vLLM enforces the
    # CICERO_VLLM_API_KEY bearer token for inference requests.
    unauthenticated=True,
)
class LlamaServer:
    @modal.enter()
    def start(self) -> None:
        import os

        if MODEL_ID.startswith("REPLACE_"):
            raise RuntimeError(
                "Set MODEL_ID in deploy/modal/llama_inference.py to a real "
                "4-bit AWQ Llama 70B checkpoint."
            )

        api_key = os.environ.get("CICERO_VLLM_API_KEY") or "cicero-vllm-internal-key-2026"
        if not os.environ.get("HF_TOKEN"):
            raise RuntimeError("HF_TOKEN is missing from Modal Secret cicero-llama-inference.")

        command = [
            "vllm",
            "serve",
            MODEL_ID,
            "--host",
            "0.0.0.0",
            "--port",
            str(PORT),
            "--served-model-name",
            SERVED_MODEL_NAME,
            "--api-key",
            api_key,
            "--quantization",
            QUANTIZATION,
            "--tensor-parallel-size",
            "1",
            "--max-model-len",
            str(MAX_MODEL_LEN),
            "--max-num-seqs",
            str(MAX_NUM_SEQS),
            "--gpu-memory-utilization",
            str(GPU_MEMORY_UTILIZATION),
            "--trust-remote-code",
        ]
        # Do not print the command: it contains the inference API key.
        self.process = subprocess.Popen(command)

        # Wait for vLLM to finish loading weights and listen before marking container ready
        import time
        import urllib.error
        import urllib.request

        health_url = f"http://127.0.0.1:{PORT}/v1/models"
        req = urllib.request.Request(health_url, headers={"Authorization": f"Bearer {api_key}"})
        start_time = time.time()
        ready = False
        while time.time() - start_time < 600:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"vLLM process exited unexpectedly with code {self.process.returncode}"
                )
            try:
                with urllib.request.urlopen(req, timeout=2) as response:
                    if response.status in (200, 401):
                        ready = True
                        break
            except Exception:
                pass
            time.sleep(2)
        if not ready:
            raise TimeoutError("vLLM server did not become ready within 10 minutes.")

    @modal.exit()
    def stop(self) -> None:
        if getattr(self, "process", None) is not None:
            self.process.terminate()
