# jev-recorder: notes for Claude sessions

USB voice recorder (Sony ICD-TX660) → confirm-first import → read-only sha256 archive → conversations
with ±10 min raw padding (byte-exact clips + manifest) → Qwen3-ASR-1.7B transcripts on an absolute clock
→ summaries via any OpenAI-compatible LLM → search; ImGui desktop UI. Plan and all decisions: `PLAN.md`
(§8 M0 results, §9 progress, §10 vault proposal).

## Environments
- `.venv`: main (qwen-asr pins transformers 4.57). `jrec` CLI = `.venv/bin/jrec`.
- `.venv-nemo`: Nemotron 3 Diarization (transformers from git). Called as a subprocess by `jrec.diarize`.
- `.venv-enh`: pyannote, ClearerVoice, scoring (spike only). `.venv-vllm`: vLLM overlay (parked, hangs on GB10).
- After (re)installing imgui-bundle: `scripts/fix-imgui-gl.sh` (the wheel vendors libglvnd → no GLXFBConfigs).
- DeepFilterNet: `spike/bin/deep-filter` (official aarch64 release binary), or `JREC_DEEP_FILTER`.

## Rules learned the hard way
- **GB10 hard-resets under heavy combined load** (CPU zones hit 95 °C; critical trip at 104 °C). Run GPU jobs
  **one at a time**; the app pauses at ≥ 90 °C (`thermal.wait_cool`) and holds a per-library GPU lock.
  Long benchmark-style runs: only when the user asks.
- The user stopped GPU benchmark runs: develop without benchmarks unless asked.
- Evidence rules: never modify archived originals, never cut padding, never transcode originals.
- Keep the demo library (`~/jrec-demo`, built by `scripts/make_demo.py`) separate from the real one (`~/jrec-library`).

## Testing
- `.venv/bin/python -m pytest -q tests` (fake ASR engine + fake LLM server; no GPU).
- UI: on the private display `:99` only (start it with `~/dev/jev/jev-photos/scripts/test-display.sh`), with
  `DISPLAY=:99 __GLX_VENDOR_LIBRARY_NAME=mesa LIBGL_ALWAYS_SOFTWARE=1` and `jrec ui --ui-script "open:1,wait:1.5,shot:/path.png"`.
  Never send key events to the user's display `:1`. Opt-in pytest: `JREC_UI_TEST_DISPLAY=:99`.

## UI (src/jrec/ui/)
app.py (layout, jobs, keys, --ui-script steps), timeline.py, transcript.py, dialogs.py, player.py (ffplay child:
speed/sound/channel), flags.py (drawn flags), data.py. Styling: polish-ui skill via theme.py tokens.
Script steps for screenshots: open:N wait:S seek:T find:Q ab:A-B note:T/text row:N rowsel:N viewlang:L
importdlg:PATH fakejob:i/n/stage/d/t progress settings theme:Dark|Light size:1.5 shot:PATH.
Use a hard-linked copy of ~/jrec-demo/lib for screenshots that write notes/translations.

## Open items (2026-10-02)
- Vault: age per-file, password + recovery key, lossless only; **waiting for the user's OK to build**.
- Segments split mid-sentence at the 25 s limit; merge at sentence boundaries.
- Tamil LID → Whisper fallback; Sony track-mark timestamps (needs a real TX660 file); vLLM backend.
- Summaries/translation need an LLM server (Qwen3.8 TensorFold on :8888 is stopped by default).
