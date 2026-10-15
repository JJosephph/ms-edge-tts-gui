# -*- coding: utf-8 -*-
"""TTS 合成引擎：封装 edge-tts，内置网络探测与“卡住”检测。

设计要点
--------
1. 生成前可选网络探测（api.msedgeservices.com 合成 WebSocket），识别离线 / 代理异常。
2. 流式接收音频分片，若超过 STALL_TIMEOUT 没有新分片，判定为“卡住”，
   通过 StallController 询问界面：重试 / 取消 / 继续等待。
3. 支持重试与用户取消；错误分类后给出网络 / 代理提示。
"""

import asyncio
import os
import queue
import random
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

import aiohttp
import edge_tts
import edge_tts.communicate as edge_tts_communicate
from edge_tts.constants import SEC_MS_GEC_VERSION, TRUSTED_CLIENT_TOKEN, WSS_HEADERS
from edge_tts.drm import DRM

# ---------------------------------------------------------------- 常量
STALL_TIMEOUT = 120            # 连续多少秒没有新音频分片 -> 判定卡住
STALL_FIRST_AUDIO_TIMEOUT = 60  # 还没收到任何数据时的等待上限（限流通常表现为连上后没数据）
STALL_WAIT_GRACE = 600         # 用户“继续等待”后，再次提醒前的更长等待时间（避免反复弹窗）
STALL_SILENT_POLL = 5          # “不再提醒”后，检查取消操作的间隔（秒）
STALL_DECISION_TIMEOUT = 300   # 卡住后等待用户决定的最长时间（秒）
CONNECT_TIMEOUT = 10          # edge-tts 建连超时
RECEIVE_TIMEOUT = 1800        # edge-tts 单次接收超时（兜底，不能抢先于界面提示）
PROBE_TIMEOUT = 6             # 网络探测超时
STALL_AUTO_RETRIES = 2        # 卡住后先静默自动重试几次，之后才弹窗询问
MAX_RETRIES = 4               # 最大生成重试次数
RETRY_BASE_DELAY = 3.0        # 首次自动重试前等待（秒）
RETRY_MAX_DELAY = 15.0        # 自动重试等待上限（秒）
RATE_LIMIT_RETRY_BASE_DELAY = 8.0   # 命中 429 限流时的首次等待（秒）
RATE_LIMIT_RETRY_MAX_DELAY = 30.0   # 命中 429 限流时的等待上限（秒）
RETRY_JITTER_RATIO = 0.25     # 退避随机抖动比例，避免多个客户端同时重试
PROGRESS_REPORT_INTERVAL = 0.25
DEFAULT_DIRECTIVE_PAUSE_MS = 300
MIN_PAUSE_MS = 50
MAX_PAUSE_MS = 10000
MAX_DIRECTIVE_PAUSE_MS = MAX_PAUSE_MS
POSTPROCESS_SAMPLE_RATE = 24000
MP3_FRAME_MS = 48

# 单次合成请求的最大 UTF-8 字节数。edge-tts 内部以 4096 字节切分，但它自带的
# 切分逻辑在“既没有空格也没有换行”的中文文本上会整体不切分，导致一次请求远超
# 上限（实测 24KB 中文只发一条请求）。这里由客户端主动切分，保证每次请求都有界。
SYNTH_SEGMENT_MAX_BYTES = 3600
# 服务端返回的音频固定为 24kHz/48kbps CBR，字节与时间片(100ns)可精确换算。
EDGE_TICKS_PER_SECOND = 10_000_000
EDGE_MP3_BITRATE_BPS = 48_000

NEW_EDGE_TTS_WSS_URL = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    f"?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"
)
SERVICE_REJECTION_MESSAGE = (
    "微软语音服务拒绝了连接（403）。这通常是服务端端点或访问策略变化导致的，"
    "不是本地网络问题。请稍后重试；如果持续出现，请更新到最新版本。"
)
RATE_LIMIT_HINT = "微软语音服务临时限流（429），不是本地网络或代理问题"
SERVER_BUSY_HINT = "微软语音服务暂时不可用（服务端错误），不是本地网络或代理问题"

_HTTP_STATUS_PATTERN = re.compile(r"(?<!\d)([1-5]\d{2})(?!\d)")


def configure_edge_tts_endpoint() -> None:
    """Use Edge 155's synthesis host while keeping the legacy client token."""
    current_url = getattr(edge_tts_communicate, "WSS_URL", "")
    if "speech.platform.bing.com" in current_url:
        edge_tts_communicate.WSS_URL = NEW_EDGE_TTS_WSS_URL


