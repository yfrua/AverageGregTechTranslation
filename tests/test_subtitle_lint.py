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
    long_en = "x" * 115
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
# flash frame warnings
# ---------------------------------------------------------------------------

def test_lint_flash_frame_warning(tmp_path):
    # gap of 100 ms = 3 frames at 30 fps -> flash frame
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\nworld\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert errors == []
    assert any(w[2] == "timing/flash-frame" for w in warnings)


def test_lint_flash_frame_boundary_2_frames(tmp_path):
    # gap of 67 ms = ~2.01 frames -> flash frame
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,067 --> 00:00:02,000\nworld\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert any(w[2] == "timing/flash-frame" for w in warnings)


def test_lint_flash_frame_boundary_4_frames(tmp_path):
    # gap of 133 ms = ~3.99 frames -> flash frame
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,133 --> 00:00:02,000\nworld\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert any(w[2] == "timing/flash-frame" for w in warnings)


def test_lint_flash_frame_no_warning_below_2_frames(tmp_path):
    # gap of 66 ms = ~1.98 frames -> no flash frame
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,066 --> 00:00:02,000\nworld\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert all(w[2] != "timing/flash-frame" for w in warnings)


def test_lint_flash_frame_no_warning_above_4_frames(tmp_path):
    # gap of 500 ms = 15 frames -> no flash frame
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,500 --> 00:00:02,000\nworld\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert all(w[2] != "timing/flash-frame" for w in warnings)


def test_lint_flash_frame_no_warning_adjacent_cues(tmp_path):
    # gap of 0 ms -> no flash frame
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nworld\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert all(w[2] != "timing/flash-frame" for w in warnings)


def test_lint_flash_frame_no_warning_overlapping_cues(tmp_path):
    # negative gap (overlap) -> no flash frame
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nhello\n\n"
        "2\n00:00:01,000 --> 00:00:03,000\nworld\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert all(w[2] != "timing/flash-frame" for w in warnings)


def test_lint_flash_frame_no_duplicate_for_en_cn(tmp_path):
    # EN+CN pairing with a 3-frame gap -> only one warning (from the EN run)
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\nworld\n\n"
        "3\n00:00:00,000 --> 00:00:01,000\n你好\n\n"
        "4\n00:00:01,100 --> 00:00:02,000\n世界\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    flash = [w for w in warnings if w[2] == "timing/flash-frame"]
    assert len(flash) == 1


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


# ---------------------------------------------------------------------------
# start_time and output formatting
# ---------------------------------------------------------------------------

def test_cue_start_time_property():
    cue = sl.Cue(1, 1, 2, "00:01:23,456 --> 00:01:25,789", [(3, "text")])
    assert cue.start_time == "00:01:23,456"

    cue_dot = sl.Cue(1, 1, 2, "00:01:23.456 --> 00:01:25.789", [(3, "text")])
    assert cue_dot.start_time == "00:01:23.456"

    cue_none = sl.Cue(1, 1, None, None, [(2, "text")])
    assert cue_none.start_time is None


def test_lint_includes_start_time(tmp_path):
    srt = (
        "1\n00:01:00,000 --> 00:01:02,000\nhello world,\n\n"
        "2\n00:02:00,000 --> 00:02:02,000\n在GTNH中\n\n"
    )
    errors, warnings = sl.lint_one(_write(tmp_path, srt))
    assert len(errors) == 2
    # error 1: EN/punct on cue 1
    assert errors[0][2] == "EN/punct"
    assert errors[0][4] == "00:01:00,000"
    # error 2: ZH/space on cue 2
    assert errors[1][2] == "ZH/space"
    assert errors[1][4] == "00:02:00,000"


def test_main_output_format_with_start_time(tmp_path, capsys):
    srt = (
        "1\n00:01:23,456 --> 00:01:25,000\nhello,\n\n"
    )
    p = _write(tmp_path, srt)
    exit_code = sl.main([p])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "line 3 (00:01:23,456): remove trailing comma" in captured.out


def test_main_output_format_without_start_time(tmp_path, capsys):
    srt = "text before cue\n\n1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
    p = _write(tmp_path, srt)
    exit_code = sl.main([p])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "line 1: text before any cue" in captured.out


# ---------------------------------------------------------------------------
# ms_to_timestamp and format_timecode
# ---------------------------------------------------------------------------

def test_ms_to_timestamp():
    assert sl.ms_to_timestamp(0) == "00:00:00,000"
    assert sl.ms_to_timestamp(1500) == "00:00:01,500"
    assert sl.ms_to_timestamp(3661005) == "01:01:01,005"
    assert sl.ms_to_timestamp(1500, sep=".") == "00:00:01.500"


def test_format_timecode():
    assert (
        sl.format_timecode(0, 1000)
        == "00:00:00,000 --> 00:00:01,000"
    )
    assert (
        sl.format_timecode(0, 1000, sep=".")
        == "00:00:00.000 --> 00:00:01.000"
    )


# ---------------------------------------------------------------------------
# flash frame interval auto-fixing
# ---------------------------------------------------------------------------

def test_fix_flash_frame_2_frames_snap_to_0(tmp_path):
    # gap of 67 ms = ~2 frames -> snapped to 0
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,067 --> 00:00:02,000\nworld\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 1
    with open(p, encoding="utf-8") as fh:
        content = fh.read()
    assert "00:00:00,000 --> 00:00:01,067" in content
    assert "00:00:01,067 --> 00:00:02,000" in content
    # No flash-frame warning after fix
    errors, warnings = sl.lint_one(p)
    assert errors == []
    assert all(w[2] != "timing/flash-frame" for w in warnings)


