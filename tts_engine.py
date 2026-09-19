# -*- coding: utf-8 -*-
"""TTS 合成引擎：封装 edge-tts，内置网络探测与“卡住”检测。

设计要点
--------
1. 生成前可选网络探测（speech.platform.bing.com），识别离线 / 代理异常。
2. 流式接收音频分片，若超过 STALL_TIMEOUT 没有新分片，判定为“卡住”，
   通过 StallController 询问界面：重试 / 取消 / 继续等待。
3. 支持重试与用户取消；错误分类后给出网络 / 代理提示。
"""

import asyncio
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import aiohttp
import edge_tts

# ---------------------------------------------------------------- 常量
STALL_TIMEOUT = 180            # 连续多少秒没有新音频分片 -> 首次提示卡住
STALL_WAIT_GRACE = 300         # 用户“继续等待”后，再次提醒前的更长等待时间（避免反复弹窗）
STALL_DECISION_TIMEOUT = 300   # 卡住后等待用户决定的最长时间（秒）
CONNECT_TIMEOUT = 10          # edge-tts 建连超时
RECEIVE_TIMEOUT = 300         # edge-tts 单次接收超时（兜底）
PROBE_TIMEOUT = 6             # 网络探测超时
MAX_RETRIES = 3               # 最大生成重试次数
PROGRESS_REPORT_INTERVAL = 0.25
DEFAULT_DIRECTIVE_PAUSE_MS = 300
MAX_DIRECTIVE_PAUSE_MS = 10000

PAUSE_DIRECTIVE_PATTERN = re.compile(
    r"\[\s*pause(?:\s*:\s*([^\]]+))?\s*\]",
    re.IGNORECASE,
)
PAUSE_PRESETS_MS = {
    "weak": 100,
    "medium": 300,
    "strong": 600,
}


def estimate_spoken_units(text: str) -> int:
    """Estimate spoken units for a responsive, approximate TTS percentage."""
    units = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)?", text)
    return max(1, len(units))


def _parse_pause_value(raw_value: Optional[str], fallback_ms: int) -> int:
    """Parse ``500ms``, ``1.5s`` and weak/medium/strong pause values."""
    raw = (raw_value or "").strip().lower()
    if not raw:
        return fallback_ms
    if raw in PAUSE_PRESETS_MS:
        return PAUSE_PRESETS_MS[raw]
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s)?", raw)
    if not match:
        return fallback_ms
    value = float(match.group(1))
    if match.group(2) == "s":
        value *= 1000
    return max(0, min(MAX_DIRECTIVE_PAUSE_MS, round(value)))


def parse_pause_directives(text: str, default_pause_ms: int = 0) -> tuple[str, dict[int, int]]:
    """Remove inline pause directives and map each one to a sentence index.

    ``[pause:500ms]`` and ``[pause:1.5s]`` use explicit durations. Named
    presets are also accepted. A bare ``[pause]`` uses the configured global
    pause, falling back to a practical 300 ms pause when that setting is off.
    """
    if not text or not PAUSE_DIRECTIVE_PATTERN.search(text):
        return text, {}
    fallback = default_pause_ms if default_pause_ms > 0 else DEFAULT_DIRECTIVE_PAUSE_MS
    overrides: dict[int, int] = {}
    pieces: list[str] = []
    cursor = 0
    for match in PAUSE_DIRECTIVE_PATTERN.finditer(text):
        pieces.append(text[cursor:match.start()])
        prefix = "".join(pieces)
        segments = split_reading_sentences(prefix)
        # A marker placed after the first segment controls the gap after
        # segment index 0 (the gap before segment index 1). This also treats
        # a newline-terminated line without punctuation as one segment.
        sentence_index = max(0, len(segments) - 1)
        overrides[sentence_index] = _parse_pause_value(match.group(1), fallback)
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces), overrides


