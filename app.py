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
import tempfile
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import pygame
import tkinter as tk
from tkinter import filedialog, messagebox

from tts_engine import (
    MAX_RETRIES,
    ProbeResult,
    StallController,
    TTSConfig,
    TTSEngine,
    detect_proxy,
    list_tts_voices,
    probe_network,
)
from text_utils import clean_text, default_filename, normalize_for_tts

APP_NAME = "Edge TTS 语音合成助手"
APP_VERSION = "1.0.6"
DEVELOPER = "WangYufan"
DEVELOPER_QQ = "1471056247"
REPOSITORY_URL = "https://github.com/JJosephph/ms-edge-tts-gui"
REPOSITORY_DISPLAY = "github.com/JJosephph/ms-edge-tts-gui"
UI_FONT_FAMILY = "Microsoft YaHei UI"
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

CURATED_VOICES = [
    ("推荐 · 兼容原工作流（Andrew）", "en-US-AndrewMultilingualNeural"),
    ("推荐 · 中文女声 晓晓", "zh-CN-XiaoxiaoNeural"),
    ("中文 · 晓伊（女）", "zh-CN-XiaoyiNeural"),
    ("中文 · 云希（男）", "zh-CN-YunxiNeural"),
    ("中文 · 云健（男）", "zh-CN-YunjianNeural"),
    ("English · Aria (US)", "en-US-AriaNeural"),
    ("English · Jenny (US)", "en-US-JennyNeural"),
    ("English · Aria (US)", "en-US-AriaNeural"),
    ("English · Jenny (US)", "en-US-JennyNeural"),
    ("English · Ryan (GB)", "en-GB-RyanNeural"),
    ("日本語 · Nanami", "ja-JP-NanamiNeural"),
    ("한국어 · SunHi", "ko-KR-SunHiNeural"),
]

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

        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("980x720")
        self.minsize(860, 640)

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
        self._search_text = ""
        self._language = "zh"
        self._selected_voice_code = DEFAULT_VOICE
        self._generated_path: str | None = None
        self._generated_text: str | None = None

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
        "helper": {"zh": "支持 Markdown / 纯文本；生成一次全文音频，之后可随时试听或保存下载，无需重复合成。", "en": "Markdown and plain text supported; synthesize once, then play or save anytime without re-rendering."},
        "voice": {"zh": "语音", "en": "Voice"},
        "search": {"zh": "搜索语音，如：晓晓 / Andrew…", "en": "Search voices, e.g. Xiaoxiao / Andrew…"},
        "original": {"zh": "原工作流默认：Andrew Multilingual · 语速 +0% · 音量 +0% · 音调 +0Hz", "en": "Original workflow: Andrew Multilingual · rate +0% · volume +0% · pitch +0Hz"},
        "restore": {"zh": "恢复原工作流默认", "en": "Restore workflow defaults"},
        "reset_compact": {"zh": "恢复", "en": "Reset"},
        "rate": {"zh": "语速", "en": "Rate"},
        "volume": {"zh": "音量", "en": "Volume"},
        "pitch": {"zh": "音调", "en": "Pitch"},
        "ready": {"zh": "就绪", "en": "Ready"},
        "generate": {"zh": "生成音频", "en": "Generate Audio"},
        "play": {"zh": "▶ 试听", "en": "▶ Play"},
        "save": {"zh": "保存下载", "en": "Save Audio"},
        "generated_ok": {"zh": "已生成 ✔ 可试听 / 保存", "en": "Generated ✔ Play or save"},
        "canceled": {"zh": "已取消", "en": "Canceled"},
        "failed": {"zh": "失败 ✖", "en": "Failed ✖"},
        "stopped": {"zh": "已停止", "en": "Stopped"},
        "no_audio": {"zh": "请先点击“生成音频”生成一段音频。", "en": "Please click “Generate Audio” first."},
        "stop": {"zh": "停止", "en": "Stop"},
        "log": {"zh": "活动日志", "en": "Activity log"},
        "footer": {"zh": "免费开源软件 · MIT License · Powered by Microsoft Edge TTS", "en": "Free open-source software · MIT License · Powered by Microsoft Edge TTS"},
        "repository": {"zh": "仓库：", "en": "Repo: "},
        "empty": {"zh": "请输入文章内容。", "en": "Please enter some article text."},
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
        return ctk.CTkFont(family=UI_FONT_FAMILY, size=size, weight=weight)

    def _c(self, key: str) -> str:
        return THEMES[self._theme][key]

    def _rebuild_ui(self):
        text = self._textbox.get("1.0", "end-1c")
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
        self._refresh_voice_combo()
        self._on_text_changed()
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
        composer.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(composer, text=self._t("composer"), text_color=self._c("accent"), font=self._font(size=11, weight="bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 0))
        title_row = ctk.CTkFrame(composer, fg_color="transparent")
        title_row.grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 6))
        ctk.CTkLabel(title_row, text=self._t("article"), text_color=self._c("text"), font=self._font(size=18, weight="bold")).pack(side="left")
        self._char_count = ctk.CTkLabel(title_row, text=self._t("count", count=0), text_color=self._c("muted"), font=self._font(size=12))
        self._char_count.pack(side="right")
        self._textbox = ctk.CTkTextbox(composer, wrap="word", corner_radius=14, fg_color=self._c("field"), border_width=1, border_color=self._c("border"), text_color=self._c("text"), font=self._font(size=14))
        self._textbox.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 8))
        ctk.CTkLabel(composer, text=self._t("helper"), text_color=self._c("muted"), anchor="w").grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 14))

        deck = ctk.CTkFrame(workspace, width=375, corner_radius=20, fg_color=self._c("card"), border_width=1, border_color=self._c("border"))
        deck.grid(row=0, column=1, sticky="ns")
        deck.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(deck, text=self._t("voice"), text_color=self._c("text"), font=self._font(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(12, 5))
        self._voice_search = ctk.CTkEntry(deck, placeholder_text=self._t("search"), height=30, font=self._font(size=13), fg_color=self._c("field"), border_color=self._c("border"), text_color=self._c("text"), placeholder_text_color=self._c("muted"))
        self._voice_search.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 4))
        self._voice_var = tk.StringVar(value=self._display_name(self._selected_voice_code))
        self._voice_combo = ctk.CTkComboBox(deck, values=[self._display_name(code) for _, code in CURATED_VOICES], variable=self._voice_var, height=32, fg_color=self._c("field"), border_color=self._c("border"), button_color=self._c("primary"), button_hover_color=self._c("primary_hover"), text_color=self._c("text"), dropdown_fg_color=self._c("surface"), dropdown_hover_color=self._c("card_raised"), font=self._font(size=13), dropdown_font=self._font(size=13), command=self._on_voice_changed)
        self._voice_combo.grid(row=2, column=0, sticky="ew", padx=18)
        voice_details = ctk.CTkFrame(deck, fg_color="transparent")
        voice_details.grid(row=3, column=0, sticky="ew", padx=18, pady=(2, 5))
        voice_details.grid_columnconfigure(0, weight=1)
        self._voice_info = ctk.CTkLabel(voice_details, text="", text_color=self._c("muted"), anchor="w", font=self._font(size=11))
        self._voice_info.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(voice_details, text=self._t("reset_compact"), width=42, height=25, font=self._font(size=11), fg_color="transparent", border_width=1, border_color=self._c("border"), hover_color=self._c("card_raised"), text_color=self._c("muted"), command=self._restore_original_defaults).grid(row=0, column=1, padx=(6, 0))

        parameters = ctk.CTkFrame(deck, corner_radius=12, fg_color=self._c("surface_alt"))
        parameters.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 7))
        for column in range(3):
            parameters.grid_columnconfigure(column, weight=1, uniform="voice_control")
        self._rate_var = tk.IntVar(value=getattr(self, "_rate_value", DEFAULT_RATE))
        self._volume_var = tk.IntVar(value=getattr(self, "_volume_value", DEFAULT_VOLUME))
        self._pitch_var = tk.IntVar(value=getattr(self, "_pitch_value", DEFAULT_PITCH))
        self._add_slider_card(parameters, 0, self._t("rate"), self._rate_var, -50, 100, self._fmt_rate)
        self._add_slider_card(parameters, 1, self._t("volume"), self._volume_var, -50, 100, self._fmt_volume)
        self._add_slider_card(parameters, 2, self._t("pitch"), self._pitch_var, -20, 20, self._fmt_pitch)

        status_row = ctk.CTkFrame(deck, fg_color="transparent")
        status_row.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 3))
        status_row.grid_columnconfigure(0, weight=1)
        self._status_label = ctk.CTkLabel(status_row, text=self._t("ready"), text_color=self._c("success"), font=self._font(size=12, weight="bold"))
        self._status_label.grid(row=0, column=0, sticky="w")
        self._btn_stop = ctk.CTkButton(status_row, text=self._t("stop"), command=self._on_stop, width=60, height=22, font=self._font(size=11), fg_color="transparent", hover_color=self._c("card_raised"), text_color=self._c("danger"), state="disabled")
        self._btn_stop.grid(row=0, column=1, sticky="e")
        self._progress = ctk.CTkProgressBar(deck, height=8, mode="determinate", progress_color=self._c("primary"), fg_color=self._c("border"))
        self._progress.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 7))
        self._progress.set(0)

        actions = ctk.CTkFrame(deck, fg_color="transparent")
        actions.grid(row=7, column=0, sticky="ew", padx=18, pady=(0, 9))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        self._btn_generate = ctk.CTkButton(actions, text=self._t("generate"), command=self._on_generate, height=36, font=self._font(size=14, weight="bold"), fg_color=self._c("primary"), hover_color=self._c("primary_hover"), text_color="#FFFFFF")
        self._btn_generate.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self._btn_play = ctk.CTkButton(actions, text=self._t("play"), command=self._on_play, height=32, font=self._font(size=12, weight="bold"), fg_color=self._c("surface_alt"), hover_color=self._c("border"), text_color=self._c("text"))
        self._btn_play.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self._btn_save = ctk.CTkButton(actions, text=self._t("save"), command=self._on_save, height=32, font=self._font(size=12, weight="bold"), fg_color=self._c("star"), hover_color=self._c("star_hover"), border_width=1, border_color=self._c("warning"), text_color=self._c("warning"))
        self._btn_save.grid(row=1, column=1, sticky="ew", padx=(4, 0))
        self._sync_generated_status()
        self._update_generated_buttons()
        self._update_voice_info()

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
        self._voice_search.bind("<KeyRelease>", self._on_search_voice)
        self._textbox.bind("<KeyRelease>", self._on_text_edited)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ============================================================ 后台任务

    def _start_background_jobs(self):
        threading.Thread(target=self._load_voices, daemon=True).start()
        threading.Thread(target=self._probe_worker, daemon=True).start()
        self.after(150, self._poll_ui)

    def _load_voices(self):
        try:
            proxy = detect_proxy()
            voices = list_tts_voices(proxy=proxy)
            self._ui_q.put(("voices", voices, ""))
        except Exception as exc:  # noqa: BLE001
            self._ui_q.put(("voices", [], str(exc)[:300]))

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
        for friendly, voice_code in CURATED_VOICES:
            if voice_code == code:
                return f"{friendly}（{code}）" if self._language == "zh" else f"{friendly} ({code})"
        return code

    def _on_voice_changed(self, value):
        for code in list(self._voice_map) + [code for _, code in CURATED_VOICES]:
            if self._display_name(code) == value:
                self._selected_voice_code = code
                break
        self._invalidate_generated()
        self._update_voice_info()

    def _restore_original_defaults(self):
        self._selected_voice_code = DEFAULT_VOICE
        self._rate_var.set(DEFAULT_RATE)
        self._volume_var.set(DEFAULT_VOLUME)
        self._pitch_var.set(DEFAULT_PITCH)
        self._refresh_voice_combo()
        self._invalidate_generated()
        self.log(self._t("original"))

    def _selected_voice(self) -> str:
        value = self._voice_var.get()
        for code in list(self._voice_map) + [code for _, code in CURATED_VOICES]:
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

    def _on_search_voice(self, _event=None):
        self._search_text = self._voice_search.get().strip().lower()
        self._refresh_voice_combo()

    def _refresh_voice_combo(self):
        codes = []
        if self._search_text:
            for code, info in self._voice_map.items():
                haystack = f"{info.get('FriendlyName', '')} {info.get('Locale', '')} {code}".lower()
                if self._search_text in haystack:
                    codes.append(code)
        else:
            codes = [c for _f, c in CURATED_VOICES if c not in codes]
            codes += [c for c in self._voice_map if c not in codes]
        names = [self._display_name(c) for c in codes[:300]]
        self._voice_combo.configure(values=names)
        selected_name = self._display_name(self._selected_voice_code)
        if names:
            self._voice_var.set(selected_name if selected_name in names else names[0])
            if selected_name not in names:
                self._selected_voice_code = codes[0]
        self._update_voice_info()

    def _apply_voices(self, voices, err):
        if err:
            self.log(f"[语音] 加载语音列表失败：{err}")
        else:
            self._voice_map = {v["ShortName"]: v for v in voices}
            self.log(f"[语音] 已加载 {len(self._voice_map)} 个可用语音")
            self._refresh_voice_combo()

    # ============================================================ 文本

    def _on_text_changed(self, _event=None):
        text = self._textbox.get("1.0", "end-1c")
        self._char_count.configure(text=self._t("count", count=len(text)))

    def _on_text_edited(self, _event=None):
        self._on_text_changed()
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
        self._ui_q.put(("task_done", task.mode, result))

    def _on_task_done(self, mode, result):
        self._busy = False
        self._set_busy_ui(False)

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
        cleaned = self._get_cleaned_text()
        if not cleaned:
            messagebox.showwarning(APP_NAME, "请输入文章内容。")
            return
        self._stop_playback()
        self.log(f"[生成] 开始合成全文音频（{len(cleaned)} 字）")
        self._start_task(cleaned, self._preview_path, "generate")

    def _on_play(self):
        if not self._generated_path or not os.path.exists(self._generated_path):
            messagebox.showinfo(APP_NAME, self._t("no_audio"))
            return
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            self._stop_playback()
            self.log("[试听] 已停止播放。")
            return
        self.log("[试听] 开始播放已生成的音频…")
        self._play_audio(self._generated_path)

    def _on_save(self):
        if not self._generated_path or not os.path.exists(self._generated_path):
            messagebox.showinfo(APP_NAME, self._t("no_audio"))
            return
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        path = filedialog.asksaveasfilename(
            title="保存音频",
            defaultextension=".mp3",
            filetypes=[("MP3 音频", "*.mp3")],
            initialdir=default_dir if os.path.isdir(default_dir) else os.path.expanduser("~"),
            initialfile=default_filename(),
        )
        if not path:
            return
        try:
            shutil.copy2(self._generated_path, path)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"保存失败：{exc}")
            return
        self.log(f"[保存] 音频已保存：{path}")
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
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
        except Exception:  # noqa: BLE001
            pass

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
            (r"^\[生成\] 音频已生成：(.*)$", r"[Generate] Audio ready: \1"),
            (r"^\[生成\] 生成期间文本已修改，请重新生成。$", r"[Generate] Text changed during generation. Please generate again."),
            (r"^\[试听\] 开始播放已生成的音频…$", r"[Play] Playing generated audio…"),
            (r"^\[试听\] 已停止播放。$", r"[Play] Playback stopped."),
            (r"^\[保存\] 音频已保存：(.*)$", r"[Save] Audio saved: \1"),
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
        if self._generated_path and os.path.exists(self._generated_path):
            self._status_label.configure(text=self._t("generated_ok"), text_color="#9ece6a")
            self._progress.set(1.0)
        else:
            self._status_label.configure(text=self._t("ready"), text_color=self._c("success"))
            self._progress.set(0)

    def _update_generated_buttons(self):
        available = bool(self._generated_path) and os.path.exists(self._generated_path)
        state = "normal" if available and not self._busy else "disabled"
        self._btn_play.configure(state=state)
        self._btn_save.configure(state=state)

    def _invalidate_generated(self):
        self._generated_path = None
        self._generated_text = None
        self._sync_generated_status()
        self._update_generated_buttons()

    def _set_busy_ui(self, busy: bool):
        self._btn_generate.configure(state="disabled" if busy else "normal")
        self._btn_stop.configure(state="normal" if busy else "disabled")
        self._update_generated_buttons()

    def _on_close(self):
        self._cancel_event.set()
        self._stop_playback()
        try:
            if os.path.exists(self._preview_path):
                os.unlink(self._preview_path)
        except OSError:
            pass
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
