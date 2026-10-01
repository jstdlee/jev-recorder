#!/usr/bin/env bash
# Public test audio for the M0 spike. Re-runnable; skips what exists.
set -euo pipefail
cd "$(dirname "$0")/data"
PY=../../.venv/bin/python
LANGS="yue_hant_hk cmn_hans_cn en_us ms_my id_id ta_in th_th vi_vn"
for l in $LANGS; do
  [ -d fleurs/$l/test ] && continue
  $PY - "$l" <<'P'
import sys, tarfile
from huggingface_hub import hf_hub_download
l = sys.argv[1]
tsv = hf_hub_download("google/fleurs", f"data/{l}/test.tsv", repo_type="dataset", local_dir="hf")
tgz = hf_hub_download("google/fleurs", f"data/{l}/audio/test.tar.gz", repo_type="dataset", local_dir="hf")
import os, shutil
os.makedirs(f"fleurs/{l}", exist_ok=True)
shutil.copy(tsv, f"fleurs/{l}/test.tsv")
tarfile.open(tgz).extractall(f"fleurs/{l}")
print("ok", l)
P
done
# AMI meeting (English, 4 speakers) with reference diarization
mkdir -p ami && cd ami
for m in ES2004a IS1009a; do
  [ -f $m.Mix-Headset.wav ] || curl -fsSL -o $m.Mix-Headset.wav https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/$m/audio/$m.Mix-Headset.wav
  [ -f $m.rttm ] || curl -fsSL -o $m.rttm https://raw.githubusercontent.com/pyannote/AMI-diarization-setup/main/only_words/rttms/test/$m.rttm
done
ls -la
