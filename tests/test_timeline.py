# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

from tts_engine import build_sentence_timeline


class TimelineTests(unittest.TestCase):
    def test_builds_timeline_directly_from_sentence_boundaries(self):
        payload = build_sentence_timeline(
            [
                {
                    "text": "First sentence.",
                    "offset": 500000,
                    "duration": 12500000,
                },
                {
                    "text": "Second sentence!",
                    "offset": 13000000,
                    "duration": 20000000,
                },
            ],
            "en-US-AndrewMultilingualNeural",
            "+0%",
        )

        self.assertEqual(payload["boundary"], "SentenceBoundary")
        self.assertEqual(payload["sentences"][0]["start"], 0.05)
        self.assertEqual(payload["sentences"][0]["end"], 1.3)
        self.assertEqual(payload["sentences"][1]["start"], 1.3)
        self.assertEqual(payload["sentences"][1]["end"], 3.3)
        self.assertEqual(payload["sentences"][1]["text"], "Second sentence!")

    def test_rejects_invalid_sentence_boundary(self):
        with self.assertRaises(RuntimeError):
            build_sentence_timeline(
                [{"text": "Missing duration.", "offset": 500000}],
                "en-US-AndrewMultilingualNeural",
                "+0%",
            )


if __name__ == "__main__":
    unittest.main()
