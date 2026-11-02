"""Offline regressions for LFS filtering in token-budgeted diff processing."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from git_tools.generators.base import diffs
from git_tools.generators.base.tokens import count_tokens


def ordinary_diff(filename: str, content: str = "+updated content") -> str:
    return f"diff --git a/{filename} b/{filename}\nindex 1111111..2222222 100644\n--- a/{filename}\n+++ b/{filename}\n@@ -1 +1 @@\n-old content\n{content}"


def lfs_diff(filename: str, marker: str = "+") -> str:
    return ordinary_diff(filename, f"{marker}version https://git-lfs.github.com/spec/v1\n{marker}oid sha256:{'a' * 64}\n{marker}size 123456")


class DiffProcessingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.processor = diffs.DiffProcessingMixin()
        self.processor.logger = Mock()
        self.settings_patch = patch.object(diffs, "settings", SimpleNamespace(min_file_token_threshold=0, protected_file_extensions=[".py"]))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_mixed_under_budget_payload_excludes_lfs_and_preserves_retained_order(self) -> None:
        first = ordinary_diff("first.py")
        last = ordinary_diff("last.py", "+final line")
        budget = count_tokens(first) + count_tokens(last)
        for marker in ("+", "-"):
            pointer = lfs_diff("asset.bin", marker)
            for position in range(3):
                blocks = [first, last]
                blocks.insert(position, pointer)
                raw = "\n".join(blocks)
                with self.subTest(marker=marker, position=position):
                    self.assertGreater(count_tokens(raw), budget)
                    with patch.object(self.processor, "_calculate_proportional_quotas", side_effect=AssertionError("under-budget allocation")):
                        processed, breakdown = self.processor._process_diff_with_size_limiting(raw, budget)
                    self.assertEqual(processed, "\n".join([first, last]))
                    self.assertNotIn("asset.bin", processed)
                    self.assertNotIn("git-lfs.github.com/spec/", processed)
                    self.assertIn("Dropped 1 LFS file(s): asset.bin", "\n".join(breakdown))
                    self.assertEqual(len(breakdown), 3)
                    self.assertTrue(breakdown[1].startswith("- first.py:"))
                    self.assertTrue(breakdown[2].startswith("- last.py:"))

    def test_all_lfs_under_budget_payload_is_empty_even_with_zero_budget(self) -> None:
        raw = "\n".join([lfs_diff("added.bin"), lfs_diff("removed.bin", "-")])
        for budget in (0, 1000):
            with self.subTest(budget=budget):
                processed, breakdown = self.processor._process_diff_with_size_limiting(raw, budget)
                self.assertEqual(processed, "")
                self.assertEqual(breakdown, ["\nDropped 2 LFS file(s): added.bin, removed.bin\n"])

    def test_under_budget_ordinary_payload_is_preserved_exactly(self) -> None:
        first = ordinary_diff("first.py", "+literal <|endoftext|> content")
        second = ordinary_diff("second.py", "+last line  ")
        for raw in ("", " \n\t\n", first, f"\n{first}\n\n{second}\n\n"):
            with self.subTest(raw=raw):
                processed, breakdown = self.processor._process_diff_with_size_limiting(raw, count_tokens(raw) + 100)
                self.assertEqual(processed, raw)
                self.assertNotIn("LFS", "\n".join(breakdown))
                if not raw.strip():
                    self.assertEqual(breakdown, [])

    def test_lfs_filter_does_not_expand_to_binary_or_unchanged_pointer_lines(self) -> None:
        binary = "diff --git a/asset.bin b/asset.bin\nindex 1111111..2222222 100644\nBinary files a/asset.bin and b/asset.bin differ"
        context = ordinary_diff("pointer.txt", " version https://git-lfs.github.com/spec/v1\n+size 123456")
        quoted = ordinary_diff("example.py", '+example = "version https://git-lfs.github.com/spec/v1"')
        raw = "\n".join([binary, context, quoted])
        processed, breakdown = self.processor._process_diff_with_size_limiting(raw, count_tokens(raw) + 100)
        self.assertEqual(processed, raw)
        self.assertNotIn("LFS", "\n".join(breakdown))

    def test_over_budget_truncation_filters_lfs_before_allocation(self) -> None:
        ordinary = ordinary_diff("source.py", "\n".join(f"+updated line {number}" for number in range(100)))
        pointer = lfs_diff("asset.bin")
        budget = 40
        self.assertGreater(count_tokens(ordinary), budget)
        with patch.object(self.processor, "_calculate_proportional_quotas", wraps=self.processor._calculate_proportional_quotas) as allocate:
            processed, breakdown = self.processor._process_diff_with_size_limiting("\n".join([pointer, ordinary]), budget)
        allocate.assert_called_once_with([("source.py", ordinary)], budget)
        self.assertTrue(processed.startswith(f"# Truncated diff for source.py (original: {count_tokens(ordinary)} tokens)\n"))
        self.assertNotIn("asset.bin", processed)
        self.assertNotIn("git-lfs.github.com/spec/", processed)
        self.assertIn("Dropped 1 LFS file(s): asset.bin", "\n".join(breakdown))
        self.assertIn(f"- source.py: Original diff size: {count_tokens(ordinary)} tokens, Quota allocated: {budget} tokens", breakdown)

    def test_over_budget_file_dropping_still_excludes_lfs(self) -> None:
        small = ordinary_diff("notes.txt")
        retained = ordinary_diff("source.py", "\n".join(f"+updated line {number}" for number in range(30)))
        pointer = lfs_diff("asset.bin")
        processed, breakdown = self.processor._process_diff_with_size_limiting("\n".join([small, pointer, retained]), count_tokens(retained))
        self.assertEqual(processed, retained)
        self.assertIn("Dropped 1 LFS file(s): asset.bin", "\n".join(breakdown))
        self.assertIn("Dropped 1 file(s) to fit context limit: notes.txt", "\n".join(breakdown))
        self.assertEqual(len(breakdown), 3)

    def test_no_limit_preserves_raw_payload_without_parsing_or_token_counting(self) -> None:
        ordinary = ordinary_diff("source.py")
        pointer = lfs_diff("asset.bin")
        for raw in ("", " \n\t", ordinary, pointer, f"\n{pointer}\n{ordinary}\n\n"):
            with self.subTest(raw=raw), patch.object(self.processor, "_parse_diff_files", side_effect=AssertionError("no-limit parsing")), patch.object(diffs, "count_tokens", side_effect=AssertionError("no-limit token counting")):
                self.assertEqual(self.processor._process_diff_with_size_limiting(raw, None), (raw, []))


if __name__ == "__main__":
    unittest.main()
