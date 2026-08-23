#!/usr/bin/env python3
"""faster-whisper transcription with Silero VAD and semantic cue splitting.

Cue-building policy (see whisper/README.md):
  * one line per cue, no wrapping
  * break priority: sentence end > clause boundary > speech pause
  * pack to <= 95 chars (translation headroom for <32 CJK chars);
    110 is the hard cap; a clause with no boundary inside may exceed it
    (lint warns, that is accepted) rather than being force-split
  * timing = raw word timestamps (no min/max duration, no gap chaining)
  * guidelines-compliant punctuation: trailing "." and "," stripped,
    "?"/"!"/"..."/"—" kept; casing comes from ASR plus the manual review pass
"""

import argparse
import json
import math
from pathlib import Path

from faster_whisper import WhisperModel

TARGET_CHARS = 95
HARD_CHARS = 110
PAUSE_THRESHOLDS = (0.8, 0.5, 0.35)

SENTENCE_ENDINGS = (".", "?", "!", "。", "？", "！")
CLAUSE_ENDINGS = (",", ";", ":", "—", "–")


def joined_text(words: list[dict]) -> str:
    return "".join(w["word"] for w in words).strip()


def group_sentences(words: list[dict]) -> list[list[dict]]:
    sentences = []
    current = []
    for w in words:
        token = w["word"].strip()
        if not token:
            continue
        current.append(w)
        if token.endswith(SENTENCE_ENDINGS):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    return [s for s in sentences if s]


def split_clauses(words: list[dict]) -> list[list[dict]]:
    clauses = []
    current = []
    for w in words:
        current.append(w)
        if w["word"].strip().endswith(CLAUSE_ENDINGS):
            clauses.append(current)
            current = []
    if current:
        clauses.append(current)
    return [c for c in clauses if c]


def split_pauses(words: list[dict], threshold: float) -> list[list[dict]]:
    segments = []
    current = []
    for w in words:
        if current and w["start"] - current[-1]["end"] >= threshold:
            segments.append(current)
            current = []
        current.append(w)
    if current:
        segments.append(current)
    return segments


def force_split_breaths(words: list[dict], n_parts: int) -> list[list[dict]]:
    """Last resort for pathological runs with no punctuation and no real
    pauses: cut into n_parts of roughly equal length, preferring inter-word
    gaps (breath points) near each target cut position."""
    if n_parts <= 1 or len(words) < n_parts:
        return [words]
    total = len(joined_text(words))
    target = total / n_parts
    prefix = [0]
    for w in words:
        prefix.append(prefix[-1] + len(w["word"]))
    cuts = []
    part_start = 0
    for k in range(1, n_parts):
        goal = round(target * k)
        best_i, best_cost = None, float("inf")
        for i in range(part_start, len(words) - 1):
            acc = prefix[i + 1]
            if acc > goal + target:
                break
            gap = words[i + 1]["start"] - words[i]["end"]
            cost = abs(acc - goal) - min(gap, 0.25) * 80.0
            if cost < best_cost:
                best_cost, best_i = cost, i
        if best_i is None:
            break
        cuts.append(best_i)
        part_start = best_i + 1
    parts = []
    prev = 0
    for ci in cuts:
        parts.append(words[prev : ci + 1])
        prev = ci + 1
    parts.append(words[prev:])
    return [p for p in parts if p]


def split_oversize(chunk: list[dict]) -> list[list[dict]]:
    """Reduce an over-HARD chunk with no clause boundary inside: escalate
    pause thresholds, then fall back to breath-point force-splits."""
    parts = None
    for threshold in PAUSE_THRESHOLDS:
        parts_ = split_pauses(chunk, threshold)
        if len(parts_) > 1:
            parts = parts_
            break
    if parts is None:
        return force_split_breaths(
            chunk, math.ceil(len(joined_text(chunk)) / TARGET_CHARS)
        )
    out = []
    for p in pack(parts, TARGET_CHARS):
        if len(joined_text(p)) <= HARD_CHARS:
            out.append(p)
        else:
            out.extend(
                force_split_breaths(p, math.ceil(len(joined_text(p)) / TARGET_CHARS))
            )
    return out


def pack(items: list[list[dict]], limit: int) -> list[list[dict]]:
    packed = []
    current: list[dict] = []
    for item in items:
        candidate = current + item
        if current and len(joined_text(candidate)) > limit:
            packed.append(current)
            current = list(item)
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def make_cue(words: list[dict]) -> dict:
    text = joined_text(words)
    stripped = text.rstrip()
    if stripped.endswith("..."):
        pass
    elif stripped.endswith("."):
        text = stripped[:-1].rstrip()
    elif stripped.endswith(","):
        text = stripped[:-1].rstrip()
    return {"start": words[0]["start"], "end": words[-1]["end"], "text": text}


def normalize_word(token: str) -> str:
    return token.strip().strip(".,!?…—:;\"'()").lower()


def dedup_echoes(cues: list[dict]) -> list[dict]:
    """Drop a cue-initial word that just repeats the previous cue's last
    word (ASR echo artifact, e.g. '...the dam' / 'dam instead of ...')."""
    out = []
    for cue in cues:
        words_cur = cue["text"].split()
        if out and words_cur:
            words_prev = out[-1]["text"].split()
            if words_prev and normalize_word(words_prev[-1]) == normalize_word(
                words_cur[0]
            ):
                words_cur = words_cur[1:]
                cue = dict(cue, text=" ".join(words_cur))
        if cue["text"].strip():
            out.append(cue)
    return out


