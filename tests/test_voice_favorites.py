# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

from voice_favorites import (
    clamp_panel_width,
    filter_favorites,
    normalize_favorites,
    toggle_favorite,
)


class VoiceFavoriteTests(unittest.TestCase):
    def test_corrupt_settings_do_not_break_the_picker(self):
        self.assertEqual(normalize_favorites(None), [])
        self.assertEqual(normalize_favorites("zf_047"), [])

    def test_saved_codes_are_trimmed_unique_and_ordered(self):
        self.assertEqual(
            normalize_favorites([" zf_047 ", "zf_047", "", None, "en-US-GuyNeural"]),
            ["zf_047", "en-US-GuyNeural"],
        )

    def test_toggle_adds_then_removes_without_reordering(self):
        saved = toggle_favorite(["zf_047", "en-US-GuyNeural"], "zm_055")
        self.assertEqual(saved, ["zf_047", "en-US-GuyNeural", "zm_055"])
        self.assertEqual(
            toggle_favorite(saved, "en-US-GuyNeural"),
            ["zf_047", "zm_055"],
        )

    def test_empty_or_corrupt_code_is_ignored(self):
        self.assertEqual(toggle_favorite(["zf_047"], ""), ["zf_047"])
        self.assertEqual(toggle_favorite(["zf_047"], "   "), ["zf_047"])
        self.assertEqual(toggle_favorite(None, "zf_047"), ["zf_047"])

    def test_favorites_are_limited_to_the_active_provider(self):
        saved = ["zf_047", "en-US-GuyNeural", "zh-CN-XiaoxiaoNeural"]

        self.assertEqual(
            filter_favorites(saved, {"zf_047", "zm_055"}),
            ["zf_047"],
        )
        self.assertEqual(
            filter_favorites(saved, {"en-US-GuyNeural", "zh-CN-XiaoxiaoNeural"}),
            ["en-US-GuyNeural", "zh-CN-XiaoxiaoNeural"],
        )
        self.assertEqual(filter_favorites(None, {"zf_047"}), [])

    def test_panel_width_stays_in_bounds(self):
        self.assertEqual(clamp_panel_width(375, 1100, 320, 560), 375)
        self.assertEqual(clamp_panel_width("bad", 1100, 320, 560), 560)
        self.assertEqual(clamp_panel_width(120, 1100, 320, 560), 320)
        self.assertEqual(clamp_panel_width(900, 1100, 320, 560), 560)
        # A narrow window caps the panel so the composer keeps usable space.
        self.assertLessEqual(clamp_panel_width(560, 800, 320, 560), 496)


if __name__ == "__main__":
    unittest.main()
