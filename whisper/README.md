# transcribe_with_fix.py

Whisper transcription with automatic looping-sentence detection and correction.
When Whisper gets stuck repeating the same phrase, the script detects it via
compression-ratio analysis and re-transcribes only the affected audio clips
with beam search.

## Installation

```bash
# Create conda environment
conda create -n whisper python=3.9 -y
conda activate whisper

# Install dependencies
pip install openai-whisper

# System dependency: ffmpeg (for audio chunk extraction)
conda install -c conda-forge ffmpeg
```

Download a model (or let Whisper fetch it automatically):
```bash
# large-v3 (recommended for English)
wget https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt
```

## Usage

### Full pipeline (transcribe + detect + fix)
```bash
python transcribe_with_fix.py audio.m4a
```

### Dry-run: check only (no re-transcription)
```bash
python transcribe_with_fix.py audio.m4a --dry-run
```

### Skip first pass (use existing .srt, only fix)
```bash
# First run normally to get .srt, then:
python transcribe_with_fix.py audio.m4a --skip-first-pass
```

### GPU selection
```bash
python transcribe_with_fix.py audio.m4a --device cuda:0
python transcribe_with_fix.py audio.m4a --device cuda:1
python transcribe_with_fix.py audio.m4a --device cpu
```

### Tune detection sensitivity
```bash
# Tighter (fewer false positives)
python transcribe_with_fix.py audio.m4a --zscore -2.0 --min-ratio 0.50

# Looser (catches more)
python transcribe_with_fix.py audio.m4a --zscore -1.0 --min-ratio 0.60
```

### Full options
```
positional arguments:
  audio                 Path to input audio file (m4a, mp3, wav, etc.)

optional arguments:
  --model MODEL         Whisper model name or path (default: ./large-v3.pt)
  --out-dir OUT_DIR     Output directory (default: same as input)
  --language LANGUAGE   Language code (default: en)
  --device DEVICE       Torch device: cuda:0, cuda:1, cpu, etc. (default: cuda:0)
  --skip-first-pass     Skip first-pass if SRT already exists
  --dry-run             Only detect buggy segments, don't re-transcribe
  --zscore ZSCORE       Z-score threshold (default: -1.5, lower = stricter)
  --min-ratio MIN_RATIO Compression ratio floor (default: 0.55)
  --hard-floor HARD_FLOOR
                        Hard compression-ratio floor (default: 0.42)
  --keep-chunks         Keep temporary audio chunks on disk
```

## How it works

1. **First pass** — Whisper transcribes the full audio with word timestamps.
2. **Detection** — Each segment's text is compressed with zlib. Looping text
   (e.g. "the cheapest drilling rig there is, the cheapest drilling rig...")
   has an unusually low compression ratio. Statistical outlier detection
   (z-score + MAD) flags suspect segments.
3. **Correction** — Each flagged segment's audio is cut with ffmpeg and
   re-transcribed with beam search (`temperature=0`, `beam_size=5`) to suppress
   the looping behavior.
4. **Output** — Corrected segments are merged back and written as a single `.srt`.
