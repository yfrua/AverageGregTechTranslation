# AGENTS.md

Guidance for AI agents (and scripts) working in this repository. Human
contributors should start with [README.md](README.md) / [README_ZH.md](README_ZH.md)
and [guidelines.md](guidelines.md).

## Task: translating a subtitle

1. Copy the pinned English `.srt` to a `_ZH` sibling (do not edit the EN file
   except for obvious transcription errors; keep words in `()`).
2. Translate following [guidelines.md](guidelines.md).
3. **Look up terminology first** (see below) and use the returned EN→ZH pairs.
4. Lint and auto-fix:
   `python3 scripts/subtitle_lint.py --fix --base origin/main <path-to.srt>`

## Terminology lookup

`scripts/terms_lookup.py` merges two sources and prints the terms that
actually occur in a subtitle, as a compact EN→ZH cheat sheet:

- `terms.json` — curated EN→CN terms **not** covered by Paratranz, plus
  project-specific conventions. **Curated wins on conflict.**
- `terms.paratranz.json` — cached copy of the public Paratranz project 4964
  glossary (https://paratranz.cn/projects/4964/terms). Slim: only
  `term` / `translation` / `variants` / `note`, deduplicated.

Run before translating:

```bash
python3 scripts/terms_lookup.py <path-to.srt>            # terms in this file
python3 scripts/terms_lookup.py --offline <path-to.srt>  # cache only, no network
```

Matching is case-insensitive, longest-term-first, word-boundary aware, and
includes Paratranz `variants` (aliases). Output notes (`# ...`) are
translation hints.

### Other modes

```bash
python3 scripts/terms_lookup.py --refresh <path-to.srt>   # re-download cache, then look up
python3 scripts/terms_lookup.py --dump                    # full merged glossary (JSON)
python3 scripts/terms_lookup.py --dump --format tsv       # ...as TSV
python3 scripts/terms_lookup.py --search assembl          # substring search
python3 scripts/terms_lookup.py --conflicts               # curated vs Paratranz disagreements
python3 scripts/terms_lookup.py --migrate-cache           # slim/dedupe an existing cache in place
python3 scripts/terms_lookup.py --prune-curated           # drop terms.json entries Paratranz already has
```

### Maintenance

- Refresh the upstream cache periodically with `--refresh` (network needed).
- After refreshing, `--prune-curated` removes any `terms.json` entry now
  covered by Paratranz and writes `terms.prune-report.json` listing what was
  dropped and any translation conflicts, for human review.
- Add new project-specific terms to `terms.json` (curated) — they override
  Paratranz and are the place for terms Paratranz lacks.

## Subtitle lint

`scripts/subtitle_lint.py` checks `.srt` files against `guidelines.md`.
Run it after translating; `--fix` auto-corrects fixable style issues
(trailing punctuation, mid-sentence `，` → space, half-width ? ! ... ( ) →
full-width, flash-frame gaps).

```bash
python3 scripts/subtitle_lint.py --fix <path-to.srt>
```

## Tests

```bash
python3 -m pytest tests/ -q
```

Unit tests mock the network; none require internet access.
