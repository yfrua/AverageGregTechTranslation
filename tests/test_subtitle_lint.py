import subtitle_lint as sl


# ---------------------------------------------------------------------------
# fix_english
# ---------------------------------------------------------------------------

def test_fix_english_removes_trailing_period_and_comma():
    assert sl.fix_english("I don't know.") == "I don't know"
    assert sl.fix_english("Let's go,") == "Let's go"
    assert sl.fix_english("Hello.") == "Hello"


def test_fix_english_keeps_kept_punctuation():
    assert sl.fix_english("Really?") == "Really?"
    assert sl.fix_english("Run!") == "Run!"
    assert sl.fix_english("Wait...") == "Wait..."
    assert sl.fix_english("I was gonna\u2014") == "I was gonna\u2014"


def test_fix_english_keeps_leading_whitespace():
    assert sl.fix_english("  Hello.") == "  Hello"


# ---------------------------------------------------------------------------
# fix_chinese
# ---------------------------------------------------------------------------

def test_fix_chinese_removes_trailing_zh_period():
    assert sl.fix_chinese("我们走吧。") == "我们走吧"


def test_fix_chinese_comma_to_space():
    assert sl.fix_chinese("等等，我看看") == "等等 我看看"


def test_fix_chinese_halfwidth_to_fullwidth():
    assert sl.fix_chinese("真的吗?") == "真的吗？"
    assert sl.fix_chinese("太好了!") == "太好了！"
    assert sl.fix_chinese("等等...") == "等等……"
    assert sl.fix_chinese("这是(注释)说明") == "这是（注释）说明"


def test_fix_chinese_spacing_cjk_latin():
    assert sl.fix_chinese("在GTNH中") == "在 GTNH 中"
    assert sl.fix_chinese("需要3个") == "需要 3 个"


def test_fix_chinese_combined():
    assert sl.fix_chinese("在GTNH中，我们走吧。") == "在 GTNH 中 我们走吧"


# ---------------------------------------------------------------------------
# space_cjk_latin
# ---------------------------------------------------------------------------

def test_space_cjk_latin_inserts_and_no_double_space():
    assert sl.space_cjk_latin("在GTNH中制作星门需要3个金锭") == "在 GTNH 中制作星门需要 3 个金锭"
    assert sl.space_cjk_latin("在 GTNH 中") == "在 GTNH 中"


def test_space_cjk_latin_ignores_fullwidth_punctuation():
    assert sl.space_cjk_latin("真的吗？") == "真的吗？"
    assert sl.space_cjk_latin("等等……") == "等等……"
    assert sl.space_cjk_latin("这么（好）啊") == "这么（好）啊"


# ---------------------------------------------------------------------------
# count_cjk
# ---------------------------------------------------------------------------

def test_count_cjk_counts_only_chinese_chars():
    assert sl.count_cjk("真的吗?") == 3
    assert sl.count_cjk("abc") == 0
    assert sl.count_cjk("GTNH中") == 1


# ---------------------------------------------------------------------------
# tc_to_ms
# ---------------------------------------------------------------------------

def test_tc_to_ms_parses_comma_and_dot():
    assert sl.tc_to_ms("00:00:01,500 --> 00:00:02,000") == (1500, 2000)
    assert sl.tc_to_ms("00:00:01.500 --> 00:00:02.000") == (1500, 2000)


def test_tc_to_ms_invalid_returns_none():
    assert sl.tc_to_ms("garbage") is None


# ---------------------------------------------------------------------------
# style_english / style_chinese
# ---------------------------------------------------------------------------

def test_style_english_trailing_punct():
    errors = []
    sl.style_english("Hello,", 1, "f.srt", errors)
    sl.style_english("Bye.", 2, "f.srt", errors)
    assert [e[2] for e in errors] == ["EN/punct", "EN/punct"]


def test_style_english_accepts_kept_punct():
    errors = []
    for l in ("Really?", "Run!", "Wait...", "I was gonna\u2014"):
        sl.style_english(l, 1, "f.srt", errors)
    assert errors == []


