#!/usr/bin/env python3
"""
Whisper transcription with automatic looping-sentence detection & correction.

The pipeline:
  1. First-pass transcription (returns segments with timestamps).
  2. Detect buggy segments by compression-ratio anomaly (repeated text
     compresses unusually well).
  3. For each buggy segment, cut the audio chunk with ffmpeg and re-transcribe
     it with beam-search (temperature=0) to suppress looping.
  4. Merge corrected segments back, output SRT.
"""

import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import whisper


def compression_ratio(text: str) -> float:
    """zlib compression ratio: compressed_size / original_size."""
    if not text.strip():
        return 1.0
    original = text.encode("utf-8")
    compressed = zlib.compress(original, level=6)
    return len(compressed) / len(original)


def detect_buggy_segments(
    segments: list[dict],
    min_text_len: int = 20,
    zscore_threshold: float = -1.5,
    mad_threshold: float = -2.0,
    min_ratio: float = 0.55,
    hard_floor: float = 0.42,
) -> set[int]:
    """
    Return set of segment indices that are likely looping/glitched.

    Uses two strategies combined with OR:
      1. Z-score outlier on per-segment compression ratio (lower = more
         repetitive → more compressible → buggy).
      2. Median Absolute Deviation (MAD) outlier — robust to skewed
         distributions.

    Additionally, any segment whose compression ratio falls below
    `hard_floor` is flagged unconditionally.
    """
    n = len(segments)
    ratios = []
    indices = []
    for i, seg in enumerate(segments):
        text = seg["text"].strip()
        if len(text) >= min_text_len:
            ratios.append(compression_ratio(text))
            indices.append(i)

    if len(ratios) < 3:
        return set()

    buggy: set[int] = set()

    # --- Z-score ---
    mean = statistics.mean(ratios)
    stdev = statistics.stdev(ratios)
    for idx, r in zip(indices, ratios):
        if stdev > 0 and ((r - mean) / stdev) < zscore_threshold:
            buggy.add(idx)

    # --- MAD ---
    median = statistics.median(ratios)
    mad = statistics.median([abs(r - median) for r in ratios])
    if mad > 0:
        for idx, r in zip(indices, ratios):
            if (r - median) / mad < mad_threshold:
                buggy.add(idx)

    # --- Hard floor ---
    for idx, r in zip(indices, ratios):
        if r < min_ratio:
            buggy.add(idx)
        if r < hard_floor:
            buggy.add(idx)

    return buggy


def cut_audio(input_path: str, start: float, end: float, output_path: str) -> None:
    """Extract [start, end] seconds from input_path using ffmpeg."""
    duration = end - start
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-i",
            input_path,
            "-c",
            "copy",
            output_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def transcribe_segment(
    model: whisper.Whisper,
    audio_path: str,
) -> dict:
    """Transcribe a short clip with beam-search to avoid looping."""
    result = model.transcribe(
        audio_path,
        language="en",
        temperature=0.0,  # greedy / beam-search
        best_of=5,
        beam_size=5,
        patience=2.0,
        compression_ratio_threshold=1.5,  # easier to trigger fallback
        logprob_threshold=-1.0,
        no_speech_threshold=0.6,
        condition_on_previous_text=False,
    )
    segs = result.get("segments", [])
    if segs:
        return segs[0]
    return {"text": ""}


