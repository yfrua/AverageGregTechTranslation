#!/usr/bin/env python3
"""Lint subtitle files (.srt) against guidelines.md style rules.

Structure checks:
  * cue index lines are valid sequential integers (allowing a fresh reset)
  * timecode lines match HH:MM:SS,mmm --> HH:MM:SS,mmm
  * the EN run and the CN run (parallel translations sharing timecodes) pair up
    (warning only; comment cues wrapped in （） are excluded from pairing)

Style checks (per text line, from guidelines.md):
  English:
    * no trailing "." or "," (but "...", "?", "!", "—" are kept)
  Chinese:
    * no trailing "。"
    * no mid-sentence "，" (use spaces instead)
    * full-width "？" "！" "……" "（）" (no half-width "?" "!" "..." "(" ")")
    * a space separates Chinese from non-Chinese characters

Length checks (soft warnings, do not affect exit code):
  English: < 102 characters (spaces counted)
  Chinese: < 32 CJK characters

With --fix, auto-fixable style violations (EN/punct, ZH/punct, ZH/comma,
ZH/halfwidth, ZH/space) are rewritten in place. Structure issues and length
warnings are never auto-fixed.

Exit code is non-zero if any hard violation is found. Soft length warnings and
EN/CN pairing warnings (count or timecode) do not fail.
"""

import argparse
import re
import sys

from collections import defaultdict

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[\u0041-\u024f]")
NOT_SPACED_CJK = re.compile(
    r"(?<=[\u4e00-\u9fff])[\u0041-\u024f0-9]|[\u0041-\u024f0-9](?=[\u4e00-\u9fff])"
)

TIMECODE_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}$"
)
INDEX_RE = re.compile(r"^\d+$")

EN_CHAR_LIMIT = 102
ZH_CJK_LIMIT = 32


class Cue:
    __slots__ = ("idx_lineno", "index", "tc_lineno", "tc", "text")

    def __init__(self, idx_lineno, index, tc_lineno, tc, text):
        self.idx_lineno = idx_lineno
        self.index = index
        self.tc_lineno = tc_lineno
        self.tc = tc
        self.text = text  # list of (lineno, raw_line)


def fix_english(line):
    new = line.rstrip()
    stripped = new.strip()
    lead = new[: len(new) - len(new.lstrip())]
    if not stripped:
        return new
    if stripped.endswith(","):
        stripped = stripped[:-1]
    elif stripped.endswith(".") and not stripped.endswith("..."):
        stripped = stripped[:-1]
    return lead + stripped


def fix_chinese(line):
    new = line.rstrip()
    stripped = new.strip()
    lead = new[: len(new) - len(new.lstrip())]
    if not stripped:
        return new
    if stripped.endswith("。"):
        stripped = stripped[:-1]
    stripped = stripped.replace("，", " ")
    stripped = stripped.replace("...", "……").replace("?", "？").replace("!", "！")
    stripped = stripped.replace("(", "（").replace(")", "）")
    stripped = space_cjk_latin(stripped)
    return lead + stripped


def space_cjk_latin(text):
    text = re.sub(r"([\u4e00-\u9fff])(?=[\u0041-\u024f0-9])", r"\1 ", text)
    text = re.sub(r"([\u0041-\u024f0-9])(?=[\u4e00-\u9fff])", r"\1 ", text)
    return text