configure_edge_tts_endpoint()

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


def validate_pause_ms(value: object, *, allow_zero: bool = True) -> int:
    """Return a pause value that the postprocessor can honour exactly.

    MP3 at 24 kHz has 1152 samples per frame (48 ms). The client deliberately
    exposes 50 ms as the smallest non-zero pause: below that, codec transients
    make the requested interval unreliable even though the PCM sample count
    could technically be written. Rejecting the range is clearer than showing
    a value that cannot be heard or measured consistently.
    """
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError("停顿时间必须是整数毫秒。") from exc
    if parsed == 0:
        if allow_zero:
            return 0
        raise ValueError(f"停顿时间必须为 {MIN_PAUSE_MS}–{MAX_PAUSE_MS} 毫秒。")
    if parsed < MIN_PAUSE_MS or parsed > MAX_PAUSE_MS:
        raise ValueError(
            f"停顿时间必须为 0 或 {MIN_PAUSE_MS}–{MAX_PAUSE_MS} 毫秒；"
            f"低于 {MIN_PAUSE_MS} 毫秒受 MP3 编码帧限制，无法保证稳定生效。"
        )
    return parsed


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
        spoken_line = PAUSE_DIRECTIVE_PATTERN.sub("", line)
        if line_end and _has_spoken_content(spoken_line):
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
    if int(pause_ms) <= 0:
        return text
    value = validate_pause_ms(pause_ms, allow_zero=False)
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


def _has_spoken_content(text: str) -> bool:
    return bool(re.search(r"[\w\u4e00-\u9fff]", text or "", flags=re.UNICODE))


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
            if char == "." and _is_decimal_point(value, i):
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
            if sentence and _has_spoken_content(sentence):
                sentences.append(sentence)
            start = end
            while start < len(value) and value[start].isspace():
                start += 1
            i = start
        tail = value[start:].strip()
        if tail and _has_spoken_content(tail):
            sentences.append(tail)
    return sentences


def _is_decimal_point(text: str, dot_index: int) -> bool:
    """Keep dots inside numbers such as 49.9 or v1.6.2 from splitting."""
    if dot_index <= 0 or dot_index + 1 >= len(text):
        return False
    return text[dot_index - 1].isdigit() and text[dot_index + 1].isdigit()


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


def http_status_from_exception(exc: BaseException) -> Optional[int]:
    """从异常链里取出 HTTP 状态码（403 / 429 / 5xx）。

    edge-tts 会抛出 aiohttp 的 WSServerHandshakeError（自带 status），
    也会把状态码只写进消息文本，因此这里同时检查属性与消息。
    """
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status", None)
        if isinstance(status, int) and 100 <= status < 600:
            return status
        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and 100 <= status_code < 600:
            return status_code
        text = str(current).lower()
        type_name = type(current).__name__.lower()
        looks_like_handshake = (
            "invalid response status" in text
            or "forbidden" in text
            or "wsserverhandshake" in type_name
        )
        if looks_like_handshake:
            match = _HTTP_STATUS_PATTERN.search(text)
            if match:
                return int(match.group(1))
        current = current.__cause__ or current.__context__
    return None


# 断句优先级：先换行/句末，再逗号类，再空格，最后按字节硬切。
_HARD_BREAK_CHARS = "\n。！？!?；;…"
_SOFT_BREAK_CHARS = "，、,：:）)】」》"
_SPACE_BREAK_CHARS = " \t\u3000"


def _char_index_for_bytes(text: str, max_bytes: int) -> int:
    """返回使 UTF-8 字节数不超过 max_bytes 的最大字符下标（至少 1）。"""
    total = 0
    for index, char in enumerate(text):
        total += len(char.encode("utf-8"))
        if total > max_bytes:
            return max(1, index)
    return len(text)


def _find_segment_cut(text: str, max_bytes: int) -> int:
    """在 max_bytes 范围内挑一个尽量自然的切分点（返回字符下标）。"""
    hard_limit = _char_index_for_bytes(text, max_bytes)
    if hard_limit >= len(text):
        return len(text)
    window = text[:hard_limit]
    for marks in (_HARD_BREAK_CHARS, _SOFT_BREAK_CHARS, _SPACE_BREAK_CHARS):
        for index in range(len(window) - 1, 0, -1):
            if window[index] in marks:
                return index + 1
    return hard_limit


