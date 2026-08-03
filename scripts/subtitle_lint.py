#!/usr/bin/env python3
"""Lint subtitle files (.srt) against guidelines.md style rules.

Structure checks:
  * cue index lines are valid sequential integers (allowing a fresh reset)
  * timecode lines match HH:MM:SS,mmm --> HH:MM:SS,mmm
  * cues are separated by blank lines

Style checks (per text line, from guidelines.md):
  English:
    * first letter of each line is uppercase
    * no trailing "." or "," (but "...", "?", "!", "—" are kept)
  Chinese:
    * no trailing "。"
    * no spaces used as a comma replacement

Exit code is non-zero if any violation is found (hard fail).
"""

import argparse
import re
import subprocess
import sys

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[\u0041-\u024f]")
WORD_RE = re.compile(r"[\u0041-\u024f]")

UNIFIED_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

TIMECODE_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}$"
)
INDEX_RE = re.compile(r"^\d+$")

SPACE_LOG = re.compile(r"\s")


def is_chinese(text):
    return bool(CJK_RE.search(text))


def style_english(line, lineno, filepath, errors):
    stripped = line.strip()
    if not stripped:
        return
    # first letter uppercase
    m = LATIN_RE.search(stripped)
    if m and m.group().islower():
        errors.append(
            (filepath, lineno, "EN/case", "line should start with an uppercase letter")
        )
    # trailing . or ,
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
    # spaces used as comma replacement: a space between two CJK segments where
    # at least one side is a multi-character word (single-char emphasis like
    # "快 快 快" is allowed)
    tokens = re.split(r"\s+", stripped)
    for i in range(len(tokens) - 1):
        left, right = tokens[i], tokens[i + 1]
        l_cjk = CJK_RE.search(left)
        r_cjk = CJK_RE.search(right)
        l_len = len([c for c in left if CJK_RE.match(c)])
        r_len = len([c for c in right if CJK_RE.match(c)])
        if l_cjk and r_cjk and (l_len > 1 or r_len > 1):
            errors.append(
                (
                    filepath,
                    lineno,
                    "ZH/space",
                    "space used as a comma replacement; use ，instead",
                )
            )


def lint_one(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as fh:
        content = fh.read()
    lines = content.split("\n")
    errors = []

    # Split into non-empty-line blocks: each cue = [index, timecode, *text]
    blocks = []
    current = []
    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r").strip("\r")
        if raw.rstrip("\r\n") == "" or raw == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append((lineno, raw.rstrip("\r")))
    if current:
        blocks.append(current)

    # structural scan across the whole file
    prev_index = None
    saw_reset = False
    cue_parsed = 0
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if len(block) < 2:
            err_lineno = block[0][0] if block else 0
            errors.append(
                (
                    filepath,
                    err_lineno,
                    "struct",
                    "cue block must have index and timecode lines",
                )
            )
            i += 1
            continue
        idx_lineno, idx_line = block[0]
        tc_lineno, tc_line = block[1]
        idx = int(idx_line) if INDEX_RE.match(idx_line.strip()) else None
        if idx is None:
            errors.append((filepath, idx_lineno, "struct", "invalid cue index"))
        elif idx != (prev_index + 1 if prev_index is not None else 1):
            # allow a fresh reset (e.g. translated section restarts at 1)
            if idx == 1:
                saw_reset = True
            else:
                errors.append(
                    (
                        filepath,
                        idx_lineno,
                        "struct",
                        "cue index not sequential (expected %s)"
                        % (prev_index + 1 if prev_index is not None else 1),
                    )
                )
            prev_index = idx
        else:
            prev_index = idx
        if not TIMECODE_RE.match(tc_line.strip()):
            errors.append(
                (filepath, tc_lineno, "struct", "invalid timecode line: %r" % tc_line)
            )
        # text lines -> style
        for t_lineno, text_line in block[2:]:
            text = text_line
            if is_chinese(text):
                style_chinese(text, t_lineno, filepath, errors)
            elif LATIN_RE.search(text):
                style_english(text, t_lineno, filepath, errors)
        i += 1

    return errors


def changed_line_numbers(base, filepath):
    """Return new-file line numbers changed by the current working tree vs `base`."""
    try:
        diff = subprocess.check_output(
            ["git", "diff", "--unified=0", base, "--", filepath],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    numbers = set()
    if not diff:
        return numbers
    for line in diff.splitlines():
        m = UNIFIED_HUNK_RE.match(line)
        if m:
            start = int(m.group(3))
            count = int(m.group(4)) if m.group(4) else 1
            for n in range(start, start + count):
                numbers.add(n)
    return numbers


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="subtitle files to check")
    parser.add_argument(
        "--base",
        metavar="REF",
        default=None,
        help="git ref to diff against; only report violations on lines changed "
        "by the working tree. Omit to check the whole file.",
    )
    args = parser.parse_args(argv)

    files = args.files
    if not files:
        parser.error("no files given")

    all_errors = []
    for f in files:
        changed = None
        if args.base is not None:
            changed = changed_line_numbers(args.base, f) or set()
        for filepath, lineno, code, msg in lint_one(f):
            if changed is not None and lineno not in changed:
                continue
            all_errors.append((filepath, lineno, code, msg))

    if all_errors:
        from collections import defaultdict

        by_file = defaultdict(list)
        for filepath, lineno, code, msg in all_errors:
            by_file[filepath].append((lineno, code, msg))
        for filepath in sorted(by_file):
            print("%s:" % filepath)
            for lineno, code, msg in sorted(by_file[filepath]):
                print("  [%s] line %d: %s" % (code, lineno, msg))
        print("\n%d violation(s) in %d file(s)" % (len(all_errors), len(by_file)))
        return 1
    print("OK: no style/structure violations in %d file(s)" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())

