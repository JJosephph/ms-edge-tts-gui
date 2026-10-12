import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import tts_engine
from tts_engine import TTSConfig, TTSEngine


class _FailingCommunicate:
    def __init__(self, *args, **kwargs):
        pass

    async def stream(self):
        if False:
            yield None
        await asyncio.sleep(0.02)
        raise RuntimeError("simulated receive timeout")


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
    def test_continue_waiting_restarts_grace_before_reporting_stream_failure(self):
        controller = _RecordingController("continue", first_delay=0.03)
        engine = TTSEngine(controller=controller)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.mp3"
            with patch("tts_engine.edge_tts.Communicate", _FailingCommunicate), patch.multiple(
                tts_engine,
                STALL_TIMEOUT=0.005,
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
                STALL_TIMEOUT=0.005,
                STALL_WAIT_GRACE=0.06,
                STALL_SILENT_POLL=0.005,
                RECEIVE_TIMEOUT=1,
            ):
                outcome = asyncio.run(
                    engine._stream_once("hello", output, TTSConfig())
                )

        self.assertEqual(outcome, "retry")
        self.assertEqual(controller.calls, 1)


if __name__ == "__main__":
    unittest.main()
