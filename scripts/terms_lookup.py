#!/usr/bin/env python3
"""Terminology lookup for GTNH subtitle translation.

Sources, merged at lookup time (hand-curated wins on conflict):

  * ``terms.json``  — hand-curated local glossary in this repo
  * Paratranz project 4964 terms, fetched from the public API
    https://paratranz.cn/api/projects/4964/terms

The Paratranz set is large (~1500 entries) and updated by upstream
translators, so it is cached to ``terms.paratranz.json``. Pass ``--refresh``
to re-download, or ``--offline`` to use only the cache (no network).

Usage
-----

Look up the terms that actually occur in one or more subtitle files, and
print a compact EN -> ZH cheat sheet for the translator (human or AI)::

    python3 scripts/terms_lookup.py <path-to.srt> [more.srt ...]

Dump the whole merged glossary (JSON or TSV) for reference or tooling::

    python3 scripts/terms_lookup.py --dump            # JSON to stdout
    python3 scripts/terms_lookup.py --dump --format tsv

Search a single term interactively (substring match, case-insensitive)::

    python3 scripts/terms_lookup.py --search "assembl"

Refresh the Paratranz cache without doing a lookup::

    python3 scripts/terms_lookup.py --refresh

Notes
-----
* Matching is case-insensitive and tries the longest term first, so
  "Advanced Assembly Line" wins over "Assembly Line" inside a line.
* Paratranz terms may carry ``variants`` (aliases, e.g. "AAL" for
  "Advanced Assembly Line"); all variants are matched.
* Leading/trailing whitespace and a single trailing ":" are stripped from
  term and translation, because the Paratranz data is inconsistent here.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

PROJECT_ID = 4964
API_URL = "https://paratranz.cn/api/projects/%d/terms" % PROJECT_ID
# 500 is a good balance: the endpoint is slow/flaky for larger pages, and the
# full ~1500-term set still only takes a handful of requests.
PAGE_SIZE = 500

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURATED_PATH = os.path.join(ROOT, "terms.json")
CACHE_PATH = os.path.join(ROOT, "terms.paratranz.json")
PRUNE_REPORT_PATH = os.path.join(ROOT, "terms.prune-report.json")

DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 3

# Bump when the on-disk cache shape changes so stale caches can be detected.
CACHE_SCHEMA = 2


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

def _fetch_page(open_fn, page, timeout, retries):
    """Fetch one page, retrying transient network errors with backoff."""
    url = "%s?page=%d&pageSize=%d" % (API_URL, page, PAGE_SIZE)
    last_exc = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, headers={"User-Agent": "terms-lookup/1.0"}
        )
        try:
            with open_fn(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_exc = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_exc


def fetch_paratranz(timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES, opener=None):
    """Return the raw list of Paratranz term dicts, following pagination."""
    open_fn = opener or urllib.request.urlopen
    results = []
    page = 1
    while True:
        payload = _fetch_page(open_fn, page, timeout, retries)
        results.extend(payload.get("results", []))
        page_count = payload.get("pageCount") or 1
        if page >= page_count or not payload.get("results"):
            break
        page += 1
    return results


# Minecraft formatting codes like "§9" / "§r" that leak in from tooltip data.
_MC_CODE = re.compile(r"\u00a7.")


def normalize_term(term):
    """Trim whitespace and noise (Minecraft codes, a trailing ":") from a term."""
    if term is None:
        return ""
    t = _MC_CODE.sub("", str(term)).strip()
    if t.endswith(":"):
        t = t[:-1].strip()
    return t


def normalize_translation(text):
    if text is None:
        return ""
    return _MC_CODE.sub("", str(text)).strip()


def normalize_pair(term, translation):
    """Normalize a (term, translation) pair for matching / dedupe.

    Trims whitespace and Minecraft color codes, drops a trailing ":" from the
    term, and — for tooltip-style entries where the term had that trailing
    colon — drops the matching ":"/"：" from the translation too. Returns a
    ``(term_key, translation)`` tuple with the term lower-cased.
    """
    raw_term = "" if term is None else str(term)
    had_colon = raw_term.strip().endswith(":")
    norm_term = normalize_term(raw_term)
    norm_translation = normalize_translation(translation)
    if had_colon:
        norm_translation = norm_translation.rstrip("：:").strip()
    return norm_term.casefold(), norm_translation


def slim_row(row):
    """Reduce a raw Paratranz API row to the fields the lookup actually needs.

    Drops the ~14 metadata fields (ids, timestamps, author/avatar objects,
    project, comment counts, ...) that bloat the cache. Keeps only:
      * term, translation  — the pair itself
      * variants           — aliases, only when present
      * note               — a translation hint, only when non-empty
      * caseSensitive      — only when true (matching is case-insensitive
                             by default; this flag is informational)
    """
    if not isinstance(row, dict):
        return None
    term = str(row.get("term") or "").strip()
    translation = str(row.get("translation") or "").strip()
    if not term or not translation:
        return None
    slim = {"term": term, "translation": translation}
    variants = [str(v).strip() for v in row.get("variants") or [] if str(v).strip()]
    if variants:
        slim["variants"] = variants
    note = str(row.get("note") or "").strip()
    if note:
        slim["note"] = note
    if row.get("caseSensitive"):
        slim["caseSensitive"] = True
    return slim


def slim_rows(rows):
    """Slim a list of raw rows and drop duplicate/empty entries.

    Two rows are duplicates when their term and translation are equal after
    normalization (whitespace + Minecraft color codes + a trailing ":"), which
    collapses entries that differ only by tooltip formatting noise.
    """
    out = []
    seen = set()
    for row in rows or []:
        slim = slim_row(row)
        if slim is None:
            continue
        key = normalize_pair(slim["term"], slim["translation"])
        if key in seen:
            continue
        seen.add(key)
        out.append(slim)
    return out


def load_cache(path=CACHE_PATH):
    """Return cached Paratranz rows, or None if no usable cache exists.

    Accepts both the slim on-disk format and the older raw API rows, so an
    existing cache keeps working after upgrading.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        rows = data.get("terms")
    else:
        rows = data
    return rows if isinstance(rows, list) else None


