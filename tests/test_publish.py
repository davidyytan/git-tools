from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from git_tools.generators.publish import publish, PublishError


class PublishTests(unittest.TestCase):
    def result(self, code=0, error=""):
        return subprocess.CompletedProcess([], code, "", error)

    def test_atomic_success_uses_exact_refs(self):
        with patch("git_tools.generators.publish.checked", return_value="abc") as check, patch("git_tools.generators.publish.git", return_value=self.result()):
            publish(Path('.'), "develop", False)
            self.assertIn(((Path('.'), "push", "--atomic", "origin", "HEAD:refs/heads/develop"),), [(c.args,) for c in check.call_args_list])

    def test_only_unsupported_allows_fallback(self):
        for error in ("authentication failed", "connection timeout", "tag conflict"):
            with self.subTest(error=error), patch("git_tools.generators.publish.checked", return_value="abc") as check, patch("git_tools.generators.publish.git", return_value=self.result(1, error)):
                with self.assertRaises(PublishError):
                    publish(Path('.'), "develop", False)
                self.assertFalse(any(c.args[1] == "push" for c in check.call_args_list))

    def test_unsupported_falls_back_but_atomic_actual_failure_does_not(self):
        with patch("git_tools.generators.publish.checked", return_value="abc") as check, patch("git_tools.generators.publish.git", return_value=self.result(1, "fatal: the receiving end does not support --atomic push")):
            publish(Path('.'), "develop", False)
            self.assertEqual(check.call_args.args[1:], ("push", "origin", "HEAD:refs/heads/develop"))
        with patch("git_tools.generators.publish.checked", side_effect=["", "abc", PublishError("push failed")]) as check, patch("git_tools.generators.publish.git", return_value=self.result()):
            with self.assertRaises(PublishError):
                publish(Path('.'), "develop", False)
            self.assertEqual(check.call_count, 3)

    def test_atomic_publication_includes_only_expected_version_tag(self):
        config = SimpleNamespace(current_version="1.0.0", tag_format="$version")
        with patch("git_tools.generators.publish.load_bump_config", return_value=config), \
             patch("git_tools.generators.publish.normalize_tag", return_value="1.0.0"), \
             patch("git_tools.generators.publish.checked", side_effect=["", "abc", "", "abc", ""]) as check, \
             patch("git_tools.generators.publish.git", return_value=self.result()) as probe, \
             patch("builtins.print") as log:
            publish(Path('.'), "develop", True)
            refs = ("HEAD:refs/heads/develop", "refs/tags/1.0.0:refs/tags/1.0.0")
            probe.assert_called_once_with(Path('.'), "push", "--dry-run", "--atomic", "origin", *refs)
            self.assertEqual(check.call_args.args, (Path('.'), "push", "--atomic", "origin", *refs))
            self.assertTrue(any("Publish mode: atomic" in str(c.args) for c in log.call_args_list))

    def test_tag_not_pointing_at_head_is_rejected_before_probe(self):
        config = SimpleNamespace(current_version="1.0.0", tag_format="$version")
        with patch("git_tools.generators.publish.load_bump_config", return_value=config), \
             patch("git_tools.generators.publish.normalize_tag", return_value="1.0.0"), \
             patch("git_tools.generators.publish.checked", side_effect=["", "abc", "", "other"]), \
             patch("git_tools.generators.publish.git") as probe:
            with self.assertRaisesRegex(PublishError, "does not point to HEAD"):
                publish(Path('.'), "develop", True)
            probe.assert_not_called()

    def setup_repo(self, tmp):
        root=Path(tmp)/"repo";remote=Path(tmp)/"remote.git"
        root.mkdir()
        def run(*args):
            return subprocess.check_output(["git", *args],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()
        run("init", "-b", "develop");run("config","user.name","Test");run("config","user.email","test@example.invalid")
        (root/".cz.toml").write_text('[tool.commitizen]\nversion = "1.0.0"\ntag_format = "$version"\n')
        run("add",".");run("commit","-m","bump: version 0.9.0 → 1.0.0");run("tag","1.0.0")
        subprocess.check_call(["git","init","--bare",str(remote)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        run("remote","add","origin",str(remote))
        return root,remote,run

    def test_real_atomic_tag_rejection_leaves_neither_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,remote,run=self.setup_repo(tmp)
            hook=remote/"hooks"/"update";hook.write_text('#!/bin/sh\ncase "$1" in refs/tags/*) exit 1;; esac\nexit 0\n');hook.chmod(0o700)
            with self.assertRaises(PublishError):
                publish(root,"develop",True)
            self.assertEqual(run("ls-remote","origin"), "")

    def test_real_non_atomic_partial_failure_and_manual_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,remote,run=self.setup_repo(tmp)
            subprocess.check_call(["git","--git-dir",str(remote),"config","receive.advertiseAtomic","false"])
            hook=remote/"hooks"/"update";hook.write_text('#!/bin/sh\ncase "$1" in refs/tags/*) exit 1;; esac\nexit 0\n');hook.chmod(0o700)
            with self.assertRaisesRegex(PublishError,"Recovery required"):
                publish(root,"develop",True)
            self.assertIn("refs/heads/develop",run("ls-remote","origin"))
            self.assertNotIn("refs/tags/1.0.0",run("ls-remote","origin"))
            hook.unlink()
            publish(root,"develop",True,recover_tag=True)
            self.assertIn("refs/tags/1.0.0",run("ls-remote","origin"))
