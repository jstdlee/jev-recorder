# jev-recorder: plan (P0, draft for sign-off)

Plug in a USB voice recorder, and the app automatically imports the recordings, finds
the conversations, cleans up the audio, transcribes it against a real wall-clock timeline,
and summarises it. Everything runs offline on the GB10.

## 1. Goals and hard rules

1. **Originals are never modified.** Each source file is copied byte-for-byte into an
   archive (read-only, content-addressed by SHA-256) before anything else happens.
2. **Trustable cuts.** A conversation clip always includes at least **10 min of raw audio
   before and after** the detected speech, even if that audio is silence or noise. The
   padding is clamped only where the recording itself starts or ends (or is stitched
   across split files, see 4.3).
3. **Derived audio can be verified.** The raw clip is a stream copy (MP3 frames copied,
   not re-encoded), so its frames are bit-identical to the original. `manifest.json`
   records the source hash and the frame/time offsets.
4. **Real time everywhere.** Every segment and word carries an absolute datetime
   (with timezone and a confidence level) as well as its offset in the file.
5. The enhanced audio is a separate track. It is used for listening, never as evidence.

## 2. Existing open source (none of it does the whole job)

| Project | What it covers | What it lacks |
|---|---|---|
| WhisperX | ASR, word alignment, pyannote diarization | ingest, padding, wall clock |
| Scriberr / Speakr / Diariz | self-hosted transcription web UI with diarization | USB auto-import, forensic padding, real-time timeline |
| Meetily / OpenWhispr | live meeting capture | made for live meetings, not recorder files |
| auto-editor | cuts silence | does the opposite of rule 2 |
| ClearerVoice-Studio, DeepFilterNet | speech enhancement | n/a |

So the plan is to **build the orchestrator and reuse the components**. The unique parts
are the ingest daemon, timestamp recovery, the padding and segmentation logic, the
manifest, and the timeline UI.

## 3. Stack

- **Python 3.12 + uv**, one package, CLI first (`jrec import|process|search|serve`)
- **ffmpeg** for decoding, resampling and stream-copy cuts. **mutagen** for ID3/MP4/BWF tags
- **Ingest:** confirm-first (4.1). A systemd user service watching **udisks2** (via D-Bus, or pyudev) for new
  mounts. Recognised devices are configured by USB vendor:product, volume label or a marker
  folder (e.g. `VOICE/`, `RECORDER/`, `DCIM/`).
  It scans `*.mp3 *.wav *.m4a *.wma *.ogg *.opus *.flac *.amr *.aac *.dss` (DSS is Olympus,
  via ffmpeg or a later decoder).
- **Storage:** SQLite (with FTS5 for transcript search), plus a plain folder tree
- **ML:** PyTorch on the GB10 (aarch64 + CUDA). Each model runs as a stage that can be
  swapped out
- **UI (M6): ImGui desktop** (decided), in the same style as jev-photos and jev-jelly.
  It has a waveform (min/max peaks precomputed and cached), an absolute clock axis, speaker
  lanes, a speech/pad shading overlay, a synced transcript, search, and playback (miniaudio).
  It reads `jrec.sqlite` and the conversation folders, and the CLI or daemon does the
  processing. Test it on Xvfb :99, never on the user's display.

## 4. Pipeline

```
USB mount -> scan -> copy + sha256 -> archive (ro) -> probe + timestamp
  -> decode 16 kHz mono -> VAD -> conversation windows (+-10 min pad, merge, stitch)
  -> cut raw clip (stream copy) -> enhance (separate track)
  -> ASR + forced alignment -> diarization -> absolute timeline
  -> outputs (json/srt/vtt/md, tags, chapters) -> LLM summary/title/actions -> index
```

### 4.1 Ingest: **confirm before anything is loaded or copied** (decided)
1. **Detect:** udisks2 sees the recorder. The app mounts it **read-only** (`-o ro`) where
   possible, so the app physically cannot change the device. Only the directory listing
   and file stats are read at this point.
2. **Preview:** the app shows a desktop notification ("Recorder X: 7 new files, 3.2 GB")
   and opens the ImGui **Import dialog** with a checkbox list showing file, size, mtime,
   estimated date, duration, and new / already-imported status. Duration comes from
   reading the file header only. Already-imported files are recognised from a cache of
   (device serial, path, size, mtime), without reading the audio.
