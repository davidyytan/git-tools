"""Only complete outer reply envelopes are removed; inner content is never searched."""

from contextlib import chdir
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from git_tools.cli import app
from git_tools.generators.base.responses import unwrap_outer_xml_response
from git_tools.generators.commitgen import CommitGenerator
from git_tools.generators.issueprgen import IssuePullRequestGenerator
from test_output_files import boundaries


class XmlResponseTests(unittest.TestCase):
    def test_matching_outer_tags_attributes_and_line_endings(self):
        body = "## Title: fix: preserve replies\r\n\r\n  Body & <type> &amp; literal  "
        for opening, closing in (("<response>", "</response>"), ('<template kind="pr">', "</template>"), ('<draft note="a > b">', "</draft>"), ('<r:reply xmlns:r="urn:reply">', "</r:reply>"), ('<?xml version="1.0"?>\n<output>', "</output>")):
            with self.subTest(opening=opening):
                raw = " \n" + opening + "\r\n" + body + "\r\n" + closing + "\t\n"
                self.assertEqual(unwrap_outer_xml_response(raw), body)
        self.assertEqual(unwrap_outer_xml_response("<response>  kept  </response>"), "  kept  ")
        self.assertEqual(unwrap_outer_xml_response("<response/>"), "")

    def test_partial_middle_and_adjacent_blocks_are_not_outer_envelopes(self):
        values = ("prose\n<reply>body</reply>", "<reply>body</reply>\nprose", "## Title: example\n<reply>body</reply>", "<reply>body", "body</reply>", "<reply>body</other>", "<reply>first</reply><reply>second</reply>", "<reply><reply>body</reply>", "<reply>first</reply>outside</reply>", "<reply/><!-- trailing -->")
        document = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
        for raw in values:
            with self.subTest(raw=raw):
                self.assertIsNone(unwrap_outer_xml_response(raw))
                self.assertEqual(document.parse_generated_content(raw), raw)

    def test_only_one_outer_layer_is_removed_and_inner_markup_stays_verbatim(self):
        inner = "<reply>## Title: inner\n\n<details><summary>Kept</summary>Body &amp; data</details></reply>"
        self.assertEqual(unwrap_outer_xml_response("<reply>" + inner + "</reply>"), inner)
        document = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
        self.assertEqual(document.parse_generated_content("<output>" + inner + "</output>"), inner)
        fenced = "```markdown\n## Title: inner\n```"
        self.assertEqual(document.parse_generated_content("<output>\n" + fenced + "\n</output>"), fenced)
        self.assertEqual(document.parse_generated_content("````xml\n" + inner + "\n````"), inner)
        self.assertIsNone(CommitGenerator(auto_commit=False).parse_commit_message("<output>\n```\nfix: do not peel twice\n```\n</output>"))

    def test_ordinary_html_document_roots_and_inner_xml_are_preserved(self):
        document = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
        for raw in ("<details><summary>Changes</summary>\n\nBody\n</details>", "<div>Body</div>", '<h1 class="title">Heading</h1>', '<a href="https://example.test">Link</a>', '<img src="diagram.svg"/>', '<br/>', "<svg><path/></svg>", "    <example>literal XML code</example>", " \t<example>literal XML code</example>", "   \t<example>literal XML code</example>", "## Title: docs: describe XML\n\n<reply>example</reply>"):
            with self.subTest(raw=raw):
                self.assertIsNone(unwrap_outer_xml_response(raw))
                self.assertEqual(document.parse_generated_content(raw), raw)
        message = "fix: preserve inner XML\n\n<reply>literal body</reply>\n\nRefs: #42  "
        self.assertEqual(CommitGenerator(auto_commit=False).parse_commit_message("<commit>\n" + message + "\n</commit>"), message)

    def test_legacy_html_roots_are_document_markup_not_reply_envelopes(self):
        document = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
        paired = "acronym applet big blink center content dir font frameset listing marquee menuitem multicol nobr noembed noframes plaintext rb rtc shadow strike tt xmp".split()
        void = "basefont bgsound command frame image isindex keygen nextid param spacer".split()
        values = [f'<{tag} class="legacy">Body &amp; <example>literal XML</example></{tag}>' for tag in paired]
        values.extend(f'<{tag} class="legacy"/>' for tag in void)
        for raw in values:
            with self.subTest(raw=raw):
                self.assertIsNone(unwrap_outer_xml_response(raw))
                self.assertEqual(document.parse_generated_content(raw), raw)
        for raw in ('<CENTER><img src="diagram.svg" alt="Architecture"></CENTER>', " \n  <xMp>\r\n<response><example>literal XML &amp; &#10;</example></response>\r\n</xMp>  \t\n"):
            with self.subTest(raw=raw):
                self.assertIsNone(unwrap_outer_xml_response(raw))
                self.assertEqual(document.parse_generated_content(raw), raw)
                self.assertEqual(document.parse_generated_content("<output>\n" + raw + "\n</output>"), raw)

    def test_generic_xml_envelopes_keep_existing_single_layer_behavior(self):
        document = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
        payload = "  <response>Body &amp; &#10; <xmp><example>literal XML</example></xmp></response>  "
        for tag in ("output", "template", "response", "result", "draft", "reply", "commit", "payload", "custom-element", "centered", "xmp-example"):
            with self.subTest(tag=tag):
                raw = f"<{tag}>\r\n{payload}\r\n</{tag}>"
                self.assertEqual(unwrap_outer_xml_response(raw), payload)
                self.assertEqual(document.parse_generated_content(raw), payload)

    def test_legacy_html_documents_are_saved_verbatim(self):
        values = ('<center><img src="diagram.svg" alt="Architecture"></center>', '<xmp><example>literal XML example</example></xmp>', '  <center class="layout"><img src="diagram.svg" alt="Architecture"></center>  \t', '  <xMp class="sample">\r\n<output><example>literal XML &amp; &#10;</example></output>\r\n</xMp>  \t')
        for command in ("pr", "issue"):
            for raw in values:
                with self.subTest(command=command, raw=raw), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    methods[IssuePullRequestGenerator, "generate_content"].return_value = {"content": raw}
                    result = CliRunner().invoke(app, [command, "--output", "legacy.html"])
                    self.assertEqual(result.exit_code, 0, result.output)
                    self.assertEqual(Path("legacy.html").read_bytes(), (raw + "\n").encode("utf-8"))
                    self.assertEqual(list(Path.cwd().iterdir()), [Path.cwd() / "legacy.html"])
                    run.assert_not_called()
                    copy.assert_not_called()

    def test_empty_xml_replies_cannot_be_saved_or_repaired_into_drafts(self):
        for command in ("commit", "pr", "issue"):
            for raw in ("<response></response>", "<response>\n \n</response>", "<response/>"):
                with self.subTest(command=command, raw=raw), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    cls = CommitGenerator if command == "commit" else IssuePullRequestGenerator
                    method = "generate_commit_message" if command == "commit" else "generate_content"
                    methods[cls, method].return_value = {"content": raw}
                    args = [command, "--output", "draft.txt"] + (["--no-commit"] if command == "commit" else [])
                    result = CliRunner().invoke(app, args)
                    self.assertNotEqual(result.exit_code, 0, result.output)
                    self.assertEqual(list(Path.cwd().iterdir()), [])
                    run.assert_not_called()
                    copy.assert_not_called()

    def test_outer_xml_replies_save_the_payload_not_the_envelope(self):
        for command in ("commit", "pr", "issue"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                cls = CommitGenerator if command == "commit" else IssuePullRequestGenerator
                method = "generate_commit_message" if command == "commit" else "generate_content"
                body = "fix: preserve reply payload\n\nBody <inner>literal</inner>" if command == "commit" else "## Title: fix: preserve reply payload\n\nBody <inner>literal</inner>"
                methods[cls, method].return_value = {"content": "<output>\n" + body + "\n</output>"}
                args = [command, "--output", "draft.txt"] + (["--no-commit"] if command == "commit" else [])
                result = CliRunner().invoke(app, args)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(Path("draft.txt").read_bytes(), (body + "\n").encode())
                run.assert_not_called()
                copy.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
            image = '<img src="diagram.svg"/>'
            methods[IssuePullRequestGenerator, "generate_content"].return_value = {"content": image}
            result = CliRunner().invoke(app, ["pr", "--output", "image.md"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Path("image.md").read_text(), image + "\n")
            run.assert_not_called()
            copy.assert_not_called()

    def test_empty_xml_azure_retry_keeps_the_original(self):
        generator = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
        original = "Original description exceeds the requested limit."
        for raw in ("<output></output>", "<output/> ", "<output>\n \n</output>"):
            with self.subTest(raw=raw), patch("git_tools.generators.issueprgen.azure.settings", SimpleNamespace(azure_pr_max_chars=10)), patch.object(generator, "generate_content", return_value={"content": raw}):
                self.assertEqual(generator._enforce_azure_pr_description_limit(original, "evidence", "system"), original)


if __name__ == "__main__":
    unittest.main()