def split_text_for_synthesis(
    text: str, max_bytes: int = SYNTH_SEGMENT_MAX_BYTES
) -> list:
    """把待合成文本切成若干不超过 max_bytes 的片段。

    返回片段按顺序拼接后与原文完全一致（不丢字符），因此后续基于原文的
    WordBoundary / SentenceBoundary 对齐逻辑不受影响。
    """
    if not text:
        return []
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]
    segments = []
    remaining = text
    while remaining:
        if len(remaining.encode("utf-8")) <= max_bytes:
            segments.append(remaining)
            break
        cut = _find_segment_cut(remaining, max_bytes)
        segments.append(remaining[:cut])
        remaining = remaining[cut:]
    return segments


def audio_duration_seconds(audio_path: str) -> float:
    """Return the duration reported by the decoder for the final audio file.

    MP3 encoders work in frame-sized chunks, so the physical duration can be
    slightly different from the requested logical timeline. Keeping this
    value separately lets the preview follow what the player really plays
    without changing sentence cue timestamps.
    """
    try:
        import miniaudio

        info = miniaudio.get_file_info(audio_path)
        if info.sample_rate and info.num_frames:
            return max(0.0, float(info.num_frames) / float(info.sample_rate))
        return max(0.0, float(info.duration or 0.0))
    except Exception:
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


def _normalize_timing_text(text: object) -> str:
    """Normalize boundary text for matching while ignoring punctuation/spacing."""
    return re.sub(r"[\W_]+", "", str(text or ""), flags=re.UNICODE).lower()


def build_sentence_timeline_from_word_boundaries(
    source_text: str, word_boundaries: list, voice: str, rate: str
) -> dict:
    """Build sentence cues from WordBoundary events.

    SentenceBoundary durations include Edge's trailing silence. WordBoundary
    gives the actual last-word end, which is the anchor needed when replacing
    native gaps with an exact user-selected duration.
    """
    segments = split_reading_sentences(source_text)
    events = []
    for boundary in word_boundaries:
        text = str(boundary.get("text", "")).strip()
        start = seconds_from_edge_ticks(boundary.get("offset"))
        duration = seconds_from_edge_ticks(boundary.get("duration"))
        end = start + duration
        if not text or duration <= 0 or end <= start:
            continue
        events.append(
            {
                "text": text,
                "start": start,
                "end": end,
                "normalized": _normalize_timing_text(text),
            }
        )
    if not segments or not events:
        raise RuntimeError("TTS 未返回可用的 WordBoundary，无法保证精确停顿。")

    entries = []
    cursor = 0
    for source_index, segment in enumerate(segments):
        target = _normalize_timing_text(segment)
        if not target:
            continue
        consumed = []
        while cursor < len(events):
            event = events[cursor]
            if not event["normalized"]:
                cursor += 1
                continue
            candidate = _normalize_timing_text(
                "".join(item["text"] for item in consumed) + event["text"]
            )
            if target.startswith(candidate):
                consumed.append(event)
                cursor += 1
                if candidate == target:
                    break
                continue
            break

        if not consumed:
            # A punctuation-only or unsupported segment can appear between
            # spoken sentences. Skip it rather than shifting every later cue.
            continue

        start = consumed[0]["start"]
        end = consumed[-1]["end"]
        if end <= start:
            continue
        entries.append(
            {
                "index": len(entries),
                "source_index": source_index,
                "start": round(start, 4),
                "end": round(end, 4),
                "word_count": count_spoken_words(segment),
                "text": segment,
            }
        )

    if not entries:
        raise RuntimeError("无法将 WordBoundary 映射到朗读文本。")

    # If the service returns extra trailing events, accept them only when the
    # remaining event text exactly matches the remaining source text. Never
    # attach unmatched words to the previous cue: that would make a requested
    # pause appear at the wrong place.
    if cursor < len(events):
        last_source_index = int(entries[-1]["source_index"])
        remaining_source = _normalize_timing_text(
            "".join(segments[last_source_index + 1 :])
        )
        remaining_events = _normalize_timing_text(
            "".join(item["text"] for item in events[cursor:])
        )
        if not remaining_source or remaining_events != remaining_source:
            raise RuntimeError(
                "WordBoundary 与朗读文本无法精确对齐，已停止后处理以避免停顿错位。"
            )
        start = events[cursor]["start"]
        end = events[-1]["end"]
        if end > start:
            entries.append(
                {
                    "index": len(entries),
                    "source_index": last_source_index + 1,
                    "start": round(start, 4),
                    "end": round(end, 4),
                    "word_count": count_spoken_words(remaining_source),
                    "text": " ".join(segments[last_source_index + 1 :]).strip(),
                }
            )

    return {
        "version": 1,
        "kind": "sentence",
        "engine": "edge-tts",
        "boundary": "WordBoundary",
        "voice": voice,
        "rate": rate,
        "sentences": entries,
    }


