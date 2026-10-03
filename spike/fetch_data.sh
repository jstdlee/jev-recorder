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
# ASCEND (Mandarin-English code-switching conversations, HK; CC BY-SA 4.0): rebuild each test session
# as one timed mono conversation (filenames hold each utterance's start), plus a reference transcript.
cd "$(dirname "$0")/data" && mkdir -p ascend && cd ascend
[ -f ses2.wav ] || uv run --no-project --with pyarrow --with soundfile --with numpy --with huggingface_hub python - <<'P'
import io, json, re
import numpy as np, soundfile as sf, pyarrow.parquet as pq
from huggingface_hub import hf_hub_download
p = hf_hub_download("CAiRE/ASCEND", "main/test-00000-of-00001.parquet", repo_type="dataset", local_dir=".")
SR, sess = 16000, {}
for r in pq.read_table(p).to_pylist():
    m = re.search(r"ses(\d+)_spk(\d+)_L\d+_([\d.]+)_([\d.]+)\.wav", r["path"])
    a, sr = sf.read(io.BytesIO(r["audio"]["bytes"]), dtype="float32")
    sess.setdefault(int(m[1]), []).append((float(m[3]), int(m[2]), a.mean(1) if a.ndim > 1 else a,
                                           r["transcription"], r["language"], r["topic"]))
for s, items in sorted(sess.items()):
    end = max(st + len(a) / SR for st, _, a, *_ in items)
    mix = np.zeros(int(end * SR) + SR, np.float32)
    for st, _, a, *_ in items:
        mix[int(st * SR):int(st * SR) + len(a)] += a
    sf.write(f"ses{s}.wav", mix / max(1e-6, np.abs(mix).max()) * 0.8, SR)
    json.dump({"session": s, "topic": items[0][5], "license": "CC BY-SA 4.0, CAiRE/ASCEND (Hugging Face)",
               "utterances": [{"start": round(st, 3), "end": round(st + len(a) / SR, 3), "speaker": spk, "text": t,
                               "lang": lg} for st, spk, a, t, lg, _ in sorted(items, key=lambda x: x[0])]},
              open(f"ses{s}.json", "w"), ensure_ascii=False, indent=1)
    print("ascend session", s, f"{end / 60:.1f} min")
P

