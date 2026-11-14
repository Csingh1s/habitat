# Qwen inference service

This container serves `Qwen/Qwen2.5-VL-3B-Instruct` through vLLM's OpenAI-compatible API.
It is the GPU-only inference service for Habitat Inspector. It is not part of the Expo mobile
app and it is not FastAPI.

## Security and cost contract

- The service requires `VLLM_API_KEY` at startup. It refuses to start without one.
- FastAPI is the only intended caller. The mobile app must never receive this key.
- Use a private, authenticated Runpod Secure Cloud Pod. Do not put customer evidence through
  public demos or Community Cloud.
- The production FastAPI service separately requires `ENABLE_REMOTE_INFERENCE=true`; local
  FastAPI development cannot call this service.
- Stop the Pod when testing is finished. A stopped Pod does not serve requests.

## Container image

The base image is pinned to `vllm/vllm-openai:v0.10.2`. Docker Hub reported the AMD64 image
digest as `sha256:df2607b26bdda2875de4832f4d08da0055b4b6e3570347f3a849bcc652771dd6`
when this package was authored. Revalidate a replacement version against Qwen and vLLM before
upgrading.

Build and push this image to a private registry before creating the Pod:

```powershell
cd qwen-service
docker build --platform linux/amd64 --tag YOUR_REGISTRY/habitat-qwen:v1 .
docker push YOUR_REGISTRY/habitat-qwen:v1
```

The model downloads at first startup to `/workspace/huggingface`. Attach a persistent volume at
`/workspace` to reuse it across Pod restarts. The model's license applies; review and accept it
before commercial use.

## Runpod Pod configuration

| Field | Value |
|---|---|
| Cloud | Secure Cloud |
| Pod type | On-demand |
| GPU | RTX A5000 24 GB; use an RTX 4090 24 GB or A10 24 GB only if the catalog has no A5000 |
| Image | Your private `habitat-qwen:v1` image |
| HTTP port | `8000` |
| Container disk | 20 GB minimum |
| Persistent volume | 50 GB minimum mounted at `/workspace` |
| CUDA floor | 12.8 |

Set these Pod environment variables:

```text
VLLM_API_KEY=<random-secret-stored-in-your-secret-manager>
MODEL_ID=Qwen/Qwen2.5-VL-3B-Instruct
MODEL_REVISION=main
SERVED_MODEL_NAME=Qwen/Qwen2.5-VL-3B-Instruct
HF_HOME=/workspace/huggingface
GPU_MEMORY_UTILIZATION=0.85
MAX_MODEL_LEN=8192
MAX_IMAGES_PER_REQUEST=1
```

Do not set `VLLM_API_KEY` in source code, the Expo app, browser variables, or screenshots.

## Verify after the Pod is running

From an authorized operator machine, obtain the Runpod HTTP service URL for port `8000` and
perform an authenticated external health check:

```powershell
$env:QWEN_BASE_URL = "https://YOUR-RUNPOD-HTTP-SERVICE"
$env:VLLM_API_KEY = "your-secret"

Invoke-RestMethod `
  -Uri "$env:QWEN_BASE_URL/v1/models" `
  -Headers @{ Authorization = "Bearer $env:VLLM_API_KEY" }
```

The response must include `Qwen/Qwen2.5-VL-3B-Instruct`. Then send one non-sensitive,
authorized test image through FastAPI and verify the resulting review candidate contains the
source media identifier, model/version, uncertainty reason, and
`requires_human_review=true`.

## Production FastAPI configuration

Only the deployed FastAPI service receives these server-side secrets:

```text
APP_ENV=production
ENABLE_REMOTE_INFERENCE=true
QWEN_INFERENCE_URL=https://YOUR-RUNPOD-HTTP-SERVICE/v1/chat/completions
QWEN_INFERENCE_API_KEY=<same VLLM_API_KEY>
QWEN_MODEL_ID=Qwen/Qwen2.5-VL-3B-Instruct
QWEN_MODEL_VERSION=runpod-v1
```

Do not configure the remote-inference flag or credentials in a local VS Code environment.
