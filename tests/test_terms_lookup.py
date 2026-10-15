import json
import urllib.request

import terms_lookup as tl


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

def test_normalize_term_trims_and_drops_colon():
    assert tl.normalize_term("   Controller:") == "Controller"
    assert tl.normalize_term("  Energy Hatch: ") == "Energy Hatch"
    assert tl.normalize_term("plain") == "plain"
    assert tl.normalize_term(None) == ""


def test_normalize_term_strips_minecraft_codes():
    assert tl.normalize_term("\u00a79Controller\u00a7r") == "Controller"


def test_normalize_translation_strips_minecraft_codes_and_ws():
    assert tl.normalize_translation("  \u00a7f控制器： ") == "控制器："


def test_normalize_pair_lowercases_term_and_trims():
    assert tl.normalize_pair("  Macerator ", " 研磨机 ") == ("macerator", "研磨机")


def test_normalize_pair_drops_tooltip_colon_from_translation():
    assert tl.normalize_pair("Controller:", "控制器：") == ("controller", "控制器")
    # A colon in the translation but not the term is preserved.
    assert tl.normalize_pair("Foo", "栏：") == ("foo", "栏：")


# ---------------------------------------------------------------------------
# entries_from_paratranz
# ---------------------------------------------------------------------------

def test_paratranz_entries_include_variants():
    rows = [
        {
            "term": "Advanced Assembly Line",
            "translation": "进阶装配线",
            "variants": ["AAL"],
        }
    ]
    entries = tl.entries_from_paratranz(rows)
    terms = {e["term"] for e in entries}
    assert terms == {"Advanced Assembly Line", "AAL"}
    assert all(e["translation"] == "进阶装配线" for e in entries)


def test_paratranz_entries_carry_note():
    rows = [{"term": "Advanced", "translation": "进阶", "note": "GT机器应翻译为进阶"}]
    entries = tl.entries_from_paratranz(rows)
    assert entries[0]["note"] == "GT机器应翻译为进阶"


def test_paratranz_entries_skip_empty():
    rows = [
        {"term": "", "translation": "x"},
        {"term": "y", "translation": ""},
        {"term": "good", "translation": "好"},
    ]
    entries = tl.entries_from_paratranz(rows)
    assert [e["term"] for e in entries] == ["good"]


def test_paratranz_colon_term_drops_trailing_colon_translation():
    rows = [{"term": "   Energy Hatch:", "translation": "   能源仓：  "}]
    entries = tl.entries_from_paratranz(rows)
    assert entries[0]["term"] == "Energy Hatch"
    assert entries[0]["translation"] == "能源仓"


def test_paratranz_plain_term_keeps_translation_colon():
    # A trailing colon in the *translation* is only stripped when the term
    # itself had the tooltip-style trailing colon.
    rows = [{"term": "Foo", "translation": "栏："}]
    entries = tl.entries_from_paratranz(rows)
    assert entries[0]["translation"] == "栏："


# ---------------------------------------------------------------------------
# entries_from_curated
# ---------------------------------------------------------------------------

def test_curated_flattens_categories_and_mappings():
    obj = {
        "meta": {"description": "ignore me"},
        "known_conventions": {"macerator": "研磨机"},
        "world_generation": {"ore vein": "矿脉"},
    }
    entries = tl.entries_from_curated(obj)
    mapping = {e["term"]: e["translation"] for e in entries}
    assert mapping == {"macerator": "研磨机", "ore vein": "矿脉"}


def test_curated_skips_underscore_keys():
    obj = {"cat": {"_note": "not a term", "real": "真的"}}
    entries = tl.entries_from_curated(obj)
    assert [e["term"] for e in entries] == ["real"]


# ---------------------------------------------------------------------------
# build_glossary / conflicts
# ---------------------------------------------------------------------------

def test_curated_wins_on_conflict():
    curated = {"known_conventions": {"macerator": "研磨机"}}
    paratranz = [{"term": "Macerator", "translation": "磨粉机", "variants": []}]
    glossary = tl.build_glossary(curated, paratranz)
    by_term = {e["term"].casefold(): e for e in glossary}
    assert by_term["macerator"]["translation"] == "研磨机"
    assert by_term["macerator"]["source"] == "curated"


