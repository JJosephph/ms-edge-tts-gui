import math
import tempfile
import unittest
from pathlib import Path

import lameenc
import miniaudio

from tts_engine import (
    append_audio_silence,
    audio_duration_seconds,
    build_sentence_timeline_from_word_boundaries,
    fill_subtitle_gaps,
    insert_sentence_pause_directives,
    insert_sentence_pauses,
    line_end_sentence_indices,
    parse_pause_directives,
    split_reading_sentences,
    timeline_to_srt,
    validate_pause_ms,
)


def _write_test_mp3(path: Path, duration_seconds: float = 1.2) -> None:
    sample_rate = 24000
    sample_count = round(sample_rate * duration_seconds)
    pcm = bytearray()
    for index in range(sample_count):
        sample = int(5000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        pcm.extend(sample.to_bytes(2, byteorder="little", signed=True))
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(48)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    path.write_bytes(encoder.encode(bytes(pcm)) + encoder.flush())


class SubtitleTests(unittest.TestCase):
    def test_pause_below_supported_mp3_range_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_pause_ms(1)
        with self.assertRaises(ValueError):
            validate_pause_ms(49)
        self.assertEqual(validate_pause_ms(50), 50)

    def test_minimum_line_pause_is_kept_in_logical_timeline_and_reports_audio_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.mp3"
            _write_test_mp3(path, duration_seconds=1.0)
            timeline = {"sentences": [{"start": 0.0, "end": 1.0, "text": "One."}]}

            adjusted = append_audio_silence(str(path), timeline, 50)
            measured = audio_duration_seconds(str(path))

        self.assertEqual(adjusted["duration_padding_ms"], 50)
        self.assertAlmostEqual(adjusted["duration"], 1.05, places=3)
        self.assertGreater(adjusted["audio_duration"], 1.0)
        self.assertAlmostEqual(adjusted["audio_duration"], measured, places=3)

    def test_word_boundaries_use_real_word_ends_for_pause_timeline(self):
        payload = build_sentence_timeline_from_word_boundaries(
            "First line.\nSecond line.",
            [
                {"text": "First", "offset": 100000, "duration": 2000000},
                {"text": "line", "offset": 2500000, "duration": 1500000},
                {"text": "Second", "offset": 5000000, "duration": 2200000},
                {"text": "line", "offset": 7600000, "duration": 1400000},
            ],
            "en-US-GuyNeural",
            "+18%",
        )

        self.assertEqual(payload["boundary"], "WordBoundary")
        self.assertEqual(payload["sentences"][0]["start"], 0.01)
        self.assertEqual(payload["sentences"][0]["end"], 0.4)
        self.assertEqual(payload["sentences"][1]["start"], 0.5)
        self.assertEqual(payload["sentences"][1]["end"], 0.9)

    def test_line_end_indexes_include_multiple_sentences_per_line(self):
        self.assertEqual(
            line_end_sentence_indices("One. Two.\nThree\nFour. Five."),
            [1, 2, 4],
        )
        self.assertEqual(
            line_end_sentence_indices("One. ...\nTwo."),
            [0, 1],
        )

    def test_word_boundary_mismatch_is_rejected_instead_of_shifted(self):
        with self.assertRaises(RuntimeError):
            build_sentence_timeline_from_word_boundaries(
                "First line.\nSecond line.",
                [
                    {"text": "First", "offset": 0, "duration": 1000000},
                    {"text": "line", "offset": 1000000, "duration": 1000000},
                    {"text": "unexpected", "offset": 2000000, "duration": 1000000},
                ],
                "en-US-GuyNeural",
                "+18%",
            )

    def test_decimal_points_do_not_split_reading_sentences(self):
        text = "川西红枫岭、49.9、金秋枫韵双人景区门票加穿越丛林加徒步线"
        self.assertEqual(split_reading_sentences(text), [text])

        text = "版本 v1.6.2、价格 27.01 元。下一句。"
        self.assertEqual(
            split_reading_sentences(text),
            ["版本 v1.6.2、价格 27.01 元。", "下一句。"],
        )

    def test_decimal_text_maps_word_boundaries_without_shifting(self):
        payload = build_sentence_timeline_from_word_boundaries(
            "价格 49.9 元。",
            [
                {"text": "价格", "offset": 0, "duration": 1000000},
                {"text": "49.9", "offset": 1000000, "duration": 1000000},
                {"text": "元", "offset": 2000000, "duration": 1000000},
            ],
            "zh-CN-XiaoyiNeural",
            "+0%",
        )
        self.assertEqual(len(payload["sentences"]), 1)
        self.assertEqual(payload["sentences"][0]["end"], 0.3)

    def test_formats_sentence_timeline_as_srt(self):
        srt = timeline_to_srt(
            {
                "sentences": [
                    {"start": 0.05, "end": 1.3, "text": "First sentence."},
                    {"start": 61.001, "end": 62.25, "text": "Second sentence!"},
                ]
            }
        )

        self.assertEqual(
            srt,
            "1\n00:00:00,050 --> 00:00:01,300\nFirst sentence.\n\n"
            "2\n00:01:01,001 --> 00:01:02,250\nSecond sentence!\n",
        )

    def test_fill_gaps_removes_line_pause_holes_from_subtitles(self):
        timeline = {
            "sentences": [
                {"index": 0, "start": 0.0, "end": 0.4, "text": "First line."},
                {"index": 1, "start": 0.5, "end": 0.9, "text": "Second line."},
            ],
            "duration": 0.95,
            "line_pause_ms": 100,
        }

        # Default export keeps every real pause visible.
        self.assertIn(
            "00:00:00,000 --> 00:00:00,400",
            timeline_to_srt(timeline),
        )

        filled = timeline_to_srt(timeline, fill_gaps=True)

        self.assertIn("00:00:00,000 --> 00:00:00,500", filled)
        # The last cue covers the requested tail pause as well.
        self.assertIn("00:00:00,500 --> 00:00:00,950", filled)

    def test_fill_gaps_leaves_the_source_timeline_untouched(self):
        timeline = {
            "sentences": [
                {"index": 0, "start": 0.0, "end": 0.4, "text": "One."},
                {"index": 1, "start": 0.7, "end": 1.0, "text": "Two."},
            ],
            "duration": 1.3,
        }

        filled = fill_subtitle_gaps(timeline)

        self.assertEqual(filled["sentences"][0]["end"], 0.7)
        self.assertEqual(filled["sentences"][1]["end"], 1.3)
        # Timeline JSON keeps the exact audio timings.
        self.assertEqual(timeline["sentences"][0]["end"], 0.4)
        self.assertEqual(timeline["sentences"][1]["end"], 1.0)

    def test_fill_gaps_never_invents_a_trailing_cue_end(self):
        timeline = {
            "sentences": [
                {"index": 0, "start": 0.0, "end": 0.4, "text": "One."},
                {"index": 1, "start": 0.5, "end": 0.9, "text": "Two."},
            ]
        }

        filled = timeline_to_srt(timeline, fill_gaps=True)

        self.assertIn("00:00:00,000 --> 00:00:00,500", filled)
        self.assertIn("00:00:00,500 --> 00:00:00,900", filled)

    def test_inserts_pause_and_shifts_later_cues(self):
        timeline = {
            "sentences": [
                {"index": 0, "start": 0.0, "end": 0.4, "text": "One."},
                {"index": 1, "start": 0.5, "end": 0.9, "text": "Two."},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.mp3"
            _write_test_mp3(path)
            before = miniaudio.get_file_info(str(path)).duration

            adjusted = insert_sentence_pauses(str(path), timeline, 300)

            after = miniaudio.get_file_info(str(path)).duration

        self.assertEqual(adjusted["sentence_pause_ms"], 300)
        self.assertEqual(adjusted["sentences"][0]["start"], 0.0)
        self.assertEqual(adjusted["sentences"][1]["start"], 0.7)
        self.assertEqual(adjusted["sentences"][1]["end"], 1.1)
        self.assertGreater(after - before, 0.1)

    def test_inserts_pause_with_unicode_output_path(self):
        timeline = {
            "sentences": [
                {"index": 0, "start": 0.0, "end": 0.4, "text": "One."},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "测试-副本.mp3"
            _write_test_mp3(path)

            adjusted = insert_sentence_pauses(
                str(path),
                timeline,
                0,
                tail_pause_ms=50,
            )

        self.assertEqual(adjusted["duration_padding_ms"], 50)

    def test_inline_pause_directives_are_removed_and_mapped(self):
        spoken, overrides = parse_pause_directives(
            "第一句。[pause:500ms]第二句。[pause:1.5s]第三句。"
        )
        self.assertEqual(spoken, "第一句。第二句。第三句。")
        self.assertEqual(overrides, {0: 500, 1: 1500})

    def test_pause_directive_presets_and_bare_marker(self):
        spoken, overrides = parse_pause_directives(
            "第一句。[pause:weak]第二句。[pause]第三句。"
        )
        self.assertEqual(spoken, "第一句。第二句。第三句。")
        self.assertEqual(overrides, {0: 100, 1: 300})

    def test_auto_inserts_markers_before_final_sentence(self):
        text = "第一句。第二句！第三句？"
        updated = insert_sentence_pause_directives(text, 200)
        self.assertEqual(
            updated,
            "第一句。 [pause:200ms]第二句！ [pause:200ms]第三句？",
        )

    def test_auto_inserts_markers_between_plain_text_lines(self):
        updated = insert_sentence_pause_directives("第一行\n第二行\n第三行", 150)
        self.assertEqual(
            updated,
            "第一行 [pause:150ms]\n第二行 [pause:150ms]\n第三行",
        )

    def test_inline_override_replaces_only_tagged_gap(self):
        timeline = {
            "sentences": [
                {"index": 0, "start": 0.0, "end": 0.4, "text": "One."},
                {"index": 1, "start": 0.5, "end": 0.9, "text": "Two."},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.mp3"
            _write_test_mp3(path)
            adjusted = insert_sentence_pauses(
                str(path), timeline, 0, pause_overrides={0: 200}
            )
        self.assertEqual(adjusted["sentences"][1]["start"], 0.6)
        self.assertEqual(adjusted["sentence_pause_overrides"], {0: 200})

    def test_zero_override_removes_native_gap(self):
        timeline = {
            "sentences": [
                {"index": 0, "start": 0.0, "end": 0.4, "text": "One."},
                {"index": 1, "start": 0.7, "end": 1.1, "text": "Two."},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.mp3"
            _write_test_mp3(path, duration_seconds=1.2)
            adjusted = insert_sentence_pauses(
                str(path), timeline, 0, pause_overrides={0: 0}
            )
        self.assertEqual(adjusted["sentences"][1]["start"], 0.4)

    def test_pause_timeline_does_not_keep_overlapping_native_boundary(self):
        timeline = {
            "sentences": [
                {"index": 0, "start": 0.1, "end": 1.675, "text": "One."},
                {"index": 1, "start": 1.625, "end": 3.2, "text": "Two."},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.mp3"
            _write_test_mp3(path, duration_seconds=4.0)
            adjusted = insert_sentence_pauses(str(path), timeline, 200)
        self.assertEqual(adjusted["sentences"][1]["start"], 1.875)


if __name__ == "__main__":
    unittest.main()
