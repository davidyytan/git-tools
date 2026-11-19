"""File-first output integration tests with all external effects mocked or blocked."""

from contextlib import ExitStack, chdir, contextmanager
import builtins
import errno
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from git_tools.cli import app
from git_tools.generators.commitgen import CommitGenerator
from git_tools.generators.issueprgen import IssuePullRequestGenerator
from git_tools.generators.utils import artifacts as artifact_writer
from git_tools.generators.utils.artifacts import resolve_output_path, save_draft
from git_tools.navigation import NavigationBack


MESSAGE = "feat(output): preserve messages\n\n- Résumé 😀 [literal] :smile:\n  continued detail  \n\nRefs: #42  "
DOCUMENT = "## Title: feat(output): preserve drafts\n\nBody [literal] :warning: 😀\n\n```python\n  print('kept')  \n```\nLAST  "
RAW_DOCUMENT = f"````markdown\n{DOCUMENT}\n````"


def bare_metadata(root, storage="refs"):
    """Create only a structural metadata fixture, never a real Git repository."""
    root.mkdir(parents=True)
    (root / "HEAD").write_text("ref: refs/heads/main\n")
    (root / "config").write_text("[core]\n\tbare = true\n")
    (root / "objects").mkdir()
    (root / ("refs/heads" if storage == "refs" else "reftable")).mkdir(parents=True)
    return root / ("refs/heads" if storage == "refs" else "reftable")


def args_for(kind, flags=()):
    if kind == "normal":
        return ["commit", *flags]
    return ["commit", "--workflow-kind", kind, *flags] if kind == "open-release" else [kind, *flags]


def text_for(kind):
    return MESSAGE if kind == "normal" else "chore: open release" if kind == "open-release" else DOCUMENT


def copied_text_for(kind):
    return RAW_DOCUMENT if kind == "issue" else text_for(kind)


@contextmanager
def boundaries():
    """Keep actual constructors, parsers, delivery and filesystem publication."""
    with ExitStack() as stack:
        def forbidden(*args, **kwargs):
            raise AssertionError("Unexpected external action or direct-mode prompt")
        stack.enter_context(patch("socket.socket.connect", side_effect=forbidden))
        stack.enter_context(patch("socket.create_connection", side_effect=forbidden))
        run = stack.enter_context(patch("subprocess.run", side_effect=forbidden))
        stack.enter_context(patch("subprocess.check_output", side_effect=forbidden))
        copy = stack.enter_context(patch("pyperclip.copy"))
        methods = {}
        for cls, values in (
            (CommitGenerator, {"get_staged_diff": "diff", "_get_staged_files": [], "_check_sensitive_files": True, "get_staged_diff_enhanced": ("diff", []), "select_provider": "openrouter", "ensure_api_key_configured": True, "select_model_params": ("mock", 0.0, 1000), "_initialize_service": True, "generate_commit_message": {"content": f"```text\n{MESSAGE}\n```"}}),
            (IssuePullRequestGenerator, {"get_default_branch": "develop", "get_commit_info": {"base_branch": "develop", "commit_count": 1}, "show_commit_summary": None, "_collect_generation_content": ("c", "input"), "resolve_pr_mode": None, "_should_apply_azure_limit": False, "select_provider": "openrouter", "ensure_api_key_configured": True, "select_model_params": ("mock", 0.0, 1000), "_initialize_service": True, "generate_content": {"content": RAW_DOCUMENT}}),
        ):
            for name, value in values.items():
                methods[(cls, name)] = stack.enter_context(patch.object(cls, name, return_value=value))
            for name in ("prompt_confirm", "prompt_select", "prompt_text"):
                methods[(cls, name)] = stack.enter_context(patch.object(cls, name, side_effect=forbidden))
        stack.enter_context(patch("git_tools.cli._has_interactive_terminal", return_value=True))
        yield methods, run, copy