def test_fix_flash_frame_3_frames_snap_to_0(tmp_path):
    # gap of 100 ms = 3 frames -> snapped to 0
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\nworld\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 1
    with open(p, encoding="utf-8") as fh:
        content = fh.read()
    assert "00:00:00,000 --> 00:00:01,100" in content
    assert "00:00:01,100 --> 00:00:02,000" in content
    errors, warnings = sl.lint_one(p)
    assert errors == []
    assert all(w[2] != "timing/flash-frame" for w in warnings)


def test_fix_flash_frame_4_frames_expand_to_5(tmp_path):
    # gap of 133 ms = ~4 frames -> expanded to 5 frames (167 ms gap)
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,133 --> 00:00:02,000\nworld\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 1
    with open(p, encoding="utf-8") as fh:
        content = fh.read()
    # 1133 - 167 = 966
    assert "00:00:00,000 --> 00:00:00,966" in content
    assert "00:00:01,133 --> 00:00:02,000" in content
    errors, warnings = sl.lint_one(p)
    assert errors == []
    assert all(w[2] != "timing/flash-frame" for w in warnings)


def test_fix_flash_frame_1_frame_untouched(tmp_path):
    # gap of 33 ms = 1 frame -> untouched
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,033 --> 00:00:02,000\nworld\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 0


def test_fix_flash_frame_5_frames_untouched(tmp_path):
    # gap of 167 ms = 5 frames -> untouched
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,167 --> 00:00:02,000\nworld\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 0


def test_fix_flash_frame_bilingual_both_runs_fixed(tmp_path):
    # EN run and CN run both fixed consistently
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\nworld\n\n"
        "3\n00:00:00,000 --> 00:00:01,000\n你好\n\n"
        "4\n00:00:01,100 --> 00:00:02,000\n世界\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 2
    with open(p, encoding="utf-8") as fh:
        content = fh.read()
    # Both EN cue 1 and CN cue 3 updated
    assert content.count("00:00:00,000 --> 00:00:01,100") == 2
    errors, warnings = sl.lint_one(p)
    assert errors == []
    assert warnings == []


def test_fix_flash_frame_preserves_dot_separator(tmp_path):
    srt = (
        "1\n00:00:00.000 --> 00:00:01.000\nhello\n\n"
        "2\n00:00:01.100 --> 00:00:02.000\nworld\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 1
    with open(p, encoding="utf-8") as fh:
        content = fh.read()
    assert "00:00:00.000 --> 00:00:01.100" in content


def test_fix_one_fixes_both_style_and_flash_frames(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\n在GTNH中\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\n我们走吧。\n\n"
    )
    p = _write(tmp_path, srt)
    # 1 style fix (ZH/space) + 1 style fix (ZH/punct) + 1 timecode fix = 3
    assert sl.fix_one(p) == 3
    with open(p, encoding="utf-8") as fh:
        content = fh.read()
    assert "在 GTNH 中\n" in content
    assert "我们走吧\n" in content
    assert "00:00:00,000 --> 00:00:01,100" in content


def test_main_with_fix_flag(tmp_path, capsys):
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\nworld\n\n"
    )
    p = _write(tmp_path, srt)
    exit_code = sl.main(["--fix", p])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Auto-fixed 1 line(s)." in captured.out
    assert "OK: no style/structure/length violations in 1 file(s)" in captured.out


def test_fix_flash_frames_chained_cues(tmp_path):
    # Cue 1 -> 2: 2 frames gap (67ms) -> snap to 0
    # Cue 2 -> 3: 4 frames gap (133ms) -> expand to 5 (167ms gap)
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nfirst\n\n"
        "2\n00:00:01,067 --> 00:00:02,000\nsecond\n\n"
        "3\n00:00:02,133 --> 00:00:03,000\nthird\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 2
    with open(p, encoding="utf-8") as fh:
        content = fh.read()
    assert "00:00:00,000 --> 00:00:01,067" in content
    assert "00:00:01,067 --> 00:00:01,966" in content
    assert "00:00:02,133 --> 00:00:03,000" in content
    errors, warnings = sl.lint_one(p)
    assert errors == []
    assert all(w[2] != "timing/flash-frame" for w in warnings)


def test_fix_flash_frames_does_not_invert_zero_length_cue(tmp_path):
    # Cue 1 starts at 1.100 and ends at 1.110 (10ms duration).
    # Cue 2 starts at 1.243 (gap is 133ms = 4 frames).
    # Expanding to 5 frames would set Cue 1 end to 1.243 - 0.167 = 1.076 (< start 1.100).
    # It must not set end <= start.
    srt = (
        "1\n00:00:01,100 --> 00:00:01,110\nshort\n\n"
        "2\n00:00:01,243 --> 00:00:02,000\nsecond\n\n"
    )
    p = _write(tmp_path, srt)
    assert sl.fix_one(p) == 0


def test_fix_flash_frames_ignores_comment_cues(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\nworld\n\n"
        "3\n00:00:02,100 --> 00:00:03,000\n（注释说明）\n\n"
    )
    p = _write(tmp_path, srt)
    # Only cue 1 is fixed (gap to cue 2 is 100ms = 3 frames); comment cue 3 is excluded
    assert sl.fix_one(p) == 1
    with open(p, encoding="utf-8") as fh:
        content = fh.read()
    assert "00:00:00,000 --> 00:00:01,100" in content
    assert "00:00:01,100 --> 00:00:02,000" in content
    assert "00:00:02,100 --> 00:00:03,000" in content