def test_conflicts_reports_disagreements():
    curated = {"known_conventions": {"macerator": "研磨机"}}
    paratranz = [
        {"term": "Macerator", "translation": "磨粉机", "variants": []},
        {"term": "Agree", "translation": "同", "variants": []},
    ]
    curated_with_agree = {"c": {"Macerator": "研磨机", "Agree": "同"}}
    rows = tl.conflicts(curated_with_agree, paratranz)
    assert rows == [("Macerator", "研磨机", "磨粉机")]


# ---------------------------------------------------------------------------
# prune_curated
# ---------------------------------------------------------------------------

def test_loose_key_normalizes_case_space_underscore_hyphen():
    assert tl._loose_key("Coke Oven") == "coke oven"
    assert tl._loose_key("coke_oven") == "coke oven"
    assert tl._loose_key("coke-oven") == "coke oven"
    assert tl._loose_key("  Coke   Oven  ") == "coke oven"


def test_paratranz_keys_includes_variants():
    rows = [{"term": "Electric Blast Furnace", "translation": "工业高炉", "variants": ["EBF"]}]
    keys = tl.paratranz_keys(rows)
    assert "electric blast furnace" in keys
    assert "ebf" in keys


def test_prune_curated_removes_matches_only():
    curated = {
        "known_conventions": {
            "coke_oven": "焦炉",       # matches "Coke Oven"
            "macerator": "研磨机",     # not in paratranz
        }
    }
    paratranz = [{"term": "Coke Oven", "translation": "焦炉", "variants": []}]
    pruned, removed, conflicts, retained = tl.prune_curated(curated, paratranz)
    assert pruned["known_conventions"] == {"macerator": "研磨机"}
    assert removed == [("coke_oven", "焦炉")]
    assert conflicts == []
    assert retained == []


def test_prune_curated_removes_via_variant():
    curated = {"machines": {"EBF": "电高炉"}}
    paratranz = [
        {"term": "Electric Blast Furnace", "translation": "工业高炉", "variants": ["EBF"]}
    ]
    pruned, removed, conflicts, _ = tl.prune_curated(curated, paratranz)
    assert pruned["machines"] == {}
    assert removed == [("EBF", "电高炉")]
    # Translation differs -> conflict recorded (but entry still removed).
    assert conflicts == [("EBF", "电高炉", ["工业高炉"])]


def test_prune_curated_keeps_meta_keep_terms():
    curated = {
        "meta": {"_keep": ["EV", "right click"]},
        "known_conventions": {"EV": "EV", "iron": "铁"},
        "game_mechanics": {"right click": "右键点击"},
    }
    paratranz = [
        {"term": "EV", "translation": "超高压", "variants": []},
        {"term": "Iron", "translation": "铁", "variants": []},
        {"term": "right click", "translation": "右击", "variants": []},
    ]
    pruned, removed, conflicts, retained = tl.prune_curated(curated, paratranz)
    # Deliberate overrides survive; they are not reported as removed.
    assert pruned["known_conventions"] == {"EV": "EV"}
    assert pruned["game_mechanics"] == {"right click": "右键点击"}
    assert removed == [("iron", "铁")]
    assert retained == [("EV", "EV"), ("right click", "右键点击")]
    # A kept term with a differing translation is NOT a conflict (we keep ours).
    assert conflicts == []


def test_curated_keep_keys_normalizes():
    curated = {"meta": {"_keep": ["Coke  Oven", "right_click", ""]}}
    assert tl.curated_keep_keys(curated) == {"coke oven", "right click"}


def test_curated_keep_keys_missing_is_empty():
    assert tl.curated_keep_keys({}) == set()
    assert tl.curated_keep_keys({"meta": {}}) == set()


def test_prune_curated_keeps_underscore_and_meta_keys():
    curated = {
        "meta": {"description": "keep"},
        "cat": {"_note": "keep me", "macerator": "研磨机"},
    }
    pruned, removed, _, _ = tl.prune_curated(curated, [])
    assert pruned["meta"] == {"description": "keep"}
    assert pruned["cat"]["_note"] == "keep me"
    assert pruned["cat"]["macerator"] == "研磨机"
    assert removed == []


def test_prune_curated_does_not_mutate_input():
    curated = {"c": {"coke_oven": "焦炉"}}
    paratranz = [{"term": "Coke Oven", "translation": "焦炉", "variants": []}]
    tl.prune_curated(curated, paratranz)
    assert curated == {"c": {"coke_oven": "焦炉"}}


# ---------------------------------------------------------------------------
# find_terms
# ---------------------------------------------------------------------------

def _g(term, translation, variants=None, source="paratranz"):
    return {
        "term": term,
        "translation": translation,
        "variants": variants or [],
        "source": source,
    }


