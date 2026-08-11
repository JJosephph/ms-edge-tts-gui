# -*- coding: utf-8 -*-
"""语音分组引擎：把远端一次性拉取的语音列表，按 语言 → 性别 → 音色 本地分组。

设计目标
--------
- 一次性从远端拉取全部语音后，只在本地做分组，避免每次都请求远端。
- 界面按三级选择：语言（如 中文 / English）→ 性别（男声 / 女声 / 全部）→ 音色。
"""

from __future__ import annotations

from typing import Dict, List, Optional


GENDER_FEMALE = "Female"
GENDER_MALE = "Male"
GENDER_OTHER = "Other"
GENDER_ALL = "All"


class VoiceGroupingEngine:
    """根据 edge-tts 语音列表构建 语言 → 性别 → 音色 的分组索引。"""

    def __init__(self, voices: List[dict]):
        self._groups: Dict[str, Dict[str, List[dict]]] = {}
        for voice in voices:
            locale = (voice.get("Locale") or "").split("-")[0].lower()
            if not locale:
                continue
            gender = voice.get("Gender") or GENDER_OTHER
            if gender not in (GENDER_FEMALE, GENDER_MALE, GENDER_OTHER):
                gender = GENDER_OTHER
            self._groups.setdefault(locale, {}).setdefault(gender, []).append(voice)
        for lang in self._groups:
            for gender in self._groups[lang]:
                self._groups[lang][gender].sort(
                    key=lambda v: (v.get("FriendlyName") or v.get("ShortName") or "")
                )

    def languages(self) -> List[str]:
        """按语言代码排序返回全部语言代码。"""
        return sorted(self._groups.keys())

    def genders(self, lang: str) -> List[str]:
        """某语言下实际存在的性别（Female / Male / Other）。"""
        return sorted(self._groups.get(lang, {}).keys())

    def voices(self, lang: str, gender: Optional[str] = None) -> List[dict]:
        """返回某语言（可选性别过滤）下的语音列表。"""
        if not lang or lang not in self._groups:
            return []
        if gender and gender in (GENDER_FEMALE, GENDER_MALE, GENDER_OTHER) and gender in self._groups[lang]:
            return list(self._groups[lang][gender])
        result: List[dict] = []
        for key in (GENDER_FEMALE, GENDER_MALE, GENDER_OTHER):
            result.extend(self._groups[lang].get(key, []))
        return result

    def count(self, lang: str, gender: Optional[str] = None) -> int:
        return len(self.voices(lang, gender))

    def find(self, code: str) -> Optional[dict]:
        """按 ShortName 查找语音（用于反查当前选择）。"""
        for lang in self._groups:
            for gender in self._groups[lang]:
                for voice in self._groups[lang][gender]:
                    if voice.get("ShortName") == code:
                        return voice
        return None

    def voice_locale(self, code: str) -> str:
        voice = self.find(code)
        return voice.get("Locale", "") if voice else ""

    def voice_gender(self, code: str) -> str:
        voice = self.find(code)
        return voice.get("Gender", GENDER_OTHER) if voice else GENDER_OTHER