class OutputFileTests(unittest.TestCase):
    def test_default_noncommit_and_issue_pr_outputs_save_without_clipboard(self):
        for kind, filename in (("normal", "COMMIT.md"), ("open-release", "COMMIT.md"), ("issue", "ISSUE.md"), ("pr", "PR.md")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                attempted_imports = []
                native_import = builtins.__import__
                def track_import(name, *args, **kwargs):
                    if name == "pyperclip":
                        attempted_imports.append(name)
                    return native_import(name, *args, **kwargs)
                with patch("builtins.__import__", side_effect=track_import):
                    result = CliRunner().invoke(app, args_for(kind, ["--no-commit"] if kind in ("normal", "open-release") else []))
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(Path(filename).read_bytes(), (text_for(kind) + "\n").encode())
                self.assertEqual(list(Path(tmp).iterdir()), [Path(tmp) / filename])
                self.assertEqual(attempted_imports, [])
                copy.assert_not_called()
                run.assert_not_called()

    def test_output_aliases_use_exact_nested_filenames_with_real_constructors(self):
        for kind in ("normal", "open-release", "issue", "pr"):
            for option in ("--output", "-o"):
                with self.subTest(kind=kind, option=option), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    Path("exports").mkdir()
                    target = Path("exports/message [literal] :smile: résumé.txt")
                    result = CliRunner().invoke(app, args_for(kind, [option, str(target)]))
                    self.assertEqual(result.exit_code, 0, result.output)
                    self.assertEqual(target.read_bytes(), (text_for(kind) + "\n").encode())
                    self.assertIn(f"Saved draft: {Path.cwd() / target}", result.output)
                    self.assertEqual(list(Path(tmp).glob("*.md")), [])
                    copy.assert_not_called()
                    run.assert_not_called()

    def test_absolute_output_and_extensionless_names_do_not_write_in_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "application").mkdir()
            (root / "exports").mkdir()
            with chdir(root / "application"), boundaries() as (methods, run, copy):
                target = (root / "exports/message").resolve()
                result = CliRunner().invoke(app, ["commit", "-o", str(target)])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(target.read_bytes(), (MESSAGE + "\n").encode())
                self.assertEqual(list(Path.cwd().iterdir()), [])
                run.assert_not_called()

    def test_explicit_copy_is_secondary_to_successful_output(self):
        for kind in ("normal", "open-release", "issue", "pr"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                target = Path("result.txt")
                def inspect_copy(content):
                    self.assertEqual(target.read_bytes(), (text_for(kind) + "\n").encode())
                copy.side_effect = inspect_copy
                result = CliRunner().invoke(app, args_for(kind, ["-o", str(target), "--copy"]))
                self.assertEqual(result.exit_code, 0, result.output)
                copy.assert_called_once_with(copied_text_for(kind))
                run.assert_not_called()

    def test_custom_occupied_entries_fail_before_generation_without_renaming(self):
        for kind in ("normal", "open-release", "issue", "pr"):
            for occupied in ("file", "directory", "symlink", "dangling"):
                with self.subTest(kind=kind, occupied=occupied), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    target = Path("result.txt")
                    if occupied == "file":
                        target.write_text("original")
                    elif occupied == "directory":
                        target.mkdir()
                    else:
                        target.symlink_to("result-target" if occupied == "dangling" else "original")
                        if occupied == "symlink":
                            Path("original").write_text("original")
                    before = set(Path.cwd().iterdir())
                    result = CliRunner().invoke(app, args_for(kind, ["-o", str(target)]))
                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertIn("already exists", result.output)
                    self.assertEqual(set(Path.cwd().iterdir()), before)
                    methods[CommitGenerator, "generate_commit_message"].assert_not_called()
                    methods[IssuePullRequestGenerator, "generate_content"].assert_not_called()
                    if occupied == "file":
                        self.assertEqual(target.read_text(), "original")
                    if occupied in ("symlink", "dangling"):
                        self.assertTrue(target.is_symlink())
                    run.assert_not_called()
                    copy.assert_not_called()

    def test_publication_race_does_not_rename_explicit_output_or_commit(self):
        for kind in ("normal", "open-release", "issue", "pr"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                native_link = os.link
                def race(source, destination, **kwargs):
                    Path(destination).write_text("other writer")
                    return native_link(source, destination, **kwargs)
                flags = ["-o", "result.txt", "--copy"] + (["--commit"] if kind in ("normal", "open-release") else [])
                with patch("git_tools.generators.utils.artifacts.os.link", side_effect=race):
                    result = CliRunner().invoke(app, args_for(kind, flags))
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertEqual(Path("result.txt").read_text(), "other writer")
                self.assertEqual(len(list(Path.cwd().iterdir())), 1)
                self.assertNotIn("Saved draft:", result.output)
                copy.assert_called_once_with(copied_text_for(kind))
                run.assert_not_called()

    def test_invalid_output_is_rejected_without_provider_work_or_parent_creation(self):
        for kind in ("normal", "open-release", "issue", "pr"):
            for target in ("missing/result.txt", "plain-file/child", "-", "", ".git/new-file"):
                with self.subTest(kind=kind, target=target), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    Path("plain-file").write_text("original")
                    Path(".git").mkdir()
                    result = CliRunner().invoke(app, args_for(kind, ["-o", target]))
                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertFalse(Path("missing").exists())
                    self.assertEqual(list(Path(".git").iterdir()), [])
                    methods[CommitGenerator, "generate_commit_message"].assert_not_called()
                    methods[IssuePullRequestGenerator, "generate_content"].assert_not_called()
                    run.assert_not_called()
                    copy.assert_not_called()

    def test_directory_syntax_is_rejected_before_generation_without_creating_entries(self):
        for kind in ("normal", "open-release", "issue", "pr"):
            for spelling in ("absent/", "absent/.", "absent//", "absent/./", "absolute"):
                with self.subTest(kind=kind, spelling=spelling), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    target = str(Path.cwd() / "absent") + "/." if spelling == "absolute" else spelling
                    result = CliRunner().invoke(app, args_for(kind, ["-o", target]))
                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertEqual(list(Path.cwd().iterdir()), [])
                    methods[CommitGenerator, "generate_commit_message"].assert_not_called()
                    methods[IssuePullRequestGenerator, "generate_content"].assert_not_called()
                    run.assert_not_called()
                    copy.assert_not_called()

    def test_automatic_outputs_reject_metadata_cwd_before_generation(self):
        for kind in ("normal", "open-release", "issue", "pr"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                metadata = Path(tmp) / ".git"
                metadata.mkdir()
                with chdir(metadata), boundaries() as (methods, run, copy):
                    flags = ["--no-commit"] if kind in ("normal", "open-release") else []
                    result = CliRunner().invoke(app, args_for(kind, flags))
                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertIn("Git administrative", result.output)
                    self.assertEqual(list(metadata.iterdir()), [])
                    methods[CommitGenerator, "generate_commit_message"].assert_not_called()
                    methods[IssuePullRequestGenerator, "generate_content"].assert_not_called()
                    run.assert_not_called()
                    copy.assert_not_called()

    def test_writer_rechecks_default_custom_and_aliased_metadata_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = root / ".git"
            metadata.mkdir()
            link = root / "metadata-alias"
            link.symlink_to(metadata, target_is_directory=True)
            aliases = [metadata, link]
            if (root / ".GIT").is_dir():
                aliases.append(root / ".GIT")
            for alias in aliases:
                for kind in ("commit", "issue", "pr", "both"):
                    with self.subTest(alias=alias.name, kind=kind):
                        with self.assertRaisesRegex(OSError, "Git administrative"):
                            save_draft("finished", kind, alias)
                        with self.assertRaisesRegex(OSError, "Git administrative"):
                            save_draft("finished", kind, root, output_path=alias / "custom.md")
                        self.assertEqual(list(metadata.iterdir()), [])
                with self.assertRaisesRegex(ValueError, "Git administrative"):
                    resolve_output_path(alias / "custom.md", root)

    def test_bare_metadata_defaults_and_explicit_paths_fail_before_generation(self):
        for storage in ("refs", "reftable"):
            for kind in ("normal", "open-release", "issue", "pr"):
                for explicit in (False, True):
                    with self.subTest(storage=storage, kind=kind, explicit=explicit), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
                        root = Path(tmp) / "server.git"
                        destination = bare_metadata(root, storage)
                        before = set(root.rglob("*"))
                        flags = ["-o", str(destination / "new-draft")] if explicit else ["--no-commit"] if kind in ("normal", "open-release") else []
                        with chdir(root), boundaries() as (methods, run, copy):
                            result = CliRunner().invoke(app, args_for(kind, flags))
                            self.assertEqual(result.exit_code, 1, result.output)
                            self.assertIn("Git administrative", result.output)
                            methods[CommitGenerator, "generate_commit_message"].assert_not_called()
                            methods[IssuePullRequestGenerator, "generate_content"].assert_not_called()
                            run.assert_not_called()
                            copy.assert_not_called()
                        self.assertEqual(set(root.rglob("*")), before)
                        for document_kind in ("commit", "issue", "pr", "both"):
                            with self.assertRaisesRegex(OSError, "Git administrative"):
                                save_draft("finished", document_kind, root)
                            with self.assertRaisesRegex(OSError, "Git administrative"):
                                save_draft("finished", document_kind, root, output_path=destination / "new-draft")
                        self.assertEqual(set(root.rglob("*")), before)

    def test_external_bare_metadata_is_detected_by_layout_not_filename(self):
        for storage in ("refs", "reftable"):
            with self.subTest(storage=storage), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
                root = Path(tmp)
                invocation = root / "checkout"
                invocation.mkdir()
                destination = bare_metadata(root / "metadata-without-git-suffix", storage)
                alias = root / "alias"
                alias.symlink_to(destination, target_is_directory=True)
                for parent in (destination, alias):
                    with self.assertRaisesRegex(ValueError, "Git administrative"):
                        resolve_output_path(parent / "new-draft", invocation)
                    with self.assertRaisesRegex(OSError, "Git administrative"):
                        save_draft("finished", "pr", invocation, output_path=parent / "new-draft")
                    self.assertEqual(list(destination.iterdir()), [])
                # A suffix and partial lookalike are not enough to classify an ordinary export folder as metadata.
                ordinary = root / "ordinary.git"
                ordinary.mkdir()
                (ordinary / "HEAD").write_text("ordinary data")
                (ordinary / "refs").mkdir()
                target = resolve_output_path(ordinary / "refs/draft", invocation)
                self.assertEqual(save_draft("finished", "pr", invocation, output_path=target).read_text(), "finished\n")

    def test_relative_git_environment_paths_stay_relative_to_invocation_directory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GIT_DIR": "admin"}, clear=True):
            root = Path(tmp)
            invocation = root / "checkout"
            (invocation / "admin").mkdir(parents=True)
            exports = root / "exports/admin"
            exports.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "Git administrative"):
                resolve_output_path(invocation / "admin/new-draft", invocation)
            target = resolve_output_path(exports / "draft", invocation)
            self.assertEqual(save_draft("finished", "pr", invocation, output_path=target).read_text(), "finished\n")

    def test_replaced_preflight_parent_cannot_redirect_output_into_metadata(self):
        for kind in ("normal", "open-release", "issue", "pr"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                root = Path.cwd()
                refs = root / ".git/refs/heads"
                refs.mkdir(parents=True)
                exports = root / "exports"
                exports.mkdir()
                def replace_after_preflight(*args, **kwargs):
                    target = resolve_output_path(*args, **kwargs)
                    exports.rename(root / "old-exports")
                    exports.symlink_to(refs, target_is_directory=True)
                    return target
                module = "git_tools.generators.commitgen.workflow" if kind in ("normal", "open-release") else "git_tools.generators.issueprgen.generator"
                flags = ["-o", "exports/result.txt", "--copy"] + (["--commit"] if kind in ("normal", "open-release") else [])
                with patch(module + ".resolve_output_path", side_effect=replace_after_preflight):
                    result = CliRunner().invoke(app, args_for(kind, flags))
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn("Git administrative", result.output)
                self.assertNotIn("Saved draft:", result.output)
                self.assertEqual(list(refs.iterdir()), [])
                self.assertEqual(list((root / "old-exports").iterdir()), [])
                copy.assert_called_once_with(copied_text_for(kind))
                run.assert_not_called()

    @unittest.skipUnless(artifact_writer._DIRECTORY_FD_IO, "Directory-relative I/O is unavailable")
    def test_parent_replacement_during_staging_and_publication_is_not_followed(self):
        for phase in ("mkdir", "flush", "link"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                refs = root / ".git/refs/heads"
                refs.mkdir(parents=True)
                exports = root / "exports"
                exports.mkdir()
                target = resolve_output_path(exports / "result.txt", root)
                native = getattr(os, "fsync" if phase == "flush" else phase)
                replaced = False
                def replace_and_continue(*args, **kwargs):
                    nonlocal replaced
                    if not replaced:
                        replaced = True
                        exports.rename(root / "old-exports")
                        exports.symlink_to(refs, target_is_directory=True)
                    return native(*args, **kwargs)
                with patch("git_tools.generators.utils.artifacts.os." + ("fsync" if phase == "flush" else phase), side_effect=replace_and_continue):
                    with self.assertRaisesRegex(OSError, "Git administrative|directory changed"):
                        save_draft("finished", "pr", root, output_path=target)
                self.assertTrue(replaced)
                self.assertEqual(list(refs.iterdir()), [])
                previous = root / "old-exports"
                self.assertEqual(list(previous.glob(".git-tools-draft-*")), [])
                if phase == "link":
                    # Publication was pinned to the original directory; never remove that complete public file on a late error.
                    self.assertEqual((previous / "result.txt").read_text(), "finished\n")
                else:
                    self.assertEqual(list(previous.iterdir()), [])

    @unittest.skipUnless(artifact_writer._DIRECTORY_FD_IO, "Directory-relative I/O is unavailable")
    def test_ancestor_replacement_while_opening_parent_fails_before_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            refs = root / ".git/refs/heads"
            (refs / "exports").mkdir(parents=True)
            ancestor = root / "ancestor"
            exports = ancestor / "exports"
            exports.mkdir(parents=True)
            target = resolve_output_path(exports / "result.txt", root)
            native_open = os.open
            replaced = False
            def replace_during_open(path, *args, **kwargs):
                nonlocal replaced
                if not replaced and Path(path) == exports:
                    replaced = True
                    ancestor.rename(root / "old-ancestor")
                    ancestor.symlink_to(refs, target_is_directory=True)
                return native_open(path, *args, **kwargs)
            with patch("git_tools.generators.utils.artifacts.os.open", side_effect=replace_during_open):
                with self.assertRaisesRegex(OSError, "directory changed"):
                    save_draft("finished", "pr", root, output_path=target)
            self.assertTrue(replaced)
            self.assertEqual(list((refs / "exports").iterdir()), [])
            self.assertEqual(list((root / "old-ancestor/exports").iterdir()), [])

    @unittest.skipUnless(artifact_writer._DIRECTORY_FD_IO and (hasattr(os, "O_PATH") or hasattr(os, "O_SEARCH")), "Search-only directory handles are unavailable")
    def test_directory_handles_do_not_require_export_directory_read_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exports = root / "dropbox"
            exports.mkdir(mode=0o300)
            try:
                target = resolve_output_path(exports / "result.txt", root)
                saved = save_draft("finished", "pr", root, output_path=target)
            finally:
                exports.chmod(0o700)
            self.assertEqual(saved.read_text(), "finished\n")
            self.assertEqual(list(exports.iterdir()), [saved])

    def test_portable_path_fallback_preserves_no_clobber_and_metadata_checks(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(artifact_writer, "_DIRECTORY_FD_IO", False):
            root = Path(tmp)
            (root / "PR.md").write_text("original")
            saved = save_draft("finished", "pr", root)
            self.assertNotEqual(saved.name, "PR.md")
            self.assertEqual(saved.read_text(), "finished\n")
            self.assertEqual((root / "PR.md").read_text(), "original")
            refs = root / ".git/refs/heads"
            refs.mkdir(parents=True)
            exports = root / "exports"
            exports.mkdir()
            target = resolve_output_path(exports / "result.txt", root)
            exports.rename(root / "old-exports")
            exports.symlink_to(refs, target_is_directory=True)
            with self.assertRaisesRegex(OSError, "Git administrative"):
                save_draft("finished", "pr", root, output_path=target)
            self.assertEqual(list(refs.iterdir()), [])

    def test_metadata_validation_never_follows_an_occupied_output_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = root / ".git"
            metadata.mkdir()
            link = root / "message.txt"
            link.symlink_to(metadata, target_is_directory=True)
            native_stat = Path.stat
            def stat(path, *args, **kwargs):
                if path == link and kwargs.get("follow_symlinks", True):
                    raise AssertionError("Output symlink was followed")
                return native_stat(path, *args, **kwargs)
            with patch.object(Path, "stat", new=stat):
                with self.assertRaisesRegex(ValueError, "already exists"):
                    resolve_output_path(link, root)
                with self.assertRaises(FileExistsError):
                    save_draft("finished", "commit", root, output_path=link)
            self.assertTrue(link.is_symlink())
            self.assertEqual(list(metadata.iterdir()), [])

    def test_metadata_guard_defers_unknown_interactive_action_and_keeps_recovery_copy(self):
        for kind in ("normal", "open-release"):
            for commit in (False, True):
                with self.subTest(kind=kind, commit=commit), tempfile.TemporaryDirectory() as tmp:
                    metadata = Path(tmp) / ".git"
                    metadata.mkdir()
                    with chdir(metadata), boundaries() as (methods, run, copy):
                        questions = []
                        def confirm(question, **kwargs):
                            questions.append(question)
                            return True if question.startswith("Generate") else commit
                        methods[CommitGenerator, "prompt_confirm"].side_effect = confirm
                        if kind == "normal":
                            methods[CommitGenerator, "prompt_select"].side_effect = None
                            methods[CommitGenerator, "prompt_select"].return_value = "Conventional Commit"
                        run.side_effect = None
                        result = CliRunner().invoke(app, args_for(kind, ["-i", "--copy"]))
                        self.assertEqual(result.exit_code, 0 if commit else 1, result.output)
                        self.assertIn("Commit changes directly?", questions)
                        self.assertEqual(list(metadata.iterdir()), [])
                        if commit:
                            run.assert_called_once()
                            copy.assert_not_called()
                        else:
                            self.assertIn("Could not save commit", result.output)
                            run.assert_not_called()
                            copy.assert_called_once_with(text_for(kind))

    def test_interactive_output_and_explicit_action_matrix(self):
        for kind in ("normal", "open-release"):
            for output in (False, True):
                for action in (None, "--commit", "--no-commit"):
                    with self.subTest(kind=kind, output=output, action=action), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                        questions = []
                        def confirm(question, **kwargs):
                            questions.append(question)
                            return question.startswith("Generate")
                        methods[CommitGenerator, "prompt_confirm"].side_effect = confirm
                        if kind == "normal":
                            methods[CommitGenerator, "prompt_select"].side_effect = None
                            methods[CommitGenerator, "prompt_select"].return_value = "Conventional Commit"
                        def git(*args, **kwargs):
                            self.assertEqual(Path("message.txt").exists(), output)
                        run.side_effect = git
                        flags = ["-i", "--no-copy"] + (["-o", "message.txt"] if output else []) + ([action] if action else [])
                        result = CliRunner().invoke(app, args_for(kind, flags))
                        self.assertEqual(result.exit_code, 0, result.output)
                        should_commit = action == "--commit"
                        self.assertEqual(run.call_count, int(should_commit))
                        self.assertEqual(questions.count("Commit changes directly?"), int(action is None and not output))
                        if output or not should_commit:
                            filename = "message.txt" if output else "COMMIT.md"
                            self.assertEqual(Path(filename).read_bytes(), (text_for(kind) + "\n").encode())
                        else:
                            self.assertEqual(list(Path.cwd().iterdir()), [])
                        copy.assert_not_called()

    def test_literal_dash_filename_is_not_stdout_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries():
            result = CliRunner().invoke(app, ["pr", "-o", "./-"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Path("-").read_bytes(), (DOCUMENT + "\n").encode())

    def test_linked_worktree_metadata_and_common_dir_are_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkout = root / "checkout"
            gitdir = root / "admin/worktrees/current"
            checkout.mkdir()
            gitdir.mkdir(parents=True)
            (root / "admin/refs").mkdir()
            (checkout / ".git").write_text(f"gitdir: {gitdir}\n")
            (gitdir / "commondir").write_text("../..\n")
            for target in (gitdir / "new-file", root / "admin/refs/new-file"):
                with self.subTest(target=target), self.assertRaisesRegex(ValueError, "Git administrative"):
                    resolve_output_path(target, checkout)
                self.assertFalse(target.exists())

    def test_git_dir_environment_and_its_common_directory_are_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gitdir = root / "metadata/worktree"
            gitdir.mkdir(parents=True)
            (gitdir / "commondir").write_text("..\n")
            with patch.dict(os.environ, {"GIT_DIR": str(gitdir)}):
                for target in (gitdir / "new-file", root / "metadata/new-file"):
                    with self.subTest(target=target), self.assertRaisesRegex(ValueError, "Git administrative"):
                        resolve_output_path(target, root)

    def test_commit_file_and_explicit_copy_preserve_crlf_and_footer_whitespace(self):
        message = "fix: preserve message bytes\r\n\r\n  Indented body  \r\n\r\nRefs: #42  "
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
            methods[CommitGenerator, "generate_commit_message"].return_value = {"content": f"```text\n{message}\n```"}
            result = CliRunner().invoke(app, ["commit", "-o", "message.txt", "--copy"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Path("message.txt").read_bytes(), (message + "\n").encode())
            copy.assert_called_once_with(message)
            run.assert_not_called()

    def test_failed_save_cannot_be_cancelled_into_success_at_the_copy_question(self):
        for kind in ("normal", "open-release"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                def confirm(question, **kwargs):
                    if question.startswith("Generate"):
                        return True
                    if question == "Commit changes directly?":
                        return False
                    raise NavigationBack
                methods[CommitGenerator, "prompt_confirm"].side_effect = confirm
                if kind == "normal":
                    methods[CommitGenerator, "prompt_select"].side_effect = None
                    methods[CommitGenerator, "prompt_select"].return_value = "Conventional Commit"
                with patch("git_tools.generators.commitgen.workflow.save_draft", side_effect=PermissionError("read-only")):
                    result = CliRunner().invoke(app, args_for(kind, ["-i"]))
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn("Could not save commit", result.output)
                self.assertEqual(list(Path.cwd().iterdir()), [])
                copy.assert_not_called()
                run.assert_not_called()

    def test_bare_commit_default_and_explicit_copy_do_not_create_drafts(self):
        for kind in ("normal", "open-release"):
            for flags in ([], ["--copy"]):
                with self.subTest(kind=kind, flags=flags), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    run.side_effect = None
                    result = CliRunner().invoke(app, args_for(kind, flags))
                    self.assertEqual(result.exit_code, 0, result.output)
                    run.assert_called_once()
                    self.assertEqual(run.call_args.args[0][:2], ["git", "commit"])
                    self.assertEqual(list(Path.cwd().iterdir()), [])
                    copy.assert_not_called()

    def test_explicit_commit_with_output_saves_before_git(self):
        for kind in ("normal", "open-release"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                def inspect_commit(argv, **kwargs):
                    self.assertEqual(Path("result.txt").read_bytes(), (text_for(kind) + "\n").encode())
                    self.assertEqual(argv[-2:], ["-m", text_for(kind)])
                run.side_effect = inspect_commit
                result = CliRunner().invoke(app, args_for(kind, ["--commit", "-o", "result.txt"]))
                self.assertEqual(result.exit_code, 0, result.output)
                run.assert_called_once()
                copy.assert_not_called()

    def test_failed_explicit_commit_retains_saved_output(self):
        for kind in ("normal", "open-release"):
            for failure in (subprocess.CalledProcessError(1, ["git", "commit"]), subprocess.TimeoutExpired(["git", "commit"], 900)):
                with self.subTest(kind=kind, failure=type(failure)), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    run.side_effect = failure
                    result = CliRunner().invoke(app, args_for(kind, ["--commit", "-o", "result.txt"]))
                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertEqual(Path("result.txt").read_bytes(), (text_for(kind) + "\n").encode())
                    self.assertIn("Saved draft:", result.output)
                    copy.assert_not_called()

    def test_failed_commit_output_blocks_git_and_keeps_explicit_copy_recovery(self):
        for kind in ("normal", "open-release"):
            for failure in (PermissionError("read-only"), OSError(errno.ENOSPC, "disk full"), UnicodeEncodeError("utf-8", "x", 0, 1, "invalid")):
                with self.subTest(kind=kind, failure=type(failure)), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    with patch("git_tools.generators.commitgen.workflow.save_draft", side_effect=failure):
                        result = CliRunner().invoke(app, args_for(kind, ["--commit", "-o", "result.txt", "--copy"]))
                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertIn("Could not save commit", result.output)
                    self.assertIn(text_for(kind).splitlines()[0], result.output)
                    self.assertNotIn("Saved draft:", result.output)
                    self.assertEqual(list(Path.cwd().iterdir()), [])
                    copy.assert_called_once_with(text_for(kind))
                    run.assert_not_called()

    def test_commit_save_precedes_metadata_and_pending_errors_survive_cancellation(self):
        for fail_save in (False, True):
            for signal in (KeyboardInterrupt, NavigationBack):
                with self.subTest(fail_save=fail_save, signal=signal), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy), ExitStack() as stack:
                    if fail_save:
                        stack.enter_context(patch("git_tools.generators.commitgen.workflow.save_draft", side_effect=PermissionError("read-only")))
                    stack.enter_context(patch.object(CommitGenerator, "display_reasoning", side_effect=signal()))
                    result = CliRunner().invoke(app, ["commit", "--no-commit", "--copy"])
                    self.assertEqual(result.exit_code, int(fail_save), result.output)
                    if fail_save:
                        self.assertIn("Could not save commit", result.output)
                    else:
                        self.assertEqual(Path("COMMIT.md").read_bytes(), (MESSAGE + "\n").encode())
                    run.assert_not_called()
                    copy.assert_not_called()

    def test_real_malformed_metadata_does_not_block_commit_output_or_copy(self):
        for fail_save in (False, True):
            with self.subTest(fail_save=fail_save), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy), ExitStack() as stack:
                methods[CommitGenerator, "generate_commit_message"].return_value = {"content": MESSAGE, "response_metadata": {"token_usage": {"cost": "invalid"}}}
                if fail_save:
                    stack.enter_context(patch("git_tools.generators.commitgen.workflow.save_draft", side_effect=PermissionError("read-only")))
                result = CliRunner().invoke(app, ["commit", "--no-commit", "--copy"])
                self.assertEqual(result.exit_code, int(fail_save), result.output)
                if fail_save:
                    self.assertIn("Could not save commit", result.output)
                    self.assertEqual(list(Path.cwd().iterdir()), [])
                else:
                    self.assertEqual(Path("COMMIT.md").read_bytes(), (MESSAGE + "\n").encode())
                copy.assert_called_once_with(MESSAGE)
                run.assert_not_called()

    def test_interactive_no_saves_before_copy_question_and_late_cancel_keeps_file(self):
        for kind in ("normal", "open-release"):
            for cancel_copy in (False, True):
                with self.subTest(kind=kind, cancel_copy=cancel_copy), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                    def confirm(question, **kwargs):
                        if question.startswith("Generate"):
                            return True
                        if question == "Commit changes directly?":
                            self.assertFalse(Path("COMMIT.md").exists())
                            return False
                        self.assertEqual(question, "Copy to clipboard?")
                        self.assertEqual(Path("COMMIT.md").read_bytes(), (text_for(kind) + "\n").encode())
                        if cancel_copy:
                            raise NavigationBack
                        return False
                    methods[CommitGenerator, "prompt_confirm"].side_effect = confirm
                    if kind == "normal":
                        methods[CommitGenerator, "prompt_select"].side_effect = None
                        methods[CommitGenerator, "prompt_select"].return_value = "Conventional Commit"
                    result = CliRunner().invoke(app, args_for(kind, ["-i"]))
                    self.assertEqual(result.exit_code, 0, result.output)
                    self.assertEqual(len(list(Path.cwd().glob("COMMIT*.md"))), 1)
                    run.assert_not_called()
                    copy.assert_not_called()

    def test_cancel_commit_decision_does_not_create_a_draft(self):
        for kind in ("normal", "open-release"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                def confirm(question, **kwargs):
                    if question.startswith("Generate"):
                        return True
                    raise NavigationBack
                methods[CommitGenerator, "prompt_confirm"].side_effect = confirm
                if kind == "normal":
                    methods[CommitGenerator, "prompt_select"].side_effect = None
                    methods[CommitGenerator, "prompt_select"].return_value = "Conventional Commit"
                result = CliRunner().invoke(app, args_for(kind, ["-i"]))
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(list(Path.cwd().iterdir()), [])
                run.assert_not_called()
                copy.assert_not_called()

    def test_default_commit_collisions_keep_existing_message(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
            Path("COMMIT.md").write_text("original")
            result = CliRunner().invoke(app, ["commit", "--no-commit"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Path("COMMIT.md").read_text(), "original")
            paths = list(Path.cwd().glob("COMMIT-*.md"))
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].read_bytes(), (MESSAGE + "\n").encode())

    def test_explicit_output_requires_a_finished_result_on_noop_or_missing_key(self):
        for kind in ("normal", "issue", "pr"):
            for scenario in ("no-input", "missing-key"):
                for explicit in (False, True):
                    with self.subTest(kind=kind, scenario=scenario, explicit=explicit), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy):
                        cls = CommitGenerator if kind == "normal" else IssuePullRequestGenerator
                        if scenario == "missing-key":
                            methods[cls, "ensure_api_key_configured"].return_value = False
                        elif kind == "normal":
                            methods[cls, "get_staged_diff"].return_value = ""
                        else:
                            methods[cls, "get_commit_info"].return_value = None
                        result = CliRunner().invoke(app, args_for(kind, ["-o", "result.txt"] if explicit else []))
                        self.assertEqual(result.exit_code, int(explicit), result.output)
                        self.assertEqual(list(Path.cwd().iterdir()), [])
                        run.assert_not_called()
                        copy.assert_not_called()

    def test_custom_output_keeps_final_azure_result_and_raw_issue_copy_contract(self):
        for kind in ("pr", "issue"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp), boundaries() as (methods, run, copy), patch.object(IssuePullRequestGenerator, "_enforce_azure_pr_description_limit", return_value="## Title: feat: condensed\n\nFinal"):
                methods[IssuePullRequestGenerator, "_should_apply_azure_limit"].return_value = True
                result = CliRunner().invoke(app, [kind, "-o", "result.txt", "--copy"])
                self.assertEqual(result.exit_code, 0, result.output)
                expected = "## Title: feat: condensed\n\nFinal" if kind == "pr" else DOCUMENT
                self.assertEqual(Path("result.txt").read_bytes(), (expected + "\n").encode())
                copy.assert_called_once_with(expected if kind == "pr" else RAW_DOCUMENT)


if __name__ == "__main__":
    unittest.main()
