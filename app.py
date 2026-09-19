# -*- coding: utf-8 -*-
"""Edge TTS 语音合成助手 —— 现代化桌面 GUI 客户端。

功能：
- 粘贴文章一键生成音频：生成一次，之后可随时试听或保存下载（无需重复合成）
- 网络检测：离线 / 代理异常会提示
- 卡住检测：长时间无音频数据时提示是否重试
- 开源标识 / 仓库地址 / 开发者信息
"""

import json
import os
import queue
import re
import shutil
import zipfile
import tempfile
import time
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import pygame
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

from tts_engine import (
    MAX_RETRIES,
    ProbeResult,
    StallController,
    TTSConfig,
    TTSEngine,
    detect_proxy,
    insert_sentence_pause_directives,
    list_tts_voices,
    probe_network,
    timeline_to_srt,
)
from text_utils import clean_text, default_filename, normalize_for_tts
from voice_groups import (
    GENDER_ALL,
    GENDER_FEMALE,
    GENDER_MALE,
    GENDER_OTHER,
    VoiceGroupingEngine,
)
from page_import import Page, import_file, import_lines, split_text_into_lines

APP_NAME = "Edge TTS 语音合成助手"
APP_VERSION = "1.5"
DEVELOPER = "WangYufan"
DEVELOPER_QQ = "1471056247"
REPOSITORY_URL = "https://github.com/JJosephph/ms-edge-tts-gui"
REPOSITORY_DISPLAY = "github.com/JJosephph/ms-edge-tts-gui"
UI_FONT_FAMILY = "Microsoft YaHei UI"
UI_FONT_FALLBACKS = ("Microsoft YaHei", "SimHei", "Arial")
SETTINGS_DIR = Path(os.environ.get("APPDATA", Path.home())) / "EdgeTTSGui"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
PREVIEW_FILENAME = "edge_tts_preview.mp3"

THEMES = {
    "dark": {
        "app_bg": "#09111F", "surface": "#111D31", "surface_alt": "#0D1728",
        "card": "#14223A", "card_raised": "#182944", "border": "#263B5C",
        "text": "#F2F6FF", "muted": "#91A4C3", "primary": "#5A8CFF",
        "primary_hover": "#4777E6", "accent": "#73D7FF", "success": "#61D69C",
        "warning": "#F6C66C", "danger": "#F47D92", "star": "#4A3B16",
        "star_hover": "#5D4B1D", "field": "#0A1322", "log": "#09121F",
    },
    "light": {
        "app_bg": "#EEF3FA", "surface": "#FFFFFF", "surface_alt": "#E6EEF9",
        "card": "#FFFFFF", "card_raised": "#F7FAFF", "border": "#CAD8EB",
        "text": "#17233A", "muted": "#61718D", "primary": "#356FEB",
        "primary_hover": "#285BCA", "accent": "#0B89C8", "success": "#168B57",
        "warning": "#A66A00", "danger": "#C33D56", "star": "#FFF3D6",
        "star_hover": "#F8E1A7", "field": "#F8FBFF", "log": "#F7FAFE",
    },
}

DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
DEFAULT_RATE = 0
DEFAULT_VOLUME = 0
DEFAULT_PITCH = 0


