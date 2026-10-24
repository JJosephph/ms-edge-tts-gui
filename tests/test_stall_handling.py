# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import tts_engine
from edge_tts import communicate as edge_tts_communicate
from tts_engine import StallController, TTSConfig, TTSEngine


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


class _DelayedSuccessfulCommunicate:
    """先静默一段时间，再返回一条完整的最小合成结果。"""

    def __init__(self, *args, **kwargs):
        pass

    async def stream(self):
        await asyncio.sleep(0.03)
        yield {
            "type": "SentenceBoundary",
            "text": "Hello world.",
            "offset": 0,
            "duration": 10_000_000,
        }
        yield {"type": "audio", "data": b"\xff\xfb\x90\x00" * 64}


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
    """Non-blocking test controller with explicit user decisions."""

    def __init__(self, decisions=()):
        self._decisions = list(decisions)
        self._lock = threading.Lock()
        self.notices = []
        self.clear_calls = 0

    def notify(self, message):
        with self._lock:
            self.notices.append(message)

    def poll(self):
        with self._lock:
            if not self.notices:
                return None
            return self._decisions.pop(0) if self._decisions else None

    def clear(self):
        with self._lock:
            self.clear_calls += 1


class StallHandlingTests(unittest.TestCase):
    def test_stall_controller_notify_poll_and_clear_do_not_block(self):
        requests = []
        clears = []
        controller = StallController(requests.append, lambda: clears.append(True))

        started = time.perf_counter()
        controller.notify("quiet")
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.05)
        self.assertEqual(requests, ["quiet"])
        self.assertIsNone(controller.poll())
        controller.decide("retry")
        self.assertEqual(controller.poll(), "retry")
        controller.clear()
        self.assertEqual(clears, [True])

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

    def test_service_rejection_does_not_show_stall_notice(self):
        controller = _RecordingController()
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _ForbiddenCommunicate):
                outcome = asyncio.run(
                    engine._stream_once("hello", output, TTSConfig())
                )

        self.assertEqual(outcome, "error")
        self.assertEqual(controller.notices, [])
        self.assertIn("403", engine.error_message)

    def test_silent_stream_keeps_waiting_until_audio_resumes(self):
        controller = _RecordingController()
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch(
                "tts_engine.edge_tts.Communicate", _DelayedSuccessfulCommunicate
            ), patch.multiple(
                tts_engine,
                STALL_TIMEOUT=0.005,
                STALL_FIRST_AUDIO_TIMEOUT=0.005,
                STALL_SILENT_POLL=0.005,
                RECEIVE_TIMEOUT=1,
            ):
                started = time.perf_counter()
                outcome = asyncio.run(
                    engine._stream_once("hello", output, TTSConfig())
                )
                elapsed = time.perf_counter() - started

        self.assertEqual(outcome, "done")
        self.assertLess(elapsed, 1.0)
        self.assertEqual(len(controller.notices), 1)
        self.assertGreaterEqual(controller.clear_calls, 1)

    def test_retry_decision_reopens_stream_without_blocking(self):
        controller = _RecordingController(["retry"])
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _SilentCommunicate), patch.multiple(
                tts_engine,
                STALL_TIMEOUT=0.005,
                STALL_FIRST_AUDIO_TIMEOUT=0.005,
                STALL_SILENT_POLL=0.005,
                RECEIVE_TIMEOUT=1,
            ):
                started = time.perf_counter()
                outcome = asyncio.run(
                    engine._stream_once("hello", output, TTSConfig())
                )
                elapsed = time.perf_counter() - started

        self.assertEqual(outcome, "retry")
        self.assertLess(elapsed, 0.5)
        self.assertEqual(len(controller.notices), 1)

    def test_continue_decision_keeps_waiting_without_reopening_stream(self):
        controller = _RecordingController(["continue"])
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch(
                "tts_engine.edge_tts.Communicate", _DelayedSuccessfulCommunicate
            ), patch.multiple(
                tts_engine,
                STALL_TIMEOUT=0.005,
                STALL_FIRST_AUDIO_TIMEOUT=0.005,
                STALL_SILENT_POLL=0.005,
                RECEIVE_TIMEOUT=1,
            ):
                outcome = asyncio.run(
                    engine._stream_once("hello", output, TTSConfig())
                )

        self.assertEqual(outcome, "done")
        self.assertEqual(len(controller.notices), 1)
        self.assertGreaterEqual(controller.clear_calls, 1)

    def test_no_user_action_does_not_auto_retry(self):
        controller = _RecordingController()
        engine = TTSEngine(controller=controller)
        cancel_timer = threading.Timer(0.04, engine.cancel_event.set)
        cancel_timer.start()

        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output.mp3"
                with patch("tts_engine.edge_tts.Communicate", _SilentCommunicate), patch.multiple(
                    tts_engine,
                    STALL_TIMEOUT=0.005,
                    STALL_FIRST_AUDIO_TIMEOUT=0.005,
                    STALL_SILENT_POLL=0.005,
                    RECEIVE_TIMEOUT=1,
                ):
                    outcome = asyncio.run(
                        engine._stream_once("hello", output, TTSConfig())
                    )
        finally:
            cancel_timer.cancel()

        self.assertEqual(outcome, "cancel")
        self.assertEqual(len(controller.notices), 1)

    def test_transient_failure_auto_retries_without_stall_notice(self):
        controller = _RecordingController()
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

        self.assertEqual(first, "retry")
        self.assertEqual(second, "retry")
        self.assertEqual(controller.notices, [])

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