def test_find_terms_longest_first():
    glossary = [_g("assembly line", "装配线"), _g("Advanced Assembly Line", "进阶装配线")]
    found = tl.find_terms("the Advanced Assembly Line rocks", glossary)
    assert found[0]["term"] == "Advanced Assembly Line"
    assert "assembly line" in [e["term"] for e in found]


def test_find_terms_case_insensitive():
    glossary = [_g("Naquadah", "硅岩")]
    found = tl.find_terms("some naquadah ore", glossary)
    assert [e["term"] for e in found] == ["Naquadah"]


def test_find_terms_respects_word_boundaries():
    glossary = [_g("lead", "铅"), _g("can", "罐")]
    assert tl.find_terms("leaded glass", glossary) == []
    assert tl.find_terms("we cannot", glossary) == []
    assert [e["term"] for e in tl.find_terms("a can here", glossary)] == ["can"]


def test_find_terms_reports_each_once():
    glossary = [_g("ore", "矿石")]
    found = tl.find_terms("ore ore ore", glossary)
    assert len(found) == 1


def test_find_terms_empty_text():
    assert tl.find_terms("", [_g("x", "y")]) == []


# ---------------------------------------------------------------------------
# terms_in_file
# ---------------------------------------------------------------------------

SAMPLE = """1
00:00:01,000 --> 00:00:03,000
Welcome to the Advanced Assembly Line

2
00:00:03,000 --> 00:00:05,000
Now the multiblock
"""


def test_terms_in_file_ignores_timecodes(tmp_path):
    p = tmp_path / "a.srt"
    p.write_text(SAMPLE, encoding="utf-8")
    glossary = [_g("Welcome", "欢迎"), _g("00:00", "时间")]
    found = tl.terms_in_file(str(p), glossary)
    assert [e["term"] for e in found] == ["Welcome"]


def test_terms_in_file_min_len(tmp_path):
    p = tmp_path / "a.srt"
    p.write_text(SAMPLE, encoding="utf-8")
    glossary = [_g("Now", "现在"), _g("multiblock", "多方块")]
    found = tl.terms_in_file(str(p), glossary, min_len=4)
    assert [e["term"] for e in found] == ["multiblock"]


# ---------------------------------------------------------------------------
# fetch / cache (mocked — no network)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_paratranz_follows_pagination(monkeypatch):
    pages = {
        1: {"results": [{"term": "a"}], "pageCount": 2},
        2: {"results": [{"term": "b"}], "pageCount": 2},
    }
    calls = []

    def opener(req, timeout=None):
        calls.append(req.full_url)
        page = int(req.full_url.split("page=")[1].split("&")[0])
        return _FakeResponse(pages[page])

    rows = tl.fetch_paratranz(opener=opener)
    assert [r["term"] for r in rows] == ["a", "b"]
    assert len(calls) == 2


