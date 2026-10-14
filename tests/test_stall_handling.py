import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import tts_engine
from edge_tts import communicate as edge_tts_communicate
from tts_engine import TTSConfig, TTSEngine


class _FailingCommunicate:
    def __init__(self, *args, **kwargs):
        pass

    async def stream(self):
        if False:
            yield None
        await asyncio.sleep(0.02)
        raise RuntimeError("simulated receive timeout")


class _SilentCommunicate:
    """连接建立后没有任何数据返回，模拟服务端限流。"""

    def __init__(self, *args, **kwargs):
        pass

    async def stream(self):
        if False:
            yield None
        await asyncio.sleep(30)
        yield {"type": "audio", "data": b"never"}


class _SuccessfulCommunicate:
    """一次成功的最小合成：一句边界 + 一段音频数据。"""

    def __init__(self, *args, **kwargs):
        pass

    async def stream(self):
        yield {
            "type": "SentenceBoundary",
            "text": "Hello world.",
            "offset": 0,
            "duration": 10_000_000,
        }
        yield {"type": "audio", "data": b"\xff\xfb\x90\x00" * 64}


class _ForbiddenCommunicate:
    def __init__(self, *args, **kwargs):
        pass

    async def stream(self):
        if False:
            yield None
        raise RuntimeError("403, message='Invalid response status'")


class _RecordingController:
    def __init__(self, first_decision, first_delay=0.0):
        self._first_decision = first_decision
        self._first_delay = first_delay
        self._lock = threading.Lock()
        self.ask_times = []
        self.return_times = []
        self.calls = 0

    def ask(self, _message):
        with self._lock:
            self.calls += 1
            call_number = self.calls
            self.ask_times.append(time.perf_counter())
        if call_number == 1:
            if self._first_delay:
                time.sleep(self._first_delay)
            with self._lock:
                self.return_times.append(time.perf_counter())
            return self._first_decision
        return "cancel"


class StallHandlingTests(unittest.TestCase):
    def test_uses_edge_155_synthesis_endpoint_for_legacy_edge_tts(self):
        original_url = edge_tts_communicate.WSS_URL
        try:
            edge_tts_communicate.WSS_URL = (
                "wss://speech.platform.bing.com/consumer/speech/synthesize/"
                "readaloud/edge/v1?TrustedClientToken=legacy"
            )
            tts_engine.configure_edge_tts_endpoint()
            self.assertIn("api.msedgeservices.com", edge_tts_communicate.WSS_URL)
            self.assertIn("Ocp-Apim-Subscription-Key", edge_tts_communicate.WSS_URL)
        finally:
            edge_tts_communicate.WSS_URL = original_url

    def test_service_rejection_does_not_show_stall_prompt(self):
        controller = _RecordingController("continue")
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _ForbiddenCommunicate):
                outcome = asyncio.run(
                    engine._stream_once("hello", output, TTSConfig())
                )

        self.assertEqual(outcome, "error")
        self.assertEqual(controller.calls, 0)
        self.assertIn("403", engine.error_message)

    def test_continue_waiting_restarts_grace_before_reporting_stream_failure(self):
        controller = _RecordingController("continue", first_delay=0.03)
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _FailingCommunicate), patch.multiple(
                tts_engine,
                STALL_AUTO_RETRIES=0,
                STALL_TIMEOUT=0.005,
                STALL_FIRST_AUDIO_TIMEOUT=0.005,
                STALL_WAIT_GRACE=0.06,
                STALL_SILENT_POLL=0.005,
                RECEIVE_TIMEOUT=1,
            ):
                outcome = asyncio.run(
                    engine._stream_once("hello", output, TTSConfig())
                )

        self.assertEqual(outcome, "cancel")
        self.assertEqual(controller.calls, 2)
        self.assertGreaterEqual(
            controller.ask_times[1] - controller.return_times[0],
            0.045,
        )

    def test_dont_remind_suppresses_followup_prompt(self):
        controller = _RecordingController("continue_silent")
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _FailingCommunicate), patch.multiple(
                tts_engine,
                STALL_AUTO_RETRIES=0,
                STALL_TIMEOUT=0.005,
                STALL_FIRST_AUDIO_TIMEOUT=0.005,
                STALL_WAIT_GRACE=0.06,
                STALL_SILENT_POLL=0.005,
                RECEIVE_TIMEOUT=1,
            ):
                outcome = asyncio.run(
                    engine._stream_once("hello", output, TTSConfig())
                )

        self.assertEqual(outcome, "retry")
        self.assertEqual(controller.calls, 1)

    def test_transient_failure_auto_retries_before_prompting(self):
        controller = _RecordingController("cancel")
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _FailingCommunicate), patch.multiple(
                tts_engine,
                STALL_AUTO_RETRIES=1,
                RECEIVE_TIMEOUT=1,
            ):
                first = asyncio.run(engine._stream_once("hello", output, TTSConfig()))
                second = asyncio.run(engine._stream_once("hello", output, TTSConfig()))

        # 第一次失败静默自动重试，不再打扰用户；额度用完后才弹窗。
        self.assertEqual(first, "retry")
        self.assertEqual(second, "cancel")
        self.assertEqual(controller.calls, 1)

    def test_silent_stream_auto_retries_before_prompting(self):
        controller = _RecordingController("cancel")
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _SilentCommunicate), patch.multiple(
                tts_engine,
                STALL_AUTO_RETRIES=1,
                STALL_TIMEOUT=0.01,
                STALL_FIRST_AUDIO_TIMEOUT=0.01,
                RECEIVE_TIMEOUT=1,
            ):
                # 连上后一直没有数据：先自动重试一次，不弹窗。
                first = asyncio.run(engine._stream_once("hello", output, TTSConfig()))
                self.assertEqual(first, "retry")
                self.assertEqual(controller.calls, 0)
                # 自动重试额度用完后才询问用户。
                second = asyncio.run(engine._stream_once("hello", output, TTSConfig()))

        self.assertEqual(second, "cancel")
        self.assertEqual(controller.calls, 1)

    def test_recreates_missing_output_directory_before_streaming(self):
        """缓存目录被清理后，生成应该自动补建目录而不是报错。"""
        engine = TTSEngine()

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "removed-cache" / "preview.mp3"
            self.assertFalse(output.parent.exists())
            with patch("tts_engine.edge_tts.Communicate", _SuccessfulCommunicate):
                outcome = asyncio.run(
                    engine._stream_once("hello world", output, TTSConfig())
                )

            self.assertEqual(outcome, "done")
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