def save_cache(rows, path=CACHE_PATH):
    """Slim, deduplicate and write rows to the on-disk cache."""
    rows = slim_rows(rows)
    payload = {
        "meta": {
            "source": API_URL,
            "project": PROJECT_ID,
            "schema": CACHE_SCHEMA,
            "count": len(rows),
            "description": "Slimmed cache of Paratranz project 4964 terms "
                           "(term/translation/variants/note only). "
                           "Do not edit by hand; run scripts/terms_lookup.py --refresh.",
        },
        "terms": rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# glossary building
# ---------------------------------------------------------------------------

def entries_from_paratranz(rows):
    """Convert Paratranz rows (slim or raw) into glossary entries.

    Each entry: {"term", "translation", "variants", "note", "source"}.
    Aliases (variants) become their own entries pointing at the same
    translation, so they are matchable too.
    """
    entries = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        term = normalize_term(row.get("term"))
        translation = normalize_translation(row.get("translation"))
        if not term or not translation:
            continue
        # Match the dedupe key used by slim_rows: drop the tooltip-style
        # trailing ":"/"：" from the translation when the term had one.
        _, translation = normalize_pair(row.get("term"), row.get("translation"))
        variants = [normalize_term(v) for v in row.get("variants") or []]
        variants = [v for v in variants if v]
        note = str(row.get("note") or "").strip()
        for surface in [term] + variants:
            key = surface.casefold()
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "term": surface,
                    "translation": translation,
                    "variants": variants,
                    "note": note,
                    "source": "paratranz",
                }
            )
    return entries


def entries_from_curated(obj):
    """Flatten the hand-curated terms.json into glossary entries.

    Every leaf string under the category dicts (and top-level string
    mappings) becomes a term -> translation pair. Meta/underscore keys
    and descriptive prose blocks are skipped.
    """
    entries = []
    if not isinstance(obj, dict):
        return entries

    def add(term, translation):
        term = normalize_term(term)
        translation = normalize_translation(translation)
        if not term or not translation:
            return
        entries.append(
            {
                "term": term,
                "translation": translation,
                "variants": [],
                "source": "curated",
            }
        )

    def walk(node):
        for key, value in node.items():
            if key.startswith("_") or key == "meta":
                continue
            if isinstance(value, dict):
                # Only descend when the dict looks like a term map (leaf
                # values are strings), never into nested prose structures.
                if all(not isinstance(v, (dict, list)) for v in value.values()):
                    for k, v in value.items():
                        if k.startswith("_"):
                            continue
                        add(k, v)
                else:
                    walk(value)
            elif isinstance(value, str):
                add(key, value)

    walk(obj)
    return entries


