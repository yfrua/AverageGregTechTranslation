#!/usr/bin/env python3
"""Read a subtitle aloud with Amazon Polly and write an audio track.

Each subtitle cue is synthesized separately with Polly's classic British
"Brian" voice, time-fitted into its slot, and laid on a silent timeline.
Input and output are audio: only the input's duration is used, so a video
file works as a timing reference too, while the result is a standalone
audio file (AAC in .m4a by default).

Project subtitle files hold an EN run followed by a ZH run that restarts
its timecodes, so the English run is selected automatically unless
``--source zh`` is given.

Timing model: cues keep their subtitle start times; a line that runs past
its slot is sped up with ffmpeg ``atempo`` up to ``--max-tempo`` and then
trimmed, a shorter line leaves natural silence behind it. Cues that would
overlap are pushed back to the end of the previous one.

Requires ffmpeg/ffprobe on PATH, the ``boto3`` package and AWS credentials
allowed to call ``polly:SynthesizeSpeech``::

    pip install boto3
    python3 scripts/tts_dub.py input.m4a GTNH_series/S4E6.srt -o dubbed.m4a
"""

import argparse
import asyncio
import html
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

TIMECODE_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})"
)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")
SENTENCE_END_RE = re.compile(r"[.?!…。？！][\"'”’)]*\s*$")

VOICE_EN = "Brian"
VOICE_ZH = "Zhiyu"
POLLY_REGION = "ap-southeast-2"
MIN_CUE_SECONDS = 0.2
SAMPLE_RATE = 48000
MERGE_GAP = 0.6
MERGE_MAX_SECONDS = 12.0


class Cue:
    __slots__ = ("start", "end", "text")

    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text

    def __repr__(self):
        return "Cue(%.3f, %.3f, %r)" % (self.start, self.end, self.text)


class Segment:
    """One cue placed on the output timeline."""

    __slots__ = ("start", "duration")

    def __init__(self, start, duration):
        self.start = start
        self.duration = duration

    def __repr__(self):
        return "Segment(%.3f, %.3f)" % (self.start, self.duration)


def _seconds(h, m, s, frac):
    frac = frac.ljust(3, "0")[:3]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(frac) / 1000.0


