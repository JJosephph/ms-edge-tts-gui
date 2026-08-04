# -*- coding: utf-8 -*-
"""文本清理：把用户粘贴的文章/Markdown/HTML 转成适合朗读的纯文本。"""

import html
import re

PREVIEW_MAX_CHARS = 400  # 试听默认只合成前 400 个字符


def remove_code_blocks(text: str) -> str:
    text = re.sub(r"```.*?```", "\n", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def remove_images(text: str) -> str:
    return re.sub(r"!\[.*?\]\(.*?\)", "", text)


def convert_links(text: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def strip_html_tags(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def remove_llm_citations(text: str) -> str:
    text = re.sub(r"\s*\[oaicite:[^\]]+\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\{index=\d+\}", "", text, flags=re.IGNORECASE)
    return text


def clean_text(raw: str) -> str:
    """清洗为适合 TTS 朗读的纯文本（保留分段）。"""
    if not raw:
        return ""

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = remove_llm_citations(text)
    text = remove_code_blocks(text)
    text = remove_images(text)
    text = convert_links(text)
    text = strip_html_tags(text)

    # 去掉 Markdown 标题 / 引用 / 列表 / 分隔线
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*([-*_]){3,}\s*$", "\n", text, flags=re.MULTILINE)

    text = text.replace("**", "").replace("__", "").replace("*", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def normalize_for_tts(text: str) -> str:
    """针对朗读的额外规范化（避免 LORD/GOD 被逐字母拼读）。"""
    text = re.sub(r"\bLORD\b", "Lord", text)
    text = re.sub(r"\bGOD\b", "God", text)
    text = re.sub(r"\bYAHWEH\b", "Yahweh", text)
    return text


def preview_text(cleaned: str, max_chars: int = PREVIEW_MAX_CHARS) -> str:
    """取前 max_chars 个字符用于试听，尽量在句子边界截断。"""
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars]
    for marker in ("。", "！", "？", ".", "!", "?", "\n"):
        idx = cut.rfind(marker)
        if idx >= max_chars * 0.5:
            return cut[: idx + 1]
    return cut


def default_filename() -> str:
    from datetime import datetime

    return "tts_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".mp3"
