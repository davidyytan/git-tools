"""Read-only history tests; every fixture commit belongs to a private temp repo."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from git_tools.history import HistoryError, LogView, history_snapshot, render_log


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="git-tools-history-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Do not inherit a caller's repository, config, signing, hooks, or identity.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
        isolated_env = patch.dict(os.environ, env, clear=True)
        isolated_env.start()
        self.addCleanup(isolated_env.stop)
        self.git("init", "--template=", "-b", "main")
        self.git("config", "user.name", "History Tests")
        self.git("config", "user.email", "history@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", f"core.hooksPath={os.devnull}", *args], cwd=self.root,
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("commit", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def snapshot(self, base: str | None = None):
        return history_snapshot(base, cwd=self.root)

    def graph(self, snapshot=None, view=LogView.BRANCH, **kwargs) -> str:
        return render_log(snapshot or self.snapshot(), view, cwd=self.root, **kwargs)

    def divergent_merge(self) -> tuple[str, str]:
        initial = self.commit("initial history")
        self.git("branch", "develop")
        self.git("switch", "-c", "side")
        self.commit("side first")
        self.commit("side second")
        self.git("switch", "main")
        self.commit("main first")
        self.git("merge", "--no-ff", "side", "-m", "merge side")
        head = self.git("rev-parse", "HEAD")
        self.git("switch", "develop")
        self.commit("base only")
        self.git("switch", "main")
        return initial, head

    def test_counts_all_reachable_commits_not_only_first_parents(self) -> None:
        _, head = self.divergent_merge()
        snapshot = self.snapshot()
        self.assertEqual(snapshot.branch, "main")
        self.assertEqual(snapshot.head, head)
        self.assertEqual(snapshot.base_ref, "develop")
        self.assertEqual((snapshot.ahead, snapshot.behind), (4, 1))
        self.assertEqual((snapshot.local_branches, snapshot.remote_branches), (3, 0))
        with self.assertRaises(FrozenInstanceError):
            snapshot.ahead = 0

    def test_first_parent_hides_merged_side_but_all_parents_includes_it(self) -> None:
        self.divergent_merge()
        snapshot = self.snapshot()
        first = self.graph(snapshot)
        full = self.graph(snapshot, first_parent=False)
        self.assertIn("merge side", first)
        self.assertIn("main first", first)
        self.assertNotIn("side first", first)
        self.assertNotIn("side second", first)
        self.assertIn("side first", full)
        self.assertIn("side second", full)
        self.assertIn("|", full)

    def test_compare_left_is_base_right_is_head_and_omits_common_history(self) -> None:
        self.divergent_merge()
        graph = self.graph(view=LogView.COMPARE, first_parent=False)
        self.assertRegex(graph, r"(?m)^.*<.*base only$")
        self.assertRegex(graph, r"(?m)^.*>.*main first$")
        self.assertIn("side first", graph)
        self.assertNotIn("initial history", graph)
        same = self.snapshot("HEAD")
        self.assertEqual((same.ahead, same.behind), (0, 0))
        self.assertEqual(self.graph(same, LogView.COMPARE), "")

    def test_all_view_includes_other_local_remote_and_tagged_history(self) -> None:
        initial = self.commit("initial")
        self.git("switch", "-c", "other")
        self.commit("other branch only")
        self.git("switch", "-c", "remote-fixture", initial)
        self.commit("cached remote only")
        self.git("update-ref", "refs/remotes/origin/topic", "HEAD")
        self.git("switch", "-c", "tag-fixture", initial)
        self.commit("tag only")
        self.git("tag", "archived")
        self.git("switch", "main")
        self.git("branch", "-D", "remote-fixture", "tag-fixture")
        branch = self.graph(first_parent=False)
        all_refs = self.graph(view=LogView.ALL, first_parent=False)
        for message in ("other branch only", "cached remote only", "tag only"):
            self.assertNotIn(message, branch)
            self.assertIn(message, all_refs)
        self.assertIn("origin/topic", all_refs)
        self.assertIn("tag: archived", all_refs)

    def test_limit_bounds_commits_and_literal_messages_have_no_color(self) -> None:
        self.commit("initial")
        self.commit("second")
        message = "[bold]literal[/bold] <tag> $HOME; `whoami` \\ path"
        self.commit(message)
        self.git("config", "color.ui", "always")
        self.git("config", "log.showSignature", "true")
        graph = self.graph(limit=1)
        self.assertIn(message, graph)
        self.assertNotIn("second", graph)
        self.assertNotIn("initial", graph)
        self.assertNotIn("\x1b[", graph)
        self.assertIn("HEAD -> main", graph)
        for limit in (0, -1, True, 1.5, "3"):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "positive integer"):
                self.graph(limit=limit)

    def test_native_color_styles_commit_hashes_refs_and_graph_lanes(self) -> None:
        self.divergent_merge()
        self.git("tag", "release")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("config", "color.ui", "never")
        self.git("config", "color.log", "false")
        snapshot = self.snapshot()
        graph = self.graph(snapshot, first_parent=False, color=True)
        styled = r"\x1b\[[0-9;]+m"
        reset = r"\x1b\[m"
        self.assertRegex(graph, styled + snapshot.head[:7] + reset)
        self.assertRegex(graph, styled + "main" + reset)
        self.assertRegex(graph, styled + "origin/main" + reset)
        self.assertRegex(graph, styled + "tag: release" + reset)
        self.assertRegex(graph, styled + r"[|/\\]" + reset)

    def test_color_strips_to_identical_plain_text_for_all_views_modes_and_limits(self) -> None:
        self.divergent_merge()
        message = "[red]café[/red] :smile: 世界 🐍 $HOME"
        self.commit(message)
        self.git("config", "color.ui", "always")
        self.git("config", "color.log", "always")
        self.git("config", "i18n.logOutputEncoding", "ISO-8859-1")
        snapshot = self.snapshot()
        for view in LogView:
            for first_parent in (True, False):
                for limit in (1, 30):
                    with self.subTest(view=view, first_parent=first_parent, limit=limit):
                        options = {"first_parent": first_parent, "limit": limit}
                        plain = self.graph(snapshot, view, **options)
                        explicit_plain = self.graph(snapshot, view, color=False, **options)
                        colored = self.graph(snapshot, view, color=True, **options)
                        self.assertNotIn("\x1b[", plain)
                        self.assertEqual(explicit_plain, plain)
                        self.assertIn("\x1b[", colored)
                        self.assertEqual(re.sub(r"\x1b\[[0-9;]*m", "", colored), plain)
                        if limit == 30:
                            self.assertIn(message, plain)
                            self.assertIn(message, colored)

    def test_default_prefers_local_develop_then_cached_origin_develop(self) -> None:
        initial = self.commit("initial")
        self.git("branch", "develop")
        newer = self.commit("new main")
        self.git("update-ref", "refs/remotes/origin/develop", newer)
        snapshot = self.snapshot()
        self.assertEqual((snapshot.base_ref, snapshot.base_sha), ("develop", initial))
        self.git("branch", "-D", "develop")
        snapshot = self.snapshot()
        self.assertEqual((snapshot.base_ref, snapshot.base_sha), ("origin/develop", newer))
        self.assertEqual((snapshot.ahead, snapshot.behind), (0, 0))

    def test_missing_default_is_not_fatal_or_a_false_zero(self) -> None:
        self.commit("initial")
        self.git("tag", "develop")  # The default must be a branch, not a same-name tag.
        snapshot = self.snapshot()
        self.assertIsNone(snapshot.base_ref)
        self.assertIsNone(snapshot.base_sha)
        self.assertIsNone(snapshot.ahead)
        self.assertIsNone(snapshot.behind)
        self.assertIn("initial", self.graph(snapshot))
        with self.assertRaisesRegex(HistoryError, "--base"):
            self.graph(snapshot, LogView.COMPARE)

    def test_explicit_short_base_prefers_local_then_origin_then_tag(self) -> None:
        initial = self.commit("initial")
        self.git("branch", "target")
        middle = self.commit("middle")
        self.git("update-ref", "refs/remotes/origin/target", middle)
        newest = self.commit("newest")
        self.git("tag", "target", newest)
        self.assertEqual(self.snapshot("target").base_sha, initial)
        self.assertEqual(self.snapshot("origin/target").base_sha, middle)
        self.assertEqual(self.snapshot("refs/tags/target").base_sha, newest)
        self.git("branch", "-D", "target")
        snapshot = self.snapshot("target")
        self.assertEqual((snapshot.base_ref, snapshot.base_sha), ("origin/target", middle))
        self.git("update-ref", "-d", "refs/remotes/origin/target")
        self.assertEqual(self.snapshot("target").base_sha, newest)

    def test_explicit_pseudo_refs_and_revisions_do_not_follow_origin_head(self) -> None:
        initial = self.commit("initial")
        middle = self.commit("middle")
        head = self.commit("current head")
        self.git("update-ref", "refs/remotes/origin/develop", middle)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
        self.git("update-ref", "ORIG_HEAD", initial)
        self.git("update-ref", "refs/remotes/origin/ORIG_HEAD", middle)
        for ref, expected in (("HEAD", head), ("@", head), ("HEAD~1", middle), ("HEAD^", middle), ("ORIG_HEAD", initial)):
            with self.subTest(ref=ref):
                snapshot = self.snapshot(ref)
                self.assertEqual(snapshot.base_ref, ref)
                self.assertEqual(snapshot.base_sha, expected)
        self.assertEqual((self.snapshot("HEAD").ahead, self.snapshot("HEAD").behind), (0, 0))

    def test_remote_qualified_base_is_not_prefixed_with_origin_again(self) -> None:
        initial = self.commit("initial")
        middle = self.commit("middle")
        head = self.commit("current head")
        for remote in ("origin", "upstream"):
            ref = f"{remote}/topic"
            self.git("update-ref", f"refs/remotes/{ref}", middle)
            self.git("update-ref", f"refs/remotes/origin/{ref}", initial)
            with self.subTest(ref=ref):
                snapshot = self.snapshot(ref)
                self.assertEqual((snapshot.base_ref, snapshot.base_sha), (ref, middle))
        self.git("branch", "origin/topic", head)
        self.assertEqual(self.snapshot("origin/topic").base_sha, head)

    def test_log_output_is_utf8_even_with_other_git_output_encoding(self) -> None:
        message = "fix: café déjà vu"
        self.commit(message)
        self.git("config", "i18n.logOutputEncoding", "ISO-8859-1")
        self.assertIn(message, self.graph())
        self.commit("fix: display 世界 and 🐍")
        self.assertIn("fix: display 世界 and 🐍", self.graph())

    def test_explicit_annotated_tag_hash_and_fully_qualified_refs(self) -> None:
        initial = self.commit("initial")
        self.git("tag", "-a", "baseline", "-m", "baseline annotation")
        self.git("update-ref", "refs/remotes/upstream/main", initial)
        self.commit("new main")
        for ref in (initial, initial[:8], "baseline", "refs/tags/baseline", "refs/heads/main", "refs/remotes/upstream/main"):
            with self.subTest(ref=ref):
                snapshot = self.snapshot(ref)
                self.assertEqual(snapshot.base_ref, ref)
                expected = snapshot.head if ref == "refs/heads/main" else initial
                self.assertEqual(snapshot.base_sha, expected)

    def test_invalid_refs_ranges_files_trees_and_options_raise(self) -> None:
        self.commit("initial")
        (self.root / "exists-only-as-file").write_text("not a ref", encoding="utf-8")
        tree = self.git("rev-parse", "HEAD^{tree}")
        (self.root / "tracked").write_text("blob", encoding="utf-8")
        self.git("add", "tracked")
        self.git("commit", "-m", "tracked")
        blob = self.git("rev-parse", "HEAD:tracked")
        for base in ("missing", "", "--all", "--output=pwned", "HEAD..HEAD", "HEAD...HEAD", "bad ref", "HEAD\n", "bad\0ref", "exists-only-as-file", tree, blob):
            with self.subTest(base=base), self.assertRaisesRegex(HistoryError, "[Bb]ase"):
                self.snapshot(base)
        self.assertFalse((self.root / "pwned").exists())

    def test_filename_collisions_do_not_become_path_filters(self) -> None:
        self.commit("initial")
        self.git("branch", "develop")
        (self.root / "develop").write_text("untracked", encoding="utf-8")
        (self.root / "main").write_text("untracked", encoding="utf-8")
        self.commit("empty commit must still appear")
        self.assertIn("empty commit must still appear", self.graph(self.snapshot("develop")))

    def test_remote_head_alias_does_not_count_as_a_remote_branch(self) -> None:
        head = self.commit("initial")
        self.git("update-ref", "refs/remotes/origin/main", head)
        self.git("update-ref", "refs/remotes/origin/develop", head)
        self.git("update-ref", "refs/remotes/upstream/main", head)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("symbolic-ref", "refs/remotes/upstream/HEAD", "refs/remotes/upstream/main")
        snapshot = self.snapshot()
        self.assertEqual((snapshot.local_branches, snapshot.remote_branches), (1, 3))

    def test_detached_head_is_named_and_rendered_without_switching(self) -> None:
        initial = self.commit("initial")
        self.commit("new main")
        self.git("switch", "--detach", initial)
        snapshot = self.snapshot()
        self.assertIn("detached", snapshot.branch.lower())
        self.assertIn(initial[:7], snapshot.branch)
        self.assertEqual(snapshot.head, initial)
        self.assertNotIn("new main", self.graph(snapshot))
        self.assertEqual(self.git("rev-parse", "HEAD"), initial)

    def test_unborn_and_empty_views_succeed_with_unknown_counts(self) -> None:
        snapshot = self.snapshot()
        self.assertIn("main", snapshot.branch)
        self.assertIn("unborn", snapshot.branch.lower())
        self.assertIsNone(snapshot.head)
        self.assertEqual((snapshot.ahead, snapshot.behind), (None, None))
        self.assertEqual((snapshot.local_branches, snapshot.remote_branches), (0, 0))
        self.assertEqual(self.graph(snapshot), "")
        self.assertEqual(self.graph(snapshot, LogView.ALL), "")
        with self.assertRaisesRegex(HistoryError, "base"):
            self.graph(snapshot, LogView.COMPARE)
        with self.assertRaisesRegex(HistoryError, "base"):
            self.snapshot("missing")

    def test_unborn_head_can_still_show_other_refs_in_all_view(self) -> None:
        initial = self.commit("existing branch")
        self.git("switch", "--orphan", "unborn")
        snapshot = self.snapshot("main")
        self.assertEqual(snapshot.base_sha, initial)
        self.assertIsNone(snapshot.head)
        self.assertEqual((snapshot.ahead, snapshot.behind), (None, None))
        self.assertEqual(self.graph(snapshot), "")
        self.assertEqual(self.graph(snapshot, LogView.COMPARE), "")
        self.assertIn("existing branch", self.graph(snapshot, LogView.ALL))

    def test_not_a_repo_missing_git_bad_cwd_and_timeout_are_actionable(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        # A nested directory would still discover this repo, so explicitly disable discovery.
        with patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.root)}):
            with self.assertRaisesRegex(HistoryError, "not a git repository"):
                history_snapshot(cwd=outside)
        with patch("git_tools.history.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(HistoryError, "Git is installed"):
                self.snapshot()
        with self.assertRaisesRegex(HistoryError, "working directory"):
            history_snapshot(cwd=self.root / "missing")
        with patch("git_tools.history.subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 30)):
            with self.assertRaisesRegex(HistoryError, "timed out"):
                self.snapshot()

    def test_partial_clone_missing_objects_fail_without_lazy_fetch_or_writes(self) -> None:
        parent = self.commit("missing parent")
        self.commit("available child")
        self.git("config", "remote.origin.url", str(self.root / "nonexistent-remote"))
        self.git("config", "remote.origin.promisor", "true")
        self.git("config", "extensions.partialClone", "origin")
        (self.root / ".git/objects" / parent[:2] / parent[2:]).unlink()
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch.dict(os.environ, {"GIT_TRACE": "1"}):
            snapshot = self.snapshot()
            for color in (False, True):
                with self.subTest(color=color), self.assertRaises(HistoryError) as error:
                    self.graph(snapshot, color=color)
                self.assertIn("lazy fetching disabled", str(error.exception))
                self.assertNotIn("run_command: git fetch", str(error.exception))
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_snapshot_graphs_use_shas_even_after_branches_move(self) -> None:
        initial = self.commit("initial")
        self.git("branch", "develop")
        head = self.commit("original head")
        snapshot = self.snapshot()
        self.git("branch", "-f", "develop", head)
        self.commit("later head")
        branch = self.graph(snapshot)
        compare = self.graph(snapshot, LogView.COMPARE)
        self.assertIn("original head", branch)
        self.assertNotIn("later head", branch)
        self.assertIn("original head", compare)
        self.assertNotIn("later head", compare)
        self.assertEqual(snapshot.base_sha, initial)
        self.assertEqual((snapshot.ahead, snapshot.behind), (1, 0))

    def test_every_view_preserves_git_metadata_index_and_worktree(self) -> None:
        self.divergent_merge()
        (self.root / "staged").write_text("staged version", encoding="utf-8")
        self.git("add", "staged")
        (self.root / "staged").write_text("working version", encoding="utf-8")
        (self.root / "untracked").write_text("user work", encoding="utf-8")

        def state():
            return {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

        before = state()
        actual_run = subprocess.run
        with patch("git_tools.history.subprocess.run", wraps=actual_run) as run:
            snapshot = self.snapshot()
            for view in LogView:
                for color in (False, True):
                    self.graph(snapshot, view, color=color)
                    self.graph(snapshot, view, first_parent=False, color=color)
        self.assertEqual(state(), before)
        for call in run.call_args_list:
            argv = call.args[0]
            self.assertIsInstance(argv, list)
            self.assertNotIn("shell", call.kwargs)
            self.assertEqual(argv[:2], ["git", "--no-pager"])
            self.assertIn(argv[2], {"rev-parse", "symbolic-ref", "for-each-ref", "rev-list", "log"})
            self.assertEqual(call.kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(call.kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
            if argv[2] in {"rev-parse", "rev-list", "log"} and "--git-dir" not in argv:
                self.assertIn("--end-of-options", argv)
            if argv[2] in {"rev-list", "log"}:
                self.assertEqual(argv[-1], "--")


if __name__ == "__main__":
    unittest.main()
