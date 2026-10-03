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
app.py (layout, keys, --ui-script steps), shell.py (command registry = keymap, palette, utility cluster,
Tasks and logs panel, Help), tasks.py (task queue, one job at a time, tasks.json), helptext.py (Help in 4
languages), timeline.py, transcript.py, dialogs.py, player.py (ffplay child:
speed/sound/channel), flags.py (drawn flags), data.py. Styling: polish-ui skill via theme.py tokens.
Script steps for screenshots: open:N wait:S seek:T find:Q ab:A-B note:T/text row:N rowsel:N viewlang:L
importdlg:PATH fakejob:i/n/stage/d/t tasks[:logs] palette:Q help:concepts|glossary|shortcuts about lang:zh-CN settings settingsq:Q tab:conv|people|rec|moments
person:NAME speaker:ROW newnote:T notetext:X righttab:insights|summary theme:System|Light|Dark|Tokyo Night size:1.5 shot:PATH.
Every UI string goes through i18n.T("English") (en, zh-CN, ja, ko tables in src/jrec/i18n.py); new commands go
into shell.COMMANDS so the palette, tooltips and Help › Shortcuts pick them up.
Use a hard-linked copy of ~/jrec-demo/lib for screenshots that write notes/translations.
Gallery: docs/gallery/*.png, regenerate with --ui-script and a fresh XDG_CONFIG_HOME (no leftover prefs).
Untranslated strings: JREC_I18N_MISSING=/tmp/miss.txt jrec ui --ui-script "lang:zh-CN,...,shot:x" lists them.
`jrec ui` is single-window per library (instance.py); --ui-script runs and JREC_MULTI_INSTANCE=1 skip the check.

## Open items (2026-10-03)
- Demo 2025-10-04 (ASCEND, real HK Mandarin–English chat) transcribed: 89 rows, 2 speakers, MER 22.9 % vs ses2.json
  (ses2[60 s:480 s]). Not yet summarized (a summary cold-boots TensorFold, ~88 GiB).
- Vault: age per-file, password + recovery key, lossless only; **waiting for the user's OK to build**.
- Segments split mid-sentence at the 25 s limit; merge at sentence boundaries.
- Tamil LID → Whisper fallback; Sony track-mark timestamps (needs a real TX660 file); vLLM backend.
- Summaries/translation need an LLM server. llmserver.py starts/stops it on demand when the profile has
  start_cmd/stop_cmd (demo: docker start/stop qwen38-flash-next-tf, ~88 GiB, cold boot ~2–4 min).
  Speech work stops it first. Never stop an unmanaged server (no start_cmd) from code.