3. **Confirm:** the choices are *Import selected*, *Import all new*, or *Skip*. Nothing is
   copied until you choose. "Auto-import this device" can be enabled per device, and is
   **off** by default.
4. **Copy:** files are copied to staging, the SHA-256 is computed, then each file is
   moved to `archive/<sha256>.<ext>` and set read-only. Hashes are compared to dedupe. A
   progress bar shows how far along it is, and the device can be ejected safely when done.
5. Files are never deleted from the device. A deletion option may come later, only with
   explicit confirmation and a remount read-write.
- The device identity (USB serial) is recorded for each source. Clock offsets are tracked per device.

### 4.2 Real datetime recovery (the TODO-heavy part)
Possible sources, ranked, each stored with a confidence level:
1. Embedded metadata: BWF `bext` OriginationDate/Time (Zoom, Tascam), ID3 `TDRC`/`TDEN`,
   WAV `LIST/INFO ICRD`, MP4 `creation_time`
2. Filename patterns: per-brand regexes (e.g. Sony `YYMMDD_HHMM.mp3`). These can be added in config
3. FAT mtime, which is usually the time the file was closed, so start = mtime - duration.
   FAT has no timezone and only 2 s resolution
4. Manual override
- **Clock drift:** cheap recorders drift and often have no timezone. There is a per-device
  offset (set once by comparing the recorder clock with real time, or applied to a single
  import). The plan also includes an optional "clock-check" helper: say the real time on
  the recording, and the ASR picks it up.
- **Split files:** recorders split long recordings (by file size or every N minutes).
  Consecutive files whose end time is within a few seconds of the next start time are
  treated as one continuous stream.

### 4.2a Device profile: **Sony ICD-TX660** (the user's recorder, 16 GB)
Facts from the Sony Help Guide (5-025-099-11):
- USB mass storage, volume **`IC RECORDER`**. Recordings live in **`REC_FILE/FOLDERxx/`**.
  `MUSIC/` holds PC-transferred music and is ignored.
- It records **MP3** (192 kbps stereo by default, 128 kbps stereo, 48 kbps mono) or
  **LPCM 44.1 kHz/16-bit `.wav`**.
- File name = **recording start, to the minute, local time**: `YYMMDD_HHMM.mp3` (e.g.
  `211010_1010.mp3`). The on-device "Change File Name" adds a prefix (`Important_211010_1010.mp3`),
  so the parser uses `(?:^|_)(\d{6})_(\d{4})\.(mp3|wav)$`. The device stores no timezone,
  so the device config holds one (default `Asia/Singapore`).
- **Seconds:** taken from FAT mtime minus duration, which should land within the
  filename's minute. If it doesn't, the file is flagged.
- **Auto split:** files split at **1 GB MP3 (~12 h 25 min at 192k)** or **4 GB WAV
  (~6 h 45 min)**, and Sony warns "some of the recording may be lost around the divided
  point". Stitching (4.2) joins them and marks the seam as a *possible gap*. A gap is never
  silently closed.
- **VOR (voice-operated recording) pauses recording during silence.** That makes the file
  shorter than the real time that passed, so every timestamp after the first pause would
  be wrong. **Rule: VOR stays OFF.** Detection: if `mtime - filename_start` is much larger
  than the duration, the file is flagged *"timeline discontinuous (VOR?)"*. Only the
  start is trusted, and the UI shows the clock axis as approximate after that point.
- **Auto Track Marks + Time Stamps:** these add a mark every 5/10/15/30 min. If the marks
  carry real clock times inside the file, they give **built-in timeline anchors** that
  correct drift and expose VOR gaps. *M0 task:* reverse-engineer where Sony stores them
  (likely a private ID3 frame or chunk) from a sample file.
- **Recording Filter NCF (Noise Cut) is ON by default.** It filters the audio *before* it
  is saved, so the "original" is already processed. M0 compares NCF vs LCF vs OFF. Our own
  enhancement (4.4) works on a separate track anyway.
- **Clock drift check:** the TX660 shows its clock in HOLD state. The import dialog
  includes an optional "Recorder shows __:__:__" field. Each entry stores a drift sample,
  and the offset is interpolated per file.

