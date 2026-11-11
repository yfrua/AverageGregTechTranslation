import pytest

import tts_dub as td


def write_srt(tmp_path, text):
    path = tmp_path / "sub.srt"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_srt
# ---------------------------------------------------------------------------

def test_parse_srt_reads_times_and_text(tmp_path):
    path = write_srt(tmp_path, (
        "1\n"
        "00:00:01,500 --> 00:00:03,250\n"
        "第一行\n"
        "第二行\n"
        "\n"
        "2\n"
        "01:02:03,004 --> 01:02:05,000\n"
        "下一句\n"
    ))
    cues = td.parse_srt(path)
    assert len(cues) == 2
    assert (cues[0].start, cues[0].end) == (1.5, 3.25)
    assert cues[0].text == "第一行 第二行"
    assert (cues[1].start, cues[1].end) == (3723.004, 3725.0)


def test_parse_srt_accepts_bom_crlf_and_dot_milliseconds(tmp_path):
    path = tmp_path / "crlf.srt"
    path.write_bytes(
        b"\xef\xbb\xbf1\r\n00:00:00.100 --> 00:00:01.900\r\nHi\r\n"
    )
    cues = td.parse_srt(path)
    assert len(cues) == 1
    assert (cues[0].start, cues[0].end) == (0.1, 1.9)


def test_parse_srt_skips_blocks_without_timecode_or_text(tmp_path):
    path = write_srt(tmp_path, (
        "1\n"
        "not a timecode\n"
        "ignored\n"
        "\n"
        "2\n"
        "00:00:01,000 --> 00:00:02,000\n"
        "\n"
        "3\n"
        "00:00:03,000 --> 00:00:04,000\n"
        "kept\n"
    ))
    cues = td.parse_srt(path)
    assert [c.text for c in cues] == ["kept"]


# ---------------------------------------------------------------------------
# plan_segments
# ---------------------------------------------------------------------------

def test_plan_segments_keeps_gaps_and_durations():
    cues = [td.Cue(1.0, 2.0, "a"), td.Cue(3.0, 5.0, "b")]
    segments, lost = td.plan_segments(cues, 10.0)
    assert [(s.start, s.duration) for s in segments] == [(1.0, 1.0), (3.0, 2.0)]
    assert lost == 0


def test_plan_segments_pushes_overlapping_cue_forward():
    cues = [td.Cue(0.0, 3.0, "a"), td.Cue(2.0, 4.0, "b")]
    segments, lost = td.plan_segments(cues, 10.0)
    assert segments[0].start == 0.0
    assert segments[1].start == 3.0
    assert segments[1].duration == 1.0
    assert lost == 1.0


def test_plan_segments_clamps_to_video_end():
    cues = [td.Cue(9.0, 15.0, "a")]
    segments, lost = td.plan_segments(cues, 10.0)
    assert [(s.start, s.duration) for s in segments] == [(9.0, 1.0)]
    assert lost >= 5.0


def test_plan_segments_ignores_cues_starting_after_end():
    cues = [td.Cue(10.0, 12.0, "late")]
    segments, lost = td.plan_segments(cues, 10.0)
    assert segments == []
    assert lost == 0


def test_plan_segments_expands_short_cue_to_minimum():
    cues = [td.Cue(1.0, 1.05, "blip")]
    segments, lost = td.plan_segments(cues, 10.0, min_duration=0.2)
    assert segments[0].duration == 0.2
    assert lost == 0


def test_plan_segments_minimum_does_not_pass_video_end():
    cues = [td.Cue(4.95, 5.0, "blip")]
    segments, _ = td.plan_segments(cues, 5.0, min_duration=0.2)
    assert segments[0].duration == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# split_runs / select_source
# ---------------------------------------------------------------------------

def bilingual_cues():
    return [
        td.Cue(0.0, 1.0, "Welcome back"),
        td.Cue(1.0, 3.0, "Today we look at HV"),
        td.Cue(0.0, 1.0, "欢迎回来"),
        td.Cue(1.0, 3.0, "今天我们看 HV"),
    ]


def test_split_runs_splits_on_timecode_reset():
    runs = td.split_runs(bilingual_cues())
    assert [len(run) for run in runs] == [2, 2]
    assert runs[1][0].text == "欢迎回来"


def test_split_runs_keeps_single_run():
    cues = [td.Cue(0.0, 1.0, "a"), td.Cue(1.0, 2.0, "b")]
    assert [len(run) for run in td.split_runs(cues)] == [2]


def test_select_source_auto_prefers_english_run():
    picked = td.select_source(bilingual_cues())
    assert [c.text for c in picked] == ["Welcome back", "Today we look at HV"]


def test_select_source_zh_picks_chinese_run():
    picked = td.select_source(bilingual_cues(), "zh")
    assert [c.text for c in picked] == ["欢迎回来", "今天我们看 HV"]


