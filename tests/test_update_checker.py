# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from unittest.mock import patch

from update_checker import (
    ReleaseInfo,
    check_for_updates,
    is_newer_version,
    release_from_payload,
    release_from_redirect_url,
)


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

    def test_builds_release_from_latest_redirect(self):
        release = release_from_redirect_url(
            "https://github.com/JJosephph/ms-edge-tts-gui/releases/tag/v1.7.2"
        )

        self.assertEqual(release.version, "1.7.2")
        self.assertEqual(release.tag_name, "v1.7.2")
        self.assertEqual(
            release.download_url,
            "https://github.com/JJosephph/ms-edge-tts-gui/releases/download/"
            "v1.7.2/EdgeTTSGui-Setup.exe",
        )

    def test_check_for_updates_prefers_redirect_and_skips_api_when_current(self):
        redirect_release = ReleaseInfo(
            version="1.7.2",
            tag_name="v1.7.2",
            name="v1.7.2",
            notes="",
            page_url="https://example.test/release",
            download_url="https://example.test/setup.exe",
            published_at="",
        )
        with (
            patch(
                "update_checker._fetch_latest_from_redirect",
                return_value=redirect_release,
            ) as redirect_fetch,
            patch("update_checker._fetch_latest_from_api") as api_fetch,
        ):
            result = check_for_updates("1.7.2")

        self.assertFalse(result.update_available)
        self.assertEqual(result.latest.version, "1.7.2")
        redirect_fetch.assert_called_once()
        api_fetch.assert_not_called()

    def test_check_for_updates_reads_notes_from_api_when_newer(self):
        redirect_release = ReleaseInfo(
            version="1.7.2",
            tag_name="v1.7.2",
            name="v1.7.2",
            notes="",
            page_url="https://example.test/release",
            download_url="https://example.test/setup.exe",
            published_at="",
        )
        payload = {
            "tag_name": "v1.7.2",
            "name": "v1.7.2",
            "body": "Bug fixes",
            "html_url": "https://example.test/release",
            "published_at": "2026-10-12T00:00:00Z",
            "assets": [],
        }
        with (
            patch(
                "update_checker._fetch_latest_from_redirect",
                return_value=redirect_release,
            ),
            patch(
                "update_checker._fetch_latest_from_api",
                return_value=release_from_payload(payload),
            ),
        ):
            result = check_for_updates("1.7.1")

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest.version, "1.7.2")
        self.assertEqual(result.latest.notes, "Bug fixes")

    def test_check_for_updates_falls_back_to_api_when_redirect_fails(self):
        payload = {
            "tag_name": "v1.7.2",
            "name": "v1.7.2",
            "body": "Bug fixes",
            "html_url": "https://example.test/release",
            "published_at": "2026-10-12T00:00:00Z",
            "assets": [],
        }
        with (
            patch(
                "update_checker._fetch_latest_from_redirect",
                side_effect=OSError("redirect failed"),
            ),
            patch(
                "update_checker._fetch_latest_from_api",
                return_value=release_from_payload(payload),
            ),
        ):
            result = check_for_updates("1.7.1")

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest.version, "1.7.2")

    def test_check_for_updates_uses_redirect_when_api_is_rate_limited(self):
        redirect_release = ReleaseInfo(
            version="1.7.2",
            tag_name="v1.7.2",
            name="v1.7.2",
            notes="",
            page_url="https://example.test/release",
            download_url="https://example.test/setup.exe",
            published_at="",
        )
        with (
            patch(
                "update_checker._fetch_latest_from_redirect",
                return_value=redirect_release,
            ),
            patch(
                "update_checker._fetch_latest_from_api",
                side_effect=RuntimeError("403 rate limited"),
            ),
        ):
            result = check_for_updates("1.7.1")

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest.version, "1.7.2")


if __name__ == "__main__":
    unittest.main()
