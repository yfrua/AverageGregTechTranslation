# Whisper Transcription Tools

Whisper transcription with Silero VAD filtering, beam search, word
timestamps, and semantic cue splitting. Built on faster-whisper
(CTranslate2): VAD removes silence/music *before* inference, which prevents
the looping/hallucination issues of raw openai-whisper at the source.

Typical episode workflow:
1. Drop the video/audio as `RDR_epN.mp4` in this directory.
2. Run `transcribe_with_fix.py` → `RDR_epN.raw.srt`.
3. Review/correct the raw SRT (jargon, stutters, cue boundaries) → final `RDR_epN.srt`.
4. Lint against repo style rules: `python3 scripts/subtitle_lint.py RDR_epN.srt`.

## Cue-building policy

Implemented in `transcribe_with_fix.py::build_cues`; limits mirror
`scripts/subtitle_lint.py`:

- **One line per cue** — no two-line wrapping (guidelines.md).
- **Split priority**: sentence end (`.?!…`) > clause boundary (`,` `;` `:` `—`)
  > speech pause (≥0.35 s) > breath-point force-split (pathological runs only).
- **Lengths**: pack to ≤95 chars per cue (leaves headroom so the Chinese
  translation sharing the timecode fits <32 CJK chars); 110 is the hard cap.
  A single clause with no boundary inside may exceed 110 rather than be
  force-split mid-thought (lint warns; accepted case-by-case).
- **Timing**: raw word timestamps — no minimum duration, no gap chaining;
  flash-frame warnings from the linter are accepted.
- **Punctuation**: trailing `.` and `,` stripped, `?` `!` `...` `—` kept,
  casing comes from ASR plus the manual review pass.
- Echo artifacts (ASR repeating the previous cue's last word) are dropped
  automatically; anything subtler is left to the correction pass.

Outputs: `<prefix>.raw.srt`, `<prefix>.raw.txt` (plain transcript),
`<prefix>.words.json` (word timestamps; enables `--reuse-words` to re-split
without re-running ASR).

## Installation

Already set up in the `whisper` conda env:
```bash
pip install faster-whisper        # pulls ctranslate2 + onnxruntime + av
```

Notes on version pinning:
- ctranslate2 >= 4.5 needs cuDNN 9 (this machine has it). For CUDA 11 /
  cuDNN 8 systems use `ctranslate2==3.24.0`.
- ctranslate2 4.x removed the old Whisper `.pt` converter, so we use a
  pre-converted CTranslate2 model instead of `large-v3.pt`.

## Model setup

HuggingFace is unreachable from this machine (even through the local proxy).
Download the ready-made CTranslate2 model from ModelScope instead:

```bash
mkdir -p models/faster-whisper-large-v3 && cd models/faster-whisper-large-v3
for f in config.json tokenizer.json vocabulary.json preprocessor_config.json model.bin; do
    curl -L -o "$f" \
      "https://www.modelscope.cn/models/gpustack/faster-whisper-large-v3/resolve/master/$f"
done
```
(`model.bin` is ~2.9 GB; mirrors `keepitsimple/faster-whisper-large-v3` and
`pengzhendong/faster-whisper-large-v3` host identical files.)

## Usage

```bash
# Typical run (video or audio input works)
python transcribe_with_fix.py RDR_ep1.mp4

# Explicit output prefix and device
python transcribe_with_fix.py RDR_ep1.mp4 --out-prefix RDR_ep1 --device cuda
```

Options:
```
positional arguments:
  media                 Input audio/video file (anything ffmpeg can read)

optional arguments:
  --model-dir           Path to CTranslate2 model dir
                        (default: ./models/faster-whisper-large-v3)
  --out-prefix          Output prefix (default: input stem)
  --device              cuda or cpu (default: cuda)
  --compute-type        float16 / int8_float16 / int8 (default: float16)
  --language            Language code (default: en)
  --beam-size           Beam width (default: 5)
```

Decoding settings baked in: `temperature=0`, `condition_on_previous_text=False`
(prevents loop propagation across chunks), `vad_filter=True`
(`min_silence_duration_ms=500`).

## Manual correction pass

No ASR is error-free on gaming audio, so every transcript gets a manual
review pass before release.

Workflow:
1. Skim `RDR_epN.raw.txt` (fast) or `RDR_epN.raw.srt` (with timings).
2. Apply fixes, typically as a small throwaway script:
   - global textual replacements — stutters, echo words
   - full-text cue overrides — jargon, grammar, boundary adjustments
   - merges of interjection cues into the following one
3. Write the final `RDR_epN.srt`, then lint (see workflow above).

Common ASR error classes seen on this content:
- Mod jargon: "Ricker's mods" → Reika's mods, "RotoEcraft" → RotaryCraft,
  "Redis tone power" → redstone power
- Word-level stutters at segment boundaries: "which which", "we We"
- Orphan echo cues: last word of a cue repeated as a tiny standalone cue
- Homophones: "first tour" → first ore, "savaged" → salvaged,
  "to mount" → amount

## File inventory

- `models/faster-whisper-large-v3/` — CTranslate2 model used by the script
- `RDR_ep*.raw.srt/.txt/.words.json` — uncorrected ASR output (keep for diffing)
- `RDR_ep*.srt` — corrected, release-ready subtitles
- `large-v3.pt` — legacy openai-whisper checkpoint, unused by the current
  pipeline (kept only as a backup; safe to delete if disk space is needed)
