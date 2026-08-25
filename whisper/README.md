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

---

## Installation

### 1. Create the environment

```bash
conda create -n whisper python=3.9 -y
conda activate whisper

# ffmpeg is a system dependency (audio decoding + chunk extraction)
conda install -c conda-forge ffmpeg -y
```

Python 3.9 is what this repo's env uses; any 3.9–3.12 works, but note that
the model-conversion script pinned in step 3 of "Model transform" must match
(see the Python-version caveat there).

### 2. Install faster-whisper

```bash
pip install faster-whisper==1.2.1
```

This pulls: `ctranslate2` (inference engine), `onnxruntime` (Silero VAD),
`av` (PyAV, media I/O), `tokenizers`, `huggingface-hub`. Verified pins:

| package | version | notes |
|---|---|---|
| faster-whisper | 1.2.1 | requires `ctranslate2>=4.0,<5` |
| ctranslate2 | 4.8.1 | needs **cuDNN 9** (see table below) |
| av | 15.x | wheels exist for py3.9; older fw versions pin old `av` that fails to build |
| tiktoken | any | only needed for model conversion |

**GPU compatibility** — pick ctranslate2 by your driver/cuDNN combo:

| ctranslate2 | CUDA | cuDNN | GPU compute types |
|---|---|---|---|
| 4.5 – 4.8.x | 12 | **9** | float16, int8_float16, int8 |
| 4.4.x | 12 | 8 | same |
| ≤ 3.24.0 | 11/12 | 8 | same (needs `faster-whisper==0.10.1`) |

Check what you have:

```bash
ldconfig -p | grep libcudnn.so.9      # cuDNN 9 present?
nvidia-smi                            # driver / CUDA version (top right)
```

### 3. Verify the install

```bash
python -c "import ctranslate2; print('ct2', ctranslate2.__version__, \
  '| CUDA devices:', ctranslate2.get_cuda_device_count())"
# expect: ct2 4.8.1 | CUDA devices: >=1
```

If `CUDA devices: 0` while you have a GPU, it is almost always the
cuDNN-majority mismatch from the table above.

---

## The model: formats and how to get one

faster-whisper does **not** load OpenAI's `.pt` checkpoints directly. Two
formats exist:

| format | example | produced by |
|---|---|---|
| OpenAI torch checkpoint | `large-v3.pt` (~3 GB) | OpenAI release page |
| **CTranslate2 model dir** | `models/faster-whisper-large-v3/` | SYSTRAN mirror, or converted locally |

A CT2 model dir contains five files — all are required for offline use:

```
config.json               # architecture metadata
model.bin                 # weights (fp16 ≈ 3 GB for large-v3)
tokenizer.json            # fast tokenizer (encoding)
vocabulary.json           # id→token table (decoding)
preprocessor_config.json  # mel-spectrogram params (80 or 128 mel bins!)
```

Three ways to obtain a CT2 dir — pick based on what your network allows:

### Route A — ModelScope download (recommended)

HuggingFace may be unreachable from your network (it is from the one this
repo was developed on), but ModelScope mirrors the exact SYSTRAN builds:

```bash
mkdir -p models/faster-whisper-large-v3 && cd models/faster-whisper-large-v3
for f in config.json tokenizer.json vocabulary.json preprocessor_config.json model.bin; do
    curl -L -o "$f" \
      "https://www.modelscope.cn/models/gpustack/faster-whisper-large-v3/resolve/master/$f"
done
```

- `model.bin` is ~2.9 GB; verify against `sha256sum` published on the
  ModelScope page if paranoid.
- Identical files also live at `keepitsimple/faster-whisper-large-v3` and
  `pengzhendong/faster-whisper-large-v3`.

### Route B — HuggingFace hub (if reachable from your network)

```bash
curl -sI -m 8 https://huggingface.co -o /dev/null -w "%{http_code}\n"   # want 200

# either let faster-whisper fetch it once (cached under ~/.cache/huggingface):
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda')"
# or download explicitly:
huggingface-cli download Systran/faster-whisper-large-v3 --local-dir models/faster-whisper-large-v3
```

### Route C — Transform `large-v3.pt` locally (fully offline)

Convert the OpenAI checkpoint we already have into CT2 format. This is a
two-step transform: **`.pt` → HF transformers dir → CTranslate2 dir**.
Every command below was validated end-to-end with `tiny.pt`
(same code path as large-v3).

#### Step 0 — extras

```bash
pip install "transformers>=4.38" tiktoken
# torch is already present (openai-whisper depends on it)
```

#### Step 1 — get the conversion script

The converter ships only in the GitHub repo, not the PyPI wheel, and
`raw.githubusercontent.com` is blocked on some networks (including this
repo's origin) — use the GitHub API instead.
Note: GH-main uses py3.10+ syntax (`str | None`); pin the `v4.38.2` tag for
a py3.9-compatible copy:

```bash
curl -s -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/huggingface/transformers/contents/src/transformers/models/whisper/convert_openai_to_hf.py?ref=v4.38.2" \
  -o convert_openai_to_hf.py
```

Also grab Whisper's tokenizer vocab (needed offline; normally fetched from
`raw.githubusercontent.com/openai/whisper`, which is blocked):

