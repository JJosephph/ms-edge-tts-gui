# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check GitHub Releases for a newer desktop-app version."""

import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.request import Request, urlopen


LATEST_RELEASE_API = (
    "https://api.github.com/repos/JJosephph/ms-edge-tts-gui/releases/latest"
)
DEFAULT_TIMEOUT = 8.0
DOWNLOAD_ASSET_NAMES = ("EdgeTTSGui-Setup.exe", "EdgeTTSGui-Portable.exe")


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    name: str
    notes: str
    page_url: str
    download_url: str
    published_at: str


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest: Optional[ReleaseInfo]
    update_available: bool
    error: str = ""


def normalize_version(value: object) -> str:
    match = re.search(r"(\d+(?:\.\d+)*)", str(value or ""))
    return match.group(1) if match else ""


def version_key(value: object) -> tuple[int, ...]:
    version = normalize_version(value)
    if not version:
        return (0,)
    return tuple(int(part) for part in version.split("."))


def is_newer_version(candidate: object, current: object) -> bool:
    candidate_key = version_key(candidate)
    current_key = version_key(current)
    width = max(len(candidate_key), len(current_key))
    return candidate_key + (0,) * (width - len(candidate_key)) > current_key + (
        0,
    ) * (width - len(current_key))


def release_from_payload(payload: dict) -> ReleaseInfo:
    tag_name = str(payload.get("tag_name") or "").strip()
    version = normalize_version(tag_name)
    if not version:
        raise ValueError("GitHub Release 缺少有效版本号。")

    assets = payload.get("assets") or []
    assets_by_name = {
        str(asset.get("name") or ""): str(asset.get("browser_download_url") or "")
        for asset in assets
        if isinstance(asset, dict)
    }
    download_url = next(
        (
            assets_by_name[name]
            for name in DOWNLOAD_ASSET_NAMES
            if assets_by_name.get(name)
        ),
        "",
    )
    return ReleaseInfo(
        version=version,
        tag_name=tag_name,
        name=str(payload.get("name") or tag_name).strip(),
        notes=str(payload.get("body") or "").strip(),
        page_url=str(payload.get("html_url") or "").strip(),
        download_url=download_url,
        published_at=str(payload.get("published_at") or "").strip(),
    )


def check_for_updates(
    current_version: str, timeout: float = DEFAULT_TIMEOUT
) -> UpdateCheckResult:
    request = Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"EdgeTTSGui/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        latest = release_from_payload(payload)
        return UpdateCheckResult(
            current_version=current_version,
            latest=latest,
            update_available=is_newer_version(latest.version, current_version),
        )
    except Exception as exc:  # noqa: BLE001 - report a user-facing check failure
        status = getattr(exc, "code", None)
        if status == 403:
            message = "GitHub 更新检查暂时受限（403），请稍后重试。"
        elif status == 404:
            message = "GitHub 上还没有可用的正式版发布。"
        else:
            message = str(exc).strip()[:300] or exc.__class__.__name__
        return UpdateCheckResult(
            current_version=current_version,
            latest=None,
            update_available=False,
            error=message,
        )