def line_end_sentence_indices(text: str) -> list[int]:
    """Return source sentence indexes that end each non-empty spoken line."""
    indexes = []
    sentence_count = 0
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.splitlines():
        segments = split_reading_sentences(line)
        if not segments:
            continue
        sentence_count += len(segments)
        indexes.append(sentence_count - 1)
    return indexes


def merge_pause_overrides(
    explicit: Optional[dict[int, int]], defaults: Optional[dict[int, int]]
) -> dict[int, int]:
    """Merge pause defaults without overriding explicit inline directives."""
    merged = dict(defaults or {})
    merged.update(dict(explicit or {}))
    return merged


def fill_subtitle_gaps(timeline: Optional[dict]) -> Optional[dict]:
    """Return the same cues with every waiting gap covered by the previous cue.

    Subtitle files are usually imported into editors that expect a cue to stay
    on screen until the next one starts, while an interpolated pause leaves a
    real hole in the audio. Each cue is therefore extended to the next cue's
    start and the final cue covers the requested tail pause. Only cue times
    change: the audio and the timeline JSON keep the real timings.
    """
    if not timeline:
        return timeline
    entries = [dict(item) for item in timeline.get("sentences", [])]
    if not entries:
        return timeline

    for current, following in zip(entries, entries[1:]):
        try:
            next_start = float(following.get("start", 0.0))
            current_end = float(current.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if next_start > current_end:
            current["end"] = round(next_start, 4)

    # A trailing pause has no following cue to absorb it, so the last cue runs
    # to the logical end of the audio when the timeline records one.
    tail_end: Optional[float] = None
    for key in ("duration", "audio_duration"):
        try:
            candidate = float(timeline.get(key))
        except (TypeError, ValueError):
            continue
        if candidate > 0 and (tail_end is None or candidate < tail_end):
            tail_end = candidate
    try:
        last_end = float(entries[-1].get("end", 0.0))
    except (TypeError, ValueError):
        last_end = 0.0
    if tail_end is not None and tail_end > last_end:
        entries[-1]["end"] = round(tail_end, 4)

    filled = dict(timeline)
    filled["sentences"] = entries
    return filled


def timeline_to_srt(timeline: Optional[dict], fill_gaps: bool = False) -> str:
    """Convert the final sentence timeline to UTF-8 SRT text.

    With ``fill_gaps`` the cues are laid end to end, so an imported subtitle
    track has no holes where a sentence or line-end pause was interpolated.
    """
    if fill_gaps:
        timeline = fill_subtitle_gaps(timeline)

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
    pause_marks: Optional[set[str]] = None,
    tail_pause_ms: Optional[int] = None,
) -> dict:
    """Replace native gaps and optionally rewrite the final tail.

    All values are converted to an exact number of 24 kHz PCM frames before
    encoding. A zero override removes the native gap instead of appending
    silence, which keeps timeline JSON, SRT cues, and audio in sync.
    """
    pause_overrides = dict(pause_overrides or {})
    pause_ms = validate_pause_ms(pause_ms)
    if tail_pause_ms is not None:
        tail_pause_ms = validate_pause_ms(tail_pause_ms)
    pause_overrides = {
        int(index): validate_pause_ms(value)
        for index, value in pause_overrides.items()
    }
    if pause_ms <= 0 and not pause_overrides and tail_pause_ms is None:
        return timeline
    entries = list((timeline or {}).get("sentences", []))
    if not entries:
        return timeline

    try:
        import lameenc
        import miniaudio
    except ImportError as exc:  # pragma: no cover - packaging dependency
        raise AudioPostProcessError(
            "缺少音频停顿处理组件，请重新安装完整版本。"
        ) from exc

    # miniaudio's file helpers use the C file API on Windows and fail on
    # non-ASCII paths such as "1 - 副本.mp3". Decode from bytes instead so
    # batch output names can safely contain Chinese and other Unicode text.
    with open(audio_path, "rb") as handle:
        audio_bytes = handle.read()
    decoded = miniaudio.decode(
        audio_bytes,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=POSTPROCESS_SAMPLE_RATE,
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
        source_index = int(entry.get("source_index", index))
        item["start"] = round(
            pending_start if pending_start is not None else original_start + shift,
            4,
        )
        item["end"] = round(item["start"] + original_duration, 4)
        adjusted.append(item)
        if index >= len(entries) - 1:
            end_frame = max(
                cursor // bytes_per_frame,
                round(original_end * decoded.sample_rate),
            )
            end_byte = min(len(pcm), end_frame * bytes_per_frame)
            output.extend(pcm[cursor:end_byte])
            if tail_pause_ms is None:
                cursor = end_byte
            else:
                silence_frames = round(decoded.sample_rate * tail_pause_ms / 1000)
                output.extend(b"\x00" * silence_frames * bytes_per_frame)
                cursor = len(pcm)
                changed = True
            continue
        end_frame = max(
            cursor // bytes_per_frame,
            round(original_end * decoded.sample_rate),
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
        desired_pause = pause_overrides.get(source_index)
        if desired_pause is None and pause_ms > 0 and (
            pause_marks is None
            or str(entry.get("text", "")).rstrip()[-1:] in pause_marks
        ):
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

        desired_pause = validate_pause_ms(desired_pause)
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
    result["audio_duration"] = round(audio_duration_seconds(audio_path), 4)
    if pause_ms > 0:
        result["sentence_pause_ms"] = pause_ms
    if pause_overrides:
        result["sentence_pause_overrides"] = pause_overrides
    if tail_pause_ms is not None:
        result["line_pause_ms"] = tail_pause_ms
        result["duration_padding_ms"] = tail_pause_ms
        sentence_end = max(
            [float(item.get("end", 0)) for item in result.get("sentences", [])] or [0.0]
        )
        result["duration"] = round(sentence_end + tail_pause_ms / 1000.0, 4)
    return result


def append_audio_silence(audio_path: str, timeline: dict, pause_ms: int) -> dict:
    """Backward-compatible wrapper for replacing the final audio tail."""
    return insert_sentence_pauses(
        audio_path,
        timeline,
        0,
        tail_pause_ms=pause_ms,
    )



# 微软 Edge 155 使用的真实合成 WebSocket 地址
PROBE_URL = NEW_EDGE_TTS_WSS_URL

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
    """异步网络探测：与真实合成 WebSocket 完成一次握手后立即关闭。"""
    result = ProbeResult(reachable=False, proxy=proxy)
    timeout = aiohttp.ClientTimeout(
        total=PROBE_TIMEOUT, connect=PROBE_TIMEOUT, sock_connect=PROBE_TIMEOUT
    )
    start = time.perf_counter()
    try:
        probe_url = (
            f"{PROBE_URL}&ConnectionId={uuid.uuid4().hex}"
            f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
            f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}"
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                probe_url,
                compress=15,
                proxy=proxy,
                headers=DRM.headers_with_muid(WSS_HEADERS),
            ):
                pass
        result.reachable = True
        result.latency_ms = round((time.perf_counter() - start) * 1000, 1)
    except Exception as exc:  # noqa: BLE001 - 探测失败统一视为不可达
        status = getattr(exc, "status", None)
        if status == 403:
            result.error = "微软语音服务拒绝了连接（403）"
        else:
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
    sentence_pause_marks: tuple[str, ...] = ()
    line_pause_enabled: bool = False
    line_pause_ms: int = 0


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
        self.word_boundaries: list = []
        self.timeline: Optional[dict] = None
        self.error_message = ""
        self._last_error_status: Optional[int] = None
        self._suppress_stall_prompts = False
        self._auto_stall_retries = 0

    # ---------------- 对外入口 ----------------

    def generate(self, text: str, output_path, cfg: TTSConfig) -> dict:
        """同步入口：在工作线程中运行事件循环，返回结果 dict。"""
        return asyncio.run(self._generate_async(text, output_path, cfg))

    # ---------------- 内部实现 ----------------

    async def _generate_async(self, text: str, output_path, cfg: TTSConfig) -> dict:
        attempts = 0
        self._auto_stall_retries = 0
        self._last_error_status: Optional[int] = None
        while True:
            attempts += 1
            self._last_error_status = None
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
                    "http_status": self._last_error_status,
                }
            # retry
            if attempts >= MAX_RETRIES:
                message = self._final_failure_message(self._last_error_status)
                self.on_log(f"已达最大重试次数（{attempts}），任务失败。")
                return {
                    "status": "error",
                    "error": message,
                    "http_status": self._last_error_status,
                }
            delay = self._retry_delay(attempts, self._last_error_status)
            self.on_log(f"等待 {delay:g} 秒后重试…")
            try:
                await self._wait_with_cancel(delay)
            except UserCanceled:
                self.on_log("任务已取消。")
                return {"status": "canceled"}

    async def _iter_synthesis_chunks(
        self, spoken_text: str, cfg: TTSConfig, needs_word_boundary: bool
    ):
        """按有界片段合成，并把各片段的边界时间轴补偿为全局时间轴。

        edge-tts 每次请求都会新建一条 WebSocket；片段之间保持顺序，后一片段
        的边界偏移要加上前面所有片段已产生的音频时长。服务端音频是
        24kHz/48kbps CBR，因此字节到时间片(100ns)可以精确换算，与 edge-tts
        内部的 offset 补偿公式一致。
        """
        segments = split_text_for_synthesis(spoken_text)
        if not segments:
            raise RuntimeError("停顿指令之外没有可朗读的文字。")
        cumulative_audio_bytes = 0
        for segment in segments:
            compensation = (
                cumulative_audio_bytes
                * 8
                * EDGE_TICKS_PER_SECOND
                // EDGE_MP3_BITRATE_BPS
            )
            communicate = edge_tts.Communicate(
                text=segment,
                voice=cfg.voice,
                rate=cfg.rate,
                volume=cfg.volume,
                pitch=cfg.pitch,
                boundary=(
                    "WordBoundary" if needs_word_boundary else "SentenceBoundary"
                ),
                proxy=self.proxy,
                connect_timeout=CONNECT_TIMEOUT,
                receive_timeout=RECEIVE_TIMEOUT,
            )
            async for chunk in communicate.stream():
                chunk_type = chunk.get("type")
                if chunk_type == "audio":
                    cumulative_audio_bytes += len(chunk.get("data", b""))
                    yield chunk
                elif chunk_type in ("SentenceBoundary", "WordBoundary"):
                    if compensation:
                        chunk = dict(chunk)
                        chunk["offset"] = (
                            int(chunk.get("offset", 0)) + compensation
                        )
                    yield chunk
                else:
                    yield chunk

    async def _stream_once(self, text: str, output_path, cfg: TTSConfig) -> str:
        """执行一次流式生成，返回 'done' | 'cancel' | 'retry'。"""
        temp_path = self._temp_path(output_path)
        # 缓存目录可能在设置后被清理/删除（临时目录清理、移动盘拔插等），
        # 这里先补建目录，避免写 .partial 文件时报“找不到路径”。
        parent_dir = os.path.dirname(os.path.abspath(temp_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        self._safe_unlink(temp_path)
        self.error_message = ""
        self.sentence_boundaries = []
        self.word_boundaries = []
        self.timeline = None
        spoken_text, pause_overrides = parse_pause_directives(
            text, cfg.sentence_pause_ms
        )
        if not spoken_text.strip():
            raise RuntimeError("停顿指令之外没有可朗读的文字。")
        try:
            cfg.sentence_pause_ms = validate_pause_ms(cfg.sentence_pause_ms)
            cfg.line_pause_ms = validate_pause_ms(cfg.line_pause_ms)
            pause_overrides = {
                int(index): validate_pause_ms(value)
                for index, value in pause_overrides.items()
            }
        except ValueError as exc:
            raise AudioPostProcessError(str(exc)) from exc

        sentence_pause_active = (
            cfg.sentence_pause_ms > 0 and bool(cfg.sentence_pause_marks)
        )
        needs_word_boundary = (
            sentence_pause_active
            or cfg.line_pause_enabled
            or bool(pause_overrides)
        )

        last_report = time.perf_counter()
        written = 0
        total_units = estimate_spoken_units(spoken_text)
        completed_units = 0
        percent = 0
        self.on_progress(percent, written)
        try:
            iterator = self._iter_synthesis_chunks(spoken_text, cfg, needs_word_boundary)
            next_chunk = None
            wait_deadline = None
            silent_waiting = False
            received_any = False
            with open(temp_path, "wb") as audio_file:
                while True:
                    if self.cancel_event.is_set():
                        if next_chunk is not None:
                            next_chunk.cancel()
                        raise UserCanceled()
                    if next_chunk is None:
                        next_chunk = asyncio.ensure_future(anext(iterator))
                    if silent_waiting:
                        wait_window = STALL_SILENT_POLL
                    elif wait_deadline is not None:
                        wait_window = max(0.0, wait_deadline - time.perf_counter())
                    else:
                        # 一个字都还没收到时更快判定卡住：限流通常表现为
                        # 连接建立后长时间没有任何数据。
                        wait_window = (
                            STALL_TIMEOUT if received_any else STALL_FIRST_AUDIO_TIMEOUT
                        )
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
                        except UserCanceled:
                            # 分段/等待期间用户点了取消，按取消处理，不当作失败重试。
                            raise
                        except Exception as exc:
                            self._last_error_status = http_status_from_exception(exc)
                            if self._is_service_rejection(exc):
                                self.error_message = SERVICE_REJECTION_MESSAGE
                                self.on_log(
                                    f"[警告] 生成失败：{exc}"
                                    f"（{SERVICE_REJECTION_MESSAGE}）"
                                )
                                return "error"
                            if silent_waiting:
                                self.on_log(
                                    f"[警告] 等待期间连接中断：{exc}；已启用不再提醒，正在自动重试。"
                                )
                                return "retry"
                            if wait_deadline is not None:
                                if self._consume_auto_stall_retry(
                                    "等待期间连接中断"
                                ):
                                    next_chunk = None
                                    self._safe_unlink(temp_path)
                                    return "retry"
                                await self._wait_with_cancel(
                                    max(0.0, wait_deadline - time.perf_counter())
                                )
                                decision = await self._ask_stall(
                                    "生成等待期间连接中断。"
                                    "可能是网络波动，也可能是服务端临时限流。要重试吗？"
                                )
                                if decision == "cancel":
                                    return "cancel"
                                if decision == "continue_silent":
                                    self._suppress_stall_prompts = True
                                self._safe_unlink(temp_path)
                                return "retry"
                            raise
                        next_chunk = None
                        wait_deadline = None
                        silent_waiting = False
                        received_any = True
                    else:
                        # 超时仍未收到新数据
                        if silent_waiting:
                            # 用户已选择“不再提醒”：静默等待，同时保留取消响应。
                            continue
                        if self._consume_auto_stall_retry(
                            "长时间没有收到新的音频数据"
                        ):
                            next_chunk.cancel()
                            self._safe_unlink(temp_path)
                            return "retry"
                        decision = await self._ask_stall(
                            "生成似乎卡住了：自动重试后仍长时间没有收到新的音频数据。"
                            "可能是网络波动，也可能是服务端临时限流。要重试吗？"
                        )
                        if decision == "cancel":
                            next_chunk.cancel()
                            raise UserCanceled()
                        if decision == "retry":
                            next_chunk.cancel()
                            self._safe_unlink(temp_path)
                            return "retry"
                        if decision == "continue_silent":
                            self._suppress_stall_prompts = True
                            silent_waiting = True
                            wait_deadline = None
                        else:
                            # 从用户点击“继续等待”的时刻重新计时。
                            wait_deadline = time.perf_counter() + STALL_WAIT_GRACE
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
                    elif chunk_type in ("SentenceBoundary", "WordBoundary"):
                        if chunk_type == "SentenceBoundary":
                            self.sentence_boundaries.append(chunk)
                        else:
                            self.word_boundaries.append(chunk)
                        completed_units += estimate_spoken_units(chunk.get("text", ""))
                        percent = min(99, int(completed_units * 100 / total_units))
                        now = time.perf_counter()
                        if now - last_report >= PROGRESS_REPORT_INTERVAL:
                            last_report = now
                            self.on_progress(percent, written)

            if written == 0:
                raise RuntimeError("TTS 未返回任何音频数据。")

            if needs_word_boundary:
                if not self.word_boundaries:
                    raise RuntimeError(
                        "TTS 未返回 WordBoundary，无法保证精确停顿。"
                    )
                self.timeline = build_sentence_timeline_from_word_boundaries(
                    spoken_text, self.word_boundaries, cfg.voice, cfg.rate
                )
            else:
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
            line_overrides: dict[int, int] = {}
            if cfg.line_pause_enabled:
                line_indexes = line_end_sentence_indices(spoken_text)
                line_overrides = {
                    source_index: cfg.line_pause_ms
                    for source_index in line_indexes[:-1]
                }
                pause_overrides = merge_pause_overrides(
                    pause_overrides, line_overrides
                )
            if (
                sentence_pause_active
                or pause_overrides
                or cfg.line_pause_enabled
            ):
                self.timeline = insert_sentence_pauses(
                    final_path,
                    self.timeline,
                    cfg.sentence_pause_ms if sentence_pause_active else 0,
                    pause_overrides=pause_overrides,
                    pause_marks=set(cfg.sentence_pause_marks),
                    tail_pause_ms=(
                        cfg.line_pause_ms if cfg.line_pause_enabled else None
                    ),
                )
            # Store the decoder-measured duration for playback controls. The
            # sentence timeline remains logical and millisecond-precise while
            # the preview follows the actual MP3 frame duration.
            if self.timeline is not None:
                self.timeline["audio_duration"] = round(
                    audio_duration_seconds(final_path), 4
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
            self._last_error_status = http_status_from_exception(exc)
            if self._is_service_rejection(exc):
                self.error_message = SERVICE_REJECTION_MESSAGE
                self.on_log(
                    f"[警告] 生成失败：{exc}"
                    f"（{SERVICE_REJECTION_MESSAGE}）"
                )
                return "error"
            hint = self._classify_error(exc)
            self.on_log(f"[警告] 生成失败：{exc}（{hint}）")
            if self._is_transient_status(self._last_error_status):
                # 限流 / 服务端临时故障属于“等一会儿再来”，静默重试比弹窗更合适。
                self.on_log(f"[提示] {hint}，正在自动重试…")
                return "retry"
            if self._suppress_stall_prompts:
                self.on_log("[提示] 已启用不再提醒，正在自动重试。")
                return "retry"
            if self._consume_auto_stall_retry(hint):
                return "retry"
            decision = await self._ask_stall(f"{hint} 是否重试？")
            if decision == "cancel":
                return "cancel"
            if decision == "continue_silent":
                self._suppress_stall_prompts = True
            return "retry"

    # ---------------- 工具 ----------------

    def _consume_auto_stall_retry(self, reason: str) -> bool:
        """卡住 / 中断后先静默自动重试几次，用完额度才弹窗询问。

        用户实测批量生成时服务端会短时限流：重试基本都能成功，
        因此自动重试比每次都弹窗更省事。
        """
        if self._auto_stall_retries >= STALL_AUTO_RETRIES:
            return False
        self._auto_stall_retries += 1
        self.on_log(
            f"[提示] {reason}，正在自动重试"
            f"（{self._auto_stall_retries}/{STALL_AUTO_RETRIES}）…"
        )
        return True

    async def _ask_stall(self, message: str) -> str:
        if self.controller is None:
            return "cancel"
        if self._suppress_stall_prompts:
            return "continue_silent"
        # 让网络事件循环继续运行；否则对话框打开期间底层超时回调会堆积，
        # 用户点击继续等待后会立即拿到已经超时的旧结果并再次弹窗。
        return await asyncio.to_thread(self.controller.ask, message)

    async def _wait_with_cancel(self, seconds: float) -> None:
        deadline = time.perf_counter() + seconds
        while True:
            if self.cancel_event.is_set():
                raise UserCanceled()
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.25, remaining))

    def _classify_error(self, exc: Exception) -> str:
        status = http_status_from_exception(exc)
        if status == 403:
            return SERVICE_REJECTION_MESSAGE
        if status == 429:
            return RATE_LIMIT_HINT
        if status is not None and 500 <= status < 600:
            return SERVER_BUSY_HINT
        if status is not None and 400 <= status < 500:
            return f"微软语音服务拒绝了本次请求（HTTP {status}）"
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

    def _is_service_rejection(self, exc: Exception) -> bool:
        """Recognize an HTTP 403 even when edge-tts wraps it in another error."""
        return http_status_from_exception(exc) == 403

    @staticmethod
    def _is_transient_status(status: Optional[int]) -> bool:
        """限流与服务端临时故障：重试即可，不该弹窗让用户判断。"""
        if status == 429:
            return True
        return status is not None and 500 <= status < 600

    def _retry_delay(self, attempt: int, status: Optional[int]) -> float:
        """按失败原因计算退避时间；429 限流等待更久，并带随机抖动。"""
        if status == 429:
            base = RATE_LIMIT_RETRY_BASE_DELAY
            cap = RATE_LIMIT_RETRY_MAX_DELAY
        else:
            base = RETRY_BASE_DELAY
            cap = RETRY_MAX_DELAY
        delay = min(cap, base * (2 ** (attempt - 1)))
        return delay + random.uniform(0.0, delay * RETRY_JITTER_RATIO)

    @staticmethod
    def _final_failure_message(status: Optional[int]) -> str:
        if status == 429:
            return (
                "连续多次请求都被微软语音服务限流（429）。"
                "这是服务端对当前出口 IP 的临时限制，不是本地网络或代理问题。"
                "请等待 1-2 分钟后重试；批量生成时可以分几次、减少单次数量。"
            )
        if status is not None and 500 <= status < 600:
            return (
                "微软语音服务连续返回服务端错误。"
                "这不是本地网络或代理问题，请稍后重试。"
            )
        if status == 403:
            return SERVICE_REJECTION_MESSAGE
        if status is not None:
            return f"生成多次失败（服务端返回 HTTP {status}），请稍后重试。"
        return "生成多次失败，请检查网络连接或代理设置后重试。"

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