def _sentence_end_positions(text: str) -> list[int]:
    """Return offsets after sentence punctuation or non-empty line endings."""
    positions: list[int] = []
    for line_start, line in _iter_lines_with_offsets(text):
        i = 0
        while i < len(line):
            char = line[i]
            if char not in ".!?\u3002\uff01\uff1f":
                i += 1
                continue
            if char == "." and _is_abbreviation_boundary(line, i):
                i += 1
                continue
            end = i + 1
            while end < len(line) and line[end] in ".!?\u3002\uff01\uff1f\"')\u2019\u201d\u300d\u3011]":
                end += 1
            positions.append(line_start + end)
            i = end
        line_end = len(line.rstrip())
        has_spoken_text = PAUSE_DIRECTIVE_PATTERN.sub("", line).strip()
        if line_end and has_spoken_text:
            position = line_start + line_end
            if position not in positions:
                positions.append(position)
    return sorted(set(positions))


def _iter_lines_with_offsets(text: str):
    offset = 0
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.splitlines(True):
        value = line.rstrip("\n")
        yield offset, value
        offset += len(line)
    if normalized and not normalized.endswith("\n") and not normalized.splitlines(True):
        yield 0, normalized


def insert_sentence_pause_directives(text: str, pause_ms: int) -> str:
    """Insert one inline pause marker after each non-final sentence."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = max(0, min(MAX_DIRECTIVE_PAUSE_MS, int(pause_ms)))
    if not text.strip() or value <= 0:
        return text
    positions = _sentence_end_positions(text)
    if len(positions) < 2:
        return text
    insertions: list[int] = []
    for position in positions[:-1]:
        tail = text[position:]
        if re.match(r"\s*\[\s*pause(?:\s*:\s*[^\]]+)?\s*\]", tail, re.IGNORECASE):
            continue
        insertions.append(position)
    marker = f" [pause:{value}ms]"
    for position in reversed(insertions):
        text = text[:position] + marker + text[position:]
    return text

# ---------------------------------------------------------------- 时间轴 JSON（.timeline.json）

SENTENCE_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "rev", "st", "prof", "sr", "jr",
    "vs", "cf", "e.g", "i.e", "etc",
}


def split_reading_sentences(text: str) -> list:
    """按 . ! ? 切分句子（带常见缩写保护），也兼容中文标点。"""
    sentences: list = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        value = re.sub(r"\s+", " ", line).strip()
        if not value:
            continue
        start = 0
        i = 0
        while i < len(value):
            char = value[i]
            if char not in ".!?\u3002\uff01\uff1f":
                i += 1
                continue
            if char == "." and _is_abbreviation_boundary(value, i):
                i += 1
                continue
            end = i + 1
            while end < len(value) and value[end] in ".!?\u3002\uff01\uff1f":
                end += 1
            while end < len(value) and value[end] in "\"')\u2019\u201d\u300d\u3011]":
                end += 1
            sentence = value[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = end
            while start < len(value) and value[start].isspace():
                start += 1
            i = start
        tail = value[start:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def _is_abbreviation_boundary(text: str, dot_index: int) -> bool:
    prefix = text[:dot_index].rstrip()
    match = re.search(r"([A-Za-z](?:[A-Za-z]|\.)*)$", prefix)
    if not match:
        return False
    token = match.group(1).lower().strip(".")
    if token in SENTENCE_ABBREVIATIONS:
        return True
    if len(token) == 1 and token.isalpha():
        return True
    return False


def count_spoken_words(text: str) -> int:
    """近似统计一句话会被朗读的“词”数：拉丁词 + 单个中文字符。"""
    words = re.findall(
        r"[\u4e00-\u9fff]|[A-Za-z0-9]+(?:['\u2019\u2013-][A-Za-z0-9]+)?",
        text,
    )
    return max(1, len(words))


def seconds_from_edge_ticks(value: object) -> float:
    try:
        return max(0.0, float(value) / 10000000.0)
    except (TypeError, ValueError):
        return 0.0


def build_sentence_timeline(
    sentence_boundaries: list, voice: str, rate: str
) -> dict:
    """直接使用 edge-tts 返回的句级边界构建精准时间轴。"""
    entries = []
    previous_start = -1.0
    for index, boundary in enumerate(sentence_boundaries):
        sentence = str(boundary.get("text", "")).strip()
        start = seconds_from_edge_ticks(boundary.get("offset"))
        duration = seconds_from_edge_ticks(boundary.get("duration"))
        end = start + duration
        if not sentence:
            raise RuntimeError(f"第 {index + 1} 个 SentenceBoundary 缺少文本。")
        if duration <= 0 or end <= start:
            raise RuntimeError(f"第 {index + 1} 个 SentenceBoundary 时间无效。")
        if start + 0.05 < previous_start:
            raise RuntimeError("SentenceBoundary 起始时间不是递增顺序。")
        entries.append(
            {
                "index": index,
                "start": round(start, 4),
                "end": round(end, 4),
                "word_count": count_spoken_words(sentence),
                "text": sentence,
            }
        )
        previous_start = start
    return {
        "version": 1,
        "kind": "sentence",
        "engine": "edge-tts",
        "boundary": "SentenceBoundary",
        "voice": voice,
        "rate": rate,
        "sentences": entries,
    }


def timeline_to_srt(timeline: Optional[dict]) -> str:
    """Convert the final sentence timeline to UTF-8 SRT text."""
    def stamp(seconds: float) -> str:
        milliseconds = max(0, round(float(seconds) * 1000))
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        secs, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    cues = []
    for number, item in enumerate((timeline or {}).get("sentences", []), start=1):
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        cues.append(
            f"{number}\n{stamp(item.get('start', 0))} --> {stamp(item.get('end', 0))}\n{text}"
        )
    return "\n\n".join(cues) + ("\n" if cues else "")


def insert_sentence_pauses(
    audio_path: str,
    timeline: dict,
    pause_ms: int,
    pause_overrides: Optional[dict[int, int]] = None,
) -> dict:
    """Replace native sentence gaps with exact silence durations.

    With no inline overrides, a positive ``pause_ms`` applies to every gap.
    When overrides are present, untagged gaps keep their native timing while
    tagged gaps are replaced by the requested duration (including ``0``).
    """
    pause_overrides = dict(pause_overrides or {})
    if pause_ms <= 0 and not pause_overrides:
        return timeline
    entries = list((timeline or {}).get("sentences", []))
    if len(entries) < 2:
        return timeline

    try:
        import lameenc
        import miniaudio
    except ImportError as exc:  # pragma: no cover - packaging dependency
        raise AudioPostProcessError(
            "缺少音频停顿处理组件，请重新安装完整版本。"
        ) from exc

    decoded = miniaudio.decode_file(
        audio_path,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=24000,
    )
    pcm = bytes(decoded.samples)
    bytes_per_frame = 2
    output = bytearray()
    cursor = 0
    shift = 0.0
    adjusted = []
    changed = False
    pending_start: Optional[float] = None

    for index, entry in enumerate(entries):
        item = dict(entry)
        original_start = float(entry["start"])
        original_end = float(entry["end"])
        original_duration = max(0.0, original_end - original_start)
        item["start"] = round(
            pending_start if pending_start is not None else original_start + shift,
            4,
        )
        item["end"] = round(item["start"] + original_duration, 4)
        adjusted.append(item)
        if index >= len(entries) - 1:
            continue
        end_frame = max(
            cursor // bytes_per_frame,
            round(float(entry["end"]) * decoded.sample_rate),
        )
        end_byte = min(len(pcm), end_frame * bytes_per_frame)
        output.extend(pcm[cursor:end_byte])
        next_start_frame = max(
            end_frame,
            round(float(entries[index + 1]["start"]) * decoded.sample_rate),
        )
        next_start_byte = min(len(pcm), next_start_frame * bytes_per_frame)
        native_gap_seconds = max(
            0.0,
            float(entries[index + 1]["start"]) - original_end,
        )
        desired_pause = pause_overrides.get(index)
        if desired_pause is None and pause_ms > 0:
            desired_pause = pause_ms
        if desired_pause is None:
            # No directive and no global setting: retain Edge's native gap.
            output.extend(pcm[end_byte:next_start_byte])
            cursor = next_start_byte
            pending_start = max(
                item["end"],
                float(entries[index + 1]["start"]) + shift,
            )
            continue

        desired_pause = max(0, min(MAX_DIRECTIVE_PAUSE_MS, int(desired_pause)))
        silence_frames = round(decoded.sample_rate * desired_pause / 1000)
        output.extend(b"\x00" * silence_frames * bytes_per_frame)
        cursor = next_start_byte
        shift += desired_pause / 1000.0 - native_gap_seconds
        pending_start = item["end"] + desired_pause / 1000.0
        changed = True

    output.extend(pcm[cursor:])
    if not changed:
        return timeline
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(48)
    encoder.set_in_sample_rate(decoded.sample_rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    encoded = encoder.encode(bytes(output)) + encoder.flush()
    temp_path = audio_path + ".pause"
    try:
        with open(temp_path, "wb") as handle:
            handle.write(encoded)
        TTSEngine._safe_replace(temp_path, audio_path)
    finally:
        TTSEngine._safe_unlink(temp_path)

    result = dict(timeline)
    result["sentences"] = adjusted
    if pause_ms > 0:
        result["sentence_pause_ms"] = pause_ms
    if pause_overrides:
        result["sentence_pause_overrides"] = pause_overrides
    return result



# edge-tts 使用的真实服务地址（用于网络探测，最贴近真实链路）
PROBE_URL = "https://speech.platform.bing.com/"

# ---------------------------------------------------------------- 异常


class UserCanceled(Exception):
    """用户主动取消。"""


class AudioPostProcessError(RuntimeError):
    """音频已生成，但句间停顿后处理无法完成。"""


@dataclass
class ProbeResult:
    """网络探测结果。"""

    reachable: bool
    proxy: Optional[str] = None
    latency_ms: float = 0.0
    error: str = ""

    @property
    def summary(self) -> str:
        if self.reachable:
            return f"网络正常（{self.latency_ms:.0f} ms）"
        if self.proxy:
            return "网络不可达，且检测到代理设置，可能是代理不正确"
        return "网络不可达"


# ---------------------------------------------------------------- 代理 / 网络探测


def detect_proxy() -> Optional[str]:
    """读取系统代理环境变量（edge-tts 走 aiohttp，会受这些变量影响）。"""
    for key in (
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
    ):
        value = os.environ.get(key)
        if value:
            return value.strip() or None
    return None


async def _probe_async(proxy: Optional[str]) -> ProbeResult:
    """异步网络探测：对 edge-tts 服务域名发起一次 HTTPS 请求。"""
    result = ProbeResult(reachable=False, proxy=proxy)
    timeout = aiohttp.ClientTimeout(
        total=PROBE_TIMEOUT, connect=PROBE_TIMEOUT, sock_connect=PROBE_TIMEOUT
    )
    start = time.perf_counter()
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(PROBE_URL, proxy=proxy) as resp:
                _ = resp.status  # 只要在超时内返回（哪怕 4xx/5xx）都算可达
        result.reachable = True
        result.latency_ms = round((time.perf_counter() - start) * 1000, 1)
    except Exception as exc:  # noqa: BLE001 - 探测失败统一视为不可达
        result.error = str(exc)[:300]
    return result


def probe_network(proxy: Optional[str] = None) -> ProbeResult:
    """同步封装：在调用方线程运行网络探测。"""
    return asyncio.run(_probe_async(proxy))


# ---------------------------------------------------------------- 语音列表


def list_tts_voices(proxy: Optional[str] = None) -> list:
    """获取 edge-tts 全部可用语音（同步封装）。"""
    return asyncio.run(edge_tts.list_voices(proxy=proxy))


# ---------------------------------------------------------------- 卡住控制器


class StallController:
    """工作线程 <-> 界面线程 之间的“卡住”问答桥。

    - ask() 由工作线程调用：发请求给界面，阻塞等待用户决定。
    - decide() 由界面线程调用：把用户选择回传给工作线程。
    """

    def __init__(self, request_callback: Callable[[str], None]):
        self._request_callback = request_callback
        self._responses: "queue.Queue[str]" = queue.Queue()

    def ask(self, message: str) -> str:
        """返回 'retry' | 'cancel' | 'continue'。"""
        try:
            self._request_callback(message)
        except Exception:
            return "cancel"
        try:
            return self._responses.get(timeout=STALL_DECISION_TIMEOUT)
        except queue.Empty:
            return "cancel"

    def decide(self, decision: str) -> None:
        self._responses.put(decision)


# ---------------------------------------------------------------- 引擎


@dataclass
class TTSConfig:
    voice: str = "en-US-AndrewMultilingualNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    sentence_pause_ms: int = 0


class TTSEngine:
    """一次完整的 TTS 任务执行器（在独立工作线程中运行）。"""

    def __init__(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        controller: Optional[StallController] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.on_log = on_log or (lambda msg: None)
        self.on_progress = on_progress or (lambda percent, written: None)
        self.controller = controller
        self.cancel_event = cancel_event or threading.Event()
        self.proxy = detect_proxy()
        self.sentence_boundaries: list = []
        self.timeline: Optional[dict] = None
        self.error_message = ""

    # ---------------- 对外入口 ----------------

    def generate(self, text: str, output_path, cfg: TTSConfig) -> dict:
        """同步入口：在工作线程中运行事件循环，返回结果 dict。"""
        return asyncio.run(self._generate_async(text, output_path, cfg))

    # ---------------- 内部实现 ----------------

    async def _generate_async(self, text: str, output_path, cfg: TTSConfig) -> dict:
        attempts = 0
        while True:
            attempts += 1
            self.on_log(f"开始第 {attempts} 次生成（语音：{cfg.voice}）")
            outcome = await self._stream_once(text, output_path, cfg)
            if outcome == "done":
                self.on_log("音频数据接收完成。")
                return {"status": "done", "path": str(output_path)}
            if outcome == "cancel":
                self.on_log("任务已取消。")
                return {"status": "canceled"}
            if outcome == "error":
                return {
                    "status": "error",
                    "error": self.error_message or "音频后处理失败。",
                }
            # retry
            if attempts >= MAX_RETRIES:
                self.on_log("已达最大重试次数，任务失败。")
                return {
                    "status": "error",
                    "error": "生成多次失败，请检查网络连接或代理设置后重试。",
                }
            self.on_log("准备重试…")

    async def _stream_once(self, text: str, output_path, cfg: TTSConfig) -> str:
        """执行一次流式生成，返回 'done' | 'cancel' | 'retry'。"""
        temp_path = self._temp_path(output_path)
        self._safe_unlink(temp_path)
        self.error_message = ""
        self.sentence_boundaries = []
        self.timeline = None
        spoken_text, pause_overrides = parse_pause_directives(
            text, cfg.sentence_pause_ms
        )
        if not spoken_text.strip():
            raise RuntimeError("停顿指令之外没有可朗读的文字。")

        communicate = edge_tts.Communicate(
            text=spoken_text,
            voice=cfg.voice,
            rate=cfg.rate,
            volume=cfg.volume,
            pitch=cfg.pitch,
            boundary="SentenceBoundary",
            proxy=self.proxy,
            connect_timeout=CONNECT_TIMEOUT,
            receive_timeout=RECEIVE_TIMEOUT,
        )

        last_report = time.perf_counter()
        written = 0
        total_units = estimate_spoken_units(spoken_text)
        completed_units = 0
        percent = 0
        self.on_progress(percent, written)
        try:
            iterator = communicate.stream()
            next_chunk = None
            keep_waiting = False
            with open(temp_path, "wb") as audio_file:
                while True:
                    if self.cancel_event.is_set():
                        if next_chunk is not None:
                            next_chunk.cancel()
                        raise UserCanceled()
                    if next_chunk is None:
                        next_chunk = asyncio.ensure_future(anext(iterator))
                    wait_window = STALL_WAIT_GRACE if keep_waiting else STALL_TIMEOUT
                    try:
                        done, _pending = await asyncio.wait(
                            {next_chunk}, timeout=wait_window
                        )
                    except asyncio.CancelledError:
                        raise
                    if done:
                        try:
                            chunk = next_chunk.result()
                        except StopAsyncIteration:
                            break
                        next_chunk = None
                        keep_waiting = False
                    else:
                        # 超时仍未收到新数据
                        if keep_waiting:
                            # 用户已选择“继续等待”：不重复弹窗，继续等这个分片
                            continue
                        decision = await self._ask_stall(
                            "生成似乎卡住了：长时间没有收到新的音频数据。"
                            "可能是网络不通或代理设置不正确。要重试吗？"
                        )
                        if decision == "cancel":
                            next_chunk.cancel()
                            raise UserCanceled()
                        if decision == "retry":
                            next_chunk.cancel()
                            self._safe_unlink(temp_path)
                            return "retry"
                        # 用户选择继续等待：放宽再次提醒的时间，不再反复打扰
                        keep_waiting = True
                        continue

                    chunk_type = chunk.get("type")
                    if chunk_type == "audio":
                        data = chunk.get("data", b"")
                        if data:
                            audio_file.write(data)
                            written += len(data)
                        now = time.perf_counter()
                        if now - last_report >= PROGRESS_REPORT_INTERVAL:
                            last_report = now
                            self.on_progress(percent, written)
                    elif chunk_type == "SentenceBoundary":
                        self.sentence_boundaries.append(chunk)
                        completed_units += estimate_spoken_units(chunk.get("text", ""))
                        percent = min(99, int(completed_units * 100 / total_units))
                        now = time.perf_counter()
                        if now - last_report >= PROGRESS_REPORT_INTERVAL:
                            last_report = now
                            self.on_progress(percent, written)

            if written == 0:
                raise RuntimeError("TTS 未返回任何音频数据。")

            if not self.sentence_boundaries:
                raise RuntimeError(
                    "TTS 未返回 SentenceBoundary，无法生成精准时间轴。"
                )
            self.timeline = build_sentence_timeline(
                self.sentence_boundaries, cfg.voice, cfg.rate
            )
            final_path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            self._safe_replace(temp_path, final_path)
            if cfg.sentence_pause_ms > 0 or pause_overrides:
                self.timeline = insert_sentence_pauses(
                    final_path,
                    self.timeline,
                    cfg.sentence_pause_ms,
                    pause_overrides=pause_overrides,
                )
            self.on_progress(100, written)
            return "done"

        except UserCanceled:
            self._safe_unlink(temp_path)
            return "cancel"
        except asyncio.CancelledError:
            self._safe_unlink(temp_path)
            raise
        except AudioPostProcessError as exc:
            self._safe_unlink(temp_path)
            self.error_message = str(exc)
            self.on_log(f"[警告] {self.error_message}")
            return "error"
        except Exception as exc:  # noqa: BLE001 - 统一兜底并让用户决定
            self._safe_unlink(temp_path)
            hint = self._classify_error(exc)
            self.on_log(f"[警告] 生成失败：{exc}（{hint}）")
            decision = await self._ask_stall(f"{hint} 是否重试？")
            if decision == "cancel":
                return "cancel"
            return "retry"

    # ---------------- 工具 ----------------

    async def _ask_stall(self, message: str) -> str:
        if self.controller is None:
            return "cancel"
        # ask() 内部是阻塞等待用户决定，可接受（此刻流已停滞）
        return self.controller.ask(message)

    def _classify_error(self, exc: Exception) -> str:
        text = str(exc).lower()
        network_kw = (
            "timeout",
            "timed out",
            "connection",
            "socket",
            "websocket",
            "ssl",
            "dns",
            "eof",
            "connect",
            "proxy",
            "clienterror",
            "getaddrinfo",
        )
        if any(kw in text for kw in network_kw):
            return "可能是网络不通或代理设置不正确"
        return "生成过程中出现异常"

    @staticmethod
    def _temp_path(output_path) -> str:
        return str(output_path) + ".partial"

    @staticmethod
    def _safe_replace(temp_path: str, final_path: str) -> None:
        """?????????????????????????????????? WinError 32?"""
        last_error = None
        for _ in range(6):
            try:
                if os.path.exists(final_path):
                    os.unlink(final_path)
                os.replace(temp_path, final_path)
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.3)
        if last_error is not None:
            raise last_error

    @staticmethod
    def _safe_unlink(path: str) -> None:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass
