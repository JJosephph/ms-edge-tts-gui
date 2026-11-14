# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

from voice_catalog import (
    MULTILINGUAL_VOICES,
    chinese_voice_group,
    merge_voice_catalog,
)
from voice_groups import GENDER_FEMALE, GENDER_MALE, VoiceGroupingEngine


def voice(code, locale, gender="Female"):
    return {
        "ShortName": code,
        "Locale": locale,
        "Gender": gender,
        "FriendlyName": f"Microsoft {code} Online (Natural)",
    }


class VoiceCatalogTests(unittest.TestCase):
    def test_regional_chinese_voices_join_the_zh_group(self):
        self.assertEqual(
            chinese_voice_group("zh-CN-liaoning", "zh-CN-liaoning-XiaobeiNeural"),
            "zh",
        )
        self.assertEqual(
            chinese_voice_group("zh-CN-shaanxi", "zh-CN-shaanxi-XiaoniNeural"),
            "zh",
        )
        self.assertEqual(chinese_voice_group("zh-HK", "zh-HK-HiuMaanNeural"), "zh")

    def test_multilingual_voices_are_grouped_under_chinese(self):
        for code, _name in MULTILINGUAL_VOICES:
            self.assertEqual(chinese_voice_group("en-US", code), "zh", code)

    def test_regular_english_voice_stays_in_english_group(self):
        self.assertEqual(chinese_voice_group("en-US", "en-US-GuyNeural"), "en")
        self.assertEqual(chinese_voice_group("ja-JP", "ja-JP-NanamiNeural"), "ja")

    def test_merge_preserves_edge_locale_and_does_not_duplicate(self):
        original = [
            voice("zh-CN-XiaoxiaoNeural", "zh-CN"),
            voice("zh-CN-liaoning-XiaobeiNeural", "zh-CN-liaoning"),
            voice("en-US-AndrewMultilingualNeural", "en-US", GENDER_MALE),
            voice("zh-CN-XiaoxiaoNeural", "zh-CN"),
        ]

        merged = merge_voice_catalog(original)

        self.assertEqual(len(merged), 3)
        by_code = {item["ShortName"]: item for item in merged}
        self.assertEqual(
            by_code["zh-CN-liaoning-XiaobeiNeural"]["EdgeLocale"],
            "zh-CN-liaoning",
        )
        self.assertEqual(
            by_code["zh-CN-liaoning-XiaobeiNeural"]["Locale"], "zh-CN-liaoning"
        )
        self.assertEqual(
            by_code["en-US-AndrewMultilingualNeural"]["Locale"], "en-US"
        )
        self.assertEqual(
            by_code["en-US-AndrewMultilingualNeural"]["EdgeLocale"], "en-US"
        )
        self.assertEqual(
            by_code["en-US-AndrewMultilingualNeural"]["VoiceGroups"],
            ["en", "zh"],
        )

    def test_engine_returns_chinese_dialects_and_multilingual_voices(self):
        voices = [
            voice("zh-CN-XiaoxiaoNeural", "zh-CN"),
            voice("zh-CN-liaoning-XiaobeiNeural", "zh-CN-liaoning"),
            voice("zh-CN-shaanxi-XiaoniNeural", "zh-CN-shaanxi"),
            voice("en-US-AndrewMultilingualNeural", "en-US", GENDER_MALE),
            voice("en-US-GuyNeural", "en-US", GENDER_MALE),
        ]

        engine = VoiceGroupingEngine(voices)
        codes = {item["ShortName"] for item in engine.voices("zh")}

        self.assertEqual(
            codes,
            {
                "zh-CN-XiaoxiaoNeural",
                "zh-CN-liaoning-XiaobeiNeural",
                "zh-CN-shaanxi-XiaoniNeural",
                "en-US-AndrewMultilingualNeural",
            },
        )
        self.assertIn(GENDER_FEMALE, engine.genders("zh"))
        self.assertIn(GENDER_MALE, engine.genders("zh"))
        self.assertNotIn(
            "en-US-GuyNeural", {item["ShortName"] for item in engine.voices("zh")}
        )
        # Multilingual voices also remain in their native language picker.
        self.assertIn(
            "en-US-AndrewMultilingualNeural",
            {item["ShortName"] for item in engine.voices("en")},
        )


if __name__ == "__main__":
    unittest.main()