def test_style_chinese_flags_each_violation():
    errors = []
    sl.style_chinese("我们走吧。", 1, "f.srt", errors)
    sl.style_chinese("等等，我看看", 2, "f.srt", errors)
    sl.style_chinese("真的吗?", 3, "f.srt", errors)
    sl.style_chinese("在GTNH中", 4, "f.srt", errors)
    codes = [e[2] for e in errors]
    assert "ZH/punct" in codes
    assert "ZH/comma" in codes
    assert "ZH/halfwidth" in codes
    assert "ZH/space" in codes


def test_style_chinese_clean():
    errors = []
    sl.style_chinese("我们走吧", 1, "f.srt", errors)
    sl.style_chinese("在 GTNH 中", 2, "f.srt", errors)
    assert errors == []


# ---------------------------------------------------------------------------
# lint_one (end-to-end on temp files)
# ---------------------------------------------------------------------------

def _write(tmp_path, text):
    p = tmp_path / "sub.srt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_lint_clean_file(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nhello world\n\n"
        "2\n00:00:00,000 --> 00:00:02,000\n大家好\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert errors == []
    assert warnings == []


def test_lint_flags_zh_violations(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nhello world\n\n"
        "2\n00:00:00,000 --> 00:00:02,000\n在GTNH中，走吧。\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    codes = {e[2] for e in errors}
    assert {"ZH/comma", "ZH/space", "ZH/punct"} <= codes


def test_lint_en_only_skips_pairing(tmp_path):
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhello\n\n"
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert all(e[2] != "struct/pairing" for e in errors)


def test_lint_pairing_count_mismatch(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nhello\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nworld\n\n"
        "3\n00:00:00,000 --> 00:00:02,000\n你好\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert any(w[2] == "struct/pairing" for w in warnings)
    assert all(e[2] != "struct/pairing" for e in errors)


def test_lint_pairing_timecode_mismatch(tmp_path):
    srt = (
        "1\n00:00:09,000 --> 00:00:10,000\nhello\n\n"
        "2\n00:00:00,000 --> 00:00:02,000\n你好\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    pairing = [w for w in warnings if w[2] == "struct/pairing"]
    assert pairing and "timecode mismatch" in pairing[0][3]
    assert all(e[2] != "struct/pairing" for e in errors)


def test_lint_comment_cue_excluded_from_pairing(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nhello\n\n"
        "2\n00:00:00,000 --> 00:00:02,000\n你好\n\n"
        "3\n00:00:00,000 --> 00:00:02,000\n（我只是在开玩笑\n不是字幕）\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert all(w[2] != "struct/pairing" for w in warnings)
    assert all(e[2] != "struct/pairing" for e in errors)


def test_lint_length_warnings(tmp_path):
    long_en = "x" * 105
    long_zh = "汉" * 35
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\n%s\n\n"
        "2\n00:00:00,000 --> 00:00:02,000\n%s\n\n" % (long_en, long_zh)
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert errors == []
    assert len(warnings) == 2
    assert all(w[2] == "style/length" for w in warnings)


def test_lint_whisper_blank_quirk(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\n\nhello world\n\n"
        "2\n00:00:00,000 --> 00:00:02,000\n大家好\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert all(e[2] != "struct" for e in errors)


def test_lint_invalid_timecode(tmp_path):
    srt = "1\nnot-a-timecode --> x\nhello\n\n"
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert any(e[2] == "struct" for e in errors)


# ---------------------------------------------------------------------------
# fix_one (end-to-end on temp files)
# ---------------------------------------------------------------------------

def test_fix_one_rewrites_zh_rules(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nhello world.\n\n"
        "2\n00:00:00,000 --> 00:00:02,000\n在GTNH中，我们走吧。\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 2
    fixed = p
    with open(fixed, encoding="utf-8") as fh:
        content = fh.read()
    assert "hello world." not in content
    assert "hello world\n" in content
    assert "在 GTNH 中 我们走吧\n" in content


def test_fix_one_noop_when_clean(tmp_path):
    srt = "1\n00:00:00,000 --> 00:00:02,000\nhello world\n\n"
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 0