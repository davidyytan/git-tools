"""Exercise the installer with fake commands; never install a real tool."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install.sh"


@unittest.skipUnless(shutil.which("bash"), "installer requires Bash")
class InstallScriptTests(unittest.TestCase):
    def run_fake_installer(self, *args: str, uv_status: int = 0, include_git_tools: bool = True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            caller = root / "unrelated working directory"
            caller.mkdir()
            home = root / "home"
            home.mkdir()
            capture = root / "calls.jsonl"
            fake = (
                f"#!{sys.executable}\n"
                "import json, os, pathlib, sys\n"
                "with open(os.environ['INSTALL_TEST_CAPTURE'], 'a') as stream:\n"
                "    stream.write(json.dumps({'command': pathlib.Path(sys.argv[0]).name, "
                "'args': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n"
                "sys.exit(int(os.environ.get('INSTALL_TEST_UV_STATUS', '0')) "
                "if pathlib.Path(sys.argv[0]).name == 'uv' else 0)\n"
            )
            for name in ("uv", "git-tools") if include_git_tools else ("uv",):
                path = commands / name
                path.write_text(fake)
                path.chmod(0o755)
            # Minimal PATH prevents using real uv/git-tools or user startup files.
            env = {"PATH": f"{commands}:/usr/bin:/bin", "HOME": str(home),
                   "XDG_CONFIG_HOME": str(home / ".config"), "LC_ALL": "C.UTF-8",
                   "INSTALL_TEST_CAPTURE": str(capture), "INSTALL_TEST_UV_STATUS": str(uv_status)}
            result = subprocess.run([str(SCRIPT), *args], cwd=caller, env=env,
                                    text=True, capture_output=True, timeout=15)
            calls = [json.loads(line) for line in capture.read_text().splitlines()] if capture.exists() else []
            return result, calls

    def test_installer_is_executable_and_root_script_is_relocated(self):
        self.assertTrue(SCRIPT.is_file())
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertFalse((ROOT / "install.sh").exists())

    def test_unrelated_cwd_installs_checkout_and_forwards_arguments_then_completion(self):
        result, calls = self.run_fake_installer("--reinstall", "--with", "example-package==1.0", "value with spaces")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(calls, [
            {"command": "uv", "args": ["tool", "install", "-e", ".", "--reinstall", "--with", "example-package==1.0", "value with spaces"],
             "cwd": str(ROOT)},
            {"command": "git-tools", "args": ["--install-completion"], "cwd": str(ROOT)},
        ])
        self.assertIn("Restart your shell", result.stdout)

    def test_uv_failure_stops_without_completion(self):
        result, calls = self.run_fake_installer("--reinstall", uv_status=17)
        self.assertEqual(result.returncode, 17)
        self.assertEqual([call["command"] for call in calls], ["uv"])
        self.assertNotIn("Installed git-tools.", result.stdout)

    def test_missing_git_tools_keeps_path_and_completion_guidance(self):
        result, calls = self.run_fake_installer(include_git_tools=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual([call["command"] for call in calls], ["uv"])
        self.assertIn("git-tools is not on PATH", result.stderr)
        self.assertIn("uv tool update-shell", result.stderr)
        self.assertIn("git-tools --install-completion", result.stderr)


if __name__ == "__main__":
    unittest.main()
