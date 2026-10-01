#!/usr/bin/env bash
# Chain A: short-utterance ASR. Chain B: long-form + diarization. Both resumable.
cd "$(dirname "$0")/.."
F='warn|pad_token|generation flags|Loading|it/s|s/it'
chainA() {
  for m in qwen3-asr-1.7b qwen3-asr-0.6b whisper-large-v3-turbo whisper-large-v3 confucius4-r2t2; do
    c=clean,noisy; [ $m = qwen3-asr-1.7b ] && c=clean,noisy,dfn3,dfn3a12,mf2
    echo "##### $m"; .venv/bin/python spike/asr_bench.py $m --conds $c 2>&1 | grep -v -i -E "$F"
  done; echo "CHAIN A DONE"
}
chainB() {
  .venv/bin/python spike/longform_bench.py qwen 2>&1 | grep -E "^qwen|Error|Traceback"
  .venv-nemo/bin/python spike/longform_bench.py vibevoice 2>&1 | grep -E "^vibevoice|Error|Traceback"
  .venv-enh/bin/python spike/diar_bench.py run pyannote 2>&1 | grep -E "^pyannote|Error|Traceback"
  echo "CHAIN B DONE"
}
chainA > spike/results/final_a.log 2>&1 &
chainB > spike/results/final_b.log 2>&1 &
wait
