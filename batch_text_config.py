# -*- coding: utf-8 -*-
"""Batch text header rules and filename helpers.

The file-batch workflow uses one optional header line at the top of a text
file.  The canonical form is::

    {tts:Ana|pause=200ms|marks=,.!?|srt=1|json=1|rate=+0%|volume=+0%|pitch=+0Hz}

The parser also accepts the compact form requested by users::

    {Ana|200ms{,.~}|srt}

The header is removed before synthesis, so it is never spoken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from tts_engine import validate_pause_ms


COMPACT_PAUSE_RE = re.compile(
    r"^(?P<pause>\d+(?:\.\d+)?(?:ms|s))(?:\{(?P<marks>[^{}]*)\})?$",
    re.IGNORECASE,
)
PAUSE_VALUE_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|s)?$",
    re.IGNORECASE,
)

TRUE_VALUES = {"1", "on", "yes", "true", "enable", "enabled", "srt", "json", "timeline"}
FALSE_VALUES = {"0", "off", "no", "false", "disable", "disabled", "none"}
BARE_SWITCHES = {
    "srt": ("srt_enabled", True),
    "subtitle": ("srt_enabled", True),
    "subtitles": ("srt_enabled", True),
    "json": ("timeline_enabled", True),
    "timeline": ("timeline_enabled", True),
    "highlight": ("timeline_enabled", True),
    "no-srt": ("srt_enabled", False),
    "no_srt": ("srt_enabled", False),
    "no-json": ("timeline_enabled", False),
    "no_json": ("timeline_enabled", False),
    "no-timeline": ("timeline_enabled", False),
    "no_timeline": ("timeline_enabled", False),
}


@dataclass
class ParsedTTSHeader:
    text: str
    options: dict = field(default_factory=dict)
    raw_header: str = ""
    warnings: list[str] = field(default_factory=list)


def parse_tts_header(text: str) -> ParsedTTSHeader:
    """Return text without its optional first-line TTS header plus options."""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    first_index = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return ParsedTTSHeader("")

    first_line = lines[first_index].strip()
    header = _split_header_line(first_line)
    if header is None:
        return ParsedTTSHeader(normalized.strip())

    body, rest, header_text = header
    options: dict = {}
    warnings: list[str] = []
    if body.lower().startswith("tts:"):
        body = body[4:].strip()

    for index, raw_token in enumerate(part.strip() for part in body.split("|")):
        if not raw_token:
            continue
        token = raw_token
        key = ""
        value = ""
        if "=" in token:
            key, value = (part.strip() for part in token.split("=", 1))
            key = key.strip().lower()
        elif index == 0:
            token = token.strip()
            if _is_voice_token(token):
                options["voice"] = token
                continue
            if _apply_bare_switch(options, token):
                continue
            key = token.lower()
        elif _is_voice_token(token):
            # A later bare voice name is treated as a voice override. This is
            # useful in hand-written compact rules such as {srt|Ana}.
            options["voice"] = token
            continue

        compact = COMPACT_PAUSE_RE.match(token)
        if compact and not key:
            try:
                options["sentence_pause_ms"] = _parse_pause(compact.group("pause"))
                options["sentence_pause_enabled"] = True
            except ValueError as exc:
                warnings.append(str(exc))
            if compact.group("marks") is not None:
                options["sentence_pause_marks"] = _clean_marks(compact.group("marks"))
            continue

        if not key:
            if _apply_bare_switch(options, token):
                continue
            warnings.append(f"无法识别标记：{token}")
            continue

        try:
            _apply_key_value(options, key, value)
        except ValueError as exc:
            warnings.append(str(exc))

    cleaned_lines = lines[:first_index]
    if rest:
        cleaned_lines.append(rest)
    cleaned_lines.extend(lines[first_index + 1 :])
    cleaned = "\n".join(cleaned_lines).strip()
    return ParsedTTSHeader(cleaned, options, header_text, warnings)


def build_tts_header(
    voice: str,
    *,
    sentence_pause_ms: int = 0,
    sentence_pause_marks: Iterable[str] = (),
    srt_enabled: bool = False,
    timeline_enabled: bool = False,
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
) -> str:
    """Build the canonical, copyable header line."""
    parts = [f"tts:{str(voice).strip() or 'voice'}"]
    pause_ms = validate_pause_ms(sentence_pause_ms)
    if pause_ms > 0:
        parts.append(f"pause={pause_ms}ms")
        marks = _clean_marks("".join(str(mark) for mark in sentence_pause_marks))
        if marks:
            parts.append(f"marks={marks}")
    parts.append(f"srt={1 if srt_enabled else 0}")
    parts.append(f"json={1 if timeline_enabled else 0}")
    parts.append(f"rate={normalize_percent(rate)}")
    parts.append(f"volume={normalize_percent(volume)}")
    parts.append(f"pitch={normalize_pitch(pitch)}")
    return "{" + "|".join(parts) + "}"


def normalize_percent(value: object) -> str:
    """Normalize ``10``, ``+10`` or ``10%`` to ``+10%``."""
    text = str(value or "").strip().replace("%", "")
    if not text:
        text = "0"
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(f"百分比格式无效：{value}") from exc
    return f"{'+' if number >= 0 else ''}{number}%"


def normalize_pitch(value: object) -> str:
    """Normalize ``10``, ``+10`` or ``10Hz`` to ``+10Hz``."""
    text = str(value or "").strip()
    text = re.sub(r"(?i)hz$", "", text).strip()
    if not text:
        text = "0"
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(f"音调格式无效：{value}") from exc
    return f"{'+' if number >= 0 else ''}{number}Hz"


def sanitize_filename_stem(name: str, fallback: str = "audio") -> str:
    """Return a Windows-safe filename stem while preserving Unicode."""
    stem = str(name or "").strip()
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if not stem:
        stem = fallback
    return stem[:120].rstrip(" .") or fallback


def build_voice_alias_index(
    voices: Iterable[dict],
    preferred_codes: Iterable[str] = (),
) -> dict[str, str]:
    """Map case-insensitive aliases such as ``Ana`` to full voice codes."""
    preferred = {str(code).lower(): index for index, code in enumerate(preferred_codes)}
    candidates: dict[str, list[str]] = {}

    def add(alias: str, code: str) -> None:
        key = str(alias or "").strip().lower()
        if key:
            candidates.setdefault(key, []).append(code)

    for voice in voices:
        code = str(voice.get("ShortName") or "").strip()
        if not code:
            continue
        locale = str(voice.get("Locale") or "").strip()
        stem = code.rsplit("-", 1)[-1]
        if stem.lower().endswith("neural"):
            stem = stem[: -len("neural")]
        add(code, code)
        add(stem, code)
        if locale:
            add(f"{locale}-{stem}", code)

    def priority(code: str) -> tuple:
        lower = code.lower()
        return (
            0 if lower in preferred else 1,
            0 if "multilingual" in lower else 1,
            len(code),
            lower,
        )

    result: dict[str, str] = {}
    for alias, codes in candidates.items():
        result[alias] = sorted(set(codes), key=priority)[0]
    return result


def resolve_voice_alias(
    value: object,
    alias_index: dict[str, str],
    known_codes: Optional[set[str]] = None,
) -> tuple[str, Optional[str]]:
    """Resolve an alias or full ShortName.

    Returns ``(resolved_value, warning)``. Unknown values are returned as-is
    so the TTS engine can still report a meaningful service error.
    """
    raw = str(value or "").strip()
    if not raw:
        return "", "语音标记为空"
    known = known_codes or set()
    if raw in known:
        return raw, None
    resolved = alias_index.get(raw.lower())
    if resolved:
        return resolved, None
    if raw.lower() in alias_index:
        return alias_index[raw.lower()], None
    return raw, f"未找到语音别名“{raw}”，将按完整语音代码尝试"


def _looks_like_header(body: str) -> bool:
    lowered = body.strip().lower()
    if lowered.startswith("tts:"):
        return True
    if lowered in BARE_SWITCHES:
        return True
    if "|" in body:
        return True
    first = body.split("|", 1)[0]
    return "=" in first and first.split("=", 1)[0].strip().lower() in {
        "voice",
        "v",
        "pause",
        "marks",
        "srt",
        "json",
        "rate",
        "volume",
        "pitch",
    }


def _split_header_line(line: str) -> tuple[str, str, str] | None:
    """Split ``{rule}text`` or ``{rule}`` without eating normal prose braces."""
    stripped = str(line or "").strip()
    if not stripped.startswith("{"):
        return None
    depth = 0
    for index, char in enumerate(stripped):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                body = stripped[1:index].strip()
                if not _looks_like_header(body):
                    return None
                rest = stripped[index + 1 :].strip()
                return body, rest, stripped[: index + 1]
    return None


def _is_voice_token(token: str) -> bool:
    lowered = token.strip().lower()
    if not lowered:
        return False
    if lowered in BARE_SWITCHES:
        return False
    if COMPACT_PAUSE_RE.match(token):
        return False
    return bool(re.search(r"[A-Za-z]", token)) or "-" in token


def _apply_bare_switch(options: dict, token: str) -> bool:
    switch = BARE_SWITCHES.get(str(token or "").strip().lower())
    if not switch:
        return False
    options[switch[0]] = switch[1]
    return True


def _apply_key_value(options: dict, key: str, value: str) -> None:
    aliases = {
        "voice": "voice",
        "v": "voice",
        "pause": "sentence_pause_ms",
        "sentence_pause": "sentence_pause_ms",
        "sentence-pause": "sentence_pause_ms",
        "sp": "sentence_pause_ms",
        "marks": "sentence_pause_marks",
        "punctuation": "sentence_pause_marks",
        "punct": "sentence_pause_marks",
        "srt": "srt_enabled",
        "subtitle": "srt_enabled",
        "subtitles": "srt_enabled",
        "json": "timeline_enabled",
        "timeline": "timeline_enabled",
        "highlight": "timeline_enabled",
        "rate": "rate",
        "speed": "rate",
        "volume": "volume",
        "vol": "volume",
        "pitch": "pitch",
    }
    normalized = aliases.get(key)
    if not normalized:
        raise ValueError(f"无法识别设置项：{key}")
    if normalized == "voice":
        options["voice"] = value.strip()
    elif normalized == "sentence_pause_ms":
        options["sentence_pause_ms"] = _parse_pause(value)
        options["sentence_pause_enabled"] = options["sentence_pause_ms"] > 0
    elif normalized == "sentence_pause_marks":
        options["sentence_pause_marks"] = _clean_marks(value)
    elif normalized in ("srt_enabled", "timeline_enabled"):
        options[normalized] = _parse_bool(value)
    elif normalized == "rate":
        options["rate"] = normalize_percent(value)
    elif normalized == "volume":
        options["volume"] = normalize_percent(value)
    elif normalized == "pitch":
        options["pitch"] = normalize_pitch(value)


def _parse_pause(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    match = PAUSE_VALUE_RE.match(text)
    if not match:
        raise ValueError(f"停顿格式无效：{value}")
    number = float(match.group("value"))
    unit = (match.group("unit") or "ms").lower()
    milliseconds = number * 1000 if unit == "s" else number
    return validate_pause_ms(int(round(milliseconds)))


def _parse_bool(value: object) -> bool:
    text = str(value or "").strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise ValueError(f"开关值无效：{value}")


def _clean_marks(value: object) -> str:
    marks = "".join(str(value or "").split())
    if marks.lower() in ("none", "off", "0"):
        return ""
    return "".join(dict.fromkeys(marks))
