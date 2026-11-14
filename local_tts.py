# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional offline voices backed by Kokoro v1.1-zh and sherpa-onnx.

Microsoft Edge remains the default provider.  This module is deliberately
separate from the Edge voice catalogue: the local model has no sentence
boundaries, so its audio must not silently feed the precise subtitle path.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


PROVIDER_EDGE = "edge"
PROVIDER_KOKORO = "kokoro"

MODEL_ID = "kokoro-v1.1-zh"
MODEL_VERSION = "1.1"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
    "kokoro-int8-multi-lang-v1_1.tar.bz2"
)
MODEL_SIZE = 147_052_523
# Verified upstream archive.  A download is never accepted without matching
# this digest, so an intercepted or truncated file cannot become model data.
MODEL_SHA256 = (
    "259c9c8bc906d6078e4e0570421885dabb68b539c2f970fcbb890a58eeaf3e9c"
)
MODEL_ROOT = "kokoro-int8-multi-lang-v1_1"
MODEL_FILES = (
    f"{MODEL_ROOT}/model.int8.onnx",
    f"{MODEL_ROOT}/voices.bin",
    f"{MODEL_ROOT}/tokens.txt",
    f"{MODEL_ROOT}/lexicon-us-en.txt",
    f"{MODEL_ROOT}/lexicon-zh.txt",
    f"{MODEL_ROOT}/phone-zh.fst",
    f"{MODEL_ROOT}/date-zh.fst",
    f"{MODEL_ROOT}/number-zh.fst",
    f"{MODEL_ROOT}/LICENSE",
)


@dataclass(frozen=True)
class LocalVoice:
    code: str
    sid: int
    name_zh: str
    name_en: str
    gender: str
    style_zh: str
    style_en: str

    def label(self, language: str) -> str:
        name = self.name_zh if language == "zh" else self.name_en
        style = self.style_zh if language == "zh" else self.style_en
        return f"{name} · {style} · {'本地' if language == 'zh' else 'Local'}"


# Curated from the 103-speaker v1.1-zh release.  Selection used DNSMOS
# naturalness/signal scores plus pitch and pacing, not speaker-number order.
# Lower-scoring and near-duplicate voices stay out of the product UI.
LOCAL_VOICES = (
    LocalVoice("zf_047", 30, "清岚", "Qinglan", "Female", "自然女声", "Natural"),
    LocalVoice("zf_044", 28, "南乔", "Nanqiao", "Female", "明亮女声", "Bright"),
    LocalVoice("zf_024", 17, "知夏", "Zhixia", "Female", "温柔女声", "Warm"),
    LocalVoice("zf_083", 47, "云舒", "Yunshu", "Female", "清亮女声", "Clear"),
    LocalVoice("zm_055", 81, "沉舟", "Chenzhou", "Male", "沉稳男声", "Deep"),
    LocalVoice("zm_081", 94, "远川", "Yuanchuan", "Male", "叙事男声", "Narration"),
    LocalVoice("zm_095", 98, "明澈", "Mingche", "Male", "清朗男声", "Clear"),
    LocalVoice("zm_054", 80, "砚秋", "Yanqiu", "Male", "温和男声", "Calm"),
)

_VOICES_BY_CODE = {voice.code: voice for voice in LOCAL_VOICES}
_VOICES_BY_SID = {voice.sid: voice for voice in LOCAL_VOICES}


def local_voice(code: str) -> Optional[LocalVoice]:
    return _VOICES_BY_CODE.get(str(code or ""))


def voice_for_sid(sid: int) -> Optional[LocalVoice]:
    return _VOICES_BY_SID.get(int(sid))


def is_local_voice(code: object) -> bool:
    return str(code or "") in _VOICES_BY_CODE


def provider_for_voice(code: object) -> str:
    return PROVIDER_KOKORO if is_local_voice(code) else PROVIDER_EDGE


def local_voices(gender: str = "") -> tuple[LocalVoice, ...]:
    if not gender:
        return LOCAL_VOICES
    return tuple(voice for voice in LOCAL_VOICES if voice.gender == gender)


def model_directory(base: Optional[Path] = None) -> Path:
    if base is not None:
        return Path(base)
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EdgeTTSGui"
    return root / "models" / MODEL_ID


def bundled_model_directory(base: Optional[Path] = None) -> Optional[Path]:
    """Return the read-only model shipped with the installed application."""
    if base is not None:
        candidate = Path(base)
        return candidate if candidate.is_dir() else None
    roots: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root))
    source_root = Path(__file__).resolve().parent
    roots.extend((source_root, source_root / "vendor"))
    for root in roots:
        candidate = root / "models" / MODEL_ID
        if candidate.is_dir():
            return candidate
    return None


def resolved_model_directory(
    user_base: Optional[Path] = None,
    bundled_base: Optional[Path] = None,
) -> Path:
    """Prefer the model installed with the app, then fall back to user data."""
    bundled = bundled_model_directory(bundled_base)
    if bundled is not None and model_installed(bundled):
        return bundled
    return model_directory(user_base)


