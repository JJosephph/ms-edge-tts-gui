import math
import tempfile
import unittest
from pathlib import Path

import lameenc
import miniaudio

from tts_engine import insert_sentence_pauses, timeline_to_srt


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
        self.assertEqual(adjusted["sentences"][1]["start"], 0.8)
        self.assertEqual(adjusted["sentences"][1]["end"], 1.2)
        self.assertGreater(after - before, 0.2)


if __name__ == "__main__":
    unittest.main()