def build_glossary(curated, paratranz_rows):
    """Merge sources. Curated wins on conflicting term (case-insensitive)."""
    curated_entries = entries_from_curated(curated)
    paratranz_entries = entries_from_paratranz(paratranz_rows)
    merged = {}
    for entry in paratranz_entries + curated_entries:
        key = entry["term"].casefold()
        merged[key] = entry  # curated processed last -> wins
    return list(merged.values())


def _loose_key(term):
    """Comparison key for cross-source matching.

    Case-insensitive, and treats spaces / underscores / hyphens as equivalent
    so curated keys like ``coke_oven`` match Paratranz ``Coke Oven``.
    """
    t = normalize_term(term)
    t = re.sub(r"[\s_\-]+", " ", t)
    return t.casefold()


def paratranz_keys(paratranz_rows):
    """Set of loose keys for every Paratranz term and variant."""
    keys = set()
    for row in paratranz_rows or []:
        if not isinstance(row, dict):
            continue
        for surface in [row.get("term")] + list(row.get("variants") or []):
            k = _loose_key(surface) if surface else ""
            if k:
                keys.add(k)
    return keys


def prune_curated(curated, paratranz_rows):
    """Remove curated entries already covered by Paratranz.

    Returns ``(pruned_obj, removed, conflicts)`` where:
      * pruned_obj is a copy of *curated* without the matched leaf terms,
        preserving category structure and empty categories' keys as needed;
      * removed is a list of ``(key, translation)`` that were dropped;
      * conflicts is a list of ``(key, curated_translation,
        [paratranz_translations])`` for dropped entries whose translation
        disagreed with Paratranz (so the change can be reviewed).
    """
    keys = paratranz_keys(paratranz_rows)
    para_trans = {}
    for row in paratranz_rows or []:
        if not isinstance(row, dict):
            continue
        trans = normalize_translation(row.get("translation")).rstrip("：:").strip()
        if not trans:
            continue
        for surface in [row.get("term")] + list(row.get("variants") or []):
            k = _loose_key(surface) if surface else ""
            if k:
                para_trans.setdefault(k, set()).add(trans)

    removed = []
    conflicts = []

    def prune(node):
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            if key.startswith("_") or key == "meta":
                out[key] = value
                continue
            if isinstance(value, dict):
                out[key] = prune(value)
            elif isinstance(value, str):
                k = _loose_key(key)
                if k in keys:
                    removed.append((key, value))
                    if value not in para_trans.get(k, set()):
                        conflicts.append((key, value, sorted(para_trans.get(k, set()))))
                    continue
                out[key] = value
            else:
                out[key] = value
        return out

    return prune(curated), removed, conflicts


def conflicts(curated, paratranz_rows):
    """Terms present in both sources with different translations."""
    curated_map = {
        e["term"].casefold(): e["translation"] for e in entries_from_curated(curated)
    }
    result = []
    for entry in entries_from_paratranz(paratranz_rows):
        key = entry["term"].casefold()
        if key in curated_map and curated_map[key] != entry["translation"]:
            result.append((entry["term"], curated_map[key], entry["translation"]))
    return result


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

def _boundary_ok(text, start, end):
    """Reject matches glued to adjacent letters/digits."""
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    word = re.compile(r"[A-Za-z0-9]")
    if before and word.match(before):
        return False
    if after and word.match(after):
        return False
    return True


def find_terms(text, glossary):
    """Return glossary entries whose term occurs in *text* (longest-first).

    Case-insensitive; requires word-ish boundaries; each term reported once.
    """
    if not text:
        return []
    lower = text.lower()
    ordered = sorted(glossary, key=lambda e: len(e["term"]), reverse=True)
    found = []
    seen = set()
    for entry in ordered:
        term = entry["term"]
        if not term:
            continue
        needle = term.lower()
        key = needle
        if key in seen:
            continue
        start = 0
        matched = False
        while True:
            idx = lower.find(needle, start)
            if idx == -1:
                break
            if _boundary_ok(text, idx, idx + len(needle)):
                matched = True
                break
            start = idx + 1
        if matched:
            seen.add(key)
            found.append(entry)
    return found


