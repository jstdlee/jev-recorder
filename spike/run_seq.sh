#!/usr/bin/env bash
# Sequential M0 runs: one GPU process at a time. Resumable.
cd "$(dirname "$0")/.."
F='warn|pad_token|generation flags|Loading|it/s|s/it'
spike/telemetry.sh & TPID=$!   # thermal guard runs separately as jrec-thermal
for m in qwen3-asr-1.7b qwen3-asr-0.6b whisper-large-v3-turbo whisper-large-v3 confucius4-r2t2; do
  c=clean,noisy; [ $m = qwen3-asr-1.7b ] && c=clean,noisy,dfn3,dfn3a12,mf2
  echo "##### $m $(date +%T)"; .venv/bin/python spike/asr_bench.py $m --conds $c 2>&1 | grep -v -i -E "$F"
done
echo "##### longform $(date +%T)"; .venv/bin/python spike/longform_bench.py qwen 2>&1 | grep -E "^qwen|Error|Traceback"
echo "##### pyannote $(date +%T)"; .venv-enh/bin/python spike/diar_bench.py run pyannote 2>&1 | grep -E "^pyannote|Error|Traceback"
echo "ALL DONE $(date +%T)"; kill $TPID
