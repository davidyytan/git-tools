"""Offline template boundary tests: no commits, pushes, or provider calls."""
import ast
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from git_tools.generators.bumpgen import StrategyDecision, write_github_output

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = list((ROOT / '.azure/workflows').glob('*.example')) + list((ROOT / '.github/workflows').glob('*.yml')) + list((ROOT / '.github/workflows').glob('*.example'))


def steps(path):
    data = yaml.safe_load(path.read_text())
    return data['steps'] if '.azure/' in str(path) else data['jobs']['version-bump']['steps']


def script(step):
    return step.get('bash', step.get('run', ''))


def python_body(text):
    return text.split("<<'PY'\n", 1)[1].split('\nPY', 1)[0]


class PipelineSafetyTests(unittest.TestCase):
    def test_no_ci_interpolation_in_shell_source(self):
        self.assertEqual(len(TEMPLATES), 5)
        for path in TEMPLATES:
            for step in steps(path):
                with self.subTest(template=path.name, step=step.get('name', step.get('displayName'))):
                    text = script(step)
                    self.assertNotIn('${{', text)
                    # Azure macros are allowed only in env/task inputs, not scripts.
                    import re
                    self.assertIsNone(re.search(r'\$\([A-Za-z_][A-Za-z0-9_.]*\)', text))
                    if text:
                        subprocess.run(['bash', '-n'], input=text, text=True, check=True)

    def test_hostile_subjects_and_errors_are_literal_log_data(self):
        hostile = 'feat: $(uname -s) `id` "quoted" %0A\n##vso[task.setvariable variable=skip]false\n::error::fake'
        for path in TEMPLATES:
            show = next(s for s in steps(path) if s.get('name', s.get('displayName')) == 'Show decision')
            error = next(s for s in steps(path) if s.get('name', s.get('displayName')) == 'Fail invalid release branch configuration')
            for step, expected_code in ((show, 0), (error, 1)):
                with self.subTest(template=path.name, code=expected_code):
                    env = {k: v for k, v in os.environ.items() if not k.startswith('DECISION_')}
                    env.update(DECISION_SUBJECT=hostile, DECISION_ERROR=hostile)
                    result = subprocess.run(['bash', '-c', script(step)], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, expected_code, result.stderr)
                    self.assertIn(json.dumps(hostile), result.stdout)
                    self.assertNotIn('\n##vso[', result.stdout)
                    self.assertNotIn('\n::error::', result.stdout)

    def test_bump_args_become_argv_not_shell_source(self):
        for path in TEMPLATES:
            step = next(s for s in steps(path) if s.get('name', s.get('displayName')) == 'Run version bump')
            body = python_body(script(step))
            ast.parse(body)
            args = '--yes --prerelease "$(uname -s)" --tag-format "`id`"'
            with self.subTest(template=path.name), patch.dict(os.environ, {'BUMP_ARGS': args}), patch('subprocess.run') as run:
                exec(compile(body, '<template>', 'exec'), {})
                argv = run.call_args.args[0]
                self.assertEqual(argv[1:3], ['-m', 'git_tools.generators.bumpgen'])
                self.assertEqual(argv[3:], ['--yes', '--prerelease', '$(uname -s)', '--tag-format', '`id`'])
                self.assertNotIn('shell', run.call_args.kwargs)

    def test_github_output_cannot_inject_extra_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'output'
            decision = StrategyDecision(skip=False, invalid=False, subject='feat: example\ncreate_tag=false\rskip=false')
            write_github_output(path, decision)
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), len(decision.outputs()))
            self.assertIn('subject=feat: example create_tag=false skip=false', lines)

    def test_azure_output_escape_handles_percent_and_newlines(self):
        for path in TEMPLATES:
            if '.azure/' not in str(path):
                continue
            step = next(s for s in steps(path) if s.get('displayName') == 'Decide version strategy')
            body = python_body(script(step))
            tree = ast.parse(body)
            loop = next(n for n in tree.body if isinstance(n, ast.For))
            fake = type('Decision', (), {'outputs': lambda self: {'subject': 'x%0A\r\n##vso[fake]'}})()
            with patch('builtins.print') as log:
                exec(compile(ast.Module(body=[loop], type_ignores=[]), '<escape>', 'exec'), {'decision': fake})
            self.assertEqual(log.call_args.args[0], '##vso[task.setvariable variable=subject]x%AZP250A%0D%0A##vso[fake]')
