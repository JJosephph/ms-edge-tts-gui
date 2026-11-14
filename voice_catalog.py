# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Chinese voice discovery for the Microsoft Edge online speech service.

Edge only exposes a subset of the voices that appear in Microsoft's Azure
documentation.  Adding Azure-only names to the picker makes the app look
richer while every synthesis attempt fails with ``NoAudioReceived``.

The multilingual voices below have been verified against the same Edge
endpoint the app uses: they synthesize Chinese text and return the normal
sentence timeline.  Region-specific Chinese voices that Edge lists are kept
under the ``zh`` group so dialect options no longer disappear from the picker.
"""

from __future__ import annotations

from typing import Iterable, List


CHINESE_GROUP = "zh"

# Verified against the Edge speech endpoint (free, no API key).
MULTILINGUAL_VOICES = (
    ("en-AU-WilliamMultilingualNeural", "威廉（多语言）"),
    ("en-US-AndrewMultilingualNeural", "安德鲁（多语言）"),
    ("en-US-AvaMultilingualNeural", "艾娃（多语言）"),
    ("en-US-BrianMultilingualNeural", "布莱恩（多语言）"),
    ("en-US-EmmaMultilingualNeural", "艾玛（多语言）"),
    ("fr-FR-VivienneMultilingualNeural", "薇薇安（多语言）"),
    ("fr-FR-RemyMultilingualNeural", "雷米（多语言）"),
    ("de-DE-SeraphinaMultilingualNeural", "塞拉菲娜（多语言）"),
    ("de-DE-FlorianMultilingualNeural", "弗洛里安（多语言）"),
    ("it-IT-GiuseppeMultilingualNeural", "朱塞佩（多语言）"),
    ("ko-KR-HyunsuMultilingualNeural", "贤秀（多语言）"),
    ("pt-BR-ThalitaMultilingualNeural", "塔莉塔（多语言）"),
)

_MULTILINGUAL_CODES = frozenset(code for code, _ in MULTILINGUAL_VOICES)


def is_chinese_locale(locale: object) -> bool:
    return str(locale or "").strip().lower().startswith("zh")


def is_multilingual_voice(code: object) -> bool:
    return str(code or "") in _MULTILINGUAL_CODES


def chinese_voice_group(locale: object, code: object) -> str:
    """Return the picker language group for a Chinese-capable voice.

    Microsoft returns ``zh-CN-liaoning`` / ``zh-CN-shaanxi`` as locales, but
    the old grouping split on ``-`` and filed them under ``zh`` while also
    keeping multilingual voices under ``en``/``fr``/``de``.  Users looking for
    "中文" therefore saw six Mandarin voices and missed the rest.
    """
    locale_text = str(locale or "").strip()
    code_text = str(code or "")
    if is_chinese_locale(locale_text) or code_text.lower().startswith("zh-"):
        return CHINESE_GROUP
    if is_multilingual_voice(code_text):
        return CHINESE_GROUP
    primary = locale_text.split("-")[0].lower()
    return primary


def merge_voice_catalog(voices: Iterable[dict]) -> List[dict]:
    """Normalise a voice list for the Chinese-aware picker.

    - Adds the multilingual voices to the ``zh`` group while keeping them in
      their original language groups, so English/French/German users still see
      the same native voices they had before.
    - Preserves every field returned by the service.
    - Records the group list in ``VoiceGroups`` and keeps the original locale.
    - Sorts voices by region then code for predictable browsing.
    """
    # One entry per voice, even when it belongs to several picker groups.
    merged: List[dict] = []
    seen = set()
    for voice in voices:
        code = voice.get("ShortName")
        if not code or code in seen:
            continue
        seen.add(code)
        item = dict(voice)
        locale = str(item.get("Locale") or "")
        item["EdgeLocale"] = locale
        primary = locale.split("-")[0].lower()
        groups = [primary] if primary else []
        if chinese_voice_group(locale, code) == CHINESE_GROUP and primary != CHINESE_GROUP:
            groups.append(CHINESE_GROUP)
        item["VoiceGroups"] = groups
        merged.append(item)

    def _order(voice: dict) -> tuple:
        code = str(voice.get("ShortName") or "")
        locale = str(voice.get("EdgeLocale") or "")
        # Standard voices first, then dialect variants (zh-CN-liaoning).
        dialect = 1 if is_chinese_locale(locale) and locale.count("-") > 1 else 0
        multilingual = 1 if is_multilingual_voice(code) else 0
        return (locale, dialect, multilingual, code)

    return sorted(merged, key=_order)
