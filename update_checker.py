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
LATEST_RELEASE_PAGE = (
    "https://github.com/JJosephph/ms-edge-tts-gui/releases/latest"
)
REPOSITORY_URL = "https://github.com/JJosephph/ms-edge-tts-gui"
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


def release_from_redirect_url(final_url: str) -> ReleaseInfo:
    """Build release metadata from GitHub's /releases/latest redirect."""
    match = re.search(r"/releases/tag/([^/?#]+)", str(final_url or ""))
    if not match:
        raise ValueError("GitHub Release 跳转地址缺少版本标签。")
    tag_name = match.group(1).strip()
    version = normalize_version(tag_name)
    if not version:
        raise ValueError("GitHub Release 跳转地址缺少有效版本号。")
    return ReleaseInfo(
        version=version,
        tag_name=tag_name,
        name=tag_name,
        notes="",
        page_url=f"{REPOSITORY_URL}/releases/tag/{tag_name}",
        download_url=(
            f"{REPOSITORY_URL}/releases/download/{tag_name}/"
            f"{DOWNLOAD_ASSET_NAMES[0]}"
        ),
        published_at="",
    )


def _request_headers(current_version: str, accept: str) -> dict[str, str]:
    return {
        "Accept": accept,
        "User-Agent": f"EdgeTTSGui/{current_version}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _fetch_latest_from_redirect(current_version: str, timeout: float) -> ReleaseInfo:
    request = Request(
        LATEST_RELEASE_PAGE,
        headers=_request_headers(current_version, "text/html"),
    )
    with urlopen(request, timeout=timeout) as response:
        final_url = getattr(response, "geturl", lambda: "")()
    return release_from_redirect_url(final_url)


def _fetch_latest_from_api(current_version: str, timeout: float) -> ReleaseInfo:
    request = Request(
        LATEST_RELEASE_API,
        headers=_request_headers(
            current_version,
            "application/vnd.github+json",
        ),
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return release_from_payload(payload)


def _check_error_message(exc: BaseException) -> str:
    status = getattr(exc, "code", None)
    if status == 403:
        return "GitHub 更新检查暂时受限（403），请稍后重试。"
    if status == 404:
        return "GitHub 上还没有可用的正式版发布。"
    return str(exc).strip()[:300] or exc.__class__.__name__


def check_for_updates(
    current_version: str, timeout: float = DEFAULT_TIMEOUT
) -> UpdateCheckResult:
    """Check the latest release without depending on the rate-limited API."""
    try:
        latest = _fetch_latest_from_redirect(current_version, timeout)
    except Exception as redirect_exc:  # noqa: BLE001
        try:
            latest = _fetch_latest_from_api(current_version, timeout)
        except Exception as api_exc:  # noqa: BLE001
            return UpdateCheckResult(
                current_version=current_version,
                latest=None,
                update_available=False,
                error=_check_error_message(api_exc or redirect_exc),
            )
        return UpdateCheckResult(
            current_version=current_version,
            latest=latest,
            update_available=is_newer_version(latest.version, current_version),
        )

    update_available = is_newer_version(latest.version, current_version)
    if not update_available:
        return UpdateCheckResult(
            current_version=current_version,
            latest=latest,
            update_available=False,
        )

    # The redirect is enough to detect the version. Try the API only when a
    # new release exists so routine checks do not consume GitHub's quota.
    try:
        api_latest = _fetch_latest_from_api(current_version, timeout)
        if is_newer_version(api_latest.version, current_version):
            latest = api_latest
    except Exception:  # noqa: BLE001 - redirect metadata is already sufficient
        pass
    return UpdateCheckResult(
        current_version=current_version,
        latest=latest,
        update_available=True,
    )
