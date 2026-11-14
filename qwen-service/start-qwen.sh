#!/usr/bin/env bash
set -euo pipefail

: "${VLLM_API_KEY:?VLLM_API_KEY must be configured as a Runpod Pod secret.}"

export MODEL_ID="${MODEL_ID:-Qwen/Qwen2.5-VL-3B-Instruct}"
export MODEL_REVISION="${MODEL_REVISION:-main}"
export SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-Qwen/Qwen2.5-VL-3B-Instruct}"
export HF_HOME="${HF_HOME:-/workspace/huggingface}"
export VLLM_PORT="${VLLM_PORT:-8000}"
export GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.85}"
export MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
export MAX_IMAGES_PER_REQUEST="${MAX_IMAGES_PER_REQUEST:-1}"

mkdir -p "${HF_HOME}"

exec vllm serve "${MODEL_ID}" \
  --revision "${MODEL_REVISION}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --host 0.0.0.0 \
  --port "${VLLM_PORT}" \
  --api-key "${VLLM_API_KEY}" \
  --download-dir "${HF_HOME}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --limit-mm-per-prompt "{\"image\":${MAX_IMAGES_PER_REQUEST}}"