**Recommended TX660 settings** (one-time, shown as a checklist in the app):

| Setting | Value | Why |
|---|---|---|
| Date & Time | set accurately, 24 h | the filename is the main time source |
| VOR | **OFF** | keeps the timeline continuous |
| REC Mode | MP3 192 kbps ST (~159 h on 16 GB), or LPCM for best evidence quality (~21 h) | |
| Recording Filter | **LCF or OFF** (pending M0) | less on-device processing of the original |
| Mic Sensitivity | Medium / Auto | avoids clipping |
| Auto Track Marks | 5 min, **Time Stamps On** | gives possible timeline anchors |

Device config (`config.toml`):
```toml
[[device]]
name = "sony-tx660"
match = { label = "IC RECORDER", usb = "054c:*" }   # vendor id 054c = Sony; product id filled in from lsusb at first plug-in
roots = ["REC_FILE"]
ignore = ["MUSIC"]
filename_time = '(?:^|_)(\d{6})_(\d{4})\.(mp3|wav)$'   # YYMMDD_HHMM = start, local time
timezone = "Asia/Singapore"
split_bytes = { mp3 = 1_073_741_824, wav = 4_294_967_296 }
auto_import = false
```

### 4.3 Conversation detection and padding
- **Silero VAD** (MIT, fast on CPU) finds speech regions
- Merge speech regions closer than `gap = 3 min` (configurable). Drop windows with less
  than `min_speech = 20 s` of speech (configurable)
- Add a pad of `pad = 10 min` on each side, then merge any windows whose padding overlaps.
  The padding can cross file boundaries within a stitched stream
- Optional M5+: an audio-event classifier (PANNs or BEATs) tags music, TV and machinery,
  so "non-useful" sound is marked rather than cut. Cutting it would break rule 2

### 4.4 Enhancement (separate track)
- Default: **DeepFilterNet3** (MIT/Apache, fast, works well for real recorder noise)
- Strong option: **ClearerVoice-Studio MossFormer2_SE_48K** (Apache-2.0)
- Then loudness normalisation (EBU R128, ffmpeg `loudnorm`)
- ASR is tested on raw audio vs enhanced audio in M0. Enhancement often makes ASR
  *worse*, so the choice is based on measurements

### 4.5 Speech to text with timeline
- **Languages (decided): mainly Asian.** Mandarin, Cantonese and other Chinese dialects,
  English, Malay/Indonesian, Japanese, Korean, Thai, Vietnamese, Filipino and Hindi are all
  covered by Qwen3-ASR. Tamil, Burmese, Khmer and Bengali go to the Whisper fallback.
  European languages are not a goal; they work only where these models happen to cover
  them. Speakers often mix languages, so language ID runs on every segment and the
  language is stored per segment.
- **Models to deploy (recommended, all open weights, all checked in M0):**

| Role | Primary | Fallback / contender | Why |
|---|---|---|---|
| ASR | **Qwen3-ASR-1.7B** (Apache-2.0, Jan 2026) | Qwen3-ASR-0.6B for fast passes | 30 languages + 22 Chinese dialects, including Cantonese, Mandarin, English and Malay. Handles code-switching, beats Whisper-large-v3 on FLEURS, serves through vLLM |
| ASR for other languages | **Whisper large-v3** (faster-whisper) | n/a | for the Asian languages Qwen3-ASR lacks: **Tamil**, Burmese, Khmer, Bengali |
| Word timestamps | **Qwen3-ForcedAligner-0.6B** (11 languages, ~32 ms error, clips of 5 min or less) | **MMS ctc-forced-aligner** (1000+ languages) | the Qwen aligner covers zh/yue/en/ja/ko but not ms/id/th/vi/tl/ta, so those go to MMS (M0 checks the exact list) |
| Diarization | **NVIDIA Nemotron 3 Diarization** (Sep 2026, up to 8 speakers, single pass) | pyannote community-1 | M0 picks the winner on your audio. pyannote needs an HF token |
| All-in-one contender | **VibeVoice-ASR 9B** (MIT; 60 min single pass with who/when/what, hotwords) | MOSS-Transcribe-Diarize 0.9B (Apache-2.0, segment-level only) | could replace ASR + diarization in one step, but has heavier memory use and unverified Cantonese/Malay support |
| Cantonese specialist | n/a | MiMo-V2.5-ASR (MIT, zh/yue/en only) | used only if Qwen3-ASR is weak on your Cantonese |
| VAD | Silero VAD (latest) | n/a | MIT, fast on CPU |
| Enhancement | DeepFilterNet3 | ClearerVoice MossFormer2_SE_48K | see 4.4 |

  Not chosen: Parakeet and Canary (European languages only), Granite Speech 4.1 (few
  languages), Moonshine (English focus), and streaming-only models (no benefit for files).
