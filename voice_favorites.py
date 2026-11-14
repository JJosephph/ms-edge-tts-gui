# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small, dependency-free helpers for saved voice selections."""

from __future__ import annotations

from typing import Iterable


def normalize_favorites(values: object) -> list[str]:
    """Return unique voice codes in first-seen order."""
    if isinstance(values, str) or not isinstance(
        values, (list, tuple, set, frozenset)
    ):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = str(value or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result


def toggle_favorite(values: Iterable[str], code: str) -> list[str]:
    """Add or remove ``code`` while preserving the remaining order."""
    current = normalize_favorites(values if values is not None else [])
    code = str(code or "").strip()
    if not code:
        return current
    if code in current:
        current.remove(code)
    else:
        current.append(code)
    return current


def filter_favorites(values: Iterable[str], available: Iterable[str]) -> list[str]:
    """Keep saved codes that the active provider can actually synthesize.

    A saved Microsoft voice is not offered while the offline pack is active,
    and vice versa.  Filtering by availability avoids exporting with a voice
    code the current engine cannot find.
    """
    available_codes = {str(code) for code in available}
    return [
        code
        for code in normalize_favorites(values if values is not None else [])
        if code in available_codes
    ]


def clamp_panel_width(width: object, total: float, minimum: float, maximum: float) -> float:
    """Keep a draggable side panel inside useful bounds.

    The current window width caps the maximum so either pane can always keep
    its own minimum, even after a window resize or a restored settings file.
    """
    try:
        value = float(width)
    except (TypeError, ValueError):
        value = maximum
    upper = max(minimum, min(float(maximum), float(total) * 0.62))
    return max(minimum, min(upper, value))