def test_fetch_paratranz_retries_then_succeeds():
    state = {"n": 0}

    def opener(req, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            raise urllib.error.URLError("boom")
        return _FakeResponse({"results": [{"term": "ok"}], "pageCount": 1})

    rows = tl.fetch_paratranz(retries=2, opener=opener)
    assert [r["term"] for r in rows] == ["ok"]
    assert state["n"] == 2


def test_save_and_load_cache_roundtrip(tmp_path):
    cache = tmp_path / "c.json"
    rows = [{"term": "x", "translation": "y"}]
    tl.save_cache(rows, str(cache))
    assert tl.load_cache(str(cache)) == rows


def test_save_cache_writes_schema_and_count(tmp_path):
    cache = tmp_path / "c.json"
    tl.save_cache([{"term": "x", "translation": "y"}], str(cache))
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["meta"]["schema"] == tl.CACHE_SCHEMA
    assert data["meta"]["count"] == 1


def test_load_cache_missing_returns_none(tmp_path):
    assert tl.load_cache(str(tmp_path / "nope.json")) is None


# ---------------------------------------------------------------------------
# slimming / dedupe / migration
# ---------------------------------------------------------------------------

RAW_ROW = {
    "id": 123,
    "createdAt": "2023-01-01T00:00:00.000Z",
    "updatedAt": "2023-01-02T00:00:00.000Z",
    "updatedBy": {"id": 1, "username": "someone", "avatar": "http://x/y.png"},
    "pos": "noun",
    "uid": 42,
    "term": "Macerator",
    "translation": "研磨机",
    "note": "",
    "project": 4964,
    "variants": [],
    "caseSensitive": False,
    "commentsCount": 0,
    "user": {"id": 42, "username": "someone"},
}


def test_slim_row_drops_metadata():
    slim = tl.slim_row(RAW_ROW)
    assert slim == {"term": "Macerator", "translation": "研磨机"}
    assert "id" not in slim and "user" not in slim and "createdAt" not in slim


def test_slim_row_keeps_variants_note_and_case_sensitive():
    row = dict(RAW_ROW, variants=["Mac"], note="hint", caseSensitive=True)
    slim = tl.slim_row(row)
    assert slim["variants"] == ["Mac"]
    assert slim["note"] == "hint"
    assert slim["caseSensitive"] is True


def test_slim_row_omits_empty_optionals():
    slim = tl.slim_row(dict(RAW_ROW, variants=[], note="  ", caseSensitive=False))
    assert "variants" not in slim
    assert "note" not in slim
    assert "caseSensitive" not in slim


def test_slim_row_rejects_empty_term_or_translation():
    assert tl.slim_row({"term": "", "translation": "x"}) is None
    assert tl.slim_row({"term": "x", "translation": ""}) is None
    assert tl.slim_row("not a dict") is None


def test_slim_rows_dedupes_normalized_duplicates():
    rows = [
        {"term": "   Controller:", "translation": "   控制器：  "},
        {"term": "\u00a7fController: ", "translation": "   \u00a7f控制器：  "},
        {"term": "Controller", "translation": "控制器"},
    ]
    slim = tl.slim_rows(rows)
    # All three normalize to ("controller", "控制器").
    assert len(slim) == 1


def test_slim_rows_keeps_distinct_translations():
    rows = [
        {"term": "Capacity", "translation": "容量"},
        {"term": "Capacity", "translation": "容量："},
    ]
    assert len(tl.slim_rows(rows)) == 2


def test_cache_schema_of_missing_is_zero(tmp_path):
    assert tl.cache_schema_of(str(tmp_path / "nope.json")) == 0


def test_migrate_cache_slims_legacy_file(tmp_path):
    cache = tmp_path / "c.json"
    # Legacy shape: raw rows, no schema, with metadata.
    legacy = {"meta": {"source": "x"}, "terms": [RAW_ROW, dict(RAW_ROW)]}
    cache.write_text(json.dumps(legacy), encoding="utf-8")
    assert tl.migrate_cache(str(cache)) is True
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["meta"]["schema"] == tl.CACHE_SCHEMA
    assert data["terms"] == [{"term": "Macerator", "translation": "研磨机"}]


def test_migrate_cache_noop_when_already_slim(tmp_path):
    cache = tmp_path / "c.json"
    tl.save_cache([{"term": "x", "translation": "y"}], str(cache))
    assert tl.migrate_cache(str(cache)) is False


def test_load_cache_reads_legacy_raw_rows(tmp_path):
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps([RAW_ROW]), encoding="utf-8")
    rows = tl.load_cache(str(cache))
    assert rows[0]["term"] == "Macerator"
    assert rows[0]["user"]["id"] == 42


def test_load_cache_corrupt_returns_none(tmp_path):
    cache = tmp_path / "bad.json"
    cache.write_text("{not json", encoding="utf-8")
    assert tl.load_cache(str(cache)) is None


# ---------------------------------------------------------------------------
# output formatting
# ---------------------------------------------------------------------------

def test_format_glossary_json_roundtrip():
    glossary = [_g("b", "乙"), _g("a", "甲")]
    out = json.loads(tl.format_glossary(glossary, "json"))
    assert out["meta"]["count"] == 2
    assert [e["term"] for e in out["terms"]] == ["a", "b"]


def test_format_glossary_tsv():
    glossary = [_g("AE2", "AE2", variants=["Applied Energistics"])]
    out = tl.format_glossary(glossary, "tsv")
    lines = out.splitlines()
    assert lines[0] == "term\ttranslation\tsource\tvariants\tnote"
    assert "Applied Energistics" in lines[1]


def test_format_matches_no_terms():
    assert "(no known terms found)" in tl.format_matches("x.srt", [])


def test_format_matches_renders_note():
    entry = {
        "term": "Advanced",
        "translation": "进阶",
        "variants": [],
        "note": "GT机器应翻译为进阶",
        "source": "paratranz",
    }
    out = tl.format_matches("x.srt", [entry])
    assert "# GT机器应翻译为进阶" in out