def merge_fragments(cues: list[dict]) -> list[dict]:
    """Merge <=3-word lowercase-starting cues backward into the previous cue
    (they are continuation tails, e.g. ASR splitting 'compared / to / a /
    vanilla / furnace'); forward if they don't fit backward."""
    out: list[dict] = []
    for cue in cues:
        words_cur = cue["text"].split()
        if (
            out
            and len(words_cur) <= 3
            and words_cur
            and words_cur[0][:1].islower()
            and len(out[-1]["text"]) + 1 + len(cue["text"]) <= HARD_CHARS
        ):
            prev = out[-1]
            out[-1] = dict(
                prev, text=prev["text"] + " " + cue["text"], end=cue["end"]
            )
            continue
        out.append(cue)
    # forward pass: tiny lowercase cue attaches to the NEXT cue when the
    # previous merge was impossible
    merged: list[dict] = []
    skip_next_merge = False
    for i, cue in enumerate(out):
        if skip_next_merge:
            merged.append(cue)
            skip_next_merge = False
            continue
        words_cur = cue["text"].split()
        if (
            len(words_cur) <= 3
            and words_cur
            and words_cur[0][:1].islower()
            and i + 1 < len(out)
        ):
            nxt = out[i + 1]
            if len(cue["text"]) + 1 + len(nxt["text"]) <= TARGET_CHARS:
                merged.append(
                    dict(
                        cue,
                        text=cue["text"] + " " + nxt["text"],
                        end=nxt["end"],
                    )
                )
                skip_next_merge = True
                continue
        merged.append(cue)
    return merged


def build_cues(words: list[dict]) -> list[dict]:
    cues = []

    def emit(chunk: list[dict]) -> None:
        if chunk:
            cues.append(make_cue(chunk))

    for sentence in group_sentences(words):
        if len(joined_text(sentence)) <= TARGET_CHARS:
            emit(sentence)
            continue
        clauses = split_clauses(sentence)
        if len(clauses) == 1:
            for chunk in split_oversize(sentence):
                emit(chunk)
            continue
        for chunk in pack(clauses, TARGET_CHARS):
            if len(joined_text(chunk)) <= HARD_CHARS:
                emit(chunk)
            else:
                # single clause over the hard cap: pauses first; mild
                # over-length (<= 2x hard cap) is kept as-is by policy;
                # only pathological runs get breath-point force-splits
                parts = split_pauses(chunk, PAUSE_THRESHOLDS[0])
                if len(parts) > 1:
                    for part in pack(parts, TARGET_CHARS):
                        emit(part)
                elif len(joined_text(chunk)) > 2 * HARD_CHARS:
                    n_parts = math.ceil(len(joined_text(chunk)) / TARGET_CHARS)
                    for part in force_split_breaths(chunk, n_parts):
                        emit(part)
                else:
                    emit(chunk)  # accepted over-length
    return merge_fragments(dedup_echoes(cues))


def format_ts(seconds: float, comma: bool = True) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def write_srt(cues: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{format_ts(c['start'])} --> {format_ts(c['end'])}\n")
            f.write(c["text"] + "\n\n")


def write_txt(cues: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(" ".join(c["text"] for c in cues))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("media", help="Input audio/video file")
    ap.add_argument("--model-dir", default="./models/faster-whisper-large-v3")
    ap.add_argument("--out-prefix", default=None, help="Output prefix (default: input stem)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--language", default="en")
    ap.add_argument("--beam-size", type=int, default=5)
    ap.add_argument(
        "--reuse-words",
        action="store_true",
        help="skip ASR; rebuild cues from the existing .words.json",
    )
    args = ap.parse_args()

    media = Path(args.media).resolve()
    stem = Path(args.out_prefix) if args.out_prefix else media.with_suffix("")

    if args.reuse_words:
        json_path = stem.with_suffix(".words.json")
        print(f"Reusing words from {json_path} ...")
        with open(json_path, encoding="utf-8") as f:
            words = json.load(f)
        info_duration = words[-1]["end"] if words else 0.0
    else:
        print(f"Loading model from {args.model_dir} ...")
        model = WhisperModel(
            args.model_dir, device=args.device, compute_type=args.compute_type
        )

        print(f"Transcribing {media.name} ...")
        segments, info = model.transcribe(
            str(media),
            language=args.language,
            beam_size=args.beam_size,
            temperature=0.0,
            condition_on_previous_text=False,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        words = []
        n_segments = 0
        speech_seconds = 0.0
        for seg in segments:
            n_segments += 1
            speech_seconds += seg.end - seg.start
            for w in seg.words or []:
                words.append({"word": w.word, "start": w.start, "end": w.end})
            print(
                f"\r  seg {n_segments} [{seg.end:.0f}s/{info.duration:.0f}s]",
                end="",
                flush=True,
            )
        print()
        info_duration = info.duration

    cues = build_cues(words)
    srt_path = stem.with_suffix(".raw.srt")
    txt_path = stem.with_suffix(".raw.txt")
    json_path = stem.with_suffix(".words.json")
    write_srt(cues, srt_path)
    write_txt(cues, txt_path)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(words, f)

    lengths = [len(c["text"]) for c in cues]
    print(f"Duration: {info_duration:.1f}s")
    print(
        f"Cues: {len(cues)} | Words: {len(words)} | "
        f"chars min/median/max: {min(lengths)}/{sorted(lengths)[len(lengths)//2]}/{max(lengths)} | "
        f"over {HARD_CHARS}: {sum(1 for L in lengths if L > HARD_CHARS)}"
    )
    print(f"Wrote {srt_path}")
    print(f"Wrote {txt_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