```bash
curl -s -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/openai/whisper/contents/whisper/assets/multilingual.tiktoken" \
  -o multilingual.tiktoken
```

#### Step 2 — `.pt` → HF transformers dir

Two hub-touching spots exist and both have offline workarounds:

1. `GenerationConfig.from_pretrained("openai/whisper-large-v3")` — runs
   unconditionally. CTranslate2 never reads `generation_config.json`, so a
   stub is harmless for our use.
2. The tokenizer build reads `multilingual.tiktoken` from
   `raw.githubusercontent.com` — patched to use the local copy.

Driver script (run next to `large-v3.pt` and the two downloaded files):

```python
import importlib.util
spec = importlib.util.spec_from_file_location("conv", "convert_openai_to_hf.py")
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)

from transformers import GenerationConfig
conv.GenerationConfig.from_pretrained = staticmethod(lambda *a, **k: GenerationConfig())

_orig_download = conv._download
def _patched_download(url, root=".", **k):
    if "tiktoken" in url:
        return "multilingual.tiktoken"      # local copy from Step 1
    return _orig_download(url, root, **k)
conv._download = _patched_download

conv.load_tiktoken_bpe = __import__("tiktoken.load",
                                    fromlist=["load_tiktoken_bpe"]).load_tiktoken_bpe

model, is_multi, nlang = conv.convert_openai_whisper_to_tfms("large-v3.pt", "hf_large_v3")
model.generation_config = GenerationConfig()
model.save_pretrained("hf_large_v3")

from transformers.models.whisper.processing_whisper import WhisperProcessor
tok = conv.convert_tiktoken_to_hf(is_multi, nlang)
fe = conv.WhisperFeatureExtractor(feature_size=model.config.num_mel_bins)
WhisperProcessor(tokenizer=tok, feature_extractor=fe).save_pretrained("hf_large_v3")
```

Resulting `hf_large_v3/`: `config.json model.safetensors generation_config.json
tokenizer.json vocab.json merges.txt added_tokens.json special_tokens_map.json
tokenizer_config.json preprocessor_config.json` (~6 GB fp32).

Alternative: if the VPN happens to be up, skip the stub entirely — the
unmodified script just works (`--convert_preprocessor True` flag does steps
the driver does manually).

#### Step 3 — HF dir → CTranslate2 dir

```bash
ct2-transformers-converter \
    --model hf_large_v3 \
    --output_dir models/faster-whisper-large-v3 \
    --quantization float16 \
    --copy_files tokenizer.json
```

Gotchas (both hit during validation):

- `--copy_files tokenizer.json` is **mandatory for offline use**. Without
  it, faster-whisper tries to fetch `openai/whisper-*/tokenizer.json` from
  the hub at every model load and dies offline.
- Do **not** add `preprocessor_config.json` or `vocabulary.json` to
  `--copy_files`: the converter generates both itself (mel bins come from
  the model config — large-v3 uses 128, everything else 80; copying across
  sizes breaks inference with shape errors), and copying `vocabulary.json`
  collides with the auto-export.

#### Step 4 — smoke test

```bash
ffmpeg -y -ss 30 -t 8 -i RDR_ep1.m4a -vn test.wav
python - <<'EOF'
from faster_whisper import WhisperModel
m = WhisperModel("models/faster-whisper-large-v3", device="cuda", compute_type="float16")
segs, _ = m.transcribe("test.wav", language="en")
print(" ".join(s.text for s in segs))
EOF
```

---

## Usage

```bash
# Typical run (video or audio input works)
python transcribe_with_fix.py RDR_ep1.mp4

# Explicit output prefix and device
python transcribe_with_fix.py RDR_ep1.mp4 --out-prefix RDR_ep1 --device cuda

# Re-split cues without re-running ASR (after tweaking splitter settings)
python transcribe_with_fix.py RDR_ep1.mp4 --reuse-words
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
  --compute-type        float16 / int8_float16 / int8 (default: float16;
                        CPU fallback: int8)
  --language            Language code (default: en)
  --beam-size           Beam width (default: 5)
  --reuse-words         Skip ASR; rebuild cues from the existing .words.json
```

Decoding settings baked in: `temperature=0`, `condition_on_previous_text=False`
(prevents loop propagation across chunks), `vad_filter=True`
(`min_silence_duration_ms=500`).

Outputs:
- `<prefix>.raw.srt` — subtitle file with semantic cue splitting (policy below)
- `<prefix>.raw.txt` — plain text transcript (one line, for LLM review)
- `<prefix>.words.json` — word timestamps (input to `--reuse-words`)

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
- `large-v3.pt` — legacy openai-whisper checkpoint; unused at runtime but
  usable as input for the Route C transform (safe to delete if disk is tight)
