import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tts_engine
from tts_engine import TTSConfig, TTSEngine


class _HandshakeError(Exception):
    """模拟 aiohttp 的 WSServerHandshakeError：只带 status 属性。"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class _RateLimitedCommunicate:
    """每次请求都返回 429，模拟服务端限流。"""

    def __init__(self, *args, **kwargs):
        pass

    async def stream(self):
        if False:
            yield None
        raise _HandshakeError(429, "429, message='Invalid response status'")


class _SegmentedCommunicate:
    """记录每次请求的文本，返回 0.1s 句边界 + 固定长度音频。"""

    instances = []
    audio_chunk = b"\xff\xfb\x90\x00" * 100

    def __init__(self, *, text, **kwargs):
        self.text = text
        _SegmentedCommunicate.instances.append(self)

    async def stream(self):
        yield {
            "type": "SentenceBoundary",
            "text": "句子。",
            "offset": 0,
            "duration": 1_000_000,
        }
        yield {"type": "audio", "data": self.audio_chunk}


class SplitTextTests(unittest.TestCase):
    def test_short_text_is_one_segment(self):
        self.assertEqual(tts_engine.split_text_for_synthesis("你好，世界。"), ["你好，世界。"])

    def test_long_chinese_without_spaces_is_bounded(self):
        text = "这是一段没有任何空格和换行的中文内容。" * 900
        self.assertGreater(len(text.encode("utf-8")), tts_engine.SYNTH_SEGMENT_MAX_BYTES)
        segments = tts_engine.split_text_for_synthesis(text)
        self.assertGreater(len(segments), 1)
        for segment in segments:
            self.assertLessEqual(
                len(segment.encode("utf-8")), tts_engine.SYNTH_SEGMENT_MAX_BYTES
            )
        # 不能丢字符，否则基于原文的边界对齐会错位。
        self.assertEqual("".join(segments), text)

    def test_long_text_without_any_punctuation_still_splits(self):
        text = "中" * 4000
        segments = tts_engine.split_text_for_synthesis(text)
        self.assertGreater(len(segments), 1)
        self.assertEqual("".join(segments), text)
        for segment in segments:
            self.assertLessEqual(
                len(segment.encode("utf-8")), tts_engine.SYNTH_SEGMENT_MAX_BYTES
            )

    def test_english_text_splits_on_spaces(self):
        text = "hello world " * 800
        segments = tts_engine.split_text_for_synthesis(text)
        self.assertGreater(len(segments), 1)
        self.assertEqual("".join(segments), text)
        for segment in segments:
            self.assertLessEqual(
                len(segment.encode("utf-8")), tts_engine.SYNTH_SEGMENT_MAX_BYTES
            )


class HttpStatusTests(unittest.TestCase):
    def test_reads_status_attribute(self):
        self.assertEqual(
            tts_engine.http_status_from_exception(_HandshakeError(429, "x")), 429
        )

    def test_reads_status_from_message_text(self):
        exc = RuntimeError("429, message='Invalid response status'")
        self.assertEqual(tts_engine.http_status_from_exception(exc), 429)

    def test_reads_status_from_wrapped_cause(self):
        inner = _HandshakeError(500, "500, message='Invalid response status'")
        outer = RuntimeError("synthesis failed")
        outer.__cause__ = inner
        self.assertEqual(tts_engine.http_status_from_exception(outer), 500)

    def test_network_error_has_no_status(self):
        self.assertIsNone(
            tts_engine.http_status_from_exception(
                RuntimeError("Cannot connect to host: Connection refused")
            )
        )

    def test_plain_number_in_message_is_not_a_status(self):
        self.assertIsNone(tts_engine.http_status_from_exception(RuntimeError("retry 3 times")))


class ErrorClassificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = TTSEngine()

    def test_rate_limit_is_not_reported_as_network_problem(self):
        hint = self.engine._classify_error(
            _HandshakeError(429, "429, message='Invalid response status'")
        )
        self.assertEqual(hint, tts_engine.RATE_LIMIT_HINT)
        self.assertNotIn("代理设置不正确", hint)
        self.assertIn("不是本地网络或代理问题", hint)
        self.assertIn("429", hint)

    def test_server_error_is_not_reported_as_network_problem(self):
        hint = self.engine._classify_error(_HandshakeError(503, "503"))
        self.assertEqual(hint, tts_engine.SERVER_BUSY_HINT)
        self.assertNotIn("代理设置不正确", hint)

    def test_403_keeps_service_rejection_message(self):
        hint = self.engine._classify_error(
            _HandshakeError(403, "403, message='Invalid response status'")
        )
        self.assertEqual(hint, tts_engine.SERVICE_REJECTION_MESSAGE)

    def test_real_network_failure_still_mentions_proxy(self):
        hint = self.engine._classify_error(
            RuntimeError("Cannot connect to host api.example.com: Connection refused")
        )
        self.assertIn("代理", hint)


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.engine = TTSEngine()

    def test_rate_limit_backoff_is_longer_than_default(self):
        limited = self.engine._retry_delay(1, 429)
        normal = self.engine._retry_delay(1, None)
        self.assertGreaterEqual(limited, tts_engine.RATE_LIMIT_RETRY_BASE_DELAY)
        self.assertGreater(limited, normal)

    def test_backoff_is_capped_and_jittered(self):
        for attempt in (1, 2, 3, 4, 5):
            delay = self.engine._retry_delay(attempt, 429)
            self.assertLessEqual(
                delay,
                tts_engine.RATE_LIMIT_RETRY_MAX_DELAY
                * (1 + tts_engine.RETRY_JITTER_RATIO),
            )
        # 抖动让同一尝试的等待时间不是一个固定值。
        samples = {round(self.engine._retry_delay(1, 429), 6) for _ in range(20)}
        self.assertGreater(len(samples), 1)

    def test_final_failure_message_explains_rate_limit(self):
        message = TTSEngine._final_failure_message(429)
        self.assertIn("429", message)
        self.assertIn("限流", message)
        self.assertNotIn("代理设置不正确", message)

    def test_final_failure_message_keeps_network_hint_when_unknown(self):
        message = TTSEngine._final_failure_message(None)
        self.assertIn("网络", message)


class SegmentedStreamingTests(unittest.TestCase):
    def test_offsets_are_compensated_across_segments(self):
        _SegmentedCommunicate.instances = []
        engine = TTSEngine()
        text = "中文测试内容。" * 900
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _SegmentedCommunicate):
                outcome = asyncio.run(engine._stream_once(text, output, TTSConfig()))

        self.assertEqual(outcome, "done")
        segments = _SegmentedCommunicate.instances
        self.assertGreater(len(segments), 1)
        for instance in segments:
            self.assertLessEqual(
                len(instance.text.encode("utf-8")),
                tts_engine.SYNTH_SEGMENT_MAX_BYTES,
            )
        self.assertEqual("".join(item.text for item in segments), text)

        offsets = [boundary["offset"] for boundary in engine.sentence_boundaries]
        self.assertEqual(len(offsets), len(segments))
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(offsets[0], 0)
        step = (
            len(_SegmentedCommunicate.audio_chunk)
            * 8
            * tts_engine.EDGE_TICKS_PER_SECOND
            // tts_engine.EDGE_MP3_BITRATE_BPS
        )
        self.assertEqual(offsets[1], step)

    def test_single_segment_keeps_offsets_untouched(self):
        _SegmentedCommunicate.instances = []
        engine = TTSEngine()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _SegmentedCommunicate):
                outcome = asyncio.run(
                    engine._stream_once("你好，世界。", output, TTSConfig())
                )

        self.assertEqual(outcome, "done")
        self.assertEqual(len(_SegmentedCommunicate.instances), 1)
        self.assertEqual(engine.sentence_boundaries[0]["offset"], 0)


class GenerateRetryTests(unittest.TestCase):
    def test_rate_limited_generation_reports_http_status(self):
        engine = TTSEngine()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _RateLimitedCommunicate), patch.multiple(
                tts_engine,
                MAX_RETRIES=2,
                STALL_AUTO_RETRIES=0,
                RETRY_BASE_DELAY=0.0,
                RATE_LIMIT_RETRY_BASE_DELAY=0.0,
            ):
                result = asyncio.run(engine._generate_async("hello", output, TTSConfig()))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("http_status"), 429)
        self.assertIn("429", result["error"])


if __name__ == "__main__":
    unittest.main()
