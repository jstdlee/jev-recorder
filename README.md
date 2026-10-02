# jev-recorder

Plug in a USB voice recorder (Sony ICD-TX660 profile built in): recordings are archived
untouched, conversations are cut with 10 min of raw audio kept on each side, transcribed
offline (Qwen3-ASR-1.7B or Cohere Transcribe, word times, speakers) on a real wall-clock timeline, summarised by
any OpenAI-compatible LLM, and searchable. Every clip is an exact byte range of the archived
original, with a shell command in `manifest.json` to verify it.

```bash
uv venv -p 3.12 && uv pip install -e ".[spike,ui,dev]"   # ML deps live in the spike extra for now
scripts/fix-imgui-gl.sh                                   # once, after installing imgui-bundle
jrec ui                                                   # desktop app (import dialog pops up on plug-in)
jrec watch                                                # or: notification-only daemon
jrec import /media/$USER/IC\ RECORDER                    # or step by step: import, cut, transcribe,
jrec process                                              #   enhance, summarize (process = all of them)
jrec search 预算                                           # full-text search (CJK works)
jrec verify                                               # re-check every clip against the archive
```

Config: `~/.config/jrec/config.toml` (defaults in `src/jrec/config.py`): library path, device
profiles, and `[llm.profiles.*]` endpoints. Plan and decisions: [PLAN.md](PLAN.md).
Diarization runs in `.venv-nemo` (Transformers >= 5); see `src/jrec/diarize.py`.

## Speech model (Settings > Transcription, or `[asr]` in the config)

| | Qwen3-ASR-1.7B (default) | [Cohere Transcribe 03-2026](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026) |
|---|---|---|
| Languages | 52, finds the language itself | 14 (ar de el en es fr it ja ko nl pl pt vi zh), language must be given |
| Runs in | `.venv` | `.venv-nemo` worker (Transformers >= 5.4) |
| Word times | Qwen3-ForcedAligner / MMS | the same aligners |

- `language = "auto"` (Cohere only): Qwen3-ASR finds each chunk's language, Cohere writes the text.
  Chunks in other languages (Malay, Tamil, ...) keep the Qwen3-ASR text.
- `language = "en"` (or another ISO code): Cohere only; Qwen3-ASR is not loaded.
- The Cohere model is gated: accept its terms on Hugging Face, then `hf auth login`.
- One run only: `jrec transcribe --asr cohere FOLDER`. `transcript.json` records the model in `asr`.

## Search syntax (sidebar search and "Find in this conversation")

```
roof price                    both words, any order (case, width and 繁/简 ignored)
roof OR 屋顶   roof | 屋顶       either
roof (price OR cost) -cheap   grouping and exclusion (NOT works too)
"next friday"                 exact phrase
/\d{4}\s?\d{4}/                regular expression
note:roof tag:家庭 by:mum lang:cantonese
time:14:00-15:30 date:2025-10-03 after:2025-10-01 before:2025-10-05
```
Rows are matched on their text, translations, notes, speaker name and the talk's/recording's tags.
