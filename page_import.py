# -*- coding: utf-8 -*-
"""文件导入与分页：把 txt/md/docx/pdf 转成逐页旁白结构。

每个 Page = 一页：text 是这一页的旁白文本（会朗读，可编辑），
note 是该页备注（不朗读，随 pages.json 一并导出）。
PDF 按真实页面拆分；txt/md/docx 按段落块智能分页。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Page:
    index: int
    text: str = ""
    note: str = ""
    title: str = ""


SUPPORTED_EXTS = (".txt", ".md", ".markdown", ".docx", ".pdf")
DEFAULT_MAX_CHARS = 1000


def import_file(path: str, max_chars: int = DEFAULT_MAX_CHARS) -> List[Page]:
    """导入文件并分页，返回 Page 列表。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".markdown"):
        pages = split_text_into_pages(_read_text(path), max_chars)
    elif ext == ".docx":
        pages = _import_docx(path, max_chars)
    elif ext == ".pdf":
        pages = _import_pdf(path, max_chars)
    else:
        raise ValueError("不支持的格式：%s（支持 txt / md / docx / pdf）" % (ext or "未知"))
    result = [p for p in pages if (p.text or "").strip()]
    if not result:
        raise ValueError("文件中没有可用的文字内容（PDF 可能是扫描件，无法提取文字）。")
    return result


def split_text_into_pages(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> List[Page]:
    """按空行分块，再合并成每页约 max_chars 的页面。"""
    text = (text or "").strip()
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    raw_pages: List[str] = []
    current: List[str] = []
    current_len = 0
    for block in blocks:
        if current and current_len + len(block) > max_chars:
            raw_pages.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(block)
        current_len += len(block)
    if current:
        raw_pages.append("\n\n".join(current))
    return [Page(i + 1, p, "", _page_title(p)) for i, p in enumerate(raw_pages)]


def _import_docx(path: str, max_chars: int) -> List[Page]:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise ValueError("缺少 docx 解析库，无法导入 Word 文档。") from exc
    document = Document(path)
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    if not paragraphs:
        raise ValueError("Word 文档中没有可提取的段落文字。")
    return split_text_into_pages("\n\n".join(paragraphs), max_chars)


def _import_pdf(path: str, max_chars: int) -> List[Page]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ValueError("缺少 PDF 解析库，无法导入 PDF 文件。") from exc
    reader = PdfReader(path)
    pages: List[Page] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(Page(i, text, "", _page_title(text)))
    if not pages:
        raise ValueError("PDF 中没有可提取的文字（可能是扫描件）。")
    return pages


def _read_text(path: str) -> str:
    """按常见编码依次尝试读取文本文件。"""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError as exc:
            last_error = exc
        except OSError as exc:
            raise ValueError("无法读取文件：%s" % exc) from exc
    raise ValueError("无法识别文件编码。") from last_error


def _page_title(text: str) -> str:
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    return first[:40] if first else ""
