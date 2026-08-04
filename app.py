# -*- coding: utf-8 -*-
"""Edge TTS 语音合成助手 —— 现代化桌面 GUI 客户端。

功能：
- 粘贴文章一键转语音，支持试听与导出 MP3
- 网络检测：离线 / 代理异常会提示
- 卡住检测：长时间无音频数据时提示是否重试
- 开源标识 / 仓库地址 / 开发者信息
"""

import os
import queue
import tempfile
import threading
import webbrowser
from datetime import datetime

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
from text_utils import clean_text, default_filename, normalize_for_tts, preview_text

APP_NAME = "Edge TTS 语音合成助手"
APP_VERSION = "1.0.0"
DEVELOPER = "WangYufan"
REPOSITORY_URL = "https://github.com/JJosephph/ms-edge-tts-gui"
REPOSITORY_DISPLAY = "github.com/JJosephph/ms-edge-tts-gui"

DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"

CURATED_VOICES = [
    ("推荐 · Daily Manna 原工作流（Andrew）", "en-US-AndrewMultilingualNeural"),
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
        self._preview_path = os.path.join(tempfile.gettempdir(), "edge_tts_preview.mp3")

        self._voice_map: dict = {}
        self._search_text = ""
        self._language = "zh"
        self._selected_voice_code = DEFAULT_VOICE

        self._build_ui()
        self._bind_events()

        # 启动后后台加载语音列表 + 网络探测
        self.after(400, self._start_background_jobs)

    # ============================================================ UI 构建

    TRANSLATIONS = {
        "app": {"zh": "Edge TTS 语音合成助手", "en": "Edge TTS Voice Studio"},
        "open": {"zh": "开源 · MIT License", "en": "Open Source · MIT License"},
        "repo": {"zh": "GitHub 仓库 ↗", "en": "GitHub Repo ↗"},
        "star": {"zh": "⭐ 去 GitHub 点 Star", "en": "⭐ Star on GitHub"},
        "developer": {"zh": "开发者", "en": "Developer"},
        "language": {"zh": "EN", "en": "中文"},
        "checking": {"zh": "●  检测中…", "en": "●  Checking network…"},
        "check_network": {"zh": "检测网络", "en": "Check network"},
        "network_ok": {"zh": "●  网络正常（{latency:.0f} ms）", "en": "●  Network OK ({latency:.0f} ms)"},
        "network_bad": {"zh": "●  网络异常", "en": "●  Network unavailable"},
        "article": {"zh": "📄 文章内容", "en": "📄 Article"},
        "count": {"zh": "字数：{count}", "en": "Characters: {count}"},
        "helper": {"zh": "支持 Markdown / 纯文本；试听只合成前 400 字。", "en": "Markdown and plain text supported; preview synthesizes the first 400 characters."},
        "voice": {"zh": "🔊 语音", "en": "🔊 Voice"},
        "search": {"zh": "搜索语音，如：晓晓 / Andrew…", "en": "Search voices, e.g. Xiaoxiao / Andrew…"},
        "original": {"zh": "原工作流默认：Andrew Multilingual · 语速 +0% · 音量 +0% · 音调 +0Hz", "en": "Original workflow: Andrew Multilingual · rate +0% · volume +0% · pitch +0Hz"},
        "restore": {"zh": "↺ 恢复原工作流默认", "en": "↺ Restore workflow defaults"},
        "rate": {"zh": "语速", "en": "Rate"},
        "volume": {"zh": "音量", "en": "Volume"},
        "pitch": {"zh": "音调", "en": "Pitch"},
        "ready": {"zh": "就绪", "en": "Ready"},
        "preview": {"zh": "▶ 试听", "en": "▶ Preview"},
        "export": {"zh": "⬇ 导出音频", "en": "⬇ Export MP3"},
        "stop": {"zh": "■ 停止", "en": "■ Stop"},
        "log": {"zh": "📋 运行日志", "en": "📋 Activity log"},
        "footer": {"zh": "🧡 开源软件 · MIT License · Powered by Microsoft Edge TTS", "en": "🧡 Open source · MIT License · Powered by Microsoft Edge TTS"},
        "repository": {"zh": "仓库：", "en": "Repo: "},
        "empty": {"zh": "请输入文章内容。", "en": "Please enter some article text."},
    }

    def _t(self, key, **kwargs):
        value = self.TRANSLATIONS[key][self._language]
        return value.format(**kwargs) if kwargs else value

    def _app_name(self):
        return self._t("app")

    def _switch_language(self):
        if self._busy:
            messagebox.showinfo(self._app_name(), "Please stop the current task first." if self._language == "en" else "请先停止当前任务。")
            return
        text = self._textbox.get("1.0", "end-1c")
        voice = self._selected_voice()
        rate = self._rate_var.get()
        volume = self._volume_var.get()
        pitch = self._pitch_var.get()
        self._language = "en" if self._language == "zh" else "zh"
        for child in self.winfo_children():
            child.destroy()
        self.title(f"{self._app_name()} v{APP_VERSION}")
        self._build_ui()
        self._bind_events()
        self._selected_voice_code = voice
        self._rate_var.set(rate)
        self._volume_var.set(volume)
        self._pitch_var.set(pitch)
        if text:
            self._textbox.insert("1.0", text)
        self._refresh_voice_combo()
        self._on_text_changed()
        self.after(150, self._poll_ui)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_network_bar()
        self._build_content()
        self._build_log()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 4))
        header.grid_columnconfigure(0, weight=1)
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_frame, text="🎙️  " + self._app_name(), font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(title_frame, text=f"  v{APP_VERSION}", text_color="#7aa2f7", font=ctk.CTkFont(size=13)).pack(side="left", padx=(8, 0))
        badges = ctk.CTkFrame(header, fg_color="transparent")
        badges.grid(row=0, column=1, sticky="e")
        self._badge(badges, self._t("open"), "#4caf50").pack(side="left", padx=4)
        ctk.CTkButton(badges, text=self._t("repo"), width=104, height=28, fg_color="transparent", hover_color="#2b3245", border_width=1, border_color="#3a4358", text_color="#8ab4f8", command=lambda: webbrowser.open(REPOSITORY_URL)).pack(side="left", padx=4)
        ctk.CTkButton(badges, text=self._t("star"), width=142, height=28, fg_color="#3b3320", hover_color="#55492c", border_width=1, border_color="#8a6d2f", text_color="#e0c068", command=lambda: webbrowser.open(REPOSITORY_URL)).pack(side="left", padx=4)
        ctk.CTkLabel(badges, text=f"{self._t('developer')}：{DEVELOPER}", text_color="#c0caf5", font=ctk.CTkFont(size=13)).pack(side="left", padx=(8, 0))
        ctk.CTkButton(badges, text=self._t("language"), width=48, height=28, fg_color="#2b3245", hover_color="#3a4358", command=self._switch_language).pack(side="left", padx=(8, 0))

    def _badge(self, master, text, color):
        return ctk.CTkLabel(master, text=text, text_color=color, font=ctk.CTkFont(size=13, weight="bold"))

    def _build_network_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=10, fg_color="#1b1f2b")
        bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 8))
        bar.grid_columnconfigure(0, weight=1)
        self._net_dot = ctk.CTkLabel(bar, text=self._t("checking"), text_color="#e0af68")
        self._net_dot.grid(row=0, column=0, sticky="w", padx=14, pady=8)
        ctk.CTkButton(bar, text=self._t("check_network"), width=104, height=28, command=self._on_check_network).grid(row=0, column=1, sticky="e", padx=12, pady=8)

    def _build_content(self):
        content = ctk.CTkFrame(self, corner_radius=12)
        content.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 8))
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0)
        content.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 8), pady=14)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        input_header = ctk.CTkFrame(left, fg_color="transparent")
        input_header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(input_header, text=self._t("article"), font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        self._char_count = ctk.CTkLabel(input_header, text=self._t("count", count=0), text_color="#8a93a6")
        self._char_count.pack(side="right")
        ctk.CTkLabel(left, text=self._t("helper"), text_color="#7f8aa2", anchor="w", justify="left").grid(row=1, column=0, sticky="ew", pady=(7, 2))
        self._textbox = ctk.CTkTextbox(left, wrap="word", corner_radius=10, font=ctk.CTkFont(size=14))
        self._textbox.grid(row=2, column=0, sticky="nsew", pady=(4, 0))

        right = ctk.CTkFrame(content, width=365, corner_radius=10)
        right.grid(row=0, column=1, sticky="ns", padx=(8, 14), pady=14)
        right.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(right, text=self._t("voice"), font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        self._voice_search = ctk.CTkEntry(right, placeholder_text=self._t("search"), height=30)
        self._voice_search.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 4))
        self._voice_var = tk.StringVar(value=self._display_name(self._selected_voice_code))
        self._voice_combo = ctk.CTkComboBox(right, values=[self._display_name(code) for _, code in CURATED_VOICES], variable=self._voice_var, height=32, command=self._on_voice_changed)
        self._voice_combo.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 2))
        self._voice_info = ctk.CTkLabel(right, text="", text_color="#7f8aa2", anchor="w", justify="left")
        self._voice_info.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 2))
        ctk.CTkButton(right, text=self._t("restore"), height=27, fg_color="transparent", border_width=1, border_color="#3a4358", hover_color="#2b3245", command=self._restore_original_defaults).grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 6))

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=14, pady=(2, 6))
        actions.grid_columnconfigure((0, 1, 2), weight=1)
        self._btn_preview = ctk.CTkButton(actions, text=self._t("preview"), command=self._on_preview, height=36)
        self._btn_preview.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self._btn_export = ctk.CTkButton(actions, text=self._t("export"), command=self._on_export, height=36)
        self._btn_export.grid(row=0, column=1, sticky="ew", padx=3)
        self._btn_stop = ctk.CTkButton(actions, text=self._t("stop"), command=self._on_stop, height=36, fg_color="#3a4358", hover_color="#4a546c", state="disabled")
        self._btn_stop.grid(row=0, column=2, sticky="ew", padx=(3, 0))

        self._rate_var = tk.IntVar(value=getattr(self, "_rate_value", 0))
        self._volume_var = tk.IntVar(value=getattr(self, "_volume_value", 0))
        self._pitch_var = tk.IntVar(value=getattr(self, "_pitch_value", 0))
        self._add_slider(right, 6, self._t("rate"), self._rate_var, -50, 100, self._fmt_rate)
        self._add_slider(right, 8, self._t("volume"), self._volume_var, -50, 100, self._fmt_volume)
        self._add_slider(right, 10, self._t("pitch"), self._pitch_var, -20, 20, self._fmt_pitch)
        self._status_label = ctk.CTkLabel(right, text=self._t("ready"), text_color="#9ece6a", font=ctk.CTkFont(size=13))
        self._status_label.grid(row=12, column=0, sticky="w", padx=14, pady=(8, 3))
        self._progress = ctk.CTkProgressBar(right, mode="indeterminate")
        self._progress.grid(row=13, column=0, sticky="ew", padx=14, pady=(0, 10))
        self._progress.set(0)
        self._update_voice_info()

    def _add_slider(self, master, row, label, var, lo, hi, fmt):
        row_frame = ctk.CTkFrame(master, fg_color="transparent")
        row_frame.grid(row=row, column=0, sticky="ew", padx=14, pady=(5, 0))
        row_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row_frame, text=label, width=48).grid(row=0, column=0, sticky="w")
        value_label = ctk.CTkLabel(row_frame, text=fmt(var.get()), width=56, text_color="#7aa2f7")
        value_label.grid(row=0, column=2, sticky="e")
        slider = ctk.CTkSlider(row_frame, from_=lo, to=hi, variable=var, command=lambda value: value_label.configure(text=fmt(value)))
        slider.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 0))

    def _fmt_rate(self, value):
        return f"{'+' if value >= 0 else ''}{int(value)}%"

    def _fmt_volume(self, value):
        return f"{'+' if value >= 0 else ''}{int(value)}%"

    def _fmt_pitch(self, value):
        return f"{'+' if value >= 0 else ''}{int(value)}Hz"

    def _build_log(self):
        log_frame = ctk.CTkFrame(self, corner_radius=10)
        log_frame.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 8))
        log_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_frame, text=self._t("log"), font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 2))
        self._log = ctk.CTkTextbox(log_frame, height=110, corner_radius=8, font=ctk.CTkFont(size=12))
        self._log.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        self._log.configure(state="disabled")

    def _build_footer(self):
        footer = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(footer, text=self._t("footer"), text_color="#7f8aa2").grid(row=0, column=0, sticky="w")
        repo = ctk.CTkLabel(footer, text=f"{self._t('repository')}{REPOSITORY_DISPLAY}", text_color="#8ab4f8", cursor="hand2")
        repo.grid(row=0, column=1, sticky="e")
        repo.bind("<Button-1>", lambda _event: webbrowser.open(REPOSITORY_URL))

    # ============================================================ 事件绑定

    def _bind_events(self):
        self._voice_search.bind("<KeyRelease>", self._on_search_voice)
        self._textbox.bind("<KeyRelease>", self._on_text_changed)
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
            self._status_label.configure(text=item[1])
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
                text=f"●  网络正常（{result.latency_ms:.0f} ms）", text_color="#9ece6a"
            )
            proxy = result.proxy or detect_proxy()
            note = f"（代理：{proxy}）" if proxy else ""
            self.log(f"网络检测通过{note}")
        else:
            self._net_dot.configure(text="●  网络异常", text_color="#f7768e")
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
            friendly = info.get("FriendlyName") or code
            return f"{friendly}（{code}）"
        for friendly, c in CURATED_VOICES:
            if c == code:
                return f"{friendly}（{c}）"
        return code

    def _on_voice_changed(self, value):
        for code in list(self._voice_map) + [code for _, code in CURATED_VOICES]:
            if self._display_name(code) == value:
                self._selected_voice_code = code
                break
        self._update_voice_info()

    def _restore_original_defaults(self):
        self._selected_voice_code = DEFAULT_VOICE
        self._rate_var.set(0)
        self._volume_var.set(0)
        self._pitch_var.set(0)
        self._refresh_voice_combo()
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
            self._voice_info.configure(
                text=f"{info.get('Locale', '')} · {info.get('Gender', '')}"
            )
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
            on_progress=lambda written: self._ui_q.put(
                ("progress", f"正在合成… 已接收 {written / 1024:.0f} KB")
            ),
            controller=controller,
            cancel_event=self._cancel_event,
        )
        task = TTSTask(text, output_path, self._build_cfg(), mode)

        self._status_label.configure(text="Preparing…" if self._language == "en" else "正在准备…", text_color="#e0af68")
        self._progress.start()

        threading.Thread(
            target=self._worker_task, args=(engine, task), daemon=True
        ).start()

    def _worker_task(self, engine: TTSEngine, task: TTSTask):
        try:
            result = engine.generate(task.text, task.output_path, task.cfg)
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "error": str(exc)}
        self._ui_q.put(("task_done", task.mode, result))

    def _on_task_done(self, mode, result):
        self._busy = False
        self._set_busy_ui(False)
        self._progress.stop()
        self._progress.set(0)

        status = result.get("status")
        if status == "done":
            self._status_label.configure(text="完成 ✔", text_color="#9ece6a")
            path = result["path"]
            if mode == "preview":
                self.log(f"[试听] 已生成试听音频，开始播放…")
                self._play_audio(path)
            else:
                self.log(f"[导出] 音频已保存：{path}")
                self._maybe_open_folder(path)
        elif status == "canceled":
            self._status_label.configure(text="已取消", text_color="#e0af68")
            self.log("[任务] 已取消。")
        else:
            self._status_label.configure(text="失败 ✖", text_color="#f7768e")
            self.log(f"[任务] 失败：{result.get('error', '未知错误')}")
            messagebox.showerror(
                APP_NAME,
                "生成失败：\n\n"
                + result.get("error", "未知错误")
                + "\n\n请检查网络连接或代理设置后重试。",
            )

    # ============================================================ 按钮动作

    def _on_preview(self):
        cleaned = self._get_cleaned_text()
        if not cleaned:
            messagebox.showwarning(APP_NAME, "请输入文章内容。")
            return
        sample = preview_text(cleaned)
        self.log(f"[试听] 使用前 {len(sample)} 字生成试听（共 {len(cleaned)} 字）")
        self._stop_playback()
        self._start_task(sample, self._preview_path, "preview")

    def _on_export(self):
        cleaned = self._get_cleaned_text()
        if not cleaned:
            messagebox.showwarning(APP_NAME, "请输入文章内容。")
            return
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        path = filedialog.asksaveasfilename(
            title="导出音频",
            defaultextension=".mp3",
            filetypes=[("MP3 音频", "*.mp3")],
            initialdir=default_dir if os.path.isdir(default_dir) else os.path.expanduser("~"),
            initialfile=default_filename(),
        )
        if not path:
            return
        self.log(f"[导出] 开始生成全文音频（{len(cleaned)} 字）→ {path}")
        self._start_task(cleaned, path, "export")

    def _on_stop(self):
        self.log("[任务] 正在停止…")
        self._cancel_event.set()
        self._stop_playback()
        self._progress.stop()
        self._status_label.configure(text="已停止", text_color="#e0af68")

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

    def _show_stall_dialog(self, message: str) -> str:
        dialog = ctk.CTkToplevel(self)
        dialog.title("⚠ 生成似乎卡住了")
        dialog.geometry("540x260")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.after(100, dialog.lift)

        ctk.CTkLabel(
            dialog,
            text="生成似乎卡住了",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#e0af68",
        ).pack(pady=(22, 6))

        ctk.CTkLabel(
            dialog,
            text=message,
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
        ctk.CTkButton(row, text="继续等待", width=120, command=lambda: choose("continue")).pack(side="left", padx=6)
        ctk.CTkButton(row, text="重试", width=120, command=lambda: choose("retry")).pack(side="left", padx=6)
        ctk.CTkButton(
            row, text="取消", width=120, fg_color="#f7768e", hover_color="#d9556d",
            command=lambda: choose("cancel"),
        ).pack(side="left", padx=6)

        dialog.wait_window()
        return result["value"]

    def _maybe_open_folder(self, path):
        if messagebox.askyesno(APP_NAME, "音频已导出：\n" + path + "\n\n是否打开所在文件夹？"):
            try:
                os.startfile(os.path.dirname(path))
            except Exception:  # noqa: BLE001
                pass

    # ============================================================ 杂项

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self._log.configure(state="normal")
        self._log.insert("end", line)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_busy_ui(self, busy: bool):
        state = "disabled" if busy else "normal"
        self._btn_preview.configure(state=state)
        self._btn_export.configure(state=state)
        self._btn_stop.configure(state="normal" if busy else "disabled")

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
