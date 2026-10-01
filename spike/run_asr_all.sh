#!/usr/bin/env bash
cd "$(dirname "$0")/.."
for m in qwen3-asr-1.7b qwen3-asr-0.6b whisper-large-v3-turbo whisper-large-v3; do
  echo "##### $m"; .venv/bin/python spike/asr_bench.py $m --conds "${CONDS:-clean,noisy}" 2>&1 | grep -v -i -E "warn|pad_token|generation flags|Loading checkpoint"
done