def terms_in_file(path, glossary, min_len=1):
    """Scan a subtitle file and return matched entries, in first-seen order."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # Drop timecode lines so numbers don't create false positives.
    lines = []
    for line in content.splitlines():
        if re.match(r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->", line):
            continue
        lines.append(line)
    text = "\n".join(lines)
    entries = find_terms(text, glossary)
    if min_len > 1:
        entries = [e for e in entries if len(e["term"]) >= min_len]
    # Sort by where the term first appears in the file (readability), with
    # longer terms first when they start at the same place.
    def sort_key(entry):
        idx = text.lower().find(entry["term"].lower())
        return (idx if idx >= 0 else len(text), -len(entry["term"]))

    return sorted(entries, key=sort_key)


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def format_matches(path, entries):
    out = []
    out.append("== %s ==" % path)
    if not entries:
        out.append("  (no known terms found)")
        return "\n".join(out)
    width = max(len(e["term"]) for e in entries)
    for e in entries:
        suffix = "" if e["source"] == "curated" else "  [paratranz]"
        line = "  %-*s -> %s%s" % (width, e["term"], e["translation"], suffix)
        note = e.get("note")
        if note:
            line += "   # %s" % note
        out.append(line)
    out.append("  (%d term(s))" % len(entries))
    return "\n".join(out)


def format_glossary(glossary, fmt="json"):
    if fmt == "tsv":
        lines = ["term\ttranslation\tsource\tvariants\tnote"]
        for e in sorted(glossary, key=lambda x: x["term"].lower()):
            lines.append(
                "\t".join(
                    [
                        e["term"],
                        e["translation"],
                        e["source"],
                        ",".join(e.get("variants") or []),
                        e.get("note") or "",
                    ]
                )
            )
        return "\n".join(lines)
    return json.dumps(
        {
            "meta": {
                "count": len(glossary),
                "sources": ["curated (terms.json)", "paratranz project %d" % PROJECT_ID],
            },
            "terms": sorted(glossary, key=lambda x: x["term"].lower()),
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------

def cache_schema_of(path=CACHE_PATH):
    """Return the schema version of the on-disk cache (0 if missing/unknown)."""
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    if isinstance(data, dict):
        return int(data.get("meta", {}).get("schema") or 0)
    return 0


def migrate_cache(path=CACHE_PATH):
    """Slim an existing cache file in place; return True if it was rewritten.

    Useful to shrink a cache written by an older version without re-downloading.
    """
    rows = load_cache(path)
    if rows is None:
        return False
    slim = slim_rows(rows)
    if len(slim) == len(rows) and cache_schema_of(path) == CACHE_SCHEMA:
        return False
    save_cache(slim, path)
    return True


def load_glossary(args):
    """Build the merged glossary according to cache/refresh/offline flags."""
    curated = {}
    if os.path.exists(CURATED_PATH):
        with open(CURATED_PATH, encoding="utf-8") as f:
            curated = json.load(f)

    paratranz_rows = None
    if args.offline:
        paratranz_rows = load_cache(args.cache)
        if paratranz_rows is None:
            print(
                "warning: --offline but no usable cache at %s; using curated terms only"
                % args.cache,
                file=sys.stderr,
            )
            paratranz_rows = []
    elif args.refresh or load_cache(args.cache) is None:
        try:
            paratranz_rows = fetch_paratranz(timeout=args.timeout)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            cached = load_cache(args.cache)
            if cached is not None:
                print(
                    "warning: fetch failed (%s); falling back to cache" % exc,
                    file=sys.stderr,
                )
                paratranz_rows = cached
            else:
                print(
                    "warning: fetch failed (%s) and no cache; using curated terms only"
                    % exc,
                    file=sys.stderr,
                )
                paratranz_rows = []
        else:
            # save_cache slims + dedupes before writing.
            save_cache(paratranz_rows, args.cache)
    else:
        paratranz_rows = load_cache(args.cache)
        # Upgrade an older raw cache in place so it stays small.
        if cache_schema_of(args.cache) != CACHE_SCHEMA:
            save_cache(paratranz_rows, args.cache)

    return build_glossary(curated, paratranz_rows), curated, paratranz_rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="subtitle file(s) to look up terms in")
    parser.add_argument(
        "--dump",
        action="store_true",
        help="print the whole merged glossary and exit",
    )
    parser.add_argument(
        "--format",
        choices=["json", "tsv"],
        default="json",
        help="output format for --dump (default: json)",
    )
    parser.add_argument(
        "--search",
        metavar="TEXT",
        help="substring-search the glossary for TEXT and exit",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download the Paratranz cache before doing anything else",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="never use the network; rely on the local cache",
    )
    parser.add_argument(
        "--cache",
        default=CACHE_PATH,
        help="path to the Paratranz cache (default: terms.paratranz.json)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="network timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--min-match",
        type=int,
        default=2,
        metavar="N",
        help="ignore matched terms shorter than N characters (default: %(default)s); "
        "use 1 to include everything",
    )
    parser.add_argument(
        "--conflicts",
        action="store_true",
        help="report curated vs Paratranz translation disagreements",
    )
    parser.add_argument(
        "--migrate-cache",
        action="store_true",
        help="slim/dedupe the on-disk cache in place and exit (no network)",
    )
    parser.add_argument(
        "--prune-curated",
        action="store_true",
        help="rewrite terms.json, removing terms already covered by Paratranz "
        "(writes a terms.prune-report.json summary)",
    )
    args = parser.parse_args(argv)

    if args.migrate_cache:
        before = os.path.getsize(args.cache) if os.path.exists(args.cache) else 0
        changed = migrate_cache(args.cache)
        after = os.path.getsize(args.cache) if os.path.exists(args.cache) else 0
        if changed:
            print(
                "Migrated %s: %.1f KB -> %.1f KB"
                % (args.cache, before / 1024, after / 1024)
            )
        else:
            print("No migration needed for %s" % args.cache)
        return 0

    if args.prune_curated:
        curated = {}
        if os.path.exists(CURATED_PATH):
            with open(CURATED_PATH, encoding="utf-8") as f:
                curated = json.load(f)
        rows = load_cache(args.cache) or []
        if not rows:
            print(
                "error: no Paratranz cache at %s; run --refresh first" % args.cache,
                file=sys.stderr,
            )
            return 1
        pruned, removed, conflicts = prune_curated(curated, rows)
        with open(CURATED_PATH, "w", encoding="utf-8") as f:
            json.dump(pruned, f, ensure_ascii=False, indent=2)
            f.write("\n")
        report = {
            "removed_count": len(removed),
            "removed": [{"term": k, "translation": v} for k, v in removed],
            "conflicts": [
                {"term": k, "curated": c, "paratranz": p} for k, c, p in conflicts
            ],
        }
        with open(PRUNE_REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(
            "Pruned %d term(s) from %s (%d translation conflict(s) recorded in %s)"
            % (
                len(removed),
                os.path.relpath(CURATED_PATH, ROOT),
                len(conflicts),
                os.path.relpath(PRUNE_REPORT_PATH, ROOT),
            )
        )
        return 0

    glossary, curated, paratranz_rows = load_glossary(args)

    if args.conflicts:
        rows = conflicts(curated, paratranz_rows)
        for term, cur, para in sorted(rows):
            print("%s: curated=%s paratranz=%s" % (term, cur, para))
        print("\n%d conflicting term(s)" % len(rows))
        return 0

    if args.dump:
        print(format_glossary(glossary, args.format))
        return 0

    if args.search:
        needle = args.search.lower()
        hits = sorted(
            (e for e in glossary if needle in e["term"].lower()),
            key=lambda e: e["term"].lower(),
        )
        for e in hits:
            print("%s\t%s" % (e["term"], e["translation"]))
        print("\n%d match(es)" % len(hits))
        return 0

    if not args.files:
        parser.error("no files given (use --dump, --search, or pass subtitle files)")

    total = 0
    for path in args.files:
        if not os.path.exists(path):
            print("error: no such file: %s" % path, file=sys.stderr)
            return 1
        entries = terms_in_file(path, glossary, args.min_match)
        total += len(entries)
        if len(args.files) > 1:
            print(format_matches(path, entries))
            print()
    if len(args.files) == 1:
        print(
            format_matches(
                args.files[0],
                terms_in_file(args.files[0], glossary, args.min_match),
            )
        )
    else:
        print("Total: %d term occurrence(s)" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
