"""Read-only CLI help, cold-start offline safety, and lazy tokenization contracts."""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch

from rich.text import Text
from typer.main import get_command
from typer.testing import CliRunner

from git_tools.cli import app
from git_tools.generators.base import BaseGenerator
from git_tools.generators.base import tokens


class HelpCliTests(unittest.TestCase):
    def test_both_flags_work_for_root_and_every_registered_command_without_actions(self):
        runner = CliRunner()
        with ExitStack() as stack:
            forbidden = []
            for target in ("subprocess.run", "subprocess.Popen", "socket.socket.connect", "socket.create_connection", "pyperclip.copy"):
                forbidden.append(stack.enter_context(patch(target, side_effect=AssertionError(f"Help attempted {target}"))))
            forbidden.append(stack.enter_context(patch.object(BaseGenerator, "__init__", side_effect=AssertionError("Help initialized a generator"))))
            commands = sorted(get_command(app).commands)
            for command in [None, *commands]:
                for flag in ("-h", "--help"):
                    arguments = ([command] if command else []) + [flag]
                    with self.subTest(arguments=arguments):
                        result = runner.invoke(app, arguments)
                        self.assertEqual(result.exit_code, 0, result.output)
                        self.assertIn("Usage:", Text.from_ansi(result.output).plain)
            for action in forbidden:
                action.assert_not_called()

    def test_help_explains_safe_commit_output_and_points_to_markdown_manual(self):
        runner = CliRunner()
        root = Text.from_ansi(runner.invoke(app, ["-h"]).output).plain
        self.assertIn("docs/usage.md", root)
        commit = Text.from_ansi(runner.invoke(app, ["commit", "-h"]).output).plain
        self.assertRegex(commit, r"commits\s+by\s+default")
        self.assertIn("git-tools commit -o commit-message.txt", commit)
        self.assertIn("git-tools commit --no-commit", commit)
        self.assertLess(commit.index("git-tools commit -o"), commit.index("git-tools commit --no-scope"))
        for command, filename in (("issue", "issue-draft.md"), ("pr", "review-pr.md")):
            with self.subTest(command=command):
                result = runner.invoke(app, [command, "--help"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn(f"git-tools {command} -o {filename}", Text.from_ansi(result.output).plain)

    def test_fresh_process_help_never_loads_tokenizer_or_uses_network(self):
        source_root = Path(__file__).resolve().parents[1]
        code = textwrap.dedent('''
            from contextlib import ExitStack
            from unittest.mock import patch
            with ExitStack() as stack:
                mocks = []
                for target in ('tiktoken.get_encoding', 'requests.get', 'socket.socket.connect', 'socket.create_connection', 'subprocess.run', 'subprocess.Popen', 'pyperclip.copy'):
                    mocks.append(stack.enter_context(patch(target, side_effect=AssertionError('Offline help attempted ' + target))))
                from git_tools.cli import app
                from typer.main import get_command
                from typer.testing import CliRunner
                runner = CliRunner()
                total = 0
                for command in [None, *sorted(get_command(app).commands)]:
                    for flag in ('-h', '--help'):
                        result = runner.invoke(app, ([command] if command else []) + [flag])
                        assert result.exit_code == 0, (command, flag, result.output, repr(result.exception))
                        total += 1
                for action in mocks:
                    action.assert_not_called()
                print(f'{total} offline help checks passed')
        ''')
        with tempfile.TemporaryDirectory() as isolated:
            root = Path(isolated)
            home, cache = root / "home", root / "tokenizer-cache"
            home.mkdir()
            cache.mkdir()
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=isolated,
                env={**os.environ, "HOME": str(home), "USERPROFILE": str(home), "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"), "PYTHONPATH": str(source_root), "TIKTOKEN_CACHE_DIR": str(cache), "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=60,
            )
            self.assertEqual(list(cache.iterdir()), [])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = 2 * (len(get_command(app).commands) + 1)
        self.assertIn(f"{expected} offline help checks passed", result.stdout)

    def test_all_special_markers_are_escaped_through_lazy_diff_truncation(self):
        from git_tools.generators.base.diffs import DiffProcessingMixin
        markers = {"<|endoftext|>", "<|fim_prefix|>", "<|fim_middle|>", "<|fim_suffix|>", "<|endofprompt|>"}
        encoder = Mock(special_tokens_set=markers)
        encoded_texts = []
        def encode(text):
            self.assertFalse(any(marker in text for marker in markers))
            encoded_texts.append(text)
            return [ord(character) for character in text]
        encoder.encode.side_effect = encode
        encoder.decode.side_effect = lambda values: "".join(chr(value) for value in values)
        tokens._get_encoder.cache_clear()
        self.addCleanup(tokens._get_encoder.cache_clear)
        raw = "prefix " + " ".join(sorted(markers)) + " suffix"
        escaped = raw.replace("|", r"\|")
        with patch.object(tokens.tiktoken, "get_encoding", return_value=encoder) as load:
            self.assertEqual(tokens.count_tokens(raw), len(escaped))
            result = DiffProcessingMixin()._truncate_diffs_to_quotas([("demo.py", raw)], {"demo.py": 3})
            self.assertEqual(result, [f"# Truncated diff for demo.py (original: {len(escaped)} tokens)\npre"])
            self.assertEqual(encoded_texts, [escaped, escaped, escaped])
            load.assert_called_once_with("cl100k_base")

    def test_tokenizer_is_loaded_once_when_needed_and_special_markers_stay_escaped(self):
        tokens._get_encoder.cache_clear()
        self.addCleanup(tokens._get_encoder.cache_clear)
        encoder = Mock(special_tokens_set={"<|endoftext|>"})
        encoder.encode.return_value = [1, 2]
        with patch.object(tokens.tiktoken, "get_encoding", return_value=encoder) as load:
            load.assert_not_called()
            self.assertEqual(tokens.count_tokens("<|endoftext|>"), 2)
            encoder.encode.assert_called_once_with(r"<\|endoftext\|>")
            self.assertEqual(tokens.count_tokens("ordinary text"), 2)
            load.assert_called_once_with("cl100k_base")


if __name__ == "__main__":
    unittest.main()
