# -*- coding: utf-8 -*-
"""TTS 合成引擎：封装 edge-tts，内置网络探测与“卡住”检测。

设计要点
--------
1. 生成前可选网络探测（speech.platform.bing.com），识别离线 / 代理异常。
2. 流式接收音频分片，若超过 STALL_TIMEOUT 没有新分片，判定为“卡住”，
   通过 StallController 询问界面：重试 / 取消 / 继续等待。
3. 支持重试与用户取消；错误分类后给出网络 / 代理提示。
"""

import asyncio
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import aiohttp
import edge_tts

# ---------------------------------------------------------------- 常量
STALL_TIMEOUT = 15            # 连续多少秒没有新音频分片 -> 判定卡住
STALL_DECISION_TIMEOUT = 90   # 卡住后等待用户决定的最长时间（秒）
CONNECT_TIMEOUT = 10          # edge-tts 建连超时
RECEIVE_TIMEOUT = 120         # edge-tts 单次接收超时（兜底）
PROBE_TIMEOUT = 6             # 网络探测超时
MAX_RETRIES = 3               # 最大生成重试次数
PROGRESS_REPORT_INTERVAL = 0.25


def estimate_spoken_units(text: str) -> int:
    """Estimate spoken units for a responsive, approximate TTS percentage."""
    units = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)?", text)
    return max(1, len(units))

# edge-tts 使用的真实服务地址（用于网络探测，最贴近真实链路）
PROBE_URL = "https://speech.platform.bing.com/"

# ---------------------------------------------------------------- 异常


class UserCanceled(Exception):
    """用户主动取消。"""


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
    """异步网络探测：对 edge-tts 服务域名发起一次 HTTPS 请求。"""
    result = ProbeResult(reachable=False, proxy=proxy)
    timeout = aiohttp.ClientTimeout(
        total=PROBE_TIMEOUT, connect=PROBE_TIMEOUT, sock_connect=PROBE_TIMEOUT
    )
    start = time.perf_counter()
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(PROBE_URL, proxy=proxy) as resp:
                _ = resp.status  # 只要在超时内返回（哪怕 4xx/5xx）都算可达
        result.reachable = True
        result.latency_ms = round((time.perf_counter() - start) * 1000, 1)
    except Exception as exc:  # noqa: BLE001 - 探测失败统一视为不可达
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

    # ---------------- 对外入口 ----------------

    def generate(self, text: str, output_path, cfg: TTSConfig) -> dict:
        """同步入口：在工作线程中运行事件循环，返回结果 dict。"""
        return asyncio.run(self._generate_async(text, output_path, cfg))

    # ---------------- 内部实现 ----------------

    async def _generate_async(self, text: str, output_path, cfg: TTSConfig) -> dict:
        attempts = 0
        while True:
            attempts += 1
            self.on_log(f"开始第 {attempts} 次生成（语音：{cfg.voice}）")
            outcome = await self._stream_once(text, output_path, cfg)
            if outcome == "done":
                self.on_log("音频数据接收完成。")
                return {"status": "done", "path": str(output_path)}
            if outcome == "cancel":
                self.on_log("任务已取消。")
                return {"status": "canceled"}
            # retry
            if attempts >= MAX_RETRIES:
                self.on_log("已达最大重试次数，任务失败。")
                return {
                    "status": "error",
                    "error": "生成多次失败，请检查网络连接或代理设置后重试。",
                }
            self.on_log("准备重试…")

    async def _stream_once(self, text: str, output_path, cfg: TTSConfig) -> str:
        """执行一次流式生成，返回 'done' | 'cancel' | 'retry'。"""
        temp_path = self._temp_path(output_path)
        self._safe_unlink(temp_path)

        communicate = edge_tts.Communicate(
            text=text,
            voice=cfg.voice,
            rate=cfg.rate,
            volume=cfg.volume,
            pitch=cfg.pitch,
            boundary="WordBoundary",
            proxy=self.proxy,
            connect_timeout=CONNECT_TIMEOUT,
            receive_timeout=RECEIVE_TIMEOUT,
        )

        last_report = time.perf_counter()
        written = 0
        total_units = estimate_spoken_units(text)
        completed_units = 0
        percent = 0
        self.on_progress(percent, written)
        try:
            iterator = communicate.stream()
            with open(temp_path, "wb") as audio_file:
                while True:
                    if self.cancel_event.is_set():
                        raise UserCanceled()
                    try:
                        chunk = await asyncio.wait_for(
                            anext(iterator), timeout=STALL_TIMEOUT
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        decision = await self._ask_stall(
                            "生成似乎卡住了：长时间没有收到新的音频数据。"
                            "可能是网络不通或代理设置不正确。要重试吗？"
                        )
                        if decision == "cancel":
                            raise UserCanceled()
                        if decision == "retry":
                            self._safe_unlink(temp_path)
                            return "retry"
                        continue  # 用户选择继续等待

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
                    elif chunk_type == "WordBoundary":
                        completed_units += 1
                        percent = min(99, int(completed_units * 100 / total_units))
                        now = time.perf_counter()
                        if now - last_report >= PROGRESS_REPORT_INTERVAL:
                            last_report = now
                            self.on_progress(percent, written)

            if written == 0:
                raise RuntimeError("TTS 未返回任何音频数据。")

            final_path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            if os.path.exists(final_path):
                os.unlink(final_path)
            os.replace(temp_path, final_path)
            self.on_progress(100, written)
            return "done"

        except UserCanceled:
            self._safe_unlink(temp_path)
            return "cancel"
        except asyncio.CancelledError:
            self._safe_unlink(temp_path)
            raise
        except Exception as exc:  # noqa: BLE001 - 统一兜底并让用户决定
            self._safe_unlink(temp_path)
            hint = self._classify_error(exc)
            self.on_log(f"[警告] 生成失败：{exc}（{hint}）")
            decision = await self._ask_stall(f"{hint} 是否重试？")
            if decision == "cancel":
                return "cancel"
            return "retry"

    # ---------------- 工具 ----------------

    async def _ask_stall(self, message: str) -> str:
        if self.controller is None:
            return "cancel"
        # ask() 内部是阻塞等待用户决定，可接受（此刻流已停滞）
        return self.controller.ask(message)

    def _classify_error(self, exc: Exception) -> str:
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

    @staticmethod
    def _temp_path(output_path) -> str:
        return str(output_path) + ".partial"

    @staticmethod
    def _safe_unlink(path: str) -> None:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass
