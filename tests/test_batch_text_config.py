# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

from batch_text_config import (
    build_tts_header,
    build_voice_alias_index,
    parse_tts_header,
    resolve_voice_alias,
    sanitize_filename_stem,
)


class BatchTextConfigTests(unittest.TestCase):
    def test_parses_canonical_header_and_removes_it(self):
        parsed = parse_tts_header(
            "{tts:Ana|pause=200ms|marks=,.!?|srt=1|json=1|"
            "rate=+10%|volume=-5%|pitch=+2Hz}\n"
            "第一句。\n第二句。"
        )

        self.assertEqual(parsed.text, "第一句。\n第二句。")
        self.assertEqual(parsed.options["voice"], "Ana")
        self.assertEqual(parsed.options["sentence_pause_ms"], 200)
        self.assertEqual(parsed.options["sentence_pause_marks"], ",.!?")
        self.assertTrue(parsed.options["srt_enabled"])
        self.assertTrue(parsed.options["timeline_enabled"])
        self.assertEqual(parsed.options["rate"], "+10%")
        self.assertEqual(parsed.options["volume"], "-5%")
        self.assertEqual(parsed.options["pitch"], "+2Hz")

    def test_line_pause_is_not_a_normal_batch_rule(self):
        parsed = parse_tts_header("{tts:Ana|line=300ms|srt=1}\nHello")

        self.assertEqual(parsed.text, "Hello")
        self.assertNotIn("line_pause_ms", parsed.options)
        self.assertTrue(parsed.options["srt_enabled"])
        self.assertTrue(any("line" in warning for warning in parsed.warnings))

    def test_parses_compact_header(self):
        parsed = parse_tts_header("{Abeo|200ms{,.~}|srt}\nHello")

        self.assertEqual(parsed.text, "Hello")
        self.assertEqual(parsed.options["voice"], "Abeo")
        self.assertEqual(parsed.options["sentence_pause_ms"], 200)
        self.assertEqual(parsed.options["sentence_pause_marks"], ",.~")
        self.assertTrue(parsed.options["srt_enabled"])

    def test_parses_inline_header_and_keeps_same_line_text(self):
        parsed = parse_tts_header(
            "{tts:Nanami|srt=1|json=1|rate=+0%|volume=+0%|pitch=+0Hz}"
            "Every time he stays at a hotel he puts a glass on the door handle"
        )

        self.assertEqual(
            parsed.text,
            "Every time he stays at a hotel he puts a glass on the door handle",
        )
        self.assertEqual(parsed.options["voice"], "Nanami")
        self.assertTrue(parsed.options["srt_enabled"])
        self.assertTrue(parsed.options["timeline_enabled"])

    def test_parses_inline_compact_header_with_nested_marks(self):
        parsed = parse_tts_header("{Abeo|200ms{,.~}|srt}Hello")

        self.assertEqual(parsed.text, "Hello")
        self.assertEqual(parsed.options["voice"], "Abeo")
        self.assertEqual(parsed.options["sentence_pause_ms"], 200)
        self.assertEqual(parsed.options["sentence_pause_marks"], ",.~")

    def test_parses_bare_switch_headers(self):
        srt = parse_tts_header("{srt}\nHello")
        timeline = parse_tts_header("{json}\nHello")
        combined = parse_tts_header("{srt|json}\nHello")

        self.assertEqual(srt.text, "Hello")
        self.assertTrue(srt.options["srt_enabled"])
        self.assertEqual(timeline.text, "Hello")
        self.assertTrue(timeline.options["timeline_enabled"])
        self.assertTrue(combined.options["srt_enabled"])
        self.assertTrue(combined.options["timeline_enabled"])

    def test_normal_text_starting_with_braces_is_not_removed(self):
        parsed = parse_tts_header("{hello}\nNot a configuration header.")

        self.assertEqual(parsed.text, "{hello}\nNot a configuration header.")
        self.assertEqual(parsed.options, {})

        inline = parse_tts_header("{hello} Not a configuration header.")
        self.assertEqual(inline.text, "{hello} Not a configuration header.")
        self.assertEqual(inline.options, {})

    def test_builds_copyable_header(self):
        header = build_tts_header(
            "Jeppe",
            sentence_pause_ms=200,
            sentence_pause_marks=",.~",
            srt_enabled=True,
            timeline_enabled=True,
            rate="+10",
            volume="-5%",
            pitch="2",
        )

        self.assertEqual(
            header,
            "{tts:Jeppe|pause=200ms|marks=,.~|srt=1|json=1|"
            "rate=+10%|volume=-5%|pitch=+2Hz}",
        )

    def test_omits_marks_when_sentence_pause_is_disabled(self):
        header = build_tts_header(
            "Ana",
            sentence_pause_ms=0,
            sentence_pause_marks=",.!?",
            srt_enabled=True,
        )

        self.assertEqual(
            header,
            "{tts:Ana|srt=1|json=0|rate=+0%|volume=+0%|pitch=+0Hz}",
        )
        self.assertNotIn("pause=", header)
        self.assertNotIn("marks=", header)

    def test_resolves_voice_aliases(self):
        voices = [
            {"ShortName": "en-US-AnaNeural", "Locale": "en-US"},
            {"ShortName": "da-DK-JeppeNeural", "Locale": "da-DK"},
        ]
        aliases = build_voice_alias_index(voices)

        self.assertEqual(resolve_voice_alias("ana", aliases)[0], "en-US-AnaNeural")
        self.assertEqual(resolve_voice_alias("Jeppe", aliases)[0], "da-DK-JeppeNeural")
        self.assertEqual(
            resolve_voice_alias("en-US-AnaNeural", aliases, set(aliases.values()))[0],
            "en-US-AnaNeural",
        )

    def test_sanitizes_windows_filenames(self):
        self.assertEqual(sanitize_filename_stem('a<b>:"/\\|?*'), "a_b________")
        self.assertEqual(sanitize_filename_stem("   "), "audio")


if __name__ == "__main__":
    unittest.main()