- **Flow:** VAD chunks of 5 min or less, then language ID, then the ASR router, then the
  aligner router, then diarization over the whole window, then word-to-speaker assignment.
  Hotwords (names, places) from config are passed as ASR context.
- Every word gets `t_file`, `t_clip` and `t_abs` (ISO 8601 + timezone) plus its speaker
  and confidence

### 4.6 LLM post-processing (offline). **Decided: any OpenAI-compatible endpoint**
For each conversation: a title, a short summary, key points, action items, named
people/places, and the language. Each item cites transcript timestamps, so every claim
links back to the audio.
Configured in `config.toml` under `[llm] base_url, model, api_key, max_tokens, extra_body`.
There can be several named profiles (e.g. `fast`, `best`), chosen per run, and the endpoint
is checked when the app starts. Prompts are written so a 4B model can follow them: JSON
output that is schema-validated and retried, and transcripts longer than the context are
chunked (map, then reduce). Summaries are written in the conversation's main language, with
an optional English copy. Thinking-mode models (e.g. Qwen3.8) need a large max_tokens.
Suggested models to point it at:

| Option | Size | Notes |
|---|---|---|
| **Qwen3.5-9B** (recommended) | ~6-8 GB at Q4, ~18 GB bf16 | strongest small model for multilingual and Chinese, long context |
| Qwen3.5-4B | ~3-4 GB | lighter. For when Qwen3.8 is loaded and memory is tight |
| Gemma 4 E4B | ~4-5 GB | good English summaries, weaker in Chinese |
| Reuse Qwen3.8 Flash Next on :8888 | already running | best quality, but it holds ~90 GB, so the app would depend on it being up |

### 4.7 Outputs (one folder per conversation)
```
library/
  archive/<sha256>.<ext>                 # read-only originals
  conversations/2026-09-30_1423_<slug>/
    raw.mp3            # stream-copied, includes the +-10 min padding
    enhanced.opus      # listening copy
    transcript.json    # words, segments, speakers, rel + abs time
    transcript.srt / .vtt / .md
    labels.txt         # Audacity label track (speech regions, speakers)
    summary.md         # LLM output with timestamp citations
    manifest.json      # source hashes, offsets, timestamp source+confidence,
                       # tool + model versions, sha256 of every derived file
  jrec.sqlite          # index + FTS
```
Tags (derived files only): ID3 `TDRC`, `TXXX:RECORDING_START` (ISO + timezone),
`TXXX:SOURCE_SHA256`, and `CHAP`/`CTOC` chapters for each speech segment. For WAV output,
these go in BWF `bext` instead.
Optional: an OpenTimestamps proof of the manifest hash (shows the manifest existed at that time).

## 5. Milestones
- **M0 spike:** on the GB10, run 2-3 of your real recordings (Cantonese, Mandarin,
  English and Malay if possible) through Qwen3-ASR 1.7B/0.6B, Whisper-v3, VibeVoice-ASR,
  both aligners, Nemotron vs pyannote, and raw vs enhanced audio. Score error rate on a
  hand-corrected 5-min sample, plus speed, and pick the defaults
- **M1:** TX660 profile, ingest daemon, archive, hashing, timestamp recovery, device config
- **M2:** VAD, windows, padding, stitching, stream-copy cuts, manifest
- **M3:** ASR, alignment, diarization, transcript outputs, tags
- **M4:** enhancement track
- **M5:** LLM summaries, SQLite FTS search, `jrec search`
- **M6:** web timeline UI

## 6. Open questions
1. ~~Recorder~~: Sony ICD-TX660 (see 4.2a)
2. Languages in the recordings (zh / en / ms / mixed / dialects?)
3. Should imported files ever be deleted from the device? (default: never)
