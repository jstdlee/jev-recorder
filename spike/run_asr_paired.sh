#!/usr/bin/env bash
# Second pass: drop the unpaired "noisy" rows, then run noisy + enhanced on the shared noisy48 set.
cd "$(dirname "$0")/.."
for m in ${MODELS:-qwen3-asr-1.7b qwen3-asr-0.6b whisper-large-v3-turbo whisper-large-v3 confucius4-r2t2}; do
  f=spike/results/asr_$m.jsonl
  echo "##### $m"; .venv/bin/python spike/asr_bench.py $m --conds clean,noisy,dfn3,dfn3a12,mf2 2>&1 | grep -v -i -E "warn|pad_token|generation flags|Loading checkpoint"
done
