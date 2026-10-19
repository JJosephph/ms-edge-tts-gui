# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import unittest
from unittest.mock import patch

from update_checker import (
    check_for_updates,
    is_newer_version,
    release_from_payload,
)


class _FakeResponse:
    def __init__(self, payload):
        self._body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body.read()


class UpdateCheckerTests(unittest.TestCase):
    def test_compares_numeric_versions(self):
        self.assertTrue(is_newer_version("v1.5.4", "1.5.3"))
        self.assertTrue(is_newer_version("1.6", "1.5.9"))
        self.assertFalse(is_newer_version("1.5.3", "v1.5.3"))
        self.assertFalse(is_newer_version("1.5.2", "1.5.3"))

    def test_extracts_installer_download_url(self):
        release = release_from_payload(
            {
                "tag_name": "v1.6.0",
                "name": "v1.6.0",
                "body": "Changes",
                "html_url": "https://example.test/release",
                "published_at": "2026-10-12T00:00:00Z",
                "assets": [
                    {
                        "name": "EdgeTTSGui-Portable.exe",
                        "browser_download_url": "https://example.test/portable.exe",
                    },
                    {
                        "name": "EdgeTTSGui-Setup.exe",
                        "browser_download_url": "https://example.test/setup.exe",
                    },
                ],
            }
        )

        self.assertEqual(release.version, "1.6.0")
        self.assertEqual(release.download_url, "https://example.test/setup.exe")

    def test_check_for_updates_reads_latest_release(self):
        payload = {
            "tag_name": "v1.5.4",
            "name": "v1.5.4",
            "body": "Bug fixes",
            "html_url": "https://example.test/release",
            "published_at": "2026-10-12T00:00:00Z",
            "assets": [],
        }
        with patch("update_checker.urlopen", return_value=_FakeResponse(payload)):
            result = check_for_updates("1.5.3")

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest.version, "1.5.4")
        self.assertEqual(result.latest.notes, "Bug fixes")


if __name__ == "__main__":
    unittest.main()
