# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
import tarfile
import unittest
import zipfile
import hashlib
import io
from pathlib import Path
from unittest import mock

from local_tts import (
    LocalTTSEngine,
    LOCAL_VOICES,
    MODEL_FILES,
    PROVIDER_EDGE,
    PROVIDER_KOKORO,
    bundled_model_directory,
    is_local_voice,
    install_model_archive,
    local_voice,
    model_installed,
    provider_for_voice,
    resolved_model_directory,
    split_local_text,
    _encode_pcm,
)


class LocalVoiceTests(unittest.TestCase):
    def test_default_edge_voice_does_not_become_local(self):
        self.assertFalse(is_local_voice("en-US-AndrewMultilingualNeural"))
        self.assertEqual(
            provider_for_voice("en-US-AndrewMultilingualNeural"), PROVIDER_EDGE
        )
        self.assertEqual(provider_for_voice("zf_047"), PROVIDER_KOKORO)

    def test_curated_catalogue_has_both_genders_and_unique_ids(self):
        ids = [item.sid for item in LOCAL_VOICES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({item.gender for item in LOCAL_VOICES}, {"Female", "Male"})
        self.assertEqual(local_voice("zf_047").sid, 30)
        self.assertIsNone(local_voice("zf_023"))

    def test_split_keeps_short_sentences_and_bounds_long_text(self):
        self.assertEqual(split_local_text("你好。世界！"), ["你好。", "世界！"])
        text = "这是一段很长的话，" * 40
        pieces = split_local_text(text, max_chars=50)
        self.assertTrue(pieces)
        self.assertTrue(all(len(piece) <= 50 for piece in pieces))
        self.assertEqual("".join(pieces), text.replace("，", "，"))

    def test_split_does_not_leave_blank_pieces(self):
        self.assertEqual(split_local_text("  \n\n \r\n "), [])

    def test_local_mp3_chunks_text_and_maps_speed_and_gain(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "out.mp3"
            engine = LocalTTSEngine(Path(folder))
            calls = []

            def fake_generate(text, voice, rate="+0%", volume="+0%"):
                self.assertIn(voice, {item.code for item in LOCAL_VOICES})
                calls.append((text, voice, rate, volume))
                return b"\x00\x00" * 240, 24000

            engine.generate_pcm = fake_generate
            result = engine.synthesize_to_mp3(
                "第一句。第二句！",
                "zf_047",
                output,
                rate="+20%",
                volume="+10%",
                pause_ms=300,
            )
            self.assertEqual(result, str(output))
            self.assertTrue(output.is_file())
            self.assertEqual([call[0] for call in calls], ["第一句。", "第二句！"])
            self.assertTrue(all(call[1:] == ("zf_047", "+20%", "+10%") for call in calls))

    def test_volume_is_audible_percent_and_peak_limited(self):
        samples = [0.5, -0.5, 0.25]
        self.assertEqual(len(_encode_pcm(samples, 1.0)), len(samples) * 2)
        boosted = _encode_pcm(samples, 2.0)
        values = [
            int.from_bytes(boosted[index : index + 2], "little", signed=True)
            for index in range(0, len(boosted), 2)
        ]
        self.assertLessEqual(max(abs(value) for value in values), 32767)
        self.assertGreater(values[0], 16383)

    def test_provider_choice_survives_only_with_a_local_voice(self):
        self.assertEqual(provider_for_voice("zf_047"), PROVIDER_KOKORO)
        self.assertEqual(provider_for_voice("zm_055"), PROVIDER_KOKORO)
        self.assertEqual(provider_for_voice(""), PROVIDER_EDGE)
        self.assertIsNone(local_voice("en-US-AndrewMultilingualNeural"))

    def test_missing_model_returns_actionable_error(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = LocalTTSEngine(Path(folder))
            with self.assertRaisesRegex(RuntimeError, "尚未下载"):
                engine.generate_pcm("你好", "zf_047")

    def test_bundled_model_takes_priority_over_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundled = root / "bundled"
            user = root / "user"
            for name in MODEL_FILES:
                target = bundled / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x")
            self.assertEqual(
                resolved_model_directory(user, bundled), bundled
            )

    def test_missing_bundled_model_falls_back_to_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundled = root / "bundled"
            user = root / "user"
            self.assertEqual(
                resolved_model_directory(user, bundled), user
            )
            self.assertIsNone(bundled_model_directory(root / "missing"))

    def test_install_rejects_wrong_digest_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "model.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                for name in MODEL_FILES:
                    handle.writestr(name, "x")
            target = root / "installed"
            target.mkdir()
            (target / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(ValueError):
                install_model_archive(
                    archive, target, expected_sha256="0" * 64
                )
            self.assertTrue((target / "keep.txt").exists())
            self.assertFalse(model_installed(target))

    def test_install_zip_slip_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../escaped.bin", "bad")
            with self.assertRaises(ValueError):
                install_model_archive(
                    archive, root / "target", expected_sha256="0" * 64
                )
            self.assertFalse((root / "escaped.bin").exists())

    def test_install_extracts_the_upstream_tar_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "model.tar.bz2"
            with tarfile.open(archive, "w:bz2") as handle:
                for name in MODEL_FILES:
                    data = b"payload"
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    handle.addfile(info, io.BytesIO(data))
            target = root / "installed"
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with mock.patch(
                "local_tts.MODEL_SIZE", archive.stat().st_size
            ):
                installed = install_model_archive(
                    archive, target, expected_sha256=digest
                )
            self.assertTrue(model_installed(target))
            self.assertTrue((installed / "kokoro-int8-multi-lang-v1_1/model.int8.onnx").is_file())

    def test_model_requires_both_chinese_and_english_lexicons(self):
        self.assertIn(
            "kokoro-int8-multi-lang-v1_1/lexicon-us-en.txt", MODEL_FILES
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in MODEL_FILES:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x")
            (root / "kokoro-int8-multi-lang-v1_1/lexicon-us-en.txt").unlink()
            self.assertFalse(model_installed(root))

    def test_tar_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "bad.tar.bz2"
            with tarfile.open(archive, "w:bz2") as handle:
                info = tarfile.TarInfo("kokoro-int8-multi-lang-v1_1/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                handle.addfile(info)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with mock.patch(
                "local_tts.MODEL_SIZE", archive.stat().st_size
            ):
                with self.assertRaises(ValueError):
                    install_model_archive(
                        archive, root / "installed", expected_sha256=digest
                    )


if __name__ == "__main__":
    unittest.main()
