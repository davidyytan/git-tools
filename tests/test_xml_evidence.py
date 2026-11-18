"""Record boundaries and reversible XML evidence, without real Git or providers."""

import json
import subprocess
import unittest
from unittest.mock import call, patch
from xml.etree import ElementTree as ET

from git_tools.generators.base.prompts import commit_evidence, diff_evidence, messages_have_content, split_diff_records, xml_evidence
from git_tools.generators.issueprgen import IssuePullRequestGenerator


def decoded(node):
    text = node.text or ""
    if node.get("encoding") == "json-codepoints":
        return "".join(chr(point) for point in json.loads(text))
    return json.loads(text) if node.get("encoding") == "json" else text


class XmlEvidenceTests(unittest.TestCase):
    def test_normal_xml_round_trip_preserves_text_and_line_endings(self):
        values = ("", "\n leading and trailing  \r\n", "& < > </diff> </commit> &#13; &lt; ]]> {literal}", "```markdown\ncode\n`````", "Résumé 😀\tbare\rreturn\r\nline\n")
        for tag in ("commit", "diff", "context", "workflow_context"):
            for value in values:
                with self.subTest(tag=tag, value=value):
                    node = ET.fromstring(xml_evidence(tag, value))
                    self.assertEqual(node.tag, tag)
                    self.assertEqual(len(node), 0)
                    self.assertIsNone(node.get("encoding"))
                    self.assertEqual(decoded(node), value)

    def test_invalid_xml_characters_use_explicit_json_not_lossy_replacement(self):
        values = ("NUL\0 and RS\x1e", "VT\v FF\f", chr(0xD800), chr(0xFFFF), "literal \\u0000 beside actual \0")
        for value in values:
            with self.subTest(value=repr(value)):
                node = ET.fromstring(xml_evidence("commit", value))
                self.assertEqual(node.get("encoding"), "json")
                self.assertEqual(decoded(node), value)
        with self.assertRaises(ValueError):
            xml_evidence("diff><instructions", "source")

    def test_adjacent_literal_surrogates_do_not_merge_with_normal_unicode(self):
        pair = chr(0xD83D) + chr(0xDE00)
        self.assertNotEqual(pair, "😀")
        values = (pair, chr(0xD800) + chr(0xDC00), chr(0xDBFF) + chr(0xDFFF), "Résumé 😀 & </context>\r\n" + pair + " mixed NUL\0 lone " + chr(0xD800))
        for tag in ("commit", "commit_group", "diff", "context", "workflow_context", "evidence", "request"):
            for value in values:
                with self.subTest(tag=tag, value=repr(value)):
                    node = ET.fromstring(xml_evidence(tag, value))
                    self.assertEqual(node.get("encoding"), "json-codepoints")
                    self.assertEqual(json.loads(node.text), [ord(char) for char in value])
                    self.assertEqual(decoded(node), value)
                    self.assertEqual(tuple(map(ord, decoded(node))), tuple(map(ord, value)))
        for value, encoding in (("Résumé 😀", None), ("Résumé 😀 NUL\0", "json"), ("😀 lone " + chr(0xD800), "json")):
            with self.subTest(value=repr(value)):
                node = ET.fromstring(xml_evidence("context", value))
                self.assertEqual(node.get("encoding"), encoding)
                self.assertEqual(decoded(node), value)

    def test_each_commit_is_one_record_without_blank_line_guesses(self):
        messages = ("\nfix: first\r\n\r\nFirst paragraph.\n\nSecond paragraph.\n", "docs: second\n\n```text\n</commit> & data\n```\n\x1e")
        root = ET.fromstring(commit_evidence(messages))
        self.assertEqual([node.tag for node in root], ["commit", "commit"])
        self.assertEqual(tuple(decoded(node) for node in root), messages)
        aggregate = "\n\n".join(messages)
        legacy = ET.fromstring(commit_evidence(aggregate))
        self.assertEqual(legacy.get("boundaries"), "unknown")
        self.assertEqual(legacy.findall("commit"), [])
        self.assertEqual(decoded(legacy.find("commit_group")), aggregate)

    def test_each_file_diff_is_losslessly_sliced(self):
        first = 'preamble\r\ndiff --git "a/a b" "b/a b"\r\n@@ -1 +1 @@\r\n+diff --git is source\r\n-diff --git is source\r\n diff --git is context\r\n\r\n'
        second = "diff --git a/c b/c\n+<rules> & literal ```\n"
        content = first + second
        parts = split_diff_records(content)
        self.assertEqual(parts, (first, second))
        self.assertEqual("".join(parts), content)
        root = ET.fromstring(diff_evidence(content))
        self.assertEqual(root.tag, "diffs")
        self.assertFalse((root.text or "").strip())
        self.assertEqual([node.tag for node in root], ["diff", "diff"])
        self.assertTrue(all(not (node.tail or "").strip() for node in root))
        self.assertEqual(tuple(decoded(node) for node in root), parts)

    def test_truncation_annotations_stay_with_their_file_even_with_cut_headers(self):
        first = "diff --git a/full b/full\n+full\n\n"
        second = "# Truncated diff for a (original: 90 tokens)\r\ndiff --git a/a b/a\r\n+partial\r\n\n"
        third = "# Truncated diff for b (original: 100 tokens)\ndif"
        for content, expected in ((first + second + third, (first, second, third)), (second + third, (second, third)), ("headerless source", ("headerless source",)), ("", ())):
            with self.subTest(content=content):
                parts = split_diff_records(content)
                self.assertEqual(parts, expected)
                self.assertEqual("".join(parts), content)
                root = ET.fromstring(diff_evidence(content))
                self.assertEqual(root.tag, "diffs")
                self.assertEqual(tuple(decoded(node) for node in root.findall("diff")), expected)
                self.assertTrue(all(node.tag == "diff" for node in root))

    def test_individual_git_records_preserve_messages_and_record_separator_characters(self):
        generator = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
        messages = ("\nfix: first\r\n\r\nBody.  \r\n", "docs: second\n\nParagraph.\n\x1einside one real commit\n")
        objects = [b"tree abc\nauthor fixture\n\n" + message.encode("utf-8") for message in messages]
        info = {"commit_range": "base..pinned-head", "commit_hashes": ("aaa", "bbb")}
        with patch("subprocess.check_output", side_effect=objects) as read:
            self.assertEqual(generator.get_commit_messages(info, individual=True), messages)
        self.assertEqual(read.call_args_list, [call(["git", "cat-file", "commit", "aaa"], timeout=30), call(["git", "cat-file", "commit", "bbb"], timeout=30)])
        with patch("subprocess.check_output", side_effect=["aaa\n", objects[0]]) as read:
            self.assertEqual(generator.get_commit_messages("base..pinned-head", individual=True), messages[:1])
        self.assertEqual(read.call_args_list[0], call(["git", "rev-list", "base..pinned-head"], text=True, timeout=30))

    def test_individual_git_records_honor_encoding_and_fail_without_inventing_data(self):
        generator = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
        self.enterContext(patch.object(generator, "logger"))
        info = {"commit_range": "base..head", "commit_hashes": ("aaa",)}
        with patch("subprocess.check_output", return_value=b"tree abc\nencoding ISO-8859-1\n\ncaf\xe9\n"):
            self.assertEqual(generator.get_commit_messages(info, individual=True), ("café\n",))
        for result in (b"malformed object", b"tree abc\nencoding unknown-fixture-codec\n\nbody", b"tree abc\n\n \r\n"):
            with self.subTest(result=result), patch("subprocess.check_output", return_value=result):
                self.assertIsNone(generator.get_commit_messages(info, individual=True))
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired("git", 30)):
            self.assertIsNone(generator.get_commit_messages(info, individual=True))

    def test_empty_tuple_evidence_is_checked_before_xml_is_added(self):
        for messages in (None, (), ("", " \r\n")):
            self.assertFalse(messages_have_content(messages))
            for source in ("c", "b"):
                with self.subTest(messages=messages, source=source):
                    generator = IssuePullRequestGenerator(generation_type="pr", input_source=source, copy_clipboard=False)
                    with patch.object(generator, "get_commit_messages", return_value=messages) as commits, patch.object(generator, "get_branch_diffs", return_value=(" \n", [])), patch.object(generator, "get_diff_processing_params", return_value=1000):
                        self.assertIsNone(generator._collect_generation_content({"commit_count": 2, "base_branch": "develop"}, None))
                    commits.assert_called_once_with({"commit_count": 2, "base_branch": "develop"}, individual=True)
        self.assertTrue(messages_have_content(("", "fix: actual evidence")))


if __name__ == "__main__":
    unittest.main()