ctk.ThemeManager.theme["CTkFont"]["family"] = UI_FONT_FAMILY
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class TTSTask:
    """一个生成任务（试听或导出）。"""

    def __init__(self, text, output_path, cfg, mode):
        self.text = text
        self.output_path = output_path
        self.cfg = cfg
        self.mode = mode  # "preview" | "export"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Prefer a Chinese UI font that is actually installed so glyph metrics
        # stay consistent instead of falling back per-widget and shifting labels.
        installed_fonts = set(tkfont.families(self))
        self._font_family = next(
            (family for family in (UI_FONT_FAMILY, *UI_FONT_FALLBACKS) if family in installed_fonts),
            UI_FONT_FAMILY,
        )
        ctk.ThemeManager.theme["CTkFont"]["family"] = self._font_family

        self.title(f"{APP_NAME} v{APP_VERSION}")
        # Give the composer and the settings deck enough room for readable controls.
        self.geometry("1180x860")
        self.minsize(1080, 760)

        self._ui_q: "queue.Queue" = queue.Queue()
        self._stall_req_q: "queue.Queue" = queue.Queue()
        self._stall_controller: StallController | None = None
        self._cancel_event = threading.Event()
        self._busy = False
        self._settings = self._load_settings()
        self._theme = self._settings.get("theme", "dark")
        if self._theme not in THEMES:
            self._theme = "dark"
        ctk.set_appearance_mode(self._theme)
        self._preview_dir = self._settings.get("preview_dir") or tempfile.gettempdir()
        self._preview_path = self._preview_file_for(self._preview_dir)
        self._cleanup_preview_file()

        self._voice_map: dict = {}
        self._groups_engine: Optional[VoiceGroupingEngine] = None
        self._voices_load_error: str | None = None
        self._language = "zh"
        self._selected_lang = "en"
        self._selected_gender = "Male"
        self._lang_map: dict = {}
        self._gender_map: dict = {}
        self._selected_voice_code = DEFAULT_VOICE
        self._generated_path: str | None = None
        self._generated_text: str | None = None
        self._timeline_enabled = bool(self._settings.get("timeline_json", False))
        self._srt_enabled = bool(self._settings.get("srt_subtitles", False))
        try:
            saved_pause_ms = int(self._settings.get("sentence_pause_ms", 0))
        except (TypeError, ValueError):
            saved_pause_ms = 0
        self._sentence_pause_ms = max(0, min(10000, saved_pause_ms))
        self._sentence_pause_enabled = bool(self._settings.get("sentence_pause_enabled", self._sentence_pause_ms > 0))
        self._line_pause_enabled = bool(self._settings.get("line_pause_enabled", False))
        try:
            self._line_pause_ms = max(0, min(10000, int(self._settings.get("line_pause_ms", 300))))
        except (TypeError, ValueError):
            self._line_pause_ms = 300
        saved_marks = self._settings.get("sentence_pause_marks")
        self._sentence_pause_marks = set(saved_marks) if isinstance(saved_marks, list) else set("。.!！?？")
        self._generated_timeline: dict | None = None
        self._timeline_var = None
        self._srt_var = None
        self._pause_var = None
        self._highlight_running = False
        self._highlight_ranges: list = []
        self._workflow_mode = "normal"
        self._mode_selector = None
        self._mode_value_to_key: dict = {}
        self._helper_label = None
        self._btn_prepare_lines = None
        self._normal_text = ""
        self._line_draft = ""
        self._batch_mode: str | None = None
        self._pages: list = []
        self._page_index = 0
        self._generated_pages: dict = {}
        self._result_preview_callbacks: dict = {}
        self._result_preview_refresh = None
        self._batch_dir: str | None = None
        self._note_var = None
        self._note_entry = None
        self._page_bar = None
        self._page_label = None
        self._btn_prev_page = None
        self._btn_next_page = None
        self._btn_import = None
        self._btn_download_example = None
        self._btn_sentence_pause = None
        self._btn_dub_pages = None
        self._btn_result_preview = None
        self._mode_settings_title = None
        self._mode_settings_hint = None
        self._pause_label = None
        self._pause_entry = None
        self._punctuation_label = None
        self._punctuation_frame = None
        self._line_pause_section = None
        self._line_pause_entry = None
        self._sentence_pause_check = None
        self._line_pause_check = None
        self._punctuation_checks = {}
        self._timeline_check = None
        self._srt_check = None

        self._build_ui()
        self._bind_events()

        # 启动后后台加载语音列表 + 网络探测
        self.after(400, self._start_background_jobs)

    # ============================================================ UI 构建

    TRANSLATIONS = {
        "app": {"zh": "Edge TTS 语音合成助手", "en": "Edge TTS Voice Studio"},
        "open": {"zh": "开源 · MIT License", "en": "Open Source · MIT License"},
        "open_badge": {"zh": "免费 · 开源", "en": "Free · Open Source"},
        "github_repo": {"zh": "GitHub 仓库", "en": "GitHub"},
        "github_star": {"zh": "GitHub 点赞", "en": "Star on GitHub"},
        "settings_short": {"zh": "设置", "en": "Settings"},
        "repo": {"zh": "GitHub 仓库 ↗", "en": "GitHub Repo ↗"},
        "star": {"zh": "⭐ 去 GitHub 点 Star", "en": "⭐ Star on GitHub"},
        "developer": {"zh": "开发者", "en": "Developer"},
        "language": {"zh": "EN", "en": "中文"},
        "settings": {"zh": "设置", "en": "Settings"},
        "theme_dark": {"zh": "夜间", "en": "Dark"},
        "theme_light": {"zh": "白天", "en": "Light"},
        "tagline": {"zh": "让文字成为清晰、自然的声音", "en": "Turn text into clear, natural voice"},
        "voice_deck": {"zh": "VOICE DECK", "en": "VOICE DECK"},
        "composer": {"zh": "COMPOSER", "en": "COMPOSER"},
        "checking": {"zh": "●  检测中…", "en": "●  Checking network…"},
        "check_network": {"zh": "检测网络", "en": "Check network"},
        "network_ok": {"zh": "●  网络正常（{latency:.0f} ms）", "en": "●  Network OK ({latency:.0f} ms)"},
        "network_bad": {"zh": "●  网络异常", "en": "●  Network unavailable"},
        "article": {"zh": "文章内容", "en": "Article"},
        "count": {"zh": "字数：{count}", "en": "Characters: {count}"},
        "mode_normal": {"zh": "普通模式", "en": "Normal"},
        "mode_page": {"zh": "逐页模式", "en": "By Page"},
        "mode_line": {"zh": "逐行模式", "en": "By Line"},
        "helper_normal": {"zh": "输入或粘贴文字，右侧直接生成一个音频。", "en": "Type or paste text, then generate one audio file from the controls on the right."},
        "helper_page": {"zh": "逐页模式请在 TXT 中用单独一行的 [分页] 标记分隔页面；标记不会被朗读，每页生成一个音频。", "en": "In page mode, put [分页] on its own line in the TXT file to separate pages; the marker is not spoken and each page becomes one audio file."},
        "helper_line": {"zh": "粘贴文本后点击“按行准备”，或直接导入文件；每个非空行生成一个音频，空行自动忽略。", "en": "Paste text and click Prepare Lines, or import a file; each non-empty line becomes one audio file."},
        "voice": {"zh": "语音", "en": "Voice"},
        "lang": {"zh": "语言", "en": "Language"},
        "gender": {"zh": "性别", "en": "Gender"},
        "gender_all": {"zh": "全部", "en": "All"},
        "gender_female": {"zh": "女声", "en": "Female"},
        "gender_male": {"zh": "男声", "en": "Male"},
        "gender_other": {"zh": "其他", "en": "Other"},
        "timeline": {"zh": "时间轴 JSON + 试听高亮", "en": "Timeline JSON + highlight"},
        "timeline_help_title": {"zh": "时间轴 JSON 与试听高亮", "en": "Timeline JSON & Playback Highlight"},
        "timeline_help_desc": {"zh": "开启后：① 保存/下载音频时，自动打包成 ZIP（内含 MP3 与同名 .timeline.json，记录每句起止秒数）；② 试听播放时，正在朗读的句子会在文章中实时高亮。时间轴与音频在同一次合成中生成，直接使用微软 TTS 返回的句级边界，无需再次合成。", "en": "When enabled: 1) saving/downloading bundles the MP3 and a .timeline.json (each sentence's start/end seconds) into one ZIP; 2) during playback, the sentence being read is highlighted live. Audio and timeline are produced in the same synthesis using Microsoft TTS sentence-boundary metadata - no re-rendering needed."},
        "timeline_help_json_title": {"zh": "示例 .timeline.json", "en": "Example .timeline.json"},
        "timeline_help_highlight_title": {"zh": "高亮演示（试听时实时跟随）", "en": "Highlight demo (follows live during playback)"},
        "timeline_help_demo_btn": {"zh": "▶ 演示高亮", "en": "▶ Demo highlight"},
        "timeline_help_demo_text": {"zh": "第一句：大家好，欢迎使用本工具。第二句：这一句正在被高亮显示。第三句：播放到哪一句，哪一句就会亮起来。", "en": "First sentence: welcome to this tool. Second sentence: this sentence is now highlighted. Third sentence: the sentence being spoken lights up."},
        "timeline_help_note": {"zh": "提示：高亮在点击「试听」后开始，随播放进度逐句跳转；保存时音频与时间轴 JSON 会打包成 ZIP 存到你选择的目录。", "en": "Tip: highlighting starts when you click Play and follows the progress; the audio and timeline JSON are saved together as a ZIP."},
        "timeline_on": {"zh": "已开启：保存时打包 ZIP（音频 + 时间轴 JSON），试听时高亮当前句子", "en": "On: saves a ZIP bundle (audio + timeline JSON); highlights the sentence being read"},
        "timeline_off": {"zh": "已关闭：不再输出时间轴 JSON 与试听高亮", "en": "Off: no timeline JSON or playback highlight"},
        "sentence_pause": {"zh": "默认句间停顿", "en": "Default sentence pause"},
        "sentence_pause_enable": {"zh": "启用句间停顿", "en": "Enable sentence pauses"},
        "line_pause": {"zh": "行末停顿", "en": "Line-end pause"},
        "line_pause_enable": {"zh": "启用行末停顿", "en": "Enable line-end pause"},
        "pause_punctuation": {"zh": "按标点应用（可多选）", "en": "Apply after punctuation (multi-select)"},
        "pause_duration": {"zh": "每次停顿", "en": "Pause length"},
        "punctuation_comma": {"zh": "逗号", "en": "Comma"},
        "punctuation_period": {"zh": "句号", "en": "Period"},
        "punctuation_exclamation": {"zh": "感叹号", "en": "Exclamation"},
        "punctuation_question": {"zh": "问号", "en": "Question"},
        "punctuation_semicolon": {"zh": "分号", "en": "Semicolon"},
        "pause_unit": {"zh": "毫秒", "en": "ms"},
        "pause_directive_help": {"zh": "支持 [pause:500ms]、[pause:1.5s]、[pause:weak/medium/strong]；指令不会被朗读。", "en": "Supports [pause:500ms], [pause:1.5s], and [pause:weak/medium/strong]; markers are not spoken."},
        "sentence_pause_action": {"zh": "批量插入句末停顿", "en": "Insert end pauses"},
        "mode_settings_normal": {"zh": "普通模式 · 音频设置", "en": "Normal · Audio settings"},
        "mode_settings_page": {"zh": "逐页模式 · 音频设置", "en": "By Page · Audio settings"},
        "mode_settings_line": {"zh": "逐行模式 · 音频设置", "en": "By Line · Audio settings"},
        "mode_settings_hint_normal": {"zh": "整段文本生成一个音频文件。", "en": "The full text becomes one audio file."},
        "mode_settings_hint_page": {"zh": "每页独立生成音频，适合章节或镜头批量导出。", "en": "Each page becomes a separate audio file for batch export."},
        "mode_settings_hint_line": {"zh": "每个非空行独立生成音频，适合短句旁白批量导出。", "en": "Each non-empty line becomes a separate audio file for short narration."},
        "pause_label_normal": {"zh": "句间停顿", "en": "Sentence pause"},
        "pause_label_page": {"zh": "每页默认句间停顿", "en": "Default pause per page"},
        "pause_label_line": {"zh": "每行默认句间停顿", "en": "Default pause per line"},
        "pause_dialog_title": {"zh": "批量插入句末停顿", "en": "Insert end-of-sentence pauses"},
        "pause_dialog_hint": {"zh": "在每个句末自动加入 pause 指令（最后一句不添加）。已有指令会跳过。", "en": "Add a pause marker after each sentence (the final sentence is skipped). Existing markers are preserved."},
        "pause_custom": {"zh": "自定义毫秒", "en": "Custom ms"},
        "pause_apply": {"zh": "插入", "en": "Insert"},
        "pause_inserted": {"zh": "已插入 {count} 个句末停顿指令。", "en": "Inserted {count} end-of-sentence pause marker(s)."},
        "pause_invalid": {"zh": "请输入 0 到 10000 之间的整数毫秒。", "en": "Enter an integer from 0 to 10000 milliseconds."},
        "srt_subtitles": {"zh": "生成 SRT 字幕", "en": "Generate SRT subtitles"},

        "search": {"zh": "搜索语音，如：晓晓 / Andrew…", "en": "Search voices, e.g. Xiaoxiao / Andrew…"},
        "voices_load_error": {"zh": "语音列表加载失败，请检查网络后点 ↻ 重试", "en": "Could not load the voice list - check network and click ↻ to retry"},
        "voices_reloading": {"zh": "正在重新加载语音列表…", "en": "Reloading voice list…"},
        "voices_loaded": {"zh": "已加载语音（{count} 个，{langs} 种语言）", "en": "Voices loaded ({count} voices, {langs} languages)"},
        "original": {"zh": "原工作流默认：Andrew Multilingual · 语速 +0% · 音量 +0% · 音调 +0Hz", "en": "Original workflow: Andrew Multilingual · rate +0% · volume +0% · pitch +0Hz"},
        "restore": {"zh": "恢复初始设置", "en": "Restore defaults"},
        "reset_compact": {"zh": "恢复", "en": "Reset"},
        "rate": {"zh": "语速", "en": "Rate"},
        "volume": {"zh": "音量", "en": "Volume"},
        "pitch": {"zh": "音调", "en": "Pitch"},
        "ready": {"zh": "就绪", "en": "Ready"},
        "generate": {"zh": "生成音频", "en": "Generate Audio"},
        "play": {"zh": "▶ 试听", "en": "▶ Play"},
        "save": {"zh": "保存下载", "en": "Save Audio"},
        "generated_ok": {"zh": "已生成 ✔ 可试听 / 保存", "en": "Generated ✔ Play or save"},
        "result_preview": {"zh": "查看结果", "en": "Review result"},
        "result_title": {"zh": "生成结果 · 试听与字幕", "en": "Generated result · Preview & subtitles"},
        "result_audio": {"zh": "音频预览", "en": "Audio preview"},
        "result_text": {"zh": "配音文本（可修改）", "en": "Narration text (editable)"},
        "result_subtitles": {"zh": "SRT 字幕", "en": "SRT subtitles"},
        "result_view_current": {"zh": "当前音频", "en": "Current audio"},
        "result_view_all": {"zh": "全部字幕", "en": "All subtitles"},
        "result_prev": {"zh": "上一条", "en": "Previous"},
        "result_next": {"zh": "下一条", "en": "Next"},
        "result_item_page": {"zh": "第 {current}/{total} 页", "en": "Page {current}/{total}"},
        "result_item_line": {"zh": "第 {current}/{total} 行", "en": "Line {current}/{total}"},
        "result_all_heading": {"zh": "音频 {number:03d}", "en": "Audio {number:03d}"},
        "result_no_subtitles": {"zh": "当前结果没有可用的句级时间轴。生成时开启时间轴后即可查看字幕。", "en": "This result has no sentence timeline. Enable timeline generation to view subtitles."},
        "result_apply": {"zh": "应用修改并重新生成", "en": "Apply edits and regenerate"},
        "result_close": {"zh": "关闭", "en": "Close"},
        "result_table_number": {"zh": "编号", "en": "No."},
        "result_table_text": {"zh": "字幕文本", "en": "Subtitle text"},
        "result_table_timeline": {"zh": "时间轴", "en": "Timeline"},
        "result_table_actions": {"zh": "操作", "en": "Actions"},
        "result_play": {"zh": "试听", "en": "Play"},
        "result_stop": {"zh": "停止", "en": "Stop"},
        "result_regenerate": {"zh": "重新生成", "en": "Regenerate"},
        "result_regenerate_all": {"zh": "全部重新生成", "en": "Regenerate all"},
        "result_export_zip": {"zh": "导出最终 ZIP", "en": "Export final ZIP"},
        "result_saved": {"zh": "修改已应用", "en": "Changes applied"},
        "canceled": {"zh": "已取消", "en": "Canceled"},
        "failed": {"zh": "失败 ✖", "en": "Failed ✖"},
        "stopped": {"zh": "已停止", "en": "Stopped"},
        "no_audio": {"zh": "请先点击“生成音频”生成一段音频。", "en": "Please click “Generate Audio” first."},
        "stop": {"zh": "停止", "en": "Stop"},
        "log": {"zh": "活动日志", "en": "Activity log"},
        "footer": {"zh": "免费开源软件 · MIT License · Powered by Microsoft Edge TTS", "en": "Free open-source software · MIT License · Powered by Microsoft Edge TTS"},
        "repository": {"zh": "仓库：", "en": "Repo: "},
        "empty": {"zh": "请输入文章内容。", "en": "Please enter some article text."},
        "import_file": {"zh": "导入文件", "en": "Import File"},
        "download_example": {"zh": "示例文件", "en": "Example"},
        "page_example_name": {"zh": "逐页配音示例.txt", "en": "page-narration-example.txt"},
        "line_example_name": {"zh": "逐行配音示例.txt", "en": "line-narration-example.txt"},
        "example_saved": {"zh": "示例文件已保存：\n{path}", "en": "Example file saved:\n{path}"},
        "page_dub": {"zh": "逐页配音", "en": "Dub All Pages"},
        "line_dub": {"zh": "逐行配音", "en": "Dub All Lines"},
        "prepare_lines": {"zh": "按行准备", "en": "Prepare Lines"},
        "reprepare_lines": {"zh": "重新按行", "en": "Rebuild Lines"},
        "edit_lines": {"zh": "编辑全部行", "en": "Edit All Lines"},
        "page_label": {"zh": "第 {current}/{total} 页", "en": "Page {current}/{total}"},
        "line_label": {"zh": "第 {current}/{total} 行", "en": "Line {current}/{total}"},
        "page_note": {"zh": "备注", "en": "Note"},
        "page_note_hint": {"zh": "备注不朗读，随 pages.json 一并导出", "en": "Note is not spoken; exported with pages.json"},
        "prev_page": {"zh": "‹ 上一页", "en": "‹ Prev"},
        "next_page": {"zh": "下一页 ›", "en": "Next ›"},
        "prev_line": {"zh": "‹ 上一行", "en": "‹ Prev"},
        "next_line": {"zh": "下一行 ›", "en": "Next ›"},
        "generate_page": {"zh": "生成当前页", "en": "Generate This Page"},
        "generate_line": {"zh": "生成当前行", "en": "Generate This Line"},
        "no_pages": {"zh": "请先点击“导入文件”导入文档进行分页。", "en": "Please import a file first to create pages."},
        "no_lines": {"zh": "请先粘贴文本并点击“按行准备”，或导入一个文件。", "en": "Paste text and click Prepare Lines, or import a file first."},
        "pages_zip_title": {"zh": "保存分页配音压缩包（音频 + pages.json + 备注）", "en": "Save page dubbing bundle (audio + pages.json + notes)"},
        "pages_zip_filetype": {"zh": "ZIP 压缩包（每页 MP3 + pages.json）", "en": "ZIP bundle (per-page MP3 + pages.json)"},
        "lines_zip_title": {"zh": "保存逐行配音压缩包（每行音频 + lines.json）", "en": "Save line dubbing bundle (per-line audio + lines.json)"},
        "lines_zip_filetype": {"zh": "ZIP 压缩包（每行 MP3 + lines.json）", "en": "ZIP bundle (per-line MP3 + lines.json)"},
    }

    def _t(self, key, **kwargs):
        value = self.TRANSLATIONS[key][self._language]
        return value.format(**kwargs) if kwargs else value

    LANGUAGE_NAMES_ZH = {
        "af": "南非语", "am": "阿姆哈拉语", "ar": "阿拉伯语", "as": "阿萨姆语",
        "az": "阿塞拜疆语", "bg": "保加利亚语", "bn": "孟加拉语", "bs": "波斯尼亚语",
        "ca": "加泰罗尼亚语", "cs": "捷克语", "cy": "威尔士语", "da": "丹麦语",
        "de": "德语", "el": "希腊语", "en": "英语", "es": "西班牙语", "et": "爱沙尼亚语",
        "fa": "波斯语", "fi": "芬兰语", "fil": "菲律宾语", "fr": "法语", "ga": "爱尔兰语",
        "gl": "加利西亚语", "gu": "古吉拉特语", "he": "希伯来语", "hi": "印地语",
        "hr": "克罗地亚语", "hu": "匈牙利语", "id": "印度尼西亚语", "is": "冰岛语",
        "it": "意大利语", "ja": "日语", "jv": "爪哇语", "ka": "格鲁吉亚语", "kk": "哈萨克语",
        "km": "高棉语", "kn": "卡纳达语", "ko": "韩语", "lo": "老挝语", "lt": "立陶宛语",
        "lv": "拉脱维亚语", "mk": "马其顿语", "ml": "马拉雅拉姆语", "mn": "蒙古语",
        "mr": "马拉地语", "ms": "马来语", "mt": "马耳他语", "my": "缅甸语", "nb": "挪威语",
        "ne": "尼泊尔语", "nl": "荷兰语", "or": "奥里亚语", "pa": "旁遮普语", "pl": "波兰语",
        "ps": "普什图语", "pt": "葡萄牙语", "ro": "罗马尼亚语", "ru": "俄语", "si": "僧伽罗语",
        "sk": "斯洛伐克语", "sl": "斯洛文尼亚语", "so": "索马里语", "sq": "阿尔巴尼亚语",
        "sr": "塞尔维亚语", "su": "巽他语", "sv": "瑞典语", "sw": "斯瓦希里语", "ta": "泰米尔语",
        "te": "泰卢固语", "th": "泰语", "tr": "土耳其语", "uk": "乌克兰语", "ur": "乌尔都语",
        "uz": "乌兹别克语", "vi": "越南语", "wuu": "吴语", "yue": "粤语", "zh": "中文", "zu": "祖鲁语",
    }
    REGION_NAMES_ZH = {
        "AE": "阿联酋", "AR": "阿根廷", "AT": "奥地利", "AU": "澳大利亚", "BA": "波黑",
        "BD": "孟加拉国", "BE": "比利时", "BG": "保加利亚", "BH": "巴林", "BO": "玻利维亚",
        "BR": "巴西", "CA": "加拿大", "CH": "瑞士", "CL": "智利", "CN": "中国大陆",
        "CO": "哥伦比亚", "CR": "哥斯达黎加", "CZ": "捷克", "DE": "德国", "DK": "丹麦",
        "DO": "多米尼加", "DZ": "阿尔及利亚", "EC": "厄瓜多尔", "EG": "埃及", "ES": "西班牙",
        "ET": "埃塞俄比亚", "FI": "芬兰", "FR": "法国", "GB": "英国", "GE": "格鲁吉亚",
        "GR": "希腊", "GT": "危地马拉", "HK": "中国香港", "HN": "洪都拉斯", "HR": "克罗地亚",
        "HU": "匈牙利", "ID": "印度尼西亚", "IE": "爱尔兰", "IL": "以色列", "IN": "印度",
        "IQ": "伊拉克", "IR": "伊朗", "IS": "冰岛", "IT": "意大利", "JM": "牙买加",
        "JO": "约旦", "JP": "日本", "KE": "肯尼亚", "KH": "柬埔寨", "KR": "韩国",
        "KW": "科威特", "KZ": "哈萨克斯坦", "LA": "老挝", "LK": "斯里兰卡", "LT": "立陶宛",
        "LV": "拉脱维亚", "LY": "利比亚", "MA": "摩洛哥", "MG": "马达加斯加", "MK": "北马其顿",
        "ML": "马里", "MM": "缅甸", "MN": "蒙古", "MO": "中国澳门", "MT": "马耳他",
        "MX": "墨西哥", "MY": "马来西亚", "NG": "尼日利亚", "NI": "尼加拉瓜", "NL": "荷兰",
        "NO": "挪威", "NP": "尼泊尔", "NZ": "新西兰", "OM": "阿曼", "PA": "巴拿马",
        "PE": "秘鲁", "PH": "菲律宾", "PK": "巴基斯坦", "PL": "波兰", "PR": "波多黎各",
        "PS": "巴勒斯坦", "PT": "葡萄牙", "PY": "巴拉圭", "QA": "卡塔尔", "RO": "罗马尼亚",
        "RS": "塞尔维亚", "RU": "俄罗斯", "SA": "沙特阿拉伯", "SE": "瑞典", "SG": "新加坡",
        "SI": "斯洛文尼亚", "SK": "斯洛伐克", "SN": "塞内加尔", "SO": "索马里", "SV": "萨尔瓦多",
        "SY": "叙利亚", "TH": "泰国", "TN": "突尼斯", "TR": "土耳其", "TW": "中国台湾",
        "TZ": "坦桑尼亚", "UA": "乌克兰", "US": "美国", "UY": "乌拉圭", "UZ": "乌兹别克斯坦",
        "VE": "委内瑞拉", "VN": "越南", "ZA": "南非",
    }
    VOICE_NAMES_ZH = {
        "Xiaoxiao": "晓晓", "Xiaoyi": "晓伊", "Yunxi": "云希", "Yunjian": "云健",
        "Yunyang": "云扬", "Yunxia": "云夏", "Yunfeng": "云枫", "Yunze": "云泽",
        "Yunhao": "云皓", "Yunshuo": "云硕", "Xiaochen": "晓辰", "Xiaohan": "晓涵",
        "Xiaomeng": "晓梦", "Xiaomo": "晓墨", "Xiaoqiu": "晓秋", "Xiaorou": "晓柔",
        "Xiaorui": "晓睿", "Xiaoshuang": "晓双", "Xiaoxuan": "晓萱", "Xiaoyan": "晓颜",
        "Xiaoyou": "晓悠", "Xiaozhen": "晓甄", "Xiaochen": "晓辰", "AndrewMultilingual": "安德鲁（多语言）",
    }

    def _app_name(self):
        return self._t("app")

    def _localized_locale(self, locale: str) -> str:
        if self._language != "zh":
            return locale
        parts = (locale or "").split("-", 1)
        language = self.LANGUAGE_NAMES_ZH.get(parts[0].lower(), parts[0] if parts else locale)
        if len(parts) == 2:
            region = self.REGION_NAMES_ZH.get(parts[1].upper(), parts[1])
            return f"{language}（{region}）"
        return language

    def _localized_voice_name(self, code: str) -> str:
        stem = code.rsplit("-", 1)[-1].removesuffix("Neural")
        return self.VOICE_NAMES_ZH.get(stem, stem)

    def _localized_gender(self, gender: str) -> str:
        if self._language != "zh":
            return gender
        return {"Female": "女声", "Male": "男声"}.get(gender, gender)

    def _load_settings(self) -> dict:
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self):
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self._settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self.log(f"[设置] 保存失败：{exc}")

    @staticmethod
    def _preview_file_for(directory: str) -> str:
        return os.path.join(os.path.abspath(os.path.expanduser(directory)), PREVIEW_FILENAME)

    def _cleanup_preview_file(self):
        try:
            if os.path.exists(self._preview_path):
                os.unlink(self._preview_path)
        except OSError:
            pass

    def _show_settings(self):
        if self._busy:
            messagebox.showinfo(self._app_name(), "Please stop the current task first." if self._language == "en" else "请先停止当前任务。")
            return
        is_english = self._language == "en"
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings" if is_english else "设置")
        dialog.geometry("610x300")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(dialog, text="Generated audio cache" if is_english else "生成音频缓存", font=self._font(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=22, pady=(22, 4))
        hint = (
            "Generated audio is kept in one temporary MP3. It is overwritten on the next generation and removed when the app closes."
            if is_english
            else "生成的音频放在一个临时 MP3 文件里：下次生成会覆盖，程序退出时自动删除，不会持续占用空间。"
        )
        ctk.CTkLabel(dialog, text=hint, wraplength=560, justify="left", text_color="#a9b1d6").grid(row=1, column=0, sticky="w", padx=22, pady=(0, 12))

        path_var = tk.StringVar(value=self._preview_dir)
        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=22)
        row.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(row, textvariable=path_var, height=34)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        def choose_directory():
            chosen = filedialog.askdirectory(title="Select generated audio cache folder" if is_english else "选择生成音频缓存目录", initialdir=path_var.get() or os.path.expanduser("~"))
            if chosen:
                path_var.set(chosen)

        ctk.CTkButton(row, text="Browse…" if is_english else "浏览…", width=88, height=34, command=choose_directory).grid(row=0, column=1)

        def save_directory():
            directory = path_var.get().strip()
            if not directory:
                messagebox.showwarning(self._app_name(), "Choose a folder first." if is_english else "请先选择一个目录。")
                return
            directory = os.path.abspath(os.path.expanduser(directory))
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(self._app_name(), str(exc))
                return
            old_path = self._preview_path
            self._preview_dir = directory
            self._preview_path = self._preview_file_for(directory)
            self._settings["preview_dir"] = directory
            self._save_settings()
            try:
                if old_path != self._preview_path and os.path.exists(old_path):
                    os.unlink(old_path)
            except OSError:
                pass
            self._invalidate_generated()
            self.log(("Generated audio cache folder set: " if is_english else "生成音频缓存目录已设置：") + directory)
            dialog.destroy()

        def clear_preview():
            self._stop_playback()
            self._cleanup_preview_file()
            self._invalidate_generated()
            self.log("Generated audio cache cleared." if is_english else "生成音频缓存已清理。")
            messagebox.showinfo(self._app_name(), "Generated audio cache cleared." if is_english else "生成音频缓存已清理。")

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="e", padx=22, pady=(20, 8))
        ctk.CTkButton(buttons, text="Open folder" if is_english else "打开目录", width=104, fg_color="#3a4358", hover_color="#4a546c", command=lambda: os.startfile(self._preview_dir)).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Clear generated audio cache" if is_english else "清理生成缓存", width=150, fg_color="#3a4358", hover_color="#4a546c", command=clear_preview).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Save" if is_english else "保存", width=86, command=save_directory).pack(side="left", padx=4)

    def _font(self, size=13, weight="normal"):
        return ctk.CTkFont(family=self._font_family, size=size, weight=weight)

    def _c(self, key: str) -> str:
        return THEMES[self._theme][key]

    def _rebuild_ui(self):
        text = self._textbox.get("1.0", "end-1c")
        if self._workflow_mode == "normal":
            self._normal_text = text
        elif self._workflow_mode == "line" and not self._pages:
            self._line_draft = text
        voice = self._selected_voice()
        rate = self._rate_var.get()
        volume = self._volume_var.get()
        pitch = self._pitch_var.get()
        for child in self.winfo_children():
            child.destroy()
        self.title(f"{self._app_name()} v{APP_VERSION}")
        self.configure(fg_color=self._c("app_bg"))
        self._rate_value = rate
        self._volume_value = volume
        self._pitch_value = pitch
        self._selected_voice_code = voice
        self._build_ui()
        self._bind_events()
        if text:
            self._textbox.insert("1.0", text)
        self._refresh_voice_selectors()
        self._on_text_changed()
        if self._pages:
            self._page_index = max(0, min(self._page_index, len(self._pages) - 1))
            page = self._pages[self._page_index]
            self._textbox.delete("1.0", "end")
            if page.text:
                self._textbox.insert("1.0", page.text)
            if self._note_var is not None:
                self._note_var.set(page.note)
            self._update_page_bar()
            self._on_text_changed()
            self._sync_generated_status()
        else:
            self._update_page_bar()
        self._update_mode_ui()
        self.after(150, self._poll_ui)

    def _switch_theme(self):
        if self._busy:
            messagebox.showinfo(self._app_name(), "Please stop the current task first." if self._language == "en" else "请先停止当前任务。")
            return
        self._theme = "light" if self._theme == "dark" else "dark"
        self._settings["theme"] = self._theme
        self._save_settings()
        ctk.set_appearance_mode(self._theme)
        self._rebuild_ui()

    def _switch_language(self):
        if self._busy:
            messagebox.showinfo(self._app_name(), "Please stop the current task first." if self._language == "en" else "请先停止当前任务。")
            return
        self._language = "en" if self._language == "zh" else "zh"
        self._rebuild_ui()

    def _build_ui(self):
        self.configure(fg_color=self._c("app_bg"))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_network_bar()
        self._build_workspace()
        self._build_log()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self, corner_radius=18, fg_color=self._c("surface"), border_width=1, border_color=self._c("border"))
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        header.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(header, width=56, height=56, corner_radius=16, fg_color=self._c("primary"))
        brand.grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=12)
        brand.grid_propagate(False)
        ctk.CTkLabel(brand, text="♫", text_color="#FFFFFF", font=self._font(size=30, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(header, text=self._app_name(), text_color=self._c("text"), font=self._font(size=23, weight="bold")).grid(row=0, column=1, sticky="sw", pady=(13, 0))
        ctk.CTkLabel(header, text=self._t("tagline"), text_color=self._c("muted"), font=self._font(size=12)).grid(row=1, column=1, sticky="nw", pady=(0, 13))

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.grid(row=0, column=2, rowspan=2, sticky="e", padx=14, pady=12)
        ctk.CTkLabel(controls, text=self._t("open_badge"), width=98, height=30, corner_radius=15, fg_color=self._c("star"), text_color=self._c("warning"), font=self._font(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        ctk.CTkButton(controls, text=self._t("github_repo"), width=92, height=30, font=self._font(size=12, weight="bold"), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("accent"), command=lambda: webbrowser.open(REPOSITORY_URL)).pack(side="left", padx=2)
        ctk.CTkButton(controls, text=self._t("github_star"), width=104, height=30, font=self._font(size=12, weight="bold"), fg_color=self._c("star"), hover_color=self._c("star_hover"), border_width=1, border_color=self._c("warning"), text_color=self._c("warning"), command=lambda: webbrowser.open(REPOSITORY_URL)).pack(side="left", padx=2)
        ctk.CTkButton(controls, text=self._t("settings_short"), width=52, height=30, font=self._font(size=12), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), text_color=self._c("text"), command=self._show_settings).pack(side="left", padx=(6, 2))
        theme_text = self._t("theme_dark") if self._theme == "dark" else self._t("theme_light")
        ctk.CTkButton(controls, text=theme_text, width=52, height=30, font=self._font(size=12), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), text_color=self._c("text"), command=self._switch_theme).pack(side="left", padx=2)
        ctk.CTkButton(controls, text=self._t("language"), width=40, height=30, font=self._font(size=12, weight="bold"), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), text_color=self._c("text"), command=self._switch_language).pack(side="left", padx=(2, 0))
    def _badge(self, master, text, color):
        return ctk.CTkLabel(master, text=text, text_color=color, font=self._font(size=12, weight="bold"))

    def _build_network_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=14, fg_color=self._c("surface_alt"))
        bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(bar, text="●", text_color=self._c("warning"), font=self._font(size=18)).grid(row=0, column=0, padx=(16, 6), pady=7)
        self._net_dot = ctk.CTkLabel(bar, text=self._t("checking"), text_color=self._c("text"), font=self._font(size=13, weight="bold"))
        self._net_dot.grid(row=0, column=1, sticky="w", pady=7)
        ctk.CTkButton(bar, text=self._t("check_network"), width=116, height=30, fg_color=self._c("card_raised"), hover_color=self._c("border"), text_color=self._c("accent"), command=self._on_check_network).grid(row=0, column=2, padx=10, pady=7)

    def _build_workspace(self):
        workspace = ctk.CTkFrame(self, fg_color="transparent")
        workspace.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 10))
        workspace.grid_columnconfigure(0, weight=1)
        workspace.grid_columnconfigure(1, weight=0)
        workspace.grid_rowconfigure(0, weight=1)

        composer = ctk.CTkFrame(workspace, corner_radius=20, fg_color=self._c("surface"), border_width=1, border_color=self._c("border"))
        composer.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        composer.grid_columnconfigure(0, weight=1)
        composer.grid_rowconfigure(3, weight=1)
        mode_row = ctk.CTkFrame(composer, fg_color="transparent")
        mode_row.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 2))
        mode_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mode_row, text=self._t("composer"), text_color=self._c("accent"), font=self._font(size=11, weight="bold")).grid(row=0, column=0, sticky="w", padx=(0, 12))
        mode_values = [self._t("mode_normal"), self._t("mode_page"), self._t("mode_line")]
        self._mode_value_to_key = dict(zip(mode_values, ("normal", "page", "line")))
        self._mode_selector = ctk.CTkSegmentedButton(
            mode_row,
            values=mode_values,
            command=self._on_mode_changed,
            height=28,
            font=self._font(size=12, weight="bold"),
            fg_color=self._c("surface_alt"),
            selected_color=self._c("primary"),
            selected_hover_color=self._c("primary_hover"),
            unselected_color=self._c("surface_alt"),
            unselected_hover_color=self._c("card_raised"),
            text_color=self._c("text"),
        )
        self._mode_selector.grid(row=0, column=1, sticky="e")
        self._mode_selector.set(self._t(f"mode_{self._workflow_mode}"))
        title_row = ctk.CTkFrame(composer, fg_color="transparent")
        title_row.grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 6))
        ctk.CTkLabel(title_row, text=self._t("article"), text_color=self._c("text"), font=self._font(size=18, weight="bold")).pack(side="left")
        title_actions = ctk.CTkFrame(title_row, fg_color="transparent")
        title_actions.pack(side="right")
        self._btn_import = ctk.CTkButton(title_actions, text=self._t("import_file"), width=88, height=26, font=self._font(size=12, weight="bold"), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("accent"), command=self._on_import_file)
        self._btn_download_example = ctk.CTkButton(title_actions, text=self._t("download_example"), width=72, height=26, font=self._font(size=12), fg_color="transparent", hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("muted"), command=self._on_download_example)
        self._btn_prepare_lines = ctk.CTkButton(title_actions, text=self._t("prepare_lines"), width=88, height=26, font=self._font(size=12, weight="bold"), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("accent"), command=self._on_prepare_lines)
        self._char_count = ctk.CTkLabel(title_actions, text=self._t("count", count=0), text_color=self._c("muted"), font=self._font(size=12))
        self._char_count.pack(side="left", padx=(0, 4))

        # 分页工具栏（导入文件后显示）
        self._page_bar = ctk.CTkFrame(composer, fg_color="transparent")
        self._page_bar.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 6))
        self._page_bar.grid_columnconfigure(4, weight=1)
        self._btn_prev_page = ctk.CTkButton(self._page_bar, text=self._t("prev_page"), width=84, height=28, font=self._font(size=12), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), command=self._on_prev_page, state="disabled")
        self._btn_prev_page.grid(row=0, column=0, padx=(0, 6))
        self._page_label = ctk.CTkLabel(self._page_bar, text=self._t("page_label", current=1, total=1), text_color=self._c("accent"), font=self._font(size=13, weight="bold"))
        self._page_label.grid(row=0, column=1, padx=(0, 6))
        self._btn_next_page = ctk.CTkButton(self._page_bar, text=self._t("next_page"), width=84, height=28, font=self._font(size=12), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), command=self._on_next_page, state="disabled")
        self._btn_next_page.grid(row=0, column=2, padx=(0, 12))
        ctk.CTkLabel(self._page_bar, text=self._t("page_note"), text_color=self._c("muted"), font=self._font(size=12)).grid(row=0, column=3, sticky="w")
        note_cell = ctk.CTkFrame(self._page_bar, fg_color="transparent")
        note_cell.grid(row=0, column=4, sticky="ew")
        note_cell.grid_columnconfigure(0, weight=1)
        self._note_var = tk.StringVar(value="")
        self._note_entry = ctk.CTkEntry(note_cell, textvariable=self._note_var, height=28, fg_color=self._c("field"), border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=12))
        self._note_entry.grid(row=0, column=0, sticky="ew")
        self._note_entry.bind("<KeyRelease>", self._on_note_edited)
        self._page_bar.grid_remove()

        self._textbox = ctk.CTkTextbox(composer, wrap="word", corner_radius=14, fg_color=self._c("field"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=14))
        self._textbox.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 8))
        self._helper_label = ctk.CTkLabel(composer, text=self._t(f"helper_{self._workflow_mode}"), text_color=self._c("muted"), anchor="w", justify="left", wraplength=520, font=self._font(size=12))
        self._helper_label.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 14))

        # CTkScrollableFrame is backed by a native Canvas on Windows. Keeping its
        # scrolling surface square prevents Canvas redraw trails around rounded borders.
        deck_shell = ctk.CTkFrame(
            workspace,
            width=375,
            corner_radius=16,
            fg_color=self._c("card"),
            border_width=1,
            border_color=self._c("border"),
        )
        deck_shell.grid(row=0, column=1, sticky="nsew")
        deck_shell.grid_columnconfigure(0, weight=1)
        deck_shell.grid_rowconfigure(0, weight=1)
        deck = ctk.CTkScrollableFrame(
            deck_shell,
            width=373,
            corner_radius=0,
            fg_color=self._c("card"),
            border_width=0,
            scrollbar_fg_color=self._c("card"),
            scrollbar_button_color=self._c("border"),
            scrollbar_button_hover_color=self._c("card_raised"),
        )
        deck.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        deck.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(deck, text=self._t("voice"), text_color=self._c("text"), font=self._font(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(12, 5))

        # 语言 / 性别 二级筛选
        selectors = ctk.CTkFrame(deck, fg_color="transparent")
        selectors.grid(row=1, column=0, sticky="ew", padx=18)
        selectors.grid_columnconfigure(0, weight=3)
        selectors.grid_columnconfigure(1, weight=2)
        lang_cell = ctk.CTkFrame(selectors, fg_color="transparent")
        lang_cell.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkLabel(lang_cell, text=self._t("lang"), text_color=self._c("muted"), font=self._font(size=10, weight="bold")).pack(anchor="w")
        self._lang_var = tk.StringVar(value="")
        self._lang_combo = ctk.CTkComboBox(
            lang_cell, values=[], variable=self._lang_var, height=30,
            fg_color=self._c("field"), border_color=self._c("border"),
            button_color=self._c("primary"), button_hover_color=self._c("primary_hover"),
            text_color=self._c("text"), dropdown_fg_color=self._c("surface"),
            dropdown_hover_color=self._c("card_raised"),
            font=self._font(size=12), dropdown_font=self._font(size=12),
            command=self._on_language_changed,
        )
        self._lang_combo.pack(fill="x")

        gender_cell = ctk.CTkFrame(selectors, fg_color="transparent")
        gender_cell.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ctk.CTkLabel(gender_cell, text=self._t("gender"), text_color=self._c("muted"), font=self._font(size=10, weight="bold")).pack(anchor="w")
        self._gender_var = tk.StringVar(value="")
        self._gender_combo = ctk.CTkComboBox(
            gender_cell, values=[], variable=self._gender_var, height=30,
            fg_color=self._c("field"), border_color=self._c("border"),
            button_color=self._c("primary"), button_hover_color=self._c("primary_hover"),
            text_color=self._c("text"), dropdown_fg_color=self._c("surface"),
            dropdown_hover_color=self._c("card_raised"),
            font=self._font(size=12), dropdown_font=self._font(size=12),
            command=self._on_gender_changed,
        )
        self._gender_combo.pack(fill="x")

        # 音色 最终列表
        self._voice_var = tk.StringVar(value=self._display_name(self._selected_voice_code))
        self._voice_combo = ctk.CTkComboBox(
            deck, values=[self._voice_var.get()], variable=self._voice_var, height=32,
            fg_color=self._c("field"), border_color=self._c("border"),
            button_color=self._c("primary"), button_hover_color=self._c("primary_hover"),
            text_color=self._c("text"), dropdown_fg_color=self._c("surface"),
            dropdown_hover_color=self._c("card_raised"),
            font=self._font(size=13), dropdown_font=self._font(size=13),
            command=self._on_voice_changed,
        )
        self._voice_combo.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 5))

        voice_details = ctk.CTkFrame(deck, fg_color="transparent")
        voice_details.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 3))
        voice_details.grid_columnconfigure(0, weight=1)
        self._voice_info = ctk.CTkLabel(voice_details, text="", text_color=self._c("muted"), anchor="w", font=self._font(size=11))
        self._voice_info.grid(row=0, column=0, sticky="ew")
        self._btn_reload_voices = ctk.CTkButton(voice_details, text="↻", width=34, height=28, font=self._font(size=13, weight="bold"), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("accent"), state="disabled", command=self._retry_load_voices)
        self._btn_reload_voices.grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(voice_details, text=self._t("restore"), width=118, height=28, font=self._font(size=12), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("accent"), command=self._restore_default_settings).grid(row=0, column=2, padx=(8, 0))

        # 当前模式的音频设置统一放在右侧，避免顶部内容操作互相挤压。
        mode_settings = ctk.CTkFrame(deck, corner_radius=12, fg_color=self._c("surface_alt"), border_width=1, border_color=self._c("border"))
        mode_settings.grid(row=4, column=0, sticky="ew", padx=18, pady=(4, 6))
        mode_settings.grid_columnconfigure(0, weight=1)
        self._mode_settings_title = ctk.CTkLabel(mode_settings, text="", text_color=self._c("text"), anchor="w", font=self._font(size=14, weight="bold"))
        self._mode_settings_title.grid(row=0, column=0, sticky="w", padx=14, pady=(11, 0))
        self._mode_settings_hint = ctk.CTkLabel(mode_settings, text="", text_color=self._c("muted"), anchor="w", justify="left", wraplength=315, font=self._font(size=11))
        self._mode_settings_hint.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 7))

        pause_row = ctk.CTkFrame(mode_settings, fg_color="transparent")
        pause_row.grid(row=2, column=0, sticky="ew", padx=14)
        pause_row.grid_columnconfigure(0, weight=1)
        self._sentence_pause_check = ctk.CTkCheckBox(
            pause_row,
            text=self._t("sentence_pause_enable"),
            variable=tk.BooleanVar(value=self._sentence_pause_enabled),
            command=self._toggle_sentence_pause,
            font=self._font(size=12, weight="bold"),
            text_color=self._c("text"),
            border_color=self._c("border"),
            hover_color=self._c("card_raised"),
            fg_color=self._c("primary"),
            checkbox_width=20, checkbox_height=20, border_width=2,
        )
        self._sentence_pause_check.grid(row=0, column=0, sticky="w")
        self._pause_var = tk.StringVar(value=str(self._sentence_pause_ms))
        duration_row = ctk.CTkFrame(pause_row, fg_color="transparent")
        duration_row.grid(row=1, column=0, sticky="w", pady=(5, 0))
        ctk.CTkLabel(duration_row, text=self._t("pause_duration"), text_color=self._c("muted"), font=self._font(size=11)).pack(side="left", padx=(0, 8))
        self._pause_entry = ctk.CTkEntry(duration_row, textvariable=self._pause_var, width=82, height=30, justify="right", fg_color=self._c("field"), border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=12))
        self._pause_entry.pack(side="left")
        self._pause_entry.bind("<FocusOut>", self._on_pause_changed)
        self._pause_entry.bind("<Return>", self._on_pause_changed)
        ctk.CTkLabel(duration_row, text=self._t("pause_unit"), text_color=self._c("muted"), font=self._font(size=11)).pack(side="left", padx=(6, 0))
        self._punctuation_label = ctk.CTkLabel(pause_row, text=self._t("pause_punctuation"), text_color=self._c("muted"), anchor="w", font=self._font(size=11, weight="bold"))
        self._punctuation_label.grid(row=2, column=0, sticky="w", pady=(9, 3))
        self._punctuation_frame = ctk.CTkFrame(pause_row, fg_color=self._c("field"), corner_radius=8, border_width=1, border_color=self._c("border"))
        self._punctuation_frame.grid(row=3, column=0, sticky="ew")
        for column in range(2):
            self._punctuation_frame.grid_columnconfigure(column, weight=1, uniform="punctuation")
        punctuation_defs = (
            ("comma", ",", {"，", ","}),
            ("period", "。", {"。", "."}),
            ("exclamation", "!", {"！", "!"}),
            ("question", "?", {"？", "?"}),
            ("semicolon", ";", {"；", ";"}),
        )
        for index, (key, mark, marks) in enumerate(punctuation_defs):
            var = tk.BooleanVar(value=bool(marks & self._sentence_pause_marks))
            label = f"{self._t('punctuation_' + key)}  {mark}"
            check = ctk.CTkCheckBox(
                self._punctuation_frame, text=label, variable=var,
                command=self._on_punctuation_changed, font=self._font(size=12),
                text_color=self._c("text"), border_color=self._c("border"),
                hover_color=self._c("card_raised"), fg_color=self._c("primary"),
                checkbox_width=20, checkbox_height=20, border_width=2,
            )
            row, column = divmod(index, 2)
            check.grid(row=row, column=column, sticky="w", padx=(12, 8), pady=(8 if row == 0 else 4, 8 if row == 2 else 4))
            self._punctuation_checks[key] = (var, marks, check)
        self._set_sentence_pause_controls_enabled(self._sentence_pause_enabled)

        self._line_pause_section = ctk.CTkFrame(mode_settings, fg_color=self._c("field"), corner_radius=8, border_width=1, border_color=self._c("border"))
        self._line_pause_section.grid(row=3, column=0, sticky="ew", padx=14, pady=(9, 4))
        self._line_pause_section.grid_columnconfigure(0, weight=1)
        self._line_pause_check = ctk.CTkCheckBox(self._line_pause_section, text=self._t("line_pause_enable"), variable=tk.BooleanVar(value=self._line_pause_enabled), command=self._toggle_line_pause, font=self._font(size=11, weight="bold"), text_color=self._c("text"), border_color=self._c("border"), hover_color=self._c("card_raised"), fg_color=self._c("primary"), checkbox_width=20, checkbox_height=20, border_width=2)
        self._line_pause_check.grid(row=0, column=0, sticky="w", padx=10, pady=(7, 0))
        self._line_pause_var = tk.StringVar(value=str(self._line_pause_ms))
        line_duration_row = ctk.CTkFrame(self._line_pause_section, fg_color="transparent")
        line_duration_row.grid(row=1, column=0, sticky="w", padx=10, pady=(4, 7))
        ctk.CTkLabel(line_duration_row, text=self._t("pause_duration"), text_color=self._c("muted"), font=self._font(size=11)).pack(side="left", padx=(0, 8))
        self._line_pause_entry = ctk.CTkEntry(line_duration_row, textvariable=self._line_pause_var, width=82, height=30, justify="right", fg_color=self._c("surface"), border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=12))
        self._line_pause_entry.pack(side="left")
        self._line_pause_entry.bind("<FocusOut>", self._on_line_pause_changed)
        self._line_pause_entry.bind("<Return>", self._on_line_pause_changed)
        ctk.CTkLabel(line_duration_row, text=self._t("pause_unit"), text_color=self._c("muted"), font=self._font(size=11)).pack(side="left", padx=(6, 0))
        self._set_line_pause_controls_enabled(self._line_pause_enabled)

        timeline_row = ctk.CTkFrame(mode_settings, fg_color="transparent")
        timeline_row.grid(row=4, column=0, sticky="ew", padx=14)
        self._timeline_var = tk.BooleanVar(value=self._timeline_enabled)
        self._timeline_check = ctk.CTkCheckBox(timeline_row, text=self._t("timeline"), variable=self._timeline_var, command=self._toggle_timeline, font=self._font(size=12), text_color=self._c("text"), border_color=self._c("border"), hover_color=self._c("card_raised"), fg_color=self._c("primary"), checkbox_width=20, checkbox_height=20, border_width=2)
        self._timeline_check.pack(side="left")
        ctk.CTkButton(timeline_row, text=" ? ", width=30, height=24, font=self._font(size=12, weight="bold"), fg_color="transparent", hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("accent"), command=self._show_timeline_help).pack(side="left", padx=(6, 0))

        self._srt_var = tk.BooleanVar(value=self._srt_enabled)
        self._srt_check = ctk.CTkCheckBox(mode_settings, text=self._t("srt_subtitles"), variable=self._srt_var, command=self._toggle_srt, font=self._font(size=12), text_color=self._c("text"), border_color=self._c("border"), hover_color=self._c("card_raised"), fg_color=self._c("primary"), checkbox_width=20, checkbox_height=20, border_width=2)
        self._srt_check.grid(row=5, column=0, sticky="w", padx=14, pady=(4, 10))

        parameters = ctk.CTkFrame(deck, corner_radius=12, fg_color=self._c("surface_alt"))
        parameters.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 5))
        for column in range(3):
            parameters.grid_columnconfigure(column, weight=1, uniform="voice_control")
        self._rate_var = tk.IntVar(value=getattr(self, "_rate_value", DEFAULT_RATE))
        self._volume_var = tk.IntVar(value=getattr(self, "_volume_value", DEFAULT_VOLUME))
        self._pitch_var = tk.IntVar(value=getattr(self, "_pitch_value", DEFAULT_PITCH))
        self._add_slider_card(parameters, 0, self._t("rate"), self._rate_var, -50, 100, self._fmt_rate)
        self._add_slider_card(parameters, 1, self._t("volume"), self._volume_var, -50, 100, self._fmt_volume)
        self._add_slider_card(parameters, 2, self._t("pitch"), self._pitch_var, -20, 20, self._fmt_pitch)

        status_row = ctk.CTkFrame(deck, fg_color="transparent")
        status_row.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 3))
        status_row.grid_columnconfigure(0, weight=1)
        self._status_label = ctk.CTkLabel(status_row, text=self._t("ready"), text_color=self._c("success"), font=self._font(size=12, weight="bold"))
        self._status_label.grid(row=0, column=0, sticky="w")
        self._btn_stop = ctk.CTkButton(status_row, text=self._t("stop"), command=self._on_stop, width=60, height=22, font=self._font(size=11), fg_color="transparent", hover_color=self._c("card_raised"), text_color=self._c("danger"), state="disabled")
        self._btn_stop.grid(row=0, column=1, sticky="e")
        self._progress = ctk.CTkProgressBar(deck, height=8, mode="determinate", progress_color=self._c("primary"), fg_color=self._c("border"))
        self._progress.grid(row=7, column=0, sticky="ew", padx=18, pady=(0, 5))
        self._progress.set(0)

        actions = ctk.CTkFrame(deck, fg_color="transparent")
        actions.grid(row=8, column=0, sticky="ew", padx=18, pady=(0, 9))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        self._btn_generate = ctk.CTkButton(actions, text=self._t("generate"), command=self._on_generate, height=36, font=self._font(size=14, weight="bold"), fg_color=self._c("primary"), hover_color=self._c("primary_hover"), text_color="#FFFFFF")
        self._btn_generate.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self._btn_dub_pages = ctk.CTkButton(actions, text=self._t("page_dub"), command=self._on_dub_pages, height=32, font=self._font(size=12, weight="bold"), fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("accent"))
        self._btn_dub_pages.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self._btn_play = ctk.CTkButton(actions, text=self._t("play"), command=self._on_play, height=32, font=self._font(size=12, weight="bold"), fg_color=self._c("surface_alt"), hover_color=self._c("border"), text_color=self._c("text"))
        self._btn_play.grid(row=2, column=0, sticky="ew", padx=(0, 4))
        self._btn_save = ctk.CTkButton(actions, text=self._t("save"), command=self._on_save, height=32, font=self._font(size=12, weight="bold"), fg_color=self._c("star"), hover_color=self._c("star_hover"), border_width=1, border_color=self._c("warning"), text_color=self._c("warning"))
        self._btn_save.grid(row=2, column=1, sticky="ew", padx=(4, 0))
        self._btn_result_preview = ctk.CTkButton(actions, text=self._t("result_preview"), command=self._open_result_preview, height=30, font=self._font(size=12, weight="bold"), fg_color="transparent", hover_color=self._c("card_raised"), border_width=1, border_color=self._c("border"), text_color=self._c("accent"))
        self._btn_result_preview.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._configure_highlight_tag()
        self._sync_generated_status()
        self._update_generated_buttons()
        self._update_voice_info()
        self._update_page_bar()
        self._update_mode_ui()

    def _add_slider_card(self, master, column, label, variable, minimum, maximum, formatter):
        card = ctk.CTkFrame(master, fg_color="transparent")
        card.grid(row=0, column=column, sticky="ew", padx=6, pady=5)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=label, text_color=self._c("muted"), anchor="w", font=self._font(size=11, weight="bold")).grid(row=0, column=0, sticky="w")
        value_label = ctk.CTkLabel(card, text=formatter(variable.get()), text_color=self._c("accent"), anchor="e", font=self._font(size=11, weight="bold"))
        value_label.grid(row=1, column=0, sticky="ew", pady=(1, 1))
        def _on_slider_change(value):
            value_label.configure(text=formatter(value))
            self._invalidate_generated()

        slider = ctk.CTkSlider(card, height=14, from_=minimum, to=maximum, variable=variable, button_color=self._c("primary"), button_hover_color=self._c("primary_hover"), progress_color=self._c("primary"), fg_color=self._c("border"), command=_on_slider_change)
        slider.grid(row=2, column=0, sticky="ew")

    def _fmt_rate(self, value):
        return f"{'+' if value >= 0 else ''}{int(value)}%"

    def _fmt_volume(self, value):
        return f"{'+' if value >= 0 else ''}{int(value)}%"

    def _fmt_pitch(self, value):
        return f"{'+' if value >= 0 else ''}{int(value)}Hz"

    def _build_log(self):
        log_frame = ctk.CTkFrame(self, corner_radius=18, fg_color=self._c("surface"), border_width=1, border_color=self._c("border"))
        log_frame.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 8))
        log_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_frame, text=self._t("log"), text_color=self._c("text"), font=self._font(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(9, 2))
        self._log = ctk.CTkTextbox(log_frame, height=72, corner_radius=12, fg_color=self._c("log"), text_color=self._c("text"), border_width=0, font=self._font(size=12))
        self._log.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self._log.configure(state="disabled")

    def _build_footer(self):
        footer = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(footer, text=self._t("footer"), text_color=self._c("muted"), font=self._font(size=11)).grid(row=0, column=0, sticky="w")
        qq_suffix = f"（QQ {DEVELOPER_QQ}）" if self._language == "zh" else f" (QQ {DEVELOPER_QQ})"
        ctk.CTkLabel(footer, text=f"{self._t('developer')} · {DEVELOPER}{qq_suffix}  |  {REPOSITORY_DISPLAY}", text_color=self._c("muted"), font=self._font(size=11)).grid(row=0, column=1, sticky="e")

    # ============================================================ 事件绑定

    def _bind_events(self):
        self._textbox.bind("<KeyRelease>", self._on_text_edited)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ============================================================ 后台任务

    def _start_background_jobs(self):
        threading.Thread(target=self._load_voices, daemon=True).start()
        threading.Thread(target=self._probe_worker, daemon=True).start()
        self.after(150, self._poll_ui)

    def _load_voices(self):
        proxy = detect_proxy()
        last_err = ""
        for attempt in range(1, 4):
            try:
                voices = list_tts_voices(proxy=proxy)
                self._ui_q.put(("voices", voices, ""))
                return
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)[:300]
                if attempt < 3:
                    time.sleep(3)
        self._ui_q.put(("voices", [], last_err))

    def _probe_worker(self):
        result = probe_network()
        self._ui_q.put(("network", result))

    # ============================================================ UI 轮询

    def _poll_ui(self):
        try:
            while True:
                item = self._ui_q.get_nowait()
                self._handle_ui_message(item)
        except queue.Empty:
            pass

        # 处理“卡住”询问
        try:
            while True:
                msg = self._stall_req_q.get_nowait()
                decision = self._show_stall_dialog(msg)
                if self._stall_controller is not None:
                    self._stall_controller.decide(decision)
        except queue.Empty:
            pass

        self.after(150, self._poll_ui)

    def _handle_ui_message(self, item):
        kind = item[0]
        if kind == "network":
            result: ProbeResult = item[1]
            self._apply_network_result(result)
        elif kind == "voices":
            voices, err = item[1], item[2]
            self._apply_voices(voices, err)
        elif kind == "log":
            self.log(item[1])
        elif kind == "progress":
            percent, written = item[1], item[2]
            current_page, total_pages = None, None
            if len(item) > 4:
                current_page, total_pages = item[3], item[4]
            if current_page is not None:
                is_line = self._batch_mode == "line"
                label = (
                    f"Dubbing {'line' if is_line else 'page'} {current_page}/{total_pages}… {percent:.0f}% · {written / 1024:.0f} KB"
                    if self._language == "en"
                    else f"{'逐行' if is_line else '逐页'}配音 第 {current_page}/{total_pages} {'行' if is_line else '页'}… {percent:.0f}% · 已接收 {written / 1024:.0f} KB"
                )
            else:
                label = (
                    f"Synthesizing… {percent}% · {written / 1024:.0f} KB"
                    if self._language == "en"
                    else f"正在合成… {percent}% · 已接收 {written / 1024:.0f} KB"
                )
            self._progress.configure(mode="determinate")
            self._progress.set(percent / 100)
            self._status_label.configure(text=label)
        elif kind == "task_done":
            self._on_task_done(item[1], item[2])
        elif kind == "batch_done":
            self._on_batch_done(item[1])
        elif kind == "result_row_done":
            self._on_result_row_done(item[1], item[2])

    # ============================================================ 网络

    def _on_check_network(self):
        self._net_dot.configure(text="●  检测中…", text_color="#e0af68")
        self.log("开始检测网络…")
        threading.Thread(target=self._probe_worker, daemon=True).start()

    def _apply_network_result(self, result: ProbeResult):
        if result.reachable:
            self._net_dot.configure(
                text=self._t("network_ok", latency=result.latency_ms), text_color="#9ece6a"
            )
            proxy = result.proxy or detect_proxy()
            note = f"（代理：{proxy}）" if proxy else ""
            self.log(f"网络检测通过{note}")
        else:
            self._net_dot.configure(text=self._t("network_bad"), text_color="#f7768e")
            if result.proxy:
                self.log(
                    f"[网络] 不可达，检测到代理 {result.proxy}，"
                    "可能是网络不通或代理设置不正确。"
                )
            else:
                self.log(
                    f"[网络] 不可达（{result.error}）。生成可能很慢或失败，建议检查网络后重试。"
                )

    # ============================================================ 语音

    def _display_name(self, code: str) -> str:
        info = self._voice_map.get(code)
        if info:
            if self._language == "zh":
                name = self._localized_voice_name(code)
                locale = self._localized_locale(info.get("Locale", ""))
                gender = self._localized_gender(info.get("Gender", ""))
                return f"{name} · {locale} · {gender}（{code}）"
            friendly = info.get("FriendlyName") or code
            return f"{friendly} ({code})"
        return code

    def _on_language_changed(self, value):
        code = self._lang_map.get(value)
        if not code or code == self._selected_lang:
            return
        self._selected_lang = code
        self._refresh_voice_selectors()
        self._invalidate_generated()

    def _on_gender_changed(self, value):
        key = self._gender_map.get(value)
        if not key or key == self._selected_gender:
            return
        self._selected_gender = key
        self._refresh_voice_selectors()
        self._invalidate_generated()

    def _on_voice_changed(self, value):
        for code in list(self._voice_map):
            if self._display_name(code) == value:
                self._selected_voice_code = code
                break
        else:
            return
        if self._groups_engine is not None:
            actual = self._groups_engine.voice_gender(self._selected_voice_code)
            genders = self._groups_engine.genders(self._selected_lang)
            if actual in genders and actual != self._selected_gender:
                self._selected_gender = actual
                label = next((k for k, v in self._gender_map.items() if v == actual), "")
                if label:
                    self._gender_var.set(label)
        self._update_voice_info()
        self._invalidate_generated()

    def _restore_default_settings(self):
        self._selected_voice_code = DEFAULT_VOICE
        self._selected_lang = "en"
        self._selected_gender = "Male"
        self._rate_var.set(DEFAULT_RATE)
        self._volume_var.set(DEFAULT_VOLUME)
        self._pitch_var.set(DEFAULT_PITCH)
        self._refresh_voice_selectors(preferred=DEFAULT_VOICE)
        self._invalidate_generated()
        self._update_voice_info()
        self.log(self._t("original"))

    def _selected_voice(self) -> str:
        value = self._voice_var.get()
        for code in self._voice_map:
            if self._display_name(code) == value:
                self._selected_voice_code = code
                return code
        return self._selected_voice_code or DEFAULT_VOICE

    def _update_voice_info(self):
        code = self._selected_voice()
        info = self._voice_map.get(code)
        if info:
            locale = self._localized_locale(info.get("Locale", ""))
            gender = self._localized_gender(info.get("Gender", ""))
            self._voice_info.configure(text=f"{locale} · {gender}")
        else:
            self._voice_info.configure(text="")

    def _gender_label(self, key: str) -> str:
        if key == GENDER_ALL:
            return self._t("gender_all")
        return {
            GENDER_FEMALE: self._t("gender_female"),
            GENDER_MALE: self._t("gender_male"),
            GENDER_OTHER: self._t("gender_other"),
        }.get(key, key)

    def _localized_lang_name(self, code: str) -> str:
        if self._language == "zh":
            return f"{self.LANGUAGE_NAMES_ZH.get(code, code)}（{code}）"
        return code.capitalize() if code.islower() else code

    def _retry_load_voices(self):
        if self._btn_reload_voices:
            self._btn_reload_voices.configure(state="disabled")
        self._voices_load_error = None
        self._voice_info.configure(text=self._t("voices_reloading"), text_color=self._c("muted"))
        self.log("[语音] 正在重新加载语音列表…")
        threading.Thread(target=self._load_voices, daemon=True).start()

    def _refresh_voice_selectors(self, preferred: Optional[str] = None):
        """重建 语言 → 性别 → 音色 三级下拉（本地分组，无远端请求）。"""
        engine = self._groups_engine
        if engine is None:
            self._refresh_voice_fallback()
            return
        langs = engine.languages()
        if not langs:
            self._refresh_voice_fallback()
            return

        def _lang_key(code: str):
            order = {"zh": 0, "en": 1}
            return (order.get(code, 2), self._localized_lang_name(code).lower())

        ordered = sorted(langs, key=_lang_key)
        self._lang_map = {self._localized_lang_name(c): c for c in ordered}
        if self._selected_lang not in langs:
            self._selected_lang = "en" if "en" in langs else langs[0]
        self._lang_combo.configure(values=list(self._lang_map.keys()))
        lang_label = next(k for k, v in self._lang_map.items() if v == self._selected_lang)
        self._lang_var.set(lang_label)

        genders = engine.genders(self._selected_lang)
        gender_opts = [GENDER_ALL] + genders
        self._gender_map = {self._gender_label(g): g for g in gender_opts}
        if self._selected_gender not in gender_opts:
            self._selected_gender = GENDER_ALL
        self._gender_combo.configure(values=list(self._gender_map.keys()))
        gender_label = next(k for k, v in self._gender_map.items() if v == self._selected_gender)
        self._gender_var.set(gender_label)

        voices = engine.voices(
            self._selected_lang,
            None if self._selected_gender == GENDER_ALL else self._selected_gender,
        )
        codes = [v.get("ShortName") for v in voices]
        target = preferred or self._selected_voice_code
        if target not in codes:
            if self._selected_lang == "en" and DEFAULT_VOICE in codes:
                target = DEFAULT_VOICE
            else:
                target = codes[0] if codes else self._selected_voice_code
        self._selected_voice_code = target
        names = [self._display_name(c) for c in codes]
        self._voice_combo.configure(values=names)
        self._voice_var.set(self._display_name(target) if names else "")
        self._update_voice_info()

    def _refresh_voice_fallback(self):
        """语音列表尚未加载/加载失败时：语言、性别、音色至少保留默认项，避免下拉为空。"""
        lang_name = self._localized_lang_name(self._selected_lang)
        self._lang_map = {lang_name: self._selected_lang}
        self._lang_combo.configure(values=[lang_name])
        self._lang_var.set(lang_name)
        gender_name = self._gender_label(self._selected_gender)
        self._gender_map = {gender_name: self._selected_gender}
        self._gender_combo.configure(values=[gender_name])
        self._gender_var.set(gender_name)
        codes = [self._selected_voice_code] if self._selected_voice_code else []
        names = [self._display_name(c) for c in codes]
        self._voice_combo.configure(values=names)
        if names:
            self._voice_var.set(names[0])
        if self._voices_load_error:
            self._voice_info.configure(text=self._t("voices_load_error"), text_color="#f7768e")
        else:
            self._update_voice_info()
    def _apply_voices(self, voices, err):
        self._voices_load_error = err
        if err:
            self.log(f"[语音] 加载语音列表失败：{err}")
            self._refresh_voice_fallback()
            if self._btn_reload_voices:
                self._btn_reload_voices.configure(state="normal")
            return
        self._voice_map = {v["ShortName"]: v for v in voices}
        self._groups_engine = VoiceGroupingEngine(voices)
        count = len(self._voice_map)
        langs = len(self._groups_engine.languages())
        self.log(f"[语音] 已加载 {count} 个可用语音（{langs} 种语言）")
        if self._btn_reload_voices:
            self._btn_reload_voices.configure(state="disabled")
        self._refresh_voice_selectors(preferred=DEFAULT_VOICE if self._selected_voice_code == DEFAULT_VOICE else None)

    # ============================================================ 文本

    def _replace_textbox(self, text: str):
        self._textbox.delete("1.0", "end")
        if text:
            self._textbox.insert("1.0", text)
        self._on_text_changed()

    def _on_mode_changed(self, value):
        if self._busy:
            self._mode_selector.set(self._t(f"mode_{self._workflow_mode}"))
            return
        new_mode = self._mode_value_to_key.get(value, "normal")
        if new_mode == self._workflow_mode:
            return
        current = self._textbox.get("1.0", "end-1c")
        if self._workflow_mode == "normal":
            self._normal_text = current
        elif self._workflow_mode == "line":
            self._sync_page_from_ui()
            self._line_draft = "\n".join(page.text for page in self._pages) if self._pages else current
        self._cleanup_batch()
        self._pages = []
        self._page_index = 0
        self._generated_pages = {}
        self._batch_mode = None
        self._workflow_mode = new_mode
        if new_mode == "normal":
            self._replace_textbox(self._normal_text)
        elif new_mode == "line":
            self._replace_textbox(self._line_draft)
        else:
            self._replace_textbox("")
        self._invalidate_generated()
        self._update_mode_ui()

    def _update_mode_ui(self):
        if self._btn_import is None:
            return
        self._btn_import.pack_forget()
        self._btn_download_example.pack_forget()
        self._btn_prepare_lines.pack_forget()
        self._btn_dub_pages.grid_remove()
        if self._workflow_mode in ("page", "line"):
            self._btn_download_example.pack(side="left", padx=(4, 0))
            self._btn_import.pack(side="left", padx=(4, 0))
        if self._workflow_mode == "line":
            label = "edit_lines" if self._pages else "prepare_lines"
            self._btn_prepare_lines.configure(text=self._t(label))
            self._btn_prepare_lines.pack(side="left", padx=(4, 0))
        if self._workflow_mode in ("page", "line"):
            self._btn_dub_pages.configure(
                text=self._t("line_dub" if self._workflow_mode == "line" else "page_dub")
            )
            if self._pages:
                self._btn_dub_pages.grid()
        self._helper_label.configure(text=self._t(f"helper_{self._workflow_mode}"))
        self._btn_generate.configure(
            text=self._t(
                "generate_line" if self._workflow_mode == "line" and self._pages
                else "generate_page" if self._workflow_mode == "page" and self._pages
                else "generate"
            )
        )
        self._update_page_bar()
        self._update_mode_settings_ui()

    def _update_mode_settings_ui(self):
        if self._mode_settings_title is None:
            return
        mode = self._workflow_mode
        self._mode_settings_title.configure(text=self._t(f"mode_settings_{mode}"))
        self._mode_settings_hint.configure(text=self._t(f"mode_settings_hint_{mode}"))
        if self._line_pause_section is not None:
            if mode == "line":
                self._line_pause_section.grid()
            else:
                self._line_pause_section.grid_remove()
        self._sentence_pause_check.configure(text=self._t("sentence_pause_enable"))
        self._line_pause_check.configure(text=self._t("line_pause_enable"))
        self._timeline_check.configure(text=self._t("timeline"))
        self._srt_check.configure(text=self._t("srt_subtitles"))

    def _on_prepare_lines(self):
        if self._busy or self._workflow_mode != "line":
            return
        if self._pages:
            self._sync_page_from_ui()
            self._line_draft = "\n".join(page.text for page in self._pages)
            self._pages = []
            self._page_index = 0
            self._generated_pages = {}
            self._batch_mode = None
            self._replace_textbox(self._line_draft)
            self._invalidate_generated()
            self._update_mode_ui()
            return
        pages = split_text_into_lines(self._textbox.get("1.0", "end-1c"))
        if not pages:
            messagebox.showwarning(APP_NAME, self._t("no_lines"))
            return
        self._line_draft = "\n".join(page.text for page in pages)
        self._pages = pages
        self._page_index = 0
        self._generated_pages = {}
        self._batch_mode = "line"
        self._load_page_into_ui(0)
        self.log(f"[逐行] 已准备 {len(pages)} 行。")
        self._update_mode_ui()

    def _on_text_changed(self, _event=None):
        text = self._textbox.get("1.0", "end-1c")
        self._char_count.configure(text=self._t("count", count=len(text)))

    def _on_text_edited(self, _event=None):
        self._on_text_changed()
        if self._pages:
            self._sync_page_from_ui()
            page = self._pages[self._page_index]
            entry = self._generated_pages.get(self._page_index + 1)
            if entry and normalize_for_tts(clean_text(entry["text"])) != self._get_cleaned_text():
                del self._generated_pages[self._page_index + 1]
        if self._generated_text is not None:
            current = self._get_cleaned_text()
            if current != self._generated_text:
                self._invalidate_generated()

    def _get_cleaned_text(self):
        raw = self._textbox.get("1.0", "end-1c")
        return normalize_for_tts(clean_text(raw))

    # ============================================================ 生成任务

    def _make_controller(self) -> StallController:
        self._stall_req_q = queue.Queue()
        self._stall_controller = StallController(self._stall_req_q.put)
        return self._stall_controller

    def _build_cfg(self) -> TTSConfig:
        return TTSConfig(
            voice=self._selected_voice(),
            rate=f"{'+' if self._rate_var.get() >= 0 else ''}{self._rate_var.get()}%",
            volume=f"{'+' if self._volume_var.get() >= 0 else ''}{self._volume_var.get()}%",
            pitch=f"{'+' if self._pitch_var.get() >= 0 else ''}{self._pitch_var.get()}Hz",
            sentence_pause_ms=self._sentence_pause_ms if self._sentence_pause_enabled else 0,
            sentence_pause_marks=tuple(sorted(self._sentence_pause_marks)),
            line_pause_ms=self._line_pause_ms if self._line_pause_enabled and self._workflow_mode == "line" else 0,
        )

    def _start_task(self, text, output_path, mode):
        if self._busy:
            messagebox.showinfo(APP_NAME, "已有任务进行中，请先停止当前任务。")
            return
        if not text.strip():
            messagebox.showwarning(APP_NAME, "请输入文章内容。")
            return
        self._busy = True
        self._cancel_event = threading.Event()
        self._set_busy_ui(True)

        controller = self._make_controller()
        engine = TTSEngine(
            on_log=lambda message: self._ui_q.put(("log", message)),
            on_progress=lambda percent, written: self._ui_q.put(
                ("progress", percent, written)
            ),
            controller=controller,
            cancel_event=self._cancel_event,
        )
        task = TTSTask(text, output_path, self._build_cfg(), mode)

        self._status_label.configure(text="Preparing…" if self._language == "en" else "正在准备…", text_color="#e0af68")
        self._progress.configure(mode="determinate")
        self._progress.set(0)

        threading.Thread(
            target=self._worker_task, args=(engine, task), daemon=True
        ).start()

    def _worker_task(self, engine: TTSEngine, task: TTSTask):
        try:
            result = engine.generate(task.text, task.output_path, task.cfg)
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "error": str(exc)}
        result["text"] = task.text
        result["timeline"] = getattr(engine, "timeline", None)
        self._ui_q.put(("task_done", task.mode, result))

    def _on_task_done(self, mode, result):
        self._busy = False
        self._set_busy_ui(False)
        self._generated_timeline = None

        status = result.get("status")
        if status == "done":
            current_text = self._get_cleaned_text()
            generated_text = result.get("text") or current_text
            if current_text != generated_text:
                self._progress.set(0)
                self._status_label.configure(text=self._t("ready"), text_color=self._c("success"))
                self.log("[生成] 生成期间文本已修改，请重新生成。")
                return
            path = result["path"]
            self._generated_path = path
            self._generated_text = generated_text
            self._generated_timeline = result.get("timeline")
            if self._pages:
                page = self._pages[self._page_index]
                self._generated_pages[self._page_index + 1] = {
                    "index": page.index,
                    "page": self._page_index + 1,
                    "title": page.title,
                    "text": generated_text,
                    "note": page.note,
                    "audio": path,
                    "timeline": result.get("timeline"),
                }
            size_kb = os.path.getsize(path) / 1024 if os.path.exists(path) else 0
            self._progress.set(1.0)
            self._status_label.configure(text=self._t("generated_ok"), text_color="#9ece6a")
            self.log(f"[生成] 音频已生成：{path}（{size_kb:.0f} KB），可试听或保存下载。")
            self._update_generated_buttons()
        elif status == "canceled":
            self._progress.set(0)
            self._status_label.configure(text=self._t("canceled"), text_color="#e0af68")
            self.log("[任务] 已取消。")
        else:
            self._progress.set(0)
            self._status_label.configure(text=self._t("failed"), text_color="#f7768e")
            self.log(f"[任务] 失败：{result.get('error', '未知错误')}")
            messagebox.showerror(
                APP_NAME,
                "生成失败：\n\n"
                + result.get("error", "未知错误")
                + "\n\n请检查网络连接或代理设置后重试。",
            )

    # ============================================================ 按钮动作

    def _on_generate(self):
        self._on_pause_changed()
        cleaned = self._get_cleaned_text()
        if not cleaned:
            messagebox.showwarning(APP_NAME, "请输入文章内容。")
            return
        self._stop_playback()
        if self._pages:
            self._sync_page_from_ui()
            unit = "行" if self._workflow_mode == "line" else "页"
            self.log(f"[生成] 开始合成第 {self._page_index + 1} {unit}音频（{len(cleaned)} 字）")
            self._start_task(cleaned, self._output_path_for_current(), "generate")
        else:
            self.log(f"[生成] 开始合成全文音频（{len(cleaned)} 字）")
            self._start_task(cleaned, self._preview_path, "generate")

    # ============================================================ 分页导入 / 逐页配音

    def _example_text(self):
        if self._workflow_mode == "line":
            if self._language == "en":
                return (
                    "Today we are testing line-by-line voice generation.\n"
                    "Each non-empty line becomes a separate audio file.\n"
                    "This line contains a comma, so you can test sentence pauses.\n"
                    "This line contains an exclamation mark!\n"
                    "This line contains a question mark?\n"
                    "This line contains a semicolon; select multiple punctuation types.\n"
                    "One line can contain several sentences, too. It will still remain one audio item.\n"
                    "Enable line-end pause to add silence after every generated line.\n\n"
                    "Blank lines are ignored during batch generation.\n"
                    "Use subtitles and the result viewer to review each generated item.\n"
                    "The final line confirms that the complete batch was generated.\n"
                )
            return (
                "今天我们来测试逐行配音功能。\n"
                "每一行非空文本都会单独生成一个音频文件。\n"
                "这一行包含逗号，方便测试句间停顿。\n"
                "这一行包含感叹号！\n"
                "这一行包含问号？\n"
                "这一行包含分号；可以测试多种标点的复选效果。\n"
                "一行也可以包含多个句子。它仍然只对应一个音频。\n"
                "开启行末停顿后，每个音频末尾都会增加静音。\n\n"
                "空行会在批量生成时自动跳过。\n"
                "开启字幕后，可以在结果窗口查看每条字幕的时间轴。\n"
                "最后一行用于确认整批音频都已完整生成。\n"
            )
        if self._language == "en":
            return (
                "This is page one. It contains several short sentences for pause and subtitle testing.\n"
                "The page marker below is used only for splitting and is never spoken.\n\n"
                "[PAGE]\n"
                "This is page two. It includes a comma, an exclamation mark, and a question mark!\n"
                "You can select any combination of punctuation types in the settings.\n\n"
                "[PAGE]\n"
                "This is page three. Generate the audio, open the result viewer, and edit the text.\n"
                "After editing, regenerate this page and compare the updated subtitle timing.\n\n"
                "[PAGE]\n"
                "This is page four. Page-by-page generation creates one independent audio file per page.\n"
                "You can review the batch and save the completed files when generation finishes.\n"
            )
        return (
            "这是第一页。这里有多句短旁白，适合测试句间停顿和字幕时间轴。\n"
            "下面的分页标记只用于拆分，不会被朗读。\n\n"
            "[分页]\n"
            "这是第二页。这里包含逗号，也包含感叹号！还包含问号？\n"
            "你可以在右侧复选需要处理的标点类型。\n\n"
            "[分页]\n"
            "这是第三页。生成后可以打开结果窗口试听、查看字幕并修改文本。\n"
            "修改完成后重新生成，可以检查新的字幕时间轴。\n\n"
            "[分页]\n"
            "这是第四页。逐页配音会为每一页生成一个独立音频。\n"
            "全部生成完成后，可以逐项检查并保存批量结果。\n"
        )

    def _on_download_example(self):
        if self._busy or self._workflow_mode == "normal":
            return
        name_key = "line_example_name" if self._workflow_mode == "line" else "page_example_name"
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        path = filedialog.asksaveasfilename(
            title=self._t("download_example"),
            defaultextension=".txt",
            filetypes=[("Text file" if self._language == "en" else "TXT 文本文件", "*.txt")],
            initialdir=default_dir if os.path.isdir(default_dir) else os.path.expanduser("~"),
            initialfile=self._t(name_key),
        )
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="\n") as handle:
                handle.write(self._example_text())
        except OSError as exc:
            messagebox.showerror(APP_NAME, ("Save failed:\n\n" if self._language == "en" else "保存失败：\n\n") + str(exc))
            return
        self.log(("[Example] Saved: " if self._language == "en" else "[示例] 已保存：") + path)
        messagebox.showinfo(APP_NAME, self._t("example_saved", path=path))

    def _on_import_file(self):
        if self._busy:
            return
        if self._workflow_mode == "normal":
            return
        is_english = self._language == "en"
        item_name = "lines" if self._workflow_mode == "line" else "pages"
        path = filedialog.askopenfilename(
            title=(
                "Import document for line-by-line narration" if is_english and item_name == "lines"
                else "Import document for page-by-page narration" if is_english
                else "导入文档，逐行旁白配音" if item_name == "lines"
                else "导入文档，逐页旁白配音"
            ),
            filetypes=[
                ("Documents (txt / md / docx / pdf)" if is_english else "文档（txt / md / docx / pdf）", "*.txt *.md *.markdown *.docx *.pdf"),
                ("All files" if is_english else "所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            pages = import_lines(path) if self._workflow_mode == "line" else import_file(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, ("Import failed:\n\n" if is_english else "导入失败：\n\n") + str(exc))
            self.log(f"[导入] 导入失败：{exc}")
            return
        self._sync_page_from_ui()
        self._cleanup_batch()
        self._pages = pages
        self._page_index = 0
        self._generated_pages = {}
        self._batch_mode = self._workflow_mode
        if self._workflow_mode == "line":
            self._line_draft = "\n".join(page.text for page in pages)
        self._load_page_into_ui(0)
        unit = "行" if self._workflow_mode == "line" else "页"
        self.log(f"[导入] 已导入 {len(pages)} {unit}：{os.path.basename(path)}")
        self._update_mode_ui()

    def _load_page_into_ui(self, index):
        if not self._pages:
            self._page_index = 0
            return
        index = max(0, min(index, len(self._pages) - 1))
        self._page_index = index
        page = self._pages[index]
        self._textbox.delete("1.0", "end")
        if page.text:
            self._textbox.insert("1.0", page.text)
        if self._note_var is not None:
            self._note_var.set(page.note)
        self._update_page_bar()
        self._on_text_changed()
        self._invalidate_generated()

    def _on_prev_page(self):
        if self._pages and self._page_index > 0:
            self._sync_page_from_ui()
            self._load_page_into_ui(self._page_index - 1)

    def _on_next_page(self):
        if self._pages and self._page_index < len(self._pages) - 1:
            self._sync_page_from_ui()
            self._load_page_into_ui(self._page_index + 1)

    def _on_note_edited(self, _event=None):
        self._sync_page_from_ui()

    def _sync_page_from_ui(self):
        if not self._pages or self._page_index >= len(self._pages):
            return
        page = self._pages[self._page_index]
        try:
            page.text = self._textbox.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            pass
        if self._note_var is not None:
            page.note = self._note_var.get()

    def _update_page_bar(self):
        has_pages = bool(self._pages)
        if self._page_bar is None:
            return
        if not has_pages:
            self._page_bar.grid_remove()
            if self._btn_dub_pages is not None:
                self._btn_dub_pages.configure(state="disabled")
                self._btn_dub_pages.grid_remove()
            return
        self._page_bar.grid()
        total = len(self._pages)
        is_line = self._workflow_mode == "line"
        self._page_label.configure(text=self._t("line_label" if is_line else "page_label", current=self._page_index + 1, total=total))
        self._btn_prev_page.configure(text=self._t("prev_line" if is_line else "prev_page"))
        self._btn_next_page.configure(text=self._t("next_line" if is_line else "next_page"))
        idle = not self._busy
        self._btn_prev_page.configure(state="normal" if idle and self._page_index > 0 else "disabled")
        self._btn_next_page.configure(state="normal" if idle and self._page_index < total - 1 else "disabled")
        if self._btn_dub_pages is not None:
            self._btn_dub_pages.configure(state="normal" if idle else "disabled")
            self._btn_dub_pages.grid()
        self._note_entry.configure(state="normal" if idle else "disabled")

    def _output_path_for_current(self):
        if self._pages:
            unit = "line" if self._workflow_mode == "line" else "page"
            return os.path.join(tempfile.gettempdir(), f"edge_tts_{unit}_{self._page_index + 1:03d}.mp3")
        return self._preview_path

    def _current_page_generated(self):
        if not self._pages or self._page_index >= len(self._pages):
            return None
        entry = self._generated_pages.get(self._page_index + 1)
        if entry and os.path.exists(entry.get("audio", "")):
            return entry
        return None

    def _cleanup_batch(self):
        if self._batch_dir and os.path.isdir(self._batch_dir):
            try:
                shutil.rmtree(self._batch_dir, ignore_errors=True)
            except OSError:
                pass
        self._batch_dir = None

    def _on_dub_pages(self):
        if self._busy:
            return
        if not self._pages:
            messagebox.showinfo(APP_NAME, self._t("no_lines" if self._workflow_mode == "line" else "no_pages"))
            return
        self._on_pause_changed()
        self._sync_page_from_ui()
        self._stop_playback()
        self._cleanup_batch()
        self._batch_mode = self._workflow_mode
        unit = "lines" if self._batch_mode == "line" else "pages"
        self._batch_dir = tempfile.mkdtemp(prefix=f"edgetts_{unit}_")
        batch_mode = self._batch_mode
        batch_dir = self._batch_dir
        batch_pages = [
            Page(page.index, page.text, page.note, page.title) for page in self._pages
        ]
        cfg = self._build_cfg()
        self._busy = True
        self._cancel_event = threading.Event()
        self._set_busy_ui(True)
        self._progress.configure(mode="determinate")
        self._progress.set(0)
        self._status_label.configure(text=(f"Dubbing {unit}…" if self._language == "en" else "正在逐行配音…" if self._batch_mode == "line" else "正在逐页配音…"), text_color="#e0af68")
        label = "逐行" if self._batch_mode == "line" else "分页"
        cn_unit = "行" if self._batch_mode == "line" else "页"
        self.log(f"[{label}] 开始{label}配音（共 {len(self._pages)} {cn_unit}）")
        threading.Thread(
            target=self._worker_batch_pages,
            args=(batch_pages, batch_dir, batch_mode, cfg),
            daemon=True,
        ).start()

    def _worker_batch_pages(self, pages, batch_dir, batch_mode, cfg):
        total = len(pages)
        is_line = batch_mode == "line"
        log_tag = "逐行" if is_line else "分页"
        unit = "行" if is_line else "页"
        stem = "line" if is_line else "page"
        results = []
        canceled = False
        for pos, page in enumerate(pages, start=1):
            if self._cancel_event.is_set():
                canceled = True
                break
            text = normalize_for_tts(clean_text(page.text))
            if not text.strip():
                self._ui_q.put(("log", f"[{log_tag}] 第 {pos}/{total} {unit}无可用文字，已跳过。"))
                continue
            output_path = os.path.join(batch_dir, f"{stem}_{pos:03d}.mp3")
            controller = self._make_controller()
            engine = TTSEngine(
                on_log=lambda message: self._ui_q.put(("log", message)),
                on_progress=lambda percent, written, pos=pos, total=total: self._ui_q.put(
                    ("progress", (pos - 1 + percent / 100.0) / total * 100, written, pos, total)
                ),
                controller=controller,
                cancel_event=self._cancel_event,
            )
            result = engine.generate(text, output_path, cfg)
            if self._cancel_event.is_set():
                canceled = True
                break
            if result.get("status") == "done":
                size_kb = os.path.getsize(output_path) / 1024 if os.path.exists(output_path) else 0
                self._ui_q.put(("log", f"[{log_tag}] 第 {pos}/{total} {unit}完成（{size_kb:.0f} KB）。"))
                results.append({
                    "index": page.index,
                    "page": pos,
                    "title": page.title,
                    "text": text,
                    "note": page.note,
                    "audio": output_path,
                    "timeline": getattr(engine, "timeline", None),
                })
            else:
                error = result.get("error", "未知错误")
                self._ui_q.put(("log", f"[{log_tag}] 第 {pos}/{total} {unit}生成失败：{error}"))
        self._ui_q.put(("batch_done", {"results": results, "canceled": canceled, "mode": batch_mode}))

    def _on_batch_done(self, payload):
        self._busy = False
        self._set_busy_ui(False)
        results = payload.get("results") or []
        canceled = bool(payload.get("canceled"))
        self._batch_mode = payload.get("mode") or self._batch_mode or "page"
        is_line = self._batch_mode == "line"
        tag = "逐行" if is_line else "分页"
        unit = "行" if is_line else "页"
        # Use the batch position as the in-memory key. Source indexes can be
        # duplicated by some importers; using them here would overwrite earlier
        # lines/pages and leave only the last item in the ZIP export.
        self._generated_pages = {entry["page"]: entry for entry in results}
        self._sync_generated_status()
        if canceled:
            self._progress.set(1.0 if results else 0)
            self._status_label.configure(text=self._t("stopped"), text_color="#e0af68")
            self.log(f"[{tag}] 已停止（完成 {len(results)} {unit}）。")
        elif not results:
            self._progress.set(0)
            self._status_label.configure(text=self._t("failed"), text_color="#f7768e")
            self.log(f"[{tag}] 未生成任何{unit}音频。")
        else:
            self.log(f"[{tag}] {tag}配音完成：{len(results)} {unit}，可试听或保存下载。")
        self._update_generated_buttons()
        self._update_page_bar()

    def _save_pages_bundle(self):
        entries = sorted(self._generated_pages.values(), key=lambda e: e.get("page", e.get("index", 0)))
        is_line = self._batch_mode == "line"
        stem = "line" if is_line else "page"
        collection = "lines" if is_line else "pages"
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        path = filedialog.asksaveasfilename(
            title=self._t("lines_zip_title" if is_line else "pages_zip_title"),
            defaultextension=".zip",
            filetypes=[(self._t("lines_zip_filetype" if is_line else "pages_zip_filetype"), "*.zip")],
            initialdir=default_dir if os.path.isdir(default_dir) else os.path.expanduser("~"),
            initialfile=default_filename().replace(".mp3", f"_{collection}.zip"),
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            cfg = self._build_cfg()
            payload = {
                "version": 1,
                "kind": collection,
                "engine": "edge-tts",
                "voice": cfg.voice,
                "rate": cfg.rate,
                "volume": cfg.volume,
                "pitch": cfg.pitch,
                "count": len(entries),
                collection: [],
            }
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for entry in entries:
                    base_name = f"{stem}_{entry['page']:03d}"
                    arcname = base_name + ".mp3"
                    audio = entry.get("audio")
                    has_audio = bool(audio and os.path.exists(audio))
                    if has_audio:
                        archive.write(audio, arcname=arcname)
                    item = {
                        "index": entry.get("index"),
                        stem: entry.get("page"),
                        "title": entry.get("title", ""),
                        "text": entry.get("text", ""),
                        "note": entry.get("note", ""),
                        "audio": arcname if has_audio else None,
                        "timeline": entry.get("timeline"),
                    }
                    if self._srt_enabled:
                        srt = timeline_to_srt(entry.get("timeline"))
                        if srt:
                            item["subtitle"] = base_name + ".srt"
                            archive.writestr(item["subtitle"], srt)
                    payload[collection].append(item)
                archive.writestr(f"{collection}.json", json.dumps(payload, ensure_ascii=False, indent=2))
            self.log(f"[保存] {'逐行' if is_line else '分页'}配音压缩包已保存：{path}")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"保存失败：{exc}")
            return
        self._maybe_open_folder(path)

    def _on_play(self):
        page_entry = self._current_page_generated()
        target = page_entry["audio"] if page_entry else self._generated_path
        if not target or not os.path.exists(target):
            messagebox.showinfo(APP_NAME, self._t("no_audio"))
            return
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            self._stop_playback()
            self.log("[试听] 已停止播放。")
            return
        self.log("[试听] 开始播放已生成的音频…")
        self._play_audio(target)
        if self._timeline_enabled:
            timeline = page_entry.get("timeline") if page_entry else self._generated_timeline
            if timeline:
                self._generated_timeline = timeline
                self._highlight_ranges = self._build_highlight_ranges()
                self._highlight_running = True
                self.after(150, self._tick_highlight)

    def _open_result_preview_legacy(self):
        """Open a batch-aware review window for generated audio and subtitles."""
        if self._generated_pages:
            entries = sorted(self._generated_pages.values(), key=lambda entry: entry.get("page", entry.get("index", 0)))
        elif self._generated_path and os.path.exists(self._generated_path):
            entries = [{
                "page": 1,
                "title": "",
                "text": self._generated_text or self._textbox.get("1.0", "end-1c"),
                "audio": self._generated_path,
                "timeline": self._generated_timeline,
            }]
        else:
            messagebox.showinfo(APP_NAME, self._t("no_audio"))
            return

        current_page = self._page_index + 1
        current_index = next((index for index, entry in enumerate(entries) if entry.get("page") == current_page), 0)
        dialog = ctk.CTkToplevel(self)
        dialog.title(self._t("result_title"))
        dialog.geometry("1020x700")
        dialog.minsize(840, 570)
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_columnconfigure(1, weight=1)
        dialog.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(dialog, text=self._t("result_title"), text_color=self._c("text"), font=self._font(size=18, weight="bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=22, pady=(18, 4))
        audio_bar = ctk.CTkFrame(dialog, corner_radius=10, fg_color=self._c("surface_alt"), border_width=1, border_color=self._c("border"))
        audio_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=22, pady=(4, 10))
        audio_bar.grid_columnconfigure(3, weight=1)
        current_label = ctk.CTkLabel(audio_bar, text="", text_color=self._c("accent"), font=self._font(size=12, weight="bold"))
        current_label.grid(row=0, column=1, padx=(5, 10), pady=7)
        filename_label = ctk.CTkLabel(audio_bar, text="", text_color=self._c("muted"), anchor="w", font=self._font(size=11))
        filename_label.grid(row=0, column=3, sticky="w", padx=(0, 8), pady=7)
        current_mode_label = self._t("result_view_current")
        all_mode_label = self._t("result_view_all")
        subtitle_mode = tk.StringVar(value=current_mode_label)
        subtitle_switch = ctk.CTkSegmentedButton(
            audio_bar,
            values=[self._t("result_view_current"), self._t("result_view_all")],
            variable=subtitle_mode,
            height=28,
            font=self._font(size=11, weight="bold"),
            fg_color=self._c("field"),
            selected_color=self._c("primary"),
            selected_hover_color=self._c("primary_hover"),
            unselected_color=self._c("field"),
            unselected_hover_color=self._c("card_raised"),
            text_color=self._c("text"),
        )
        subtitle_switch.grid(row=0, column=4, padx=5, pady=7)

        text_frame = ctk.CTkFrame(dialog, corner_radius=10, fg_color=self._c("surface_alt"), border_width=1, border_color=self._c("border"))
        text_frame.grid(row=2, column=0, sticky="nsew", padx=(22, 7), pady=(0, 12))
        text_frame.grid_rowconfigure(1, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(text_frame, text=self._t("result_text"), text_color=self._c("text"), font=self._font(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
        text_editor = ctk.CTkTextbox(text_frame, wrap="word", fg_color=self._c("field"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=13))
        text_editor.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        subtitle_frame = ctk.CTkFrame(dialog, corner_radius=10, fg_color=self._c("surface_alt"), border_width=1, border_color=self._c("border"))
        subtitle_frame.grid(row=2, column=1, sticky="nsew", padx=(7, 22), pady=(0, 12))
        subtitle_frame.grid_rowconfigure(1, weight=1)
        subtitle_frame.grid_columnconfigure(0, weight=1)
        subtitle_heading = ctk.CTkLabel(subtitle_frame, text=self._t("result_subtitles"), text_color=self._c("text"), font=self._font(size=13, weight="bold"))
        subtitle_heading.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
        subtitle_view = ctk.CTkTextbox(subtitle_frame, wrap="none", fg_color=self._c("field"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=12))
        subtitle_view.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        action_bar = ctk.CTkFrame(dialog, fg_color="transparent")
        action_bar.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 16))
        action_bar.grid_columnconfigure(1, weight=1)
        previous_button = ctk.CTkButton(action_bar, text=self._t("result_prev"), width=92, height=34, fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("accent"), text_color=self._c("accent"), text_color_disabled=self._c("muted"))
        previous_button.grid(row=0, column=0, sticky="w")
        next_button = ctk.CTkButton(action_bar, text=self._t("result_next"), width=92, height=34, fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("accent"), text_color=self._c("accent"), text_color_disabled=self._c("muted"))
        next_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        ctk.CTkButton(action_bar, text=self._t("result_close"), width=90, height=34, fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("muted"), text_color=self._c("text"), command=dialog.destroy).grid(row=0, column=3, padx=(16, 5))

        def entry_subtitles(entry):
            timeline = entry.get("timeline")
            return timeline_to_srt(timeline) if timeline else self._t("result_no_subtitles")

        def all_subtitles():
            blocks = []
            for number, entry in enumerate(entries, start=1):
                heading = self._t("result_all_heading", number=number)
                title = (entry.get("title") or "").strip()
                blocks.append(f"{heading}{' · ' + title if title else ''}\n{entry_subtitles(entry)}")
            return "\n\n".join(blocks)

        def refresh_subtitles():
            subtitle_view.configure(state="normal")
            subtitle_view.delete("1.0", "end")
            if subtitle_mode.get() == all_mode_label:
                subtitle_heading.configure(text=self._t("result_view_all"))
                subtitle_view.insert("1.0", all_subtitles())
            else:
                subtitle_heading.configure(text=self._t("result_subtitles"))
                subtitle_view.insert("1.0", entry_subtitles(entries[current_index]))
            subtitle_view.configure(state="disabled")

        def refresh_entry():
            entry = entries[current_index]
            total = len(entries)
            item_key = "result_item_line" if self._batch_mode == "line" else "result_item_page"
            current_label.configure(text=self._t(item_key, current=current_index + 1, total=total))
            filename_label.configure(text=os.path.basename(entry.get("audio") or ""))
            text_editor.delete("1.0", "end")
            text_editor.insert("1.0", entry.get("text", ""))
            previous_button.configure(state="normal" if current_index > 0 else "disabled")
            next_button.configure(state="normal" if current_index < total - 1 else "disabled")
            refresh_subtitles()

        def change_entry(step):
            nonlocal current_index
            next_index = max(0, min(len(entries) - 1, current_index + step))
            if next_index != current_index:
                current_index = next_index
                refresh_entry()

        def preview_current():
            audio = entries[current_index].get("audio")
            if audio and os.path.exists(audio):
                self._stop_playback()
                self._play_audio(audio)

        def apply_edits():
            edited = text_editor.get("1.0", "end-1c").strip()
            if not edited:
                messagebox.showwarning(APP_NAME, self._t("empty"), parent=dialog)
                return
            entry = entries[current_index]
            if self._pages:
                target_index = max(0, min(len(self._pages) - 1, int(entry.get("page", 1)) - 1))
                self._sync_page_from_ui()
                self._pages[target_index].text = edited
                self._page_index = target_index
                self._load_page_into_ui(target_index)
            else:
                self._replace_textbox(edited)
            dialog.destroy()
            self._on_generate()

        previous_button.configure(command=lambda: change_entry(-1))
        next_button.configure(command=lambda: change_entry(1))
        subtitle_switch.configure(command=lambda _value: refresh_subtitles())
        ctk.CTkButton(audio_bar, text=self._t("play"), width=76, height=28, fg_color=self._c("primary"), hover_color=self._c("primary_hover"), command=preview_current).grid(row=0, column=5, padx=5, pady=7)
        ctk.CTkButton(audio_bar, text=self._t("save"), width=88, height=28, fg_color=self._c("star"), hover_color=self._c("star_hover"), text_color=self._c("warning"), command=self._on_save).grid(row=0, column=6, padx=(0, 10), pady=7)
        ctk.CTkButton(action_bar, text=self._t("result_apply"), width=170, height=32, fg_color=self._c("primary"), hover_color=self._c("primary_hover"), command=apply_edits).grid(row=0, column=4, sticky="e")
        refresh_entry()

    def _open_result_preview(self):
        if self._generated_pages:
            entries = sorted(self._generated_pages.values(), key=lambda e: e.get("page", 0))
        elif self._generated_path and os.path.exists(self._generated_path):
            entries = [{"page": 1, "text": self._generated_text or self._textbox.get("1.0", "end-1c"), "audio": self._generated_path, "timeline": self._generated_timeline}]
        else:
            messagebox.showinfo(APP_NAME, self._t("no_audio"))
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(self._t("result_title"))
        dialog.geometry("1260x760")
        dialog.minsize(960, 580)
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(dialog, text=self._t("result_title"), text_color=self._c("text"), font=self._font(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 5))
        toolbar = ctk.CTkFrame(dialog, fg_color=self._c("surface_alt"), corner_radius=10, border_width=1, border_color=self._c("border"))
        toolbar.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        toolbar.grid_columnconfigure(2, weight=1)
        current_label = self._t("result_view_current")
        all_label = self._t("result_view_all")
        mode = tk.StringVar(value=current_label)
        switch = ctk.CTkSegmentedButton(toolbar, values=[current_label, all_label], variable=mode, height=30, font=self._font(size=11, weight="bold"), fg_color=self._c("field"), selected_color=self._c("primary"), selected_hover_color=self._c("primary_hover"), unselected_color=self._c("field"), unselected_hover_color=self._c("card_raised"), text_color=self._c("text"))
        switch.grid(row=0, column=0, padx=10, pady=8)
        summary = ctk.CTkLabel(toolbar, text="", text_color=self._c("muted"), anchor="w")
        summary.grid(row=0, column=2, sticky="w", padx=10)
        ctk.CTkButton(toolbar, text=self._t("result_regenerate_all"), width=126, height=30, fg_color=self._c("primary"), hover_color=self._c("primary_hover"), command=self._on_dub_pages).grid(row=0, column=3, padx=5, pady=8)
        ctk.CTkButton(toolbar, text=self._t("result_export_zip"), width=118, height=30, fg_color=self._c("star"), hover_color=self._c("star_hover"), text_color=self._c("warning"), command=self._save_pages_bundle).grid(row=0, column=4, padx=(0, 10), pady=8)
        table = ctk.CTkScrollableFrame(dialog, fg_color=self._c("surface"), corner_radius=10, border_width=1, border_color=self._c("border"))
        table.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        table.grid_columnconfigure(1, weight=4)
        table.grid_columnconfigure(2, weight=3)
        for col, label in ((0, self._t("result_table_number")), (1, self._t("result_table_text")), (2, self._t("result_table_timeline")), (3, self._t("result_table_actions"))):
            ctk.CTkLabel(table, text=label, anchor="w", text_color=self._c("muted"), font=self._font(size=11, weight="bold")).grid(row=0, column=col, sticky="ew", padx=8, pady=(8, 5))
        row_state = {}
        active = {"page": None, "after": None}
        def format_time(seconds):
            seconds = max(0, int(seconds or 0))
            return f"{seconds // 60}:{seconds % 60:02d}"
        def entry_duration(entry):
            timeline = entry.get("timeline") or {}
            duration = float(timeline.get("duration", 0) or 0)
            if duration <= 0:
                duration = max([float(item.get("end", 0)) for item in timeline.get("sentences", [])] or [0.0])
                duration += float(timeline.get("duration_padding_ms", 0) or 0) / 1000.0
            if duration <= 0:
                try:
                    if not pygame.mixer.get_init(): pygame.mixer.init()
                    duration = float(pygame.mixer.Sound(entry.get("audio")).get_length())
                except Exception:
                    duration = 1.0
            return max(0.1, duration)
        def timeline_text(entry):
            sentences = (entry.get("timeline") or {}).get("sentences") or []
            lines = [f"{float(item.get('start', 0)):05.2f} - {float(item.get('end', 0)):05.2f}  {item.get('text', '')}" for item in sentences]
            timeline = entry.get("timeline") or {}
            padding = float(timeline.get("duration_padding_ms", 0) or 0) / 1000.0
            if padding > 0:
                end = max([float(item.get("end", 0)) for item in sentences] or [0.0])
                lines.append(f"{end:05.2f} - {end + padding:05.2f}  （行末静音）")
            return "\n".join(lines) or self._t("result_no_subtitles")
        def stop_playback():
            if active["after"]:
                try:
                    dialog.after_cancel(active["after"])
                except Exception:
                    pass
            active.update(page=None, after=None)
            self._stop_playback()
            for state in row_state.values():
                state["progress"].set(0)
                state["elapsed"].configure(text=format_time(0))
                state["frame"].configure(fg_color=self._c("card"))
        def play_row(entry, state):
            audio = entry.get("audio")
            if not audio or not os.path.exists(audio):
                return
            if active["page"] == entry.get("page") and pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                stop_playback()
                return
            stop_playback()
            self._play_audio(audio)
            active["page"] = entry.get("page")
            state["frame"].configure(fg_color=self._c("card_raised"))
            duration = state.get("duration") or entry_duration(entry)
            state["duration"] = duration
            state["total"].configure(text=format_time(duration))
            def tick():
                if active["page"] != entry.get("page"):
                    return
                pos = pygame.mixer.music.get_pos() / 1000.0 if pygame.mixer.get_init() else 0.0
                state["progress"].set(min(duration, max(0.0, pos)))
                state["elapsed"].configure(text=format_time(pos))
                if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                    active["after"] = dialog.after(80, tick)
                else:
                    state["progress"].set(duration)
                    state["elapsed"].configure(text=format_time(duration))
                    active.update(page=None, after=None)
                    state["frame"].configure(fg_color=self._c("card"))
            tick()
        def seek_row(entry, state, value):
            duration = state.get("duration") or entry_duration(entry)
            state["duration"] = duration
            target = max(0.0, min(float(value), duration))
            state["elapsed"].configure(text=format_time(target))
            if active["page"] != entry.get("page"):
                self._stop_playback()
                self._play_audio(entry.get("audio"))
                active["page"] = entry.get("page")
            try:
                if pygame.mixer.get_init(): pygame.mixer.music.set_pos(target)
            except Exception:
                pass
        def regenerate(entry, state):
            text = state["editor"].get("1.0", "end-1c").strip()
            if not text:
                messagebox.showwarning(APP_NAME, self._t("empty"), parent=dialog)
                return
            if not self._generated_pages:
                self._replace_textbox(text)
                self._on_generate()
                return
            entry["text"] = normalize_for_tts(clean_text(text))
            page = int(entry.get("page", 1))
            if self._pages and page <= len(self._pages):
                self._pages[page - 1].text = text
            if self._busy:
                return
            self._busy = True
            self._cancel_event = threading.Event()
            self._set_busy_ui(True)
            out_dir = self._batch_dir or tempfile.mkdtemp(prefix="edgetts_review_")
            self._batch_dir = out_dir
            output = os.path.join(out_dir, f"{'line' if self._batch_mode == 'line' else 'page'}_{page:03d}.mp3")
            cfg = self._build_cfg()
            def worker():
                try:
                    engine = TTSEngine(on_log=lambda msg: self._ui_q.put(("log", msg)), on_progress=lambda p, w: None, controller=self._make_controller(), cancel_event=self._cancel_event)
                    result = engine.generate(entry["text"], output, cfg)
                    result["timeline"] = getattr(engine, "timeline", None)
                    result["text"] = entry["text"]
                except Exception as exc:
                    result = {"status": "error", "error": str(exc)}
                self._ui_q.put(("result_row_done", page, result))
            threading.Thread(target=worker, daemon=True).start()
        def refresh():
            for child in table.winfo_children():
                if int(child.grid_info().get("row", 0)) > 0:
                    child.destroy()
            row_state.clear()
            visible = entries if mode.get() == all_label else entries[:1]
            summary.configure(text=f"{len(entries)} {'条目' if self._language != 'en' else 'items'}")
            for row_no, entry in enumerate(visible, 1):
                frame = ctk.CTkFrame(table, fg_color=self._c("card"), corner_radius=8, border_width=1, border_color=self._c("border"))
                frame.grid(row=row_no, column=0, columnspan=4, sticky="ew", padx=6, pady=4)
                frame.grid_columnconfigure(1, weight=4)
                frame.grid_columnconfigure(2, weight=3)
                ctk.CTkLabel(frame, text=f"{int(entry.get('page', row_no)):03d}", width=55, text_color=self._c("accent"), font=self._font(size=13, weight="bold")).grid(row=0, column=0, sticky="nw", padx=8, pady=10)
                editor = ctk.CTkTextbox(frame, height=72, wrap="word", fg_color=self._c("field"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=12))
                editor.grid(row=0, column=1, sticky="ew", padx=6, pady=8)
                editor.insert("1.0", entry.get("text", ""))
                ctk.CTkLabel(frame, text=timeline_text(entry), justify="left", anchor="nw", wraplength=360, text_color=self._c("muted"), font=self._font(size=11)).grid(row=0, column=2, sticky="new", padx=8, pady=10)
                actions = ctk.CTkFrame(frame, fg_color="transparent"); actions.grid(row=0, column=3, sticky="nsew", padx=8, pady=8)
                duration = entry_duration(entry)
                timeline_bar = ctk.CTkFrame(actions, fg_color="transparent"); timeline_bar.pack(fill="x", pady=(0, 2)); timeline_bar.grid_columnconfigure(1, weight=1)
                elapsed = ctk.CTkLabel(timeline_bar, text=format_time(0), width=42, anchor="w", text_color=self._c("success"), font=self._font(size=10, weight="bold")); elapsed.grid(row=0, column=0, sticky="w")
                progress = ctk.CTkSlider(timeline_bar, from_=0, to=duration, number_of_steps=max(1, int(duration * 10)), height=16, button_length=12, fg_color=self._c("field"), progress_color=self._c("success"), button_color=self._c("success"), button_hover_color=self._c("accent")); progress.grid(row=0, column=1, sticky="ew", padx=4); progress.set(0)
                total = ctk.CTkLabel(timeline_bar, text=format_time(duration), width=42, anchor="e", text_color=self._c("muted"), font=self._font(size=10)); total.grid(row=0, column=2, sticky="e")
                buttons = ctk.CTkFrame(actions, fg_color="transparent"); buttons.pack(fill="x")
                state = {"frame": frame, "editor": editor, "progress": progress, "elapsed": elapsed, "total": total, "duration": duration}; row_state[entry.get("page")] = state
                progress.configure(command=lambda value, e=entry, s=state: seek_row(e, s, value))
                ctk.CTkButton(buttons, text=self._t("result_play"), width=72, height=28, fg_color=self._c("primary"), hover_color=self._c("primary_hover"), command=lambda e=entry, s=state: play_row(e, s)).pack(side="left", padx=(0, 5))
                ctk.CTkButton(buttons, text=self._t("result_regenerate"), width=88, height=28, fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("accent"), text_color=self._c("accent"), command=lambda e=entry, s=state: regenerate(e, s)).pack(side="left")
                for widget in (frame, editor):
                    widget.bind("<Enter>", lambda _e, f=frame: f.configure(fg_color=self._c("card_raised")))
                    widget.bind("<Leave>", lambda _e, f=frame: f.configure(fg_color=self._c("card")))
        self._result_preview_refresh = refresh
        switch.configure(command=lambda _value: refresh())
        ctk.CTkButton(dialog, text=self._t("result_close"), width=100, height=34, fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), border_width=1, border_color=self._c("accent"), text_color=self._c("accent"), command=lambda: (stop_playback(), dialog.destroy())).grid(row=3, column=0, sticky="e", padx=20, pady=(0, 14))
        refresh()

    def _on_result_row_done(self, page, result):
        self._busy = False
        self._set_busy_ui(False)
        entry = self._generated_pages.get(page)
        if result.get("status") == "done" and entry:
            entry["audio"] = result.get("path") or entry.get("audio")
            entry["timeline"] = result.get("timeline")
            entry["text"] = result.get("text") or entry.get("text")
            self._generated_path = entry.get("audio")
            self._generated_timeline = entry.get("timeline")
            self.log(f"[结果] 第 {page} 条已重新生成。")
            if self._result_preview_refresh:
                self._result_preview_refresh()
        elif result.get("status") != "done":
            messagebox.showerror(APP_NAME, f"生成失败：{result.get('error', '未知错误')}")

    def _on_save(self):
        if self._generated_pages:
            self._save_pages_bundle()
            return
        if not self._generated_path or not os.path.exists(self._generated_path):
            messagebox.showinfo(APP_NAME, self._t("no_audio"))
            return
        bundle = bool((self._timeline_enabled or self._srt_enabled) and self._generated_timeline)
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if bundle:
            path = filedialog.asksaveasfilename(
                title=("Save ZIP (audio + metadata)" if self._language == "en" else "保存 ZIP 压缩包（音频 + 字幕/时间轴）"),
                defaultextension=".zip",
                filetypes=[("ZIP Archive (MP3 + timeline JSON)" if self._language == "en" else "ZIP 压缩包（MP3 + 时间轴 JSON）", "*.zip")],
                initialdir=default_dir if os.path.isdir(default_dir) else os.path.expanduser("~"),
                initialfile=default_filename().replace(".mp3", ".zip"),
            )
        else:
            path = filedialog.asksaveasfilename(
                title=("Save audio" if self._language == "en" else "保存音频"),
                defaultextension=".mp3",
                filetypes=[("MP3 audio" if self._language == "en" else "MP3 音频", "*.mp3")],
                initialdir=default_dir if os.path.isdir(default_dir) else os.path.expanduser("~"),
                initialfile=default_filename(),
            )
        if not path:
            return
        try:
            if bundle:
                if not path.lower().endswith(".zip"):
                    path += ".zip"
                base_name = os.path.basename(os.path.splitext(path)[0])
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(self._generated_path, arcname=os.path.basename(self._generated_path))
                    if self._timeline_enabled:
                        archive.writestr(
                            base_name + ".timeline.json",
                            json.dumps(self._generated_timeline, ensure_ascii=False, indent=2),
                        )
                    if self._srt_enabled:
                        archive.writestr(base_name + ".srt", timeline_to_srt(self._generated_timeline))
                self.log(f"[保存] 音频与字幕/时间轴已打包：{path}")
            else:
                shutil.copy2(self._generated_path, path)
                self.log(f"[保存] 音频已保存：{path}")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"保存失败：{exc}")
            return

        self._maybe_open_folder(path)

    def _on_stop(self):
        self.log("[任务] 正在停止…")
        self._cancel_event.set()
        self._stop_playback()
        self._status_label.configure(text=self._t("stopped"), text_color="#e0af68")

    # ============================================================ 播放

    def _play_audio(self, path):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
        except Exception as exc:  # noqa: BLE001
            self.log(f"[试听] 播放失败：{exc}（可改用导出功能获取音频文件）")

    def _stop_playback(self):
        try:
            if pygame.mixer.get_init():
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                pygame.mixer.music.unload()
        except Exception:  # noqa: BLE001
            pass
        self._clear_highlight()

    def _toggle_timeline(self):
        self._timeline_enabled = bool(self._timeline_var.get())
        self._settings["timeline_json"] = self._timeline_enabled
        self._save_settings()
        if not self._timeline_enabled:
            self._clear_highlight()
        self.log(self._t("timeline_on") if self._timeline_enabled else self._t("timeline_off"))

    def _toggle_srt(self):
        self._srt_enabled = bool(self._srt_var.get())
        self._settings["srt_subtitles"] = self._srt_enabled
        self._save_settings()

    def _toggle_sentence_pause(self):
        self._sentence_pause_enabled = bool(self._sentence_pause_check.get())
        self._settings["sentence_pause_enabled"] = self._sentence_pause_enabled
        self._save_settings()
        self._set_sentence_pause_controls_enabled(self._sentence_pause_enabled)
        self._invalidate_generated()

    def _set_sentence_pause_controls_enabled(self, enabled: bool):
        """Keep dependent duration and punctuation controls in sync with the master switch."""
        state = "normal" if enabled else "disabled"
        if self._pause_entry is not None:
            self._pause_entry.configure(state=state)
        if self._punctuation_label is not None:
            self._punctuation_label.configure(text_color=self._c("muted") if enabled else self._c("border"))
        for item in self._punctuation_checks.values():
            check = item[2] if len(item) > 2 else item[0]
            check.configure(state=state)

    def _toggle_line_pause(self):
        self._line_pause_enabled = bool(self._line_pause_check.get())
        self._settings["line_pause_enabled"] = self._line_pause_enabled
        self._save_settings()
        self._set_line_pause_controls_enabled(self._line_pause_enabled)
        self._invalidate_generated()

    def _set_line_pause_controls_enabled(self, enabled: bool):
        """Keep the line-end duration field linked to its master switch."""
        state = "normal" if enabled else "disabled"
        if self._line_pause_entry is not None:
            self._line_pause_entry.configure(state=state)

    def _on_punctuation_changed(self):
        marks = set()
        for item in self._punctuation_checks.values():
            var, values = item[0], item[1]
            if var.get():
                marks.update(values)
        self._sentence_pause_marks = marks
        self._settings["sentence_pause_marks"] = sorted(marks)
        self._save_settings()
        self._invalidate_generated()

    def _on_pause_changed(self, _event=None):
        try:
            value = int(self._pause_var.get().strip() or "0")
        except ValueError:
            value = self._sentence_pause_ms
        value = max(0, min(10000, value))
        self._sentence_pause_ms = value
        self._pause_var.set(str(value))
        self._settings["sentence_pause_ms"] = value
        self._save_settings()
        self._invalidate_generated()

    def _on_line_pause_changed(self, _event=None):
        try:
            value = int(self._line_pause_var.get().strip() or "0")
        except ValueError:
            value = self._line_pause_ms
        value = max(0, min(10000, value))
        self._line_pause_ms = value
        self._line_pause_var.set(str(value))
        self._settings["line_pause_ms"] = value
        self._save_settings()
        self._invalidate_generated()

    def _on_sentence_pause(self):
        """Open the batch action that adds inline pause markers to the editor."""
        if self._busy:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(self._t("pause_dialog_title"))
        dialog.geometry("520x300")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.after(100, dialog.lift)

        ctk.CTkLabel(
            dialog,
            text=self._t("pause_dialog_title"),
            font=self._font(size=18, weight="bold"),
            text_color=self._c("text"),
        ).pack(anchor="w", padx=24, pady=(22, 6))
        ctk.CTkLabel(
            dialog,
            text=self._t("pause_dialog_hint"),
            wraplength=460,
            justify="left",
            text_color=self._c("muted"),
        ).pack(anchor="w", padx=24, pady=(0, 16))

        presets = ctk.CTkFrame(dialog, fg_color="transparent")
        presets.pack(fill="x", padx=20)

        def apply_value(raw_value):
            try:
                value = int(str(raw_value).strip())
            except (TypeError, ValueError):
                messagebox.showwarning(APP_NAME, self._t("pause_invalid"), parent=dialog)
                return
            if not 0 <= value <= 10000:
                messagebox.showwarning(APP_NAME, self._t("pause_invalid"), parent=dialog)
                return
            if self._pages:
                self._sync_page_from_ui()
            current = self._textbox.get("1.0", "end-1c")
            updated = insert_sentence_pause_directives(current, value)
            if updated == current:
                dialog.destroy()
                return
            count = len(re.findall(r"\[\s*pause\s*:", updated, re.IGNORECASE)) - len(
                re.findall(r"\[\s*pause\s*:", current, re.IGNORECASE)
            )
            self._replace_textbox(updated)
            if self._pages:
                self._sync_page_from_ui()
            self._invalidate_generated()
            self.log(self._t("pause_inserted", count=max(0, count)))
            dialog.destroy()

        preset_values = (100, 150, 200, 300, 400, 600)
        for column, value in enumerate(preset_values):
            ctk.CTkButton(
                presets,
                text=f"{value} ms",
                width=72,
                height=32,
                fg_color=self._c("surface_alt"),
                hover_color=self._c("card_raised"),
                border_width=1,
                border_color=self._c("border"),
                text_color=self._c("text"),
                command=lambda value=value: apply_value(value),
            ).grid(row=0, column=column, padx=3, pady=3)

        custom = ctk.CTkFrame(dialog, fg_color="transparent")
        custom.pack(fill="x", padx=24, pady=(16, 0))
        ctk.CTkLabel(
            custom,
            text=self._t("pause_custom"),
            text_color=self._c("muted"),
            font=self._font(size=12, weight="bold"),
        ).pack(side="left")
        custom_var = tk.StringVar(value=str(self._sentence_insert_pause_ms))
        entry = ctk.CTkEntry(
            custom,
            textvariable=custom_var,
            width=100,
            height=32,
            justify="right",
            fg_color=self._c("field"),
            border_color=self._c("border"),
            text_color=self._c("text"),
        )
        entry.pack(side="left", padx=(10, 6))
        ctk.CTkButton(
            custom,
            text=self._t("pause_apply"),
            width=76,
            height=32,
            fg_color=self._c("primary"),
            hover_color=self._c("primary_hover"),
            text_color="#FFFFFF",
            command=lambda: apply_value(custom_var.get()),
        ).pack(side="left")
        entry.bind("<Return>", lambda _event: apply_value(custom_var.get()))
        entry.focus_set()

    def _configure_highlight_tag(self):
        try:
            self._textbox.tag_config(
                "highlight_sentence",
                background="#2A4A7F" if self._theme == "dark" else "#CFE0FF",
                foreground="#F2F6FF" if self._theme == "dark" else "#17233A",
            )
        except Exception:  # noqa: BLE001
            pass

    def _build_highlight_ranges(self):
        """把时间轴句子映射到文本框中的位置（尽力而为，找不到就跳过）。"""
        ranges = []
        if not self._generated_timeline:
            return ranges
        try:
            for entry in self._generated_timeline.get("sentences", []):
                text = entry.get("text", "")
                if not text:
                    continue
                start = self._textbox.search(text, "1.0", stopindex="end")
                if start:
                    end = f"{start}+{len(text)}c"
                    ranges.append((entry.get("index", 0), start, end))
        except Exception:  # noqa: BLE001
            pass
        return ranges

    def _tick_highlight(self):
        if not self._highlight_running:
            return
        try:
            if not (pygame.mixer.get_init() and pygame.mixer.music.get_busy()):
                self._clear_highlight()
                return
            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms < 0:
                self._clear_highlight()
                return
            seconds = pos_ms / 1000.0
            idx = -1
            for entry in self._generated_timeline.get("sentences", []):
                if entry.get("start", 0) <= seconds < entry.get("end", 0):
                    idx = entry.get("index", -1)
                    break
            self._textbox.tag_remove("highlight_sentence", "1.0", "end")
            if idx >= 0:
                for index, start, end in self._highlight_ranges:
                    if index == idx:
                        self._textbox.tag_add("highlight_sentence", start, end)
                        self._textbox.see(start)
                        break
        except Exception:  # noqa: BLE001
            pass
        self.after(150, self._tick_highlight)

    def _clear_highlight(self):
        self._highlight_running = False
        try:
            self._textbox.tag_remove("highlight_sentence", "1.0", "end")
        except Exception:  # noqa: BLE001
            pass

    def _show_timeline_help(self):
        is_english = self._language == "en"
        dialog = ctk.CTkToplevel(self)
        dialog.title(self._t("timeline_help_title"))
        dialog.geometry("680x560")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            dialog, text=self._t("timeline_help_title"),
            font=self._font(size=18, weight="bold"), text_color=self._c("text"),
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(20, 8))
        ctk.CTkLabel(
            dialog, text=self._t("timeline_help_desc"), wraplength=630, justify="left",
            text_color=self._c("muted"),
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 12))

        # JSON 示例
        ctk.CTkLabel(
            dialog, text=self._t("timeline_help_json_title"),
            font=self._font(size=13, weight="bold"), text_color=self._c("accent"),
        ).grid(row=2, column=0, sticky="w", padx=24)
        example_json = (
            "{\n"
            '  "version": 1,\n'
            '  "kind": "sentence",\n'
            '  "engine": "edge-tts",\n'
            '  "boundary": "SentenceBoundary",\n'
            '  "voice": "en-US-AndrewMultilingualNeural",\n'
            '  "rate": "+0%",\n'
            '  "sentences": [\n'
            '    { "index": 0, "start": 0.000, "end": 2.540, "word_count": 6, "text": "Hello world." },\n'
            '    { "index": 1, "start": 2.540, "end": 5.120, "word_count": 5, "text": "This is a great tool." },\n'
            '    { "index": 2, "start": 5.120, "end": 8.000, "word_count": 6, "text": "Hope you enjoy it." }\n'
            "  ]\n"
            "}"
        )
        json_box = ctk.CTkTextbox(dialog, height=190, corner_radius=12, fg_color=self._c("field"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), font=ctk.CTkFont(family="Consolas", size=13), wrap="none")
        json_box.grid(row=3, column=0, sticky="nsew", padx=24, pady=(6, 12))
        json_box.insert("1.0", example_json)
        json_box.configure(state="disabled")

        # 高亮演示
        ctk.CTkLabel(
            dialog, text=self._t("timeline_help_highlight_title"),
            font=self._font(size=13, weight="bold"), text_color=self._c("accent"),
        ).grid(row=4, column=0, sticky="w", padx=24)
        demo_text = self._t("timeline_help_demo_text")
        demo_box = ctk.CTkTextbox(dialog, height=96, corner_radius=12, fg_color=self._c("field"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=13), wrap="word")
        demo_box.grid(row=5, column=0, sticky="ew", padx=24, pady=(6, 4))
        demo_box.insert("1.0", demo_text)
        demo_box.configure(state="disabled")
        demo_bg = "#2A4A7F" if self._theme == "dark" else "#CFE0FF"
        demo_fg = "#F2F6FF" if self._theme == "dark" else "#17233A"
        demo_box.tag_config("demo_hl", background=demo_bg, foreground=demo_fg)

        state = {"idx": -1}

        def step_demo():
            sentences = [s for s in demo_text.replace("\n", " ").split("。") if s.strip()]
            if not sentences:
                return
            state["idx"] = (state["idx"] + 1) % len(sentences)
            demo_box.tag_remove("demo_hl", "1.0", "end")
            cursor = "1.0"
            count = 0
            for sent in sentences:
                found = demo_box.search(sent, cursor, stopindex="end")
                if not found:
                    break
                if count == state["idx"]:
                    demo_box.tag_add("demo_hl", found, f"{found}+{len(sent)}c")
                    break
                cursor = f"{found}+{len(sent)}c"
                count += 1
            dialog.after(900, step_demo)

        def stop_demo():
            demo_box.tag_remove("demo_hl", "1.0", "end")

        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.grid(row=6, column=0, sticky="w", padx=24, pady=(2, 4))
        ctk.CTkButton(row, text=self._t("timeline_help_demo_btn"), width=130, height=30, fg_color=self._c("primary"), hover_color=self._c("primary_hover"), text_color="#FFFFFF", command=step_demo).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="Stop" if is_english else "停止", width=80, height=30, fg_color=self._c("surface_alt"), hover_color=self._c("card_raised"), text_color=self._c("text"), command=stop_demo).pack(side="left")
        ctk.CTkLabel(
            dialog, text=self._t("timeline_help_note"), wraplength=630, justify="left",
            text_color=self._c("muted"),
        ).grid(row=7, column=0, sticky="w", padx=24, pady=(8, 18))

    # ============================================================ 对话框

    def _localized_log_message(self, message: str) -> str:
        if self._language != "en":
            return message
        match = re.fullmatch(r"开始第 (\d+) 次生成（语音：(.*)）", message)
        if match:
            return f"Starting synthesis attempt {match.group(1)} (voice: {match.group(2)})"
        exact = {
            "音频数据接收完成。": "Audio data received.",
            "任务已取消。": "Task canceled.",
            "准备重试…": "Preparing retry…",
            "开始检测网络…": "Checking network…",
            "网络检测通过": "Network check passed.",
            "生成音频缓存已清理。": "Generated audio cache cleared.",
            "[任务] 正在停止…": "[Task] Stopping…",
            "[任务] 已取消。": "[Task] Canceled.",
        }
        if message in exact:
            return exact[message]
        proxy_match = re.fullmatch(r"\u7f51\u7edc\u68c0\u6d4b\u901a\u8fc7\uff08\u4ee3\u7406\uff1a(.*)\uff09", message)
        if proxy_match:
            return f"Network check passed (proxy: {proxy_match.group(1)})."

        substitutions = [
            (r"^\[语音\] 已加载 (\d+) 个可用语音$", r"[Voice] Loaded \1 available voices"),
            (r"^\[语音\] 加载语音列表失败：(.*)$", r"[Voice] Could not load voice list: \1"),
            (r"^\[生成\] 开始合成全文音频（(\d+) 字）$", r"[Generate] Synthesizing full audio (\1 characters)"),
            (r"^\[生成\] 开始合成第 (\d+) 页音频（(\d+) 字）$", r"[Generate] Synthesizing page \1 audio (\2 characters)"),
            (r"^\[导入\] 已导入 (\d+) 页：(.+)$", r"[Import] Imported \1 page(s): \2"),
            (r"^\[导入\] 导入失败：(.*)$", r"[Import] Import failed: \1"),
            (r"^\[分页\] 开始逐页配音（共 (\d+) 页）$", r"[Pages] Starting page-by-page dubbing (\1 pages)"),
            (r"^\[分页\] 第 (\d+)/(\d+) 页完成（(.+) KB）。$", r"[Pages] Page \1/\2 done (\3 KB)."),
            (r"^\[分页\] 第 (\d+)/(\d+) 页无可用文字，已跳过。$", r"[Pages] Page \1/\2 has no readable text; skipped."),
            (r"^\[分页\] 第 (\d+)/(\d+) 页生成失败：(.*)$", r"[Pages] Page \1/\2 failed: \3"),
            (r"^\[分页\] 逐页配音完成：(\d+) 页，可试听或保存下载。$", r"[Pages] Dubbing complete: \1 pages. Play or save anytime."),
            (r"^\[分页\] 已停止（完成 (\d+) 页）。$", r"[Pages] Stopped (\1 page(s) done)."),
            (r"^\[分页\] 未生成任何页面音频。$", r"[Pages] No page audio was generated."),
            (r"^\[保存\] 分页配音压缩包已保存：(.*)$", r"[Save] Page bundle saved: \1"),
            (r"^\[生成\] 音频已生成：(.*)$", r"[Generate] Audio ready: \1"),
            (r"^\[生成\] 生成期间文本已修改，请重新生成。$", r"[Generate] Text changed during generation. Please generate again."),
            (r"^\[试听\] 开始播放已生成的音频…$", r"[Play] Playing generated audio…"),
            (r"^\[试听\] 已停止播放。$", r"[Play] Playback stopped."),
            (r"^\[保存\] 音频已保存：(.*)$", r"[Save] Audio saved: \1"),
            (r"^\[保存\] 时间轴 JSON 已保存：(.*)$", r"[Save] Timeline JSON saved: \1"),
            (r"^\[警告\] 时间轴 JSON 保存失败：(.*)$", r"[Warning] Could not save timeline JSON: \1"),
            (r"^\[任务\] 失败：(.*)$", r"[Task] Failed: \1"),
            (r"^\[网络\] 不可达，检测到代理 (.*)，可能是网络不通或代理设置不正确。$", r"[Network] Unreachable; proxy detected: \1. Check the connection or proxy configuration."),
            (r"^\[网络\] 不可达（(.*)）。生成可能很慢或失败，建议检查网络后重试。$", r"[Network] Unreachable (\1). Synthesis may be slow or fail; check your network and retry."),
            (r"^\[警告\] 生成失败：(.*)（可能是网络不通或代理设置不正确）$", r"[Warning] Synthesis failed: \1 (network or proxy may be unavailable or misconfigured)"),
        ]
        for pattern, replacement in substitutions:
            localized = re.sub(pattern, replacement, message)
            if localized != message:
                return localized
        return message

    def _localized_stall_message(self, message: str) -> str:
        if self._language != "en":
            return message
        if "长时间没有收到新的音频数据" in message:
            return (
                "No new audio data has arrived for a while. Your network connection "
                "or proxy may be unavailable or misconfigured. Would you like to retry?"
            )
        if "网络不通或代理设置不正确" in message:
            return "Your network connection or proxy may be unavailable or misconfigured. Would you like to retry?"
        return message

    def _show_stall_dialog(self, message: str) -> str:
        is_english = self._language == "en"
        dialog = ctk.CTkToplevel(self)
        dialog.title("⚠ Generation appears stalled" if is_english else "⚠ 生成似乎卡住了")
        dialog.geometry("540x260")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.after(100, dialog.lift)

        ctk.CTkLabel(
            dialog,
            text="Generation appears stalled" if is_english else "生成似乎卡住了",
            font=self._font(size=18, weight="bold"),
            text_color="#e0af68",
        ).pack(pady=(22, 6))

        ctk.CTkLabel(
            dialog,
            text=self._localized_stall_message(message),
            wraplength=470,
            justify="left",
            text_color="#c0caf5",
        ).pack(padx=30, pady=(0, 14))

        result = {"value": "cancel"}

        def choose(value):
            result["value"] = value
            dialog.destroy()

        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.pack(pady=(6, 20))
        ctk.CTkButton(row, text="Keep waiting" if is_english else "继续等待", width=120, command=lambda: choose("continue")).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Retry" if is_english else "重试", width=120, command=lambda: choose("retry")).pack(side="left", padx=6)
        ctk.CTkButton(
            row, text="Cancel" if is_english else "取消", width=120, fg_color="#f7768e", hover_color="#d9556d",
            command=lambda: choose("cancel"),
        ).pack(side="left", padx=6)

        dialog.wait_window()
        return result["value"]

    def _maybe_open_folder(self, path):
        is_english = self._language == "en"
        message = (
            f"Audio saved:\n{path}\n\nOpen the containing folder?"
            if is_english
            else f"音频已保存：\n{path}\n\n是否打开所在文件夹？"
        )
        if messagebox.askyesno(APP_NAME, message):
            try:
                os.startfile(os.path.dirname(path))
            except Exception:  # noqa: BLE001
                pass

    # ============================================================ 杂项

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {self._localized_log_message(message)}\n"
        self._log.configure(state="normal")
        self._log.insert("end", line)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _sync_generated_status(self):
        if self._current_page_generated() is not None:
            self._status_label.configure(text=self._t("generated_ok"), text_color="#9ece6a")
            self._progress.set(1.0)
        elif self._generated_path and os.path.exists(self._generated_path):
            self._status_label.configure(text=self._t("generated_ok"), text_color="#9ece6a")
            self._progress.set(1.0)
        else:
            self._status_label.configure(text=self._t("ready"), text_color=self._c("success"))
            self._progress.set(0)

    def _update_generated_buttons(self):
        # 试听/保存始终可见可用：尚未生成时点击会提示“请先生成”，避免按钮被误认为缺失
        state = "disabled" if self._busy else "normal"
        self._btn_play.configure(state=state)
        self._btn_save.configure(state=state)
        has_result = bool(self._generated_pages or (self._generated_path and os.path.exists(self._generated_path)))
        if self._btn_result_preview is not None:
            self._btn_result_preview.configure(state=state if has_result else "disabled")

    def _invalidate_generated(self):
        self._generated_path = None
        self._generated_text = None
        self._generated_timeline = None
        self._sync_generated_status()
        self._update_generated_buttons()

    def _set_busy_ui(self, busy: bool):
        self._btn_generate.configure(state="disabled" if busy else "normal")
        self._btn_stop.configure(state="normal" if busy else "disabled")
        if self._mode_selector is not None:
            self._mode_selector.configure(state="disabled" if busy else "normal")
        if self._btn_import is not None:
            self._btn_import.configure(state="disabled" if busy else "normal")
        if self._btn_download_example is not None:
            self._btn_download_example.configure(state="disabled" if busy else "normal")
        if self._btn_sentence_pause is not None:
            self._btn_sentence_pause.configure(state="disabled" if busy else "normal")
        if self._btn_dub_pages is not None:
            self._btn_dub_pages.configure(state="disabled" if busy else ("normal" if self._pages else "disabled"))
        if self._btn_prepare_lines is not None:
            self._btn_prepare_lines.configure(state="disabled" if busy else "normal")
        self._update_page_bar()
        self._update_generated_buttons()

    def _on_close(self):
        self._cancel_event.set()
        self._stop_playback()
        self._cleanup_batch()
        try:
            if os.path.exists(self._preview_path):
                os.unlink(self._preview_path)
        except OSError:
            pass
        self.destroy()


def main():
    try:
        app = App()
        app.mainloop()
    except Exception:
        import traceback
        try:
            log_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "EdgeTTSGui")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "crash.log"), "w", encoding="utf-8") as crash_file:
                crash_file.write(traceback.format_exc())
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
