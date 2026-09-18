import tempfile
import unittest
from pathlib import Path

from page_import import import_lines, split_text_into_lines, split_text_into_pages


class LineImportTests(unittest.TestCase):
    def test_splits_every_non_empty_line(self):
        pages = split_text_into_lines("  first line  \r\n\r\nsecond line\n   \nthird line")

        self.assertEqual([page.index for page in pages], [1, 2, 3])
        self.assertEqual(
            [page.text for page in pages],
            ["first line", "second line", "third line"],
        )

    def test_imports_txt_as_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "script.txt"
            path.write_text("one\ntwo\n\nthree", encoding="utf-8")

            pages = import_lines(str(path))

        self.assertEqual([page.text for page in pages], ["one", "two", "three"])


class PageImportTests(unittest.TestCase):
    def test_blank_line_is_the_default_page_break(self):
        pages = split_text_into_pages("第一页\n第一句\n\n第二页\n第二句\n\n第三页")

        self.assertEqual(
            [page.text for page in pages],
            ["第一页\n第一句", "第二页\n第二句", "第三页"],
        )

    def test_explicit_chinese_page_markers_are_exact(self):
        pages = split_text_into_pages("第一页\n\n[分页]\n\n第二页\n第二句\n[分页]\n第三页")

        self.assertEqual([page.text for page in pages], ["第一页", "第二页\n第二句", "第三页"])

    def test_explicit_english_page_markers_are_exact(self):
        pages = split_text_into_pages("Page one\n[PAGE]\nPage two")

        self.assertEqual([page.text for page in pages], ["Page one", "Page two"])

    def test_inline_page_marker_is_removed_from_spoken_text(self):
        pages = split_text_into_pages("第一页。[分页] 第二页。")

        self.assertEqual([page.text for page in pages], ["第一页。", "第二页。"])


if __name__ == "__main__":
    unittest.main()