def model_installed(base: Optional[Path] = None) -> bool:
    root = model_directory(base)
    return all((root / name).is_file() for name in MODEL_FILES)


def model_file(base: Optional[Path], name: str) -> Path:
    """Return one installed model file, validating its relative name."""
    root = model_directory(base)
    target = (root / MODEL_ROOT / name).resolve()
    if root.resolve() not in target.parents:
        raise ValueError("模型文件路径无效")
    return target


def file_sha256(path: Path, cancel: Optional[threading.Event] = None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("canceled")
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for entry in archive.infolist():
        target = (destination / entry.filename).resolve()
        if root != target and root not in target.parents:
            raise ValueError("模型压缩包包含非法路径")
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(entry) as source, open(target, "wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def _safe_extract_tar(archive: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for entry in archive.getmembers():
        target = (destination / entry.name).resolve()
        if root != target and root not in target.parents:
            raise ValueError("模型压缩包包含非法路径")
        if entry.issym() or entry.islnk() or entry.isdev():
            raise ValueError("模型压缩包包含不允许的链接")
        if entry.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not entry.isfile():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(entry)
        if source is None:
            raise ValueError("模型压缩包文件无法读取")
        with source, open(target, "wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def install_model_archive(
    archive_path: Path,
    base: Optional[Path] = None,
    expected_sha256: Optional[str] = None,
) -> Path:
    archive_path = Path(archive_path)
    expected = (expected_sha256 if expected_sha256 is not None else MODEL_SHA256).lower()
    if not expected:
        raise ValueError("模型校验值尚未配置")
    if archive_path.stat().st_size != MODEL_SIZE:
        raise ValueError("模型文件大小不正确，请重新下载")
    actual = file_sha256(archive_path)
    if actual != expected:
        raise ValueError("模型文件校验失败，请重新下载")

    root = model_directory(base)
    staging = root.with_name(root.name + ".installing")
    previous = root.with_name(root.name + ".previous")
    for path in (staging, previous):
        if path.exists():
            shutil.rmtree(path)
    staging.mkdir(parents=True)
    try:
        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:bz2") as archive:
                _safe_extract_tar(archive, staging)
        else:
            with zipfile.ZipFile(archive_path) as archive:
                if archive.testzip() is not None:
                    raise ValueError("模型压缩包已损坏，请重新下载")
                _safe_extract(archive, staging)
        missing = [name for name in MODEL_FILES if not (staging / name).is_file()]
        if missing:
            raise ValueError("模型压缩包缺少文件：" + "、".join(missing))
        for extra in (
            "espeak-ng-data",
            "dict",
            "lexicon-gb-en.txt",
            "README.md",
        ):
            path = staging / MODEL_ROOT / extra
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
        try:
            archive_path.unlink()
        except OSError:
            pass
        if root.exists():
            root.rename(previous)
        try:
            staging.rename(root)
        except Exception:
            if previous.exists() and not root.exists():
                previous.rename(root)
            raise
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return root


def download_model(
    destination: Optional[Path] = None,
    *,
    cancel: Optional[threading.Event] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    url: str = MODEL_URL,
    expected_sha256: Optional[str] = None,
) -> Path:
    """Download and install the archive; callers run this off the UI thread."""
    if not expected_sha256 and not MODEL_SHA256:
        raise ValueError("模型下载地址尚未完成发布配置")
    expected = expected_sha256 or MODEL_SHA256
    base = model_directory(destination)
    if model_installed(base):
        return base
    base.parent.mkdir(parents=True, exist_ok=True)
    archive_path = base.with_suffix(".zip.part")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "EdgeTTSGui-ModelDownloader/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response, open(
            archive_path, "wb"
        ) as output:
            total = int(response.headers.get("Content-Length") or 0)
            if total and total != MODEL_SIZE:
                raise ValueError(f"下载包大小异常：{total} 字节")
            received = 0
            last_report = 0.0
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("canceled")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                now = time.monotonic()
                if progress is not None and now - last_report >= 0.2:
                    progress(received, total or MODEL_SIZE)
                    last_report = now
            if progress is not None:
                progress(received, total or MODEL_SIZE)
        return install_model_archive(
            archive_path, base, expected_sha256=expected
        )
    finally:
        try:
            archive_path.unlink()
        except OSError:
            pass


class LocalTTSEngine:
    """Lazy sherpa-onnx wrapper shared by preview and export."""

    _shared_model = None
    _shared_lock = threading.Lock()

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        *,
        cancel_event: Optional[threading.Event] = None,
        num_threads: int = 4,
    ):
        # Callers such as App resolve the bundled/user-data preference before
        # constructing an engine.  An explicit path stays explicit so tests
        # and future embedders can point at an isolated model.
        self.model_dir = model_directory(model_dir)
        self.cancel_event = cancel_event or threading.Event()
        self.num_threads = max(1, min(8, int(num_threads or 4)))
        self.timeline = None

    def _model(self):
        if not model_installed(self.model_dir):
            raise RuntimeError("本地语音包尚未下载或缺失，请重新安装完整版本")
        with self._shared_lock:
            if self._shared_model is None:
                try:
                    import sherpa_onnx
                except ImportError as exc:  # pragma: no cover - packaging guard
                    raise RuntimeError("本地语音运行组件缺失，请重新安装完整版本") from exc
                root = self.model_dir / MODEL_ROOT
                config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                            model=str(root / "model.int8.onnx"),
                            voices=str(root / "voices.bin"),
                            tokens=str(root / "tokens.txt"),
                            lexicon=",".join(
                                str(root / name)
                                for name in ("lexicon-us-en.txt", "lexicon-zh.txt")
                            ),
                        ),
                        provider="cpu",
                        num_threads=self.num_threads,
                    ),
                    rule_fsts=",".join(
                        str(root / name)
                        for name in ("phone-zh.fst", "date-zh.fst", "number-zh.fst")
                    ),
                )
                self.__class__._shared_model = sherpa_onnx.OfflineTts(config)
            return self._shared_model

    def generate_pcm(
        self,
        text: str,
        voice: str,
        rate: str = "+0%",
        volume: str = "+0%",
    ) -> tuple[bytes, int]:
        selected = local_voice(voice)
        if selected is None:
            raise ValueError("不是可用的本地音色")
        model = self._model()
        speed = max(0.5, min(2.0, 1.0 + _percent(rate) / 100.0))
        # Match the online control's intuitive percentage: -50% is about
        # -3 dB and +100% is about +6 dB.  _encode_pcm limits peaks so a
        # boosted chunk cannot wrap around into harsh digital clipping.
        gain = 2.0 ** (_percent(volume) / 100.0)

        def stop_generation(_samples, _progress) -> int:
            return 0 if self.cancel_event.is_set() else 1

        audio = model.generate(
            text,
            sid=selected.sid,
            speed=speed,
            callback=stop_generation,
        )
        if self.cancel_event.is_set():
            raise InterruptedError("canceled")
        return _encode_pcm(audio.samples, gain), int(audio.sample_rate)

    def synthesize_to_mp3(
        self,
        text: str,
        voice: str,
        output_path: str | Path,
        rate: str = "+0%",
        volume: str = "+0%",
        pause_ms: int = 0,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """Generate sentence-sized chunks and encode one MP3.

        Kokoro has no sentence-boundary metadata.  Chunking is used only to
        keep long text stable; the UI must still treat subtitle timing as
        unavailable for this provider.
        """
        import lameenc

        pieces = split_local_text(text)
        if not pieces:
            raise ValueError("没有可朗读的文字")
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(48)
        encoder.set_in_sample_rate(24000)
        encoder.set_channels(1)
        encoder.set_quality(2)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".partial")
        pause_frames = max(0, int(round(24000 * max(0, pause_ms) / 1000)))
        silence = b"\x00\x00" * pause_frames
        try:
            with open(temp_path, "wb") as handle:
                for index, piece in enumerate(pieces):
                    if self.cancel_event.is_set():
                        raise InterruptedError("canceled")
                    pcm, sample_rate = self.generate_pcm(
                        piece, voice, rate=rate, volume=volume
                    )
                    if sample_rate != 24000:
                        raise RuntimeError(
                            f"本地模型采样率异常：{sample_rate} Hz"
                        )
                    handle.write(encoder.encode(pcm))
                    if silence and index < len(pieces) - 1:
                        handle.write(encoder.encode(silence))
                    if progress is not None:
                        progress(index + 1, len(pieces))
                handle.write(encoder.flush())
            os.replace(temp_path, output_path)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass
        return str(output_path)


def _percent(value: object) -> float:
    import re

    match = re.search(r"([+-]?\d+(?:\.\d+)?)", str(value or "0"))
    return float(match.group(1)) if match else 0.0


def _encode_pcm(samples, gain: float = 1.0) -> bytes:
    import array

    values = [float(value) * gain for value in samples]
    peak = max((abs(value) for value in values), default=0.0)
    limiter = 1.0 / peak if peak > 1.0 else 1.0
    pcm = array.array("h")
    for value in values:
        level = max(-1.0, min(1.0, value * limiter))
        pcm.append(int(round(level * 32767)))
    return pcm.tobytes()


def split_local_text(text: str, max_chars: int = 180) -> list[str]:
    """Split at sentence boundaries before Kokoro's long-line speed-up."""
    import re

    value = str(text or "").strip()
    if not value:
        return []
    pieces = re.split(r"(?<=[。！？!?；;])\s*|\n+", value)
    result: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        while len(piece) > max_chars:
            cut = max(
                piece.rfind("，", 0, max_chars),
                piece.rfind(",", 0, max_chars),
                piece.rfind(" ", 0, max_chars),
            )
            if cut < max_chars // 3:
                cut = max_chars
            result.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            result.append(piece)
    return result