def parse_srt(path):
    """Parse an .srt file into Cue objects (text lines joined by spaces)."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in raw.strip().split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        match = TIMECODE_RE.search(lines[1])
        if not match:
            continue
        text = " ".join(lines[2:]).strip()
        if not text:
            continue
        groups = match.groups()
        cues.append(
            Cue(_seconds(*groups[0:4]), _seconds(*groups[4:8]), text)
        )
    return cues


def split_runs(cues):
    """Split cues into runs that each restart their timecodes.

    Project subtitles put the EN run first and the ZH run right after it,
    with the ZH run starting again at 00:00:00.
    """
    runs = []
    for cue in cues:
        if not runs or cue.start < runs[-1][-1].start - 0.001:
            runs.append([])
        runs[-1].append(cue)
    return runs


def latin_ratio(cues):
    text = " ".join(cue.text for cue in cues)
    latin = len(LATIN_RE.findall(text))
    cjk = len(CJK_RE.findall(text))
    total = latin + cjk
    return latin / total if total else 0.0


def select_source(cues, source="auto"):
    """Pick the cue run to speak: 'auto', 'en' or 'zh'."""
    runs = split_runs(cues)
    if source == "en":
        return max(runs, key=latin_ratio)
    if source == "zh":
        return min(runs, key=latin_ratio)
    if len(runs) == 1:
        return runs[0]
    english = max(runs, key=latin_ratio)
    return english if latin_ratio(english) >= 0.5 else runs[0]


def group_sentences(cues, max_gap=MERGE_GAP, max_duration=MERGE_MAX_SECONDS):
    """Merge cues that continue a sentence the subtitle split across lines.

    A cue is joined to the previous one when there is no terminal
    punctuation yet, the gap is short, and the merged slot stays within
    ``max_duration``. Speaking whole sentences avoids falling intonation
    at every line break.
    """
    groups = []
    for cue in cues:
        if not groups:
            groups.append(Cue(cue.start, cue.end, cue.text))
            continue
        current = groups[-1]
        mergeable = (
            cue.start - current.end < max_gap
            and not SENTENCE_END_RE.search(current.text)
            and cue.end - current.start <= max_duration
        )
        if mergeable:
            current.end = max(current.end, cue.end)
            current.text += " " + cue.text
        else:
            groups.append(Cue(cue.start, cue.end, cue.text))
    return groups


def plan_segments(cues, total_duration, min_duration=MIN_CUE_SECONDS):
    """Place cues sequentially on a 0..total_duration timeline.

    Cues starting before the previous one ends are shifted forward; cues
    running past the input end are cut at the end. Returns (segments,
    lost_seconds) where lost_seconds counts cue time dropped because of
    overlap with the previous line or because the cue sat at the input end.
    """
    segments = []
    cursor = 0.0
    lost = 0.0
    for cue in cues:
        if cue.start >= total_duration:
            continue
        start = max(cue.start, cursor)
        room = total_duration - start
        if room <= 0:
            continue
        natural = cue.end - cue.start
        available = cue.end - start
        duration = min(max(available, min_duration), room)
        if duration <= 0:
            continue
        if natural > duration:
            lost += natural - duration
        segments.append(Segment(start, duration))
        cursor = start + duration
    return segments, lost


def tempo_factor(tts_duration, slot, max_tempo):
    """Speed-up factor applied to a clip so it fits its slot."""
    if slot <= 0:
        return 1.0
    return max(1.0, min(tts_duration / slot, max_tempo))


def _run(cmd):
    proc = subprocess.run(
        [str(part) for part in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "command failed: %s\n%s" % (" ".join(str(c) for c in cmd), proc.stderr[-2000:])
        )
    return proc


def probe_duration(path):
    out = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0", path,
    ]).stdout.strip()
    return float(out)


def make_silence(path, seconds):
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "anullsrc=r=%d:cl=stereo" % SAMPLE_RATE,
        "-t", "%.3f" % seconds, "-c:a", "pcm_s16le", path,
    ])


def cut_silence(src, path, seconds):
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-t", "%.3f" % seconds, "-i", src,
        "-c:a", "pcm_s16le", path,
    ])


def fit_clip(src, path, slot, max_tempo):
    """Convert a TTS clip to PCM, speed it up if needed, pad/trim to slot."""
    factor = tempo_factor(probe_duration(src), slot, max_tempo)
    filters = []
    if factor > 1.005:
        filters.append("atempo=%.4f" % factor)
    filters += [
        "aresample=%d" % SAMPLE_RATE,
        "aformat=channel_layouts=stereo",
        "apad=whole_dur=%.3f" % slot,
        "atrim=0:%.3f" % slot,
    ]
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", src,
        "-af", ",".join(filters),
        "-ar", str(SAMPLE_RATE), "-ac", "2",
        "-c:a", "pcm_s16le", path,
    ])
    return factor


_POLLY_CLIENTS = {}
_POLLY_LOCK = threading.Lock()


def _polly(region):
    import boto3

    with _POLLY_LOCK:
        client = _POLLY_CLIENTS.get(region)
        if client is None:
            client = boto3.client("polly", region_name=region)
            _POLLY_CLIENTS[region] = client
    return client


def polly_ssml(text, rate=0):
    body = html.escape(text, quote=False)
    if rate:
        body = '<prosody rate="%d%%">%s</prosody>' % (100 + rate, body)
    return "<speak>%s</speak>" % body


def synth_polly(text, voice, path, rate, region):
    args = {"VoiceId": voice, "Engine": "standard", "OutputFormat": "mp3"}
    if rate:
        args.update(Text=polly_ssml(text, rate), TextType="ssml")
    else:
        args.update(Text=text)
    audio = _polly(region).synthesize_speech(**args)["AudioStream"].read()
    Path(path).write_bytes(audio)


async def synthesize(text, voice, path, semaphore, rate=0, region=POLLY_REGION):
    async with semaphore:
        await asyncio.to_thread(synth_polly, text, voice, path, rate, region)


async def synthesize_all(cues, voice, out_dir, concurrency, region=POLLY_REGION):
    semaphore = asyncio.Semaphore(max(1, concurrency))
    await asyncio.gather(*[
        synthesize(cue.text, voice, out_dir / ("%05d.mp3" % i), semaphore,
                   region=region)
        for i, cue in enumerate(cues)
    ])


def rate_needed(tts_seconds, slot, max_rate, threshold=1.12):
    """Extra speaking rate (%) that would make a clip fit its slot."""
    if slot <= 0 or tts_seconds <= slot * threshold:
        return 0
    percent = int(round((tts_seconds / slot - 1.0) * 100))
    percent = min(max_rate, ((percent + 4) // 5) * 5)
    return max(5, percent)


async def adjust_rates(cues, segments, voice, out_dir, concurrency, max_rate,
                       region=POLLY_REGION):
    """Re-synthesize lines that overrun badly, faster instead of time-stretched."""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    jobs = []
    for i, (cue, segment) in enumerate(zip(cues, segments)):
        path = out_dir / ("%05d.mp3" % i)
        percent = rate_needed(probe_duration(path), segment.duration, max_rate)
        if percent:
            jobs.append(synthesize(cue.text, voice, path, semaphore, rate=percent,
                                   region=region))
    if jobs:
        await asyncio.gather(*jobs)
    return len(jobs)


def concat_file(paths, path):
    lines = []
    for item in paths:
        escaped = str(item).replace("'", "'\\''")
        lines.append("file '%s'\n" % escaped)
    Path(path).write_text("".join(lines), encoding="utf-8")


def write_output(audio, out, duration):
    suffix = Path(out).suffix.lower()
    if suffix == ".wav":
        codec = ["-c:a", "pcm_s16le"]
    elif suffix == ".mp3":
        codec = ["-c:a", "libmp3lame", "-b:a", "192k"]
    else:
        codec = ["-c:a", "aac", "-b:a", "192k"]
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-i", audio, "-t", "%.3f" % duration, *codec, out,
    ])


def run_dub(input_path, srt, out, voice=None, source="auto", merge=False, max_tempo=1.5,
            max_rate=40, region=POLLY_REGION,
            concurrency=4, limit=None, workdir=None):
    total = probe_duration(input_path)
    if limit:
        total = min(total, limit)
    all_cues = parse_srt(srt)
    cues = [c for c in select_source(all_cues, source) if c.start < total]
    cue_count = len(cues)
    if merge:
        cues = group_sentences(cues)
    segments, lost = plan_segments(cues, total)
    if not segments:
        raise SystemExit("no cues overlap the input timeline")
    assert len(segments) == len(cues)

    if voice is None:
        voice = VOICE_EN if latin_ratio(cues) >= 0.5 else VOICE_ZH

    print("input %.1fs, %d cues -> %d segments, voice %s"
          % (total, cue_count, len(segments), voice))

    cleanup = workdir is None
    work = Path(workdir or tempfile.mkdtemp(prefix="tts-dub-"))
    tts_dir = work / "tts"
    seg_dir = work / "segments"
    tts_dir.mkdir(parents=True, exist_ok=True)
    seg_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(synthesize_all(cues, voice, tts_dir, concurrency, region=region))
    adjusted = asyncio.run(
        adjust_rates(cues, segments, voice, tts_dir, concurrency, max_rate,
                     region=region)
    )
    if adjusted:
        print("re-synthesized %d overrunning lines at a faster rate" % adjusted)

    silence = work / "silence.wav"
    make_silence(silence, total)

    parts = []
    cursor = 0.0
    sped_up = 0
    for i, segment in enumerate(segments):
        gap = segment.start - cursor
        if gap > 0.01:
            gap_file = seg_dir / ("gap_%05d.wav" % i)
            cut_silence(silence, gap_file, gap)
            parts.append(gap_file)
        clip_file = seg_dir / ("cue_%05d.wav" % i)
        factor = fit_clip(tts_dir / ("%05d.mp3" % i), clip_file,
                          segment.duration, max_tempo)
        if factor > 1.005:
            sped_up += 1
        parts.append(clip_file)
        cursor = segment.start + segment.duration

    tail = total - cursor
    if tail > 0.01:
        tail_file = seg_dir / "tail.wav"
        cut_silence(silence, tail_file, tail)
        parts.append(tail_file)

    list_file = work / "concat.txt"
    concat_file(parts, list_file)
    dub = work / "dub.wav"
    _run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c:a", "pcm_s16le", dub,
    ])

    write_output(dub, out, total)
    print(
        "wrote %s (%.1fs); %d/%d lines sped up, %.1fs of cue time lost"
        % (out, probe_duration(out), sped_up, len(segments), lost)
    )
    if cleanup:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print("workdir %s" % work)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read a subtitle aloud with Polly and write an audio track."
    )
    parser.add_argument("input", help="input audio or video (only its duration is used)")
    parser.add_argument("srt")
    parser.add_argument("-o", "--out", default=None,
                        help="output audio (default: <input>_dubbed.m4a)")
    parser.add_argument("--voice", default=None,
                        help="Polly voice id (default: Brian for English, Zhiyu for Chinese)")
    parser.add_argument("--region", default=POLLY_REGION,
                        help="AWS region for Polly (default: %(default)s)")
    parser.add_argument("--source", choices=("auto", "en", "zh"), default="auto",
                        help="which cue run to speak (default: auto)")
    parser.add_argument("--merge", action="store_true",
                        help="merge cues split mid-sentence before synthesis")
    parser.add_argument("--max-tempo", type=float, default=1.5,
                        help="cap on atempo speed-up to fit a cue (default: 1.5)")
    parser.add_argument("--max-rate", type=int, default=40,
                        help="cap on TTS speaking-rate boost in percent (default: 40)")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="parallel TTS requests (default: 4)")
    parser.add_argument("--limit", type=float, default=None,
                        help="only dub the first N seconds")
    parser.add_argument("--workdir", default=None,
                        help="keep intermediate files in this directory")
    args = parser.parse_args(argv)

    out = args.out
    if out is None:
        media = Path(args.input)
        out = str(media.with_name(media.stem + "_dubbed.m4a"))

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("ffmpeg and ffprobe must be on PATH")

    run_dub(
        args.input, args.srt, out,
        voice=args.voice, source=args.source, merge=args.merge,
        max_tempo=args.max_tempo, max_rate=args.max_rate,
        region=args.region,
        concurrency=args.concurrency, limit=args.limit, workdir=args.workdir,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
