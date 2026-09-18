# -*- coding: utf-8 -*-
"""文件导入与分页：把 txt/md/docx/pdf 转成逐页/逐行旁白结构。

每个 Page = 一条旁白：text 会朗读（可编辑），note 是备注（不朗读）。
- 普通模式：读取完整文本，不分页。
- 逐页模式：PDF 按真实页面；txt/md/docx 按空行分隔成页面。
- 逐行模式：每个非空行一条旁白，空行跳过。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List


@dataclass
class Page:
    index: int
    text: str = ""
    note: str = ""
    title: str = ""


SUPPORTED_EXTS = (".txt", ".md", ".markdown", ".docx", ".pdf")
DEFAULT_MAX_CHARS = 1000
PAGE_BREAK_PATTERN = re.compile(
    r"(?:\[分页\]|\[page\]|---\s*(?:分页|page break)\s*---)",
    re.IGNORECASE,
)


def import_file(path: str, max_chars: int = DEFAULT_MAX_CHARS) -> List[Page]:
    """导入文件并分页，返回 Page 列表。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".markdown"):
        pages = split_text_into_pages(_read_text(path), max_chars)
    elif ext == ".docx":
        pages = split_text_into_pages(_read_docx_text(path), max_chars)
    elif ext == ".pdf":
        pages = _import_pdf(path)
    else:
        raise ValueError("不支持的格式：%s（支持 txt / md / docx / pdf）" % (ext or "未知"))
    result = [p for p in pages if (p.text or "").strip()]
    if not result:
        raise ValueError("文件中没有可用的文字内容（PDF 可能是扫描件，无法提取文字）。")
    return result


def read_document_text(path: str) -> str:
    """导入文件为完整文本，不分页、不按行拆分。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".markdown"):
        text = _read_text(path)
    elif ext == ".docx":
        text = _read_docx_text(path)
    elif ext == ".pdf":
        text = "\n\n".join(_read_pdf_page_texts(path))
    else:
        raise ValueError("不支持的格式：%s（支持 txt / md / docx / pdf）" % (ext or "未知"))
    text = (text or "").strip()
    if not text:
        raise ValueError("文件中没有可用的文字内容（PDF 可能是扫描件，无法提取文字）。")
    return text


def import_lines(path: str) -> List[Page]:
    """导入文件并按非空行拆分，每行一条旁白。"""
    pages = split_text_into_lines(read_document_text(path))
    if not pages:
        raise ValueError("文件中没有可用的文字行。")
    return pages


def split_text_into_pages(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> List[Page]:
    """按空行分隔页面；可选分页标记会被移除且不会进入配音。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    if PAGE_BREAK_PATTERN.search(text):
        raw_pages = [part.strip() for part in PAGE_BREAK_PATTERN.split(text) if part.strip()]
        return [Page(i + 1, page, "", _page_title(page)) for i, page in enumerate(raw_pages)]
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [Page(i + 1, block, "", _page_title(block)) for i, block in enumerate(blocks)]


def split_text_into_lines(text: str) -> List[Page]:
    """每个非空行生成一条旁白。空行会被跳过，不会合成空音频。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return [Page(i + 1, line, "", _page_title(line)) for i, line in enumerate(lines)]


def _import_pdf(path: str) -> List[Page]:
    pages: List[Page] = []
    for i, text in enumerate(_read_pdf_page_texts(path), start=1):
        if text:
            pages.append(Page(i, text, "", _page_title(text)))
    if not pages:
        raise ValueError("PDF 中没有可提取的文字（可能是扫描件）。")
    return pages


def _read_docx_text(path: str) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise ValueError("缺少 docx 解析库，无法导入 Word 文档。") from exc
    document = Document(path)
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    if not paragraphs:
        raise ValueError("Word 文档中没有可提取的段落文字。")
    return "\n\n".join(paragraphs)


def _read_pdf_page_texts(path: str) -> List[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ValueError("缺少 PDF 解析库，无法导入 PDF 文件。") from exc
    reader = PdfReader(path)
    texts: List[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            texts.append(text)
    if not texts:
        raise ValueError("PDF 中没有可提取的文字（可能是扫描件）。")
    return texts


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