def format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = format_timestamp(seg["start"])
            end = format_timestamp(seg["end"])
            text = seg["text"].strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def main():
    parser = argparse.ArgumentParser(
        description="Whisper transcription with looping-sentence detection & correction"
    )
    parser.add_argument("audio", help="Path to input audio file (m4a, mp3, wav, etc.)")
    parser.add_argument(
        "--model",
        default="./large-v3.pt",
        help="Whisper model name or path (default: large-v3)",
    )
    parser.add_argument(
        "--out-dir", default=None, help="Output directory (default: same as input)"
    )
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument(
        "--skip-first-pass",
        action="store_true",
        help="Skip first-pass if SRT already exists (use cached)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only detect buggy segments without re-transcribing",
    )
    parser.add_argument(
        "--zscore",
        type=float,
        default=-1.5,
        help="Z-score threshold for buggy detection (default: -1.5)",
    )
    parser.add_argument(
        "--min-ratio",
        type=float,
        default=0.55,
        help="Compression ratio floor (default: 0.55)",
    )
    parser.add_argument(
        "--hard-floor",
        type=float,
        default=0.42,
        help="Hard compression-ratio floor (default: 0.42)",
    )
    parser.add_argument(
        "--keep-chunks", action="store_true", help="Keep temporary audio chunks on disk"
    )
    args = parser.parse_args()

    audio_path = Path(args.audio).resolve()
    stem = audio_path.stem
    out_dir = Path(args.out_dir) if args.out_dir else audio_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Load model ---
    print(f"Loading model: {args.model}")
    model = whisper.load_model(args.model)

    # --- 1st pass ---
    srt_path = out_dir / f"{stem}.srt"
    if args.skip_first_pass and srt_path.exists():
        print(f"Skipping first pass, loading cached SRT: {srt_path}")
        segments = []
        with open(srt_path, encoding="utf-8") as f:
            content = f.read()
        blocks = content.strip().split("\n\n")
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue
            timestamp_line = lines[1] if len(lines) >= 2 else lines[0]
            text = " ".join(lines[2:]) if len(lines) >= 3 else ""
            try:
                start_str, end_str = timestamp_line.split(" --> ")
                start = sum(
                    float(x) * m
                    for x, m in zip(
                        start_str.replace(",", ".").split(":"), [3600, 60, 1]
                    )
                )
                end = sum(
                    float(x) * m
                    for x, m in zip(end_str.replace(",", ".").split(":"), [3600, 60, 1])
                )
            except (ValueError, IndexError):
                continue
            segments.append({"start": start, "end": end, "text": text})
        result = {"segments": segments}
    else:
        print("First pass: transcribing full audio ...")
        result = model.transcribe(
            str(audio_path),
            language=args.language,
            word_timestamps=True,
        )
        segments = result.get("segments", [])
        print(f"  got {len(segments)} segments")

    if not segments:
        print("No segments found. Exiting.")
        sys.exit(1)

    # --- Detect buggy segments ---
    buggy = detect_buggy_segments(
        segments,
        zscore_threshold=args.zscore,
        min_ratio=args.min_ratio,
        hard_floor=args.hard_floor,
    )
    print(f"Detected {len(buggy)} buggy segments out of {len(segments)}")
    if buggy:
        print("\n--- Buggy segments ---")
        for i in sorted(buggy):
            seg = segments[i]
            r = compression_ratio(seg["text"].strip())
            print(f"  #{i} [{seg['start']:.1f}-{seg['end']:.1f}s]  ratio={r:.3f}")
            print(
                f"      \"{seg['text'].strip()[:120]}{'...' if len(seg['text'].strip())>120 else ''}\""
            )
        print()

    if args.dry_run:
        print("Dry run: stopping here.")
        return

    # --- Re-transcribe buggy segments ---
    if buggy:
        print("Re-transcribing buggy segments with beam-search ...")
        tmp_dir = Path(tempfile.mkdtemp(prefix="whisper_fix_"))
        corrections: dict[int, dict] = {}

        for i in sorted(buggy):
            seg = segments[i]
            chunk_path = tmp_dir / f"chunk_{i:04d}.m4a"
            try:
                cut_audio(str(audio_path), seg["start"], seg["end"], str(chunk_path))
            except subprocess.CalledProcessError:
                print(f"  #{i} ffmpeg cut failed, skipping")
                continue

            print(f"  #{i} re-transcribing [{seg['start']:.1f}-{seg['end']:.1f}s] ...")
            new_seg = transcribe_segment(model, str(chunk_path))
            new_seg["start"] = seg["start"]
            new_seg["end"] = seg["end"]
            corrections[i] = new_seg
            new_r = compression_ratio(new_seg.get("text", "").strip())
            old_r = compression_ratio(seg["text"].strip())
            print(f"      old: ratio={old_r:.3f}  \"{seg['text'].strip()[:100]}\"")
            print(
                f"      new: ratio={new_r:.3f}  \"{new_seg.get('text', '').strip()[:100]}\""
            )

        # Merge corrections
        merged = []
        for i, seg in enumerate(segments):
            if i in corrections:
                merged.append(corrections[i])
            else:
                merged.append(seg)

        # Cleanup temp dir
        if args.keep_chunks:
            print(f"\nKeeping temp chunks in: {tmp_dir}")
        else:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        merged = segments

    # --- Write outputs ---
    print(f"\nWriting outputs to {out_dir}/ ...")
    write_srt(merged, str(out_dir / f"{stem}.srt"))
    print("Done.")


if __name__ == "__main__":
    main()