def test_select_source_en_on_chinese_only_file_returns_it():
    cues = [td.Cue(0.0, 1.0, "欢迎回来")]
    assert td.select_source(cues, "en") == cues


def test_latin_ratio_ignores_shared_english_terms():
    english = [td.Cue(0, 1, "The HV age is here")]
    mixed = [td.Cue(0, 1, "HV 时代来了")]
    assert td.latin_ratio(english) == 1.0
    assert td.latin_ratio(mixed) < 0.5


# ---------------------------------------------------------------------------
# group_sentences
# ---------------------------------------------------------------------------

def test_group_sentences_joins_continuation_lines():
    cues = [
        td.Cue(0.0, 2.0, "And the first thing"),
        td.Cue(2.0, 4.0, "we notice is that"),
        td.Cue(4.0, 7.0, "as soon as we reach HV"),
    ]
    groups = td.group_sentences(cues)
    assert len(groups) == 1
    assert groups[0].text == "And the first thing we notice is that as soon as we reach HV"
    assert (groups[0].start, groups[0].end) == (0.0, 7.0)


def test_group_sentences_breaks_at_terminal_punctuation():
    cues = [td.Cue(0.0, 2.0, "Welcome back."), td.Cue(2.1, 4.0, "Today we start")]
    assert len(td.group_sentences(cues)) == 2


def test_group_sentences_breaks_at_chinese_full_stop():
    cues = [td.Cue(0.0, 2.0, "欢迎回来。"), td.Cue(2.1, 4.0, "今天我们开始")]
    assert len(td.group_sentences(cues)) == 2


def test_group_sentences_breaks_across_long_gap():
    cues = [td.Cue(0.0, 1.0, "and then"), td.Cue(2.0, 3.0, "something else")]
    assert len(td.group_sentences(cues)) == 2


def test_group_sentences_respects_max_duration():
    cues = [td.Cue(0.0, 8.0, "a long clause"), td.Cue(8.0, 13.0, "continues here")]
    assert len(td.group_sentences(cues, max_duration=12.0)) == 2


def test_group_sentences_leaves_single_cue_alone():
    cues = [td.Cue(1.0, 2.0, "just one")]
    groups = td.group_sentences(cues)
    assert len(groups) == 1
    assert groups[0] is not cues[0]


# ---------------------------------------------------------------------------
# polly_ssml
# ---------------------------------------------------------------------------

def test_polly_ssml_escapes_text():
    assert td.polly_ssml("a < b & c") == "<speak>a &lt; b &amp; c</speak>"


def test_polly_ssml_adds_prosody_rate():
    assert td.polly_ssml("Hello", 15) == (
        '<speak><prosody rate="115%">Hello</prosody></speak>'
    )


def test_polly_ssml_without_rate_has_no_prosody():
    assert td.polly_ssml("Hello") == "<speak>Hello</speak>"


# ---------------------------------------------------------------------------
# tempo_factor
# ---------------------------------------------------------------------------

def test_tempo_factor_leaves_short_clip_alone():
    assert td.tempo_factor(3.0, 5.0, 1.5) == 1.0


def test_tempo_factor_speeds_up_to_fit():
    assert td.tempo_factor(6.0, 4.0, 1.5) == 1.5
    assert td.tempo_factor(4.4, 4.0, 1.5) == 1.1


def test_tempo_factor_respects_cap():
    assert td.tempo_factor(20.0, 4.0, 1.5) == 1.5


def test_tempo_factor_handles_empty_slot():
    assert td.tempo_factor(2.0, 0.0, 1.5) == 1.0


# ---------------------------------------------------------------------------
# rate_needed
# ---------------------------------------------------------------------------

def test_rate_needed_ignores_small_overrun():
    assert td.rate_needed(4.4, 4.0, 40) == 0


def test_rate_needed_speeds_up_overrun_in_five_percent_steps():
    assert td.rate_needed(4.6, 4.0, 40) == 15
    assert td.rate_needed(5.0, 4.0, 40) == 25


def test_rate_needed_respects_cap():
    assert td.rate_needed(8.0, 4.0, 40) == 40


def test_rate_needed_handles_empty_slot():
    assert td.rate_needed(3.0, 0.0, 40) == 0


# ---------------------------------------------------------------------------
# concat_file
# ---------------------------------------------------------------------------

def test_concat_file_quotes_and_escapes_paths(tmp_path):
    listing = tmp_path / "list.txt"
    td.concat_file([tmp_path / "a.wav", tmp_path / "it's.wav"], listing)
    assert listing.read_text(encoding="utf-8") == (
        "file '%s'\n" % (tmp_path / "a.wav")
        + "file '%s'\n" % str(tmp_path / "it's.wav").replace("'", "'\\''")
    )