def read_lines(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as fh:
        return fh.read().split("\n")


def fix_one(filepath):
    lines = read_lines(filepath)
    fixed = 0
    for idx in range(1, len(lines) + 1):
        orig = lines[idx - 1]
        if not orig.strip():
            continue
        if is_chinese(orig):
            new = fix_chinese(orig)
        elif LATIN_RE.search(orig):
            new = fix_english(orig)
        else:
            continue
        if new != orig:
            lines[idx - 1] = new
            fixed += 1
    if fixed:
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    return fixed


def is_chinese(text):
    return bool(CJK_RE.search(text))


def is_comment_cue(cue):
    if not cue.text:
        return False
    first = cue.text[0][1].strip()
    last = cue.text[-1][1].strip()
    if not first or not last:
        return False
    return (first.startswith("(") or first.startswith("\uff08")) and (
        last.endswith(")") or last.endswith("\uff09")
    )


def style_english(line, lineno, filepath, errors):
    stripped = line.strip()
    if not stripped:
        return
    if stripped.endswith(","):
        errors.append((filepath, lineno, "EN/punct", "remove trailing comma"))
    elif stripped.endswith(".") and not stripped.endswith("..."):
        errors.append((filepath, lineno, "EN/punct", "remove trailing period"))


def style_chinese(line, lineno, filepath, errors):
    stripped = line.strip()
    if not stripped:
        return
    if stripped.endswith("。"):
        errors.append((filepath, lineno, "ZH/punct", "remove trailing 。"))
    if "，" in stripped:
        errors.append((filepath, lineno, "ZH/comma", "replace ， with a space"))
    if "?" in stripped or "!" in stripped or "..." in stripped or "(" in stripped or ")" in stripped:
        errors.append(
            (
                filepath,
                lineno,
                "ZH/halfwidth",
                "use full-width ？！……（） instead of half-width ? ! ... ( )",
            )
        )
    if NOT_SPACED_CJK.search(stripped):
        errors.append(
            (
                filepath,
                lineno,
                "ZH/space",
                "add a space between Chinese and non-Chinese characters",
            )
        )


def count_cjk(text):
    return len([c for c in text if CJK_RE.match(c)])


def tc_to_ms(tc):
    m = re.match(
        r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$",
        tc,
    )
    if not m:
        return None

    def to_ms(h, mi, s, ms):
        return int(h) * 3600000 + int(mi) * 60000 + int(s) * 1000 + int(ms)

    return (
        to_ms(m.group(1), m.group(2), m.group(3), m.group(4)),
        to_ms(m.group(5), m.group(6), m.group(7), m.group(8)),
    )


def build_cues(lines, filepath, errors):
    """Parse raw lines into Cue objects, tolerating whisper's blank lines that
    separate a timecode from its text (a text-only block attaches to the prior
    cue)."""
    blocks = []
    current = []
    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r")
        if raw.rstrip("\r\n") == "" or raw == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append((lineno, line))
    if current:
        blocks.append(current)

    cues = []
    for block in blocks:
        idx_lineno, idx_line = block[0]
        first = idx_line.strip()
        if INDEX_RE.match(first):
            idx = int(first)
            if len(block) >= 2 and TIMECODE_RE.match(block[1][1].strip()):
                tc_lineno, tc_line = block[1]
                tc = tc_line.strip()
                text = block[2:]
                cues.append(Cue(idx_lineno, idx, tc_lineno, tc, text))
            else:
                errors.append(
                    (
                        filepath,
                        idx_lineno,
                        "struct",
                        "cue index %d not followed by a timecode line" % idx,
                    )
                )
                text = block[1:]
                cues.append(Cue(idx_lineno, idx, None, None, text))
        else:
            if cues:
                cues[-1].text.extend(block)
            else:
                errors.append(
                    (filepath, idx_lineno, "struct", "text before any cue")
                )
    return cues


def lint_one(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as fh:
        content = fh.read()
    lines = content.split("\n")
    errors = []
    warnings = []

    cues = build_cues(lines, filepath, errors)

    # --- structural: index sequence + timecode format ---
    prev_index = None
    for cue in cues:
        if cue.index is not None:
            if prev_index is not None and cue.index != prev_index + 1 and cue.index != 1:
                errors.append(
                    (
                        filepath,
                        cue.idx_lineno,
                        "struct",
                        "cue index not sequential (expected %d)" % (prev_index + 1),
                    )
                )
            prev_index = cue.index
        if cue.tc is not None and not TIMECODE_RE.match(cue.tc):
            errors.append(
                (filepath, cue.tc_lineno, "struct", "invalid timecode line: %r" % cue.tc)
            )

    # --- style checks on each text line ---
    for cue in cues:
        for lineno, text_line in cue.text:
            if not text_line.strip():
                continue
            if is_chinese(text_line):
                style_chinese(text_line, lineno, filepath, errors)
            elif LATIN_RE.search(text_line):
                style_english(text_line, lineno, filepath, errors)

    # --- length warnings (soft) per cue ---
    for cue in cues:
        texts = [ln for (_, ln) in cue.text if ln.strip()]
        if not texts:
            continue
        full = " ".join(t.strip() for t in texts)
        if is_chinese(full):
            cjk = count_cjk(full)
            if cjk >= ZH_CJK_LIMIT:
                warnings.append(
                    (
                        filepath,
                        cue.idx_lineno,
                        "style/length",
                        "Chinese line has %d CJK chars (limit < %d)" % (cjk, ZH_CJK_LIMIT),
                    )
                )
        elif LATIN_RE.search(full):
            chars = len(full)
            if chars >= EN_CHAR_LIMIT:
                warnings.append(
                    (
                        filepath,
                        cue.idx_lineno,
                        "style/length",
                        "English line has %d chars (limit < %d)" % (chars, EN_CHAR_LIMIT),
                    )
                )

    # --- EN/CN pairing (warning only; comment cues are excluded) ---
    real = [cue for cue in cues if not is_comment_cue(cue)]
    split = next(
        (i for i, cue in enumerate(real) if any(is_chinese(t) for (_, t) in cue.text)),
        None,
    )
    if split is not None and split > 0:
        en_run = real[:split]
        cn_run = real[split:]
        if len(en_run) != len(cn_run):
            warnings.append(
                (
                    filepath,
                    cn_run[0].idx_lineno,
                    "struct/pairing",
                    "EN run has %d cues but CN run has %d (timecodes must pair up)"
                    % (len(en_run), len(cn_run)),
                )
            )
        else:
            for i, (en, cn) in enumerate(zip(en_run, cn_run), start=1):
                if en.tc and cn.tc:
                    en_t = tc_to_ms(en.tc)
                    cn_t = tc_to_ms(cn.tc)
                    if en_t is not None and cn_t is not None and en_t != cn_t:
                        warnings.append(
                            (
                                filepath,
                                cn.idx_lineno,
                                "struct/pairing",
                                "pair %d timecode mismatch: EN [%s] vs CN [%s]"
                                % (i, en.tc, cn.tc),
                            )
                        )

    return errors, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="subtitle files to check")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="auto-fix auto-fixable style violations in place before reporting",
    )
    args = parser.parse_args(argv)

    files = args.files
    if not files:
        parser.error("no files given")

    if args.fix:
        total_fixed = 0
        for f in files:
            total_fixed += fix_one(f)
        print("Auto-fixed %d line(s)." % total_fixed)

    all_errors = []
    all_warnings = []
    for f in files:
        e, w = lint_one(f)
        all_errors.extend(e)
        all_warnings.extend(w)

    def print_grouped(items, label):
        by_file = defaultdict(list)
        for filepath, lineno, code, msg in items:
            by_file[filepath].append((lineno, code, msg))
        for filepath in sorted(by_file):
            print("%s:" % filepath)
            for lineno, code, msg in sorted(by_file[filepath]):
                print("  [%s] line %d: %s" % (code, lineno, msg))
        print("\n%d %s in %d file(s)" % (len(items), label, len(by_file)))
        print()

    if all_errors:
        print_grouped(all_errors, "violation(s)")
    if all_warnings:
        print_grouped(all_warnings, "warning(s)")

    if all_errors:
        return 1
    if all_warnings:
        print("OK with %d warning(s); no hard violations." % len(all_warnings))
        return 0
    print("OK: no style/structure/length violations in %d file(s)" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())