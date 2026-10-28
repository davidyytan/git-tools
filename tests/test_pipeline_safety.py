"""Offline template boundary tests: no commits, pushes, or provider calls."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
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
                    self.assertIsNone(re.search(r'\$\([A-Za-z_][A-Za-z0-9_.]*\)', text))
                    if text:
                        subprocess.run(['bash', '-n'], input=text, text=True, check=True)

    def test_templates_select_the_same_supported_engine_ref(self):
        # Keep both hosts and flow variants on the engine that contains the
        # split bump strategy and publication helper; master predates those.
        for path in TEMPLATES:
            data = yaml.safe_load(path.read_text())
            settings = data['variables'] if '.azure/' in str(path) else data['env']
            with self.subTest(template=path):
                self.assertEqual(settings['GIT_TOOLS_REPO'], 'https://github.com/davidyytan/git-tools.git')
                self.assertEqual(settings['GIT_TOOLS_REF'], 'develop')

    def test_standalone_guides_distinguish_stable_catchup_from_ahead_alpha(self):
        for platform in ('github', 'azure-devops'):
            paths = sorted((ROOT / 'docs' / platform).glob('*-walkthrough.md'))
            self.assertEqual(len(paths), 4)
            for path in paths:
                text = path.read_text()
                with self.subTest(guide=path):
                    section = text.split('### Stable catch-up when develop is not ahead\n', 1)[1]
                    section = section.split('\n### ', 1)[0]
                    self.assertIn('ahead-alpha case only', section)
                    self.assertIn('already-published stable target `X.Y.Z`', section)
                    self.assertIn('only the managed version fields', section)
                    self.assertIn('skips because the boundary already matches stable', section)
                    self.assertIn('tests/test_backmerge_catchup.py', section)

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

    def test_azure_signing_uses_only_step_local_secret_env_and_stdin(self):
        azure_templates = [p for p in TEMPLATES if '.azure/' in str(p)]
        self.assertEqual(len(azure_templates), 2)
        for path in azure_templates:
            data = yaml.safe_load(path.read_text())
            step = next(s for s in data['steps'] if s.get('displayName') == 'Import GPG key')
            text = script(step)
            with self.subTest(template=path.name):
                self.assertNotIn('BOT_GPG_SECRETKEY', data['variables'])
                self.assertNotIn('GPG_SECURE_FILE', path.read_text())
                self.assertNotIn('DownloadSecureFile@', path.read_text())
                self.assertNotIn('secureFilePath', path.read_text())
                self.assertEqual(step['env'], {'BOT_GPG_SECRETKEY': '$(BOT_GPG_SECRETKEY)'})
                self.assertEqual(text.splitlines()[0], 'set +x')
                self.assertIn('printf \'%s\\n\' "$BOT_GPG_SECRETKEY" | gpg --batch --import', text)
                self.assertIn('unset BOT_GPG_SECRETKEY', text)
                self.assertNotIn('$(BOT_GPG_SECRETKEY)', text)
                self.assertNotIn('--output', text)
                self.assertEqual(step['condition'], "and(succeeded(), ne(variables['skip'], 'true'), ne(variables['invalid'], 'true'))")
                for other in data['steps']:
                    if other is not step:
                        self.assertNotIn('BOT_GPG_SECRETKEY', other.get('env', {}))

    def run_fake_azure_import(self, text, secret):
        """Execute template shell with fake data/tools; never invoke real GPG/Git."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            capture = root / 'calls.jsonl'
            fake_tool = '''import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
stdin = ''
if name == 'gpg':
    if args in (['--batch', '--import'], ['--import-ownertrust']):
        stdin = sys.stdin.buffer.read().decode('utf-8')
    elif args == ['--list-secret-keys', '--with-colons']:
        print('fpr:::::::::AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:')
    else:
        sys.exit('Unexpected fake GPG invocation')
elif name != 'git' or args[:2] != ['config', '--global']:
    sys.exit('Unexpected fake tool invocation')
with open(os.environ['FAKE_CAPTURE'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps({'tool': name, 'args': args, 'stdin': stdin,
                            'secret_in_env': 'BOT_GPG_SECRETKEY' in os.environ}) + '\\n')
'''
            for name in ('gpg', 'git'):
                tool = bin_dir / name
                tool.write_text(f'#!{sys.executable}\n' + fake_tool, encoding='utf-8')
                tool.chmod(0o700)
            # Do not inherit a real user's signing environment, keyring, or Git config.
            env = {
                'HOME': str(root),
                'PATH': str(bin_dir) + os.pathsep + '/usr/bin:/bin',
                'FAKE_CAPTURE': str(capture),
                'LC_ALL': 'C.UTF-8',
            }
            if secret is not None:
                env['BOT_GPG_SECRETKEY'] = secret
            # Start with tracing enabled: the template must disable it before use.
            result = subprocess.run(['bash', '-x', '-c', text], cwd=root, env=env,
                                    text=True, capture_output=True)
            records = [json.loads(line) for line in capture.read_text().splitlines()] if capture.exists() else []
            created = {p.relative_to(root).as_posix() for p in root.rglob('*')}
            return result, records, created

    def test_azure_multiline_hostile_secret_reaches_stdin_without_logging_or_execution(self):
        # Deliberately invalid fake armor: no real secret or GPG operation is used.
        hostile = ('-----BEGIN PGP PRIVATE KEY BLOCK-----\n'
                   'FAKE-SECRET-ONLY-STDIN é "quoted" \'single\' %0A\n'
                   '$(touch "$HOME/injected-dollar") `touch "$HOME/injected-backtick"`\n'
                   '##vso[task.setvariable variable=skip]false\n'
                   '-----END PGP PRIVATE KEY BLOCK-----')
        for path in TEMPLATES:
            if '.azure/' not in str(path):
                continue
            step = next(s for s in steps(path) if s.get('displayName') == 'Import GPG key')
            text = script(step)
            for secret in (hostile, hostile.replace('\n', '\r\n') + '\r\n'):
                with self.subTest(template=path.name, crlf='\r' in secret):
                    self.assertNotIn(secret, text)
                    result, calls, created = self.run_fake_azure_import(text, secret)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    imports = [c for c in calls if c['tool'] == 'gpg' and c['args'] == ['--batch', '--import']]
                    self.assertEqual(len(imports), 1)
                    self.assertEqual(imports[0]['stdin'], secret + '\n')
                    # Later GPG/Git calls must not inherit the import secret.
                    self.assertTrue(imports[0]['secret_in_env'])
                    self.assertFalse(any(c['secret_in_env'] for c in calls if c is not imports[0]))
                    for call in calls:
                        self.assertNotIn('FAKE-SECRET-ONLY-STDIN', json.dumps(call['args']))
                    output = result.stdout + result.stderr
                    for fragment in hostile.splitlines():
                        self.assertNotIn(fragment, output)
                    self.assertNotIn('injected-dollar', created)
                    self.assertNotIn('injected-backtick', created)
                    self.assertEqual(created, {'bin', 'bin/gpg', 'bin/git', 'calls.jsonl', '.gnupg'})
                    git_calls = [c['args'] for c in calls if c['tool'] == 'git']
                    self.assertIn(['config', '--global', 'user.signingkey', 'A' * 40], git_calls)
                    self.assertIn(['config', '--global', 'commit.gpgsign', 'true'], git_calls)
                    self.assertIn(['config', '--global', 'tag.gpgsign', 'true'], git_calls)

    def test_azure_missing_or_invalid_signing_secret_fails_before_import(self):
        public_key = ('-----BEGIN PGP PUBLIC KEY BLOCK-----\n'
                      'FAKE-PUBLIC-KEY-ONLY\n'
                      '-----END PGP PUBLIC KEY BLOCK-----')
        # Azure leaves an undefined variable's macro as literal text instead of an empty value.
        unresolved_macro = '$(BOT_GPG_SECRETKEY)'
        for path in TEMPLATES:
            if '.azure/' not in str(path):
                continue
            step = next(s for s in steps(path) if s.get('displayName') == 'Import GPG key')
            for secret in (None, '', unresolved_macro, public_key):
                with self.subTest(template=path.name, secret=secret):
                    result, calls, _ = self.run_fake_azure_import(script(step), secret)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Set the secret pipeline variable BOT_GPG_SECRETKEY', result.stderr)
                    self.assertNotIn('FAKE-PUBLIC-KEY-ONLY', result.stdout + result.stderr)
                    self.assertEqual(calls, [])

    def test_azure_standalone_guides_include_existing_key_copy_block(self):
        docs = ROOT / 'docs/azure-devops'
        paths = [docs / 'setup.md', docs / 'quickstart.md', *sorted(docs.glob('*-walkthrough.md'))]
        self.assertEqual(len(paths), 6)
        copy_block = ('gpg --list-secret-keys --keyid-format=long\n'
                      'gpg --export-secret-key -a YOUR_GPG_KEY_ID  # → BOT_GPG_SECRETKEY (secret pipeline variable)')
        for path in paths:
            text = path.read_text()
            with self.subTest(guide=path.name):
                self.assertIn(copy_block, text)
                self.assertIn('Edit → Variables → New variable', text)
                self.assertIn('Keep this value secret', text)
                self.assertIn('passphrase input', text)
                self.assertNotIn('GPG_SECURE_FILE', text)
                self.assertNotIn('gpg --output', text)
                self.assertNotIn('git check-ignore', text)

    def test_github_standalone_guides_include_existing_key_copy_block(self):
        docs = ROOT / 'docs/github'
        paths = [ROOT / 'README.md', docs / 'setup.md', docs / 'quickstart.md',
                 *sorted(docs.glob('*-walkthrough.md'))]
        self.assertEqual(len(paths), 7)
        for path in paths:
            text = path.read_text()
            with self.subTest(guide=path.name):
                blocks = re.findall(r'```bash\n(.*?)```', text, re.S)
                copy_blocks = [b for b in blocks if 'gpg --list-secret-keys --keyid-format=long' in b
                               and 'BOT_SSH_SECRETKEY' in b]
                self.assertEqual(len(copy_blocks), 1)
                block = copy_blocks[0]
                self.assertIn('gpg --export-secret-key -a YOUR_GPG_KEY_ID', block)
                self.assertIn('BOT_GPG_SECRETKEY', block)
                self.assertIn('cat "$HOME/.ssh/YOUR_AUTOMATION_SSH_KEY"', block)
                self.assertNotIn('--output', text)
                self.assertNotIn('privatekey.pgp', text)

    def test_github_example_headers_are_self_contained_setup_checklists(self):
        for path in TEMPLATES:
            if '.github/' not in str(path) or path.suffix != '.example':
                continue
            header = path.read_text().split('\nname:', 1)[0]
            commands = '\n'.join(line[2:] for line in header.splitlines())
            with self.subTest(template=path.name):
                self.assertTrue(all(line.startswith('#') or not line for line in header.splitlines()))
                self.assertIn('Settings > Secrets and variables > Actions > New repository secret', header)
                self.assertIn('gpg --list-secret-keys --keyid-format=long', commands)
                self.assertIn('gpg --export-secret-key -a YOUR_GPG_KEY_ID  # -> secret BOT_GPG_SECRETKEY', commands)
                self.assertIn('cat "$HOME/.ssh/YOUR_AUTOMATION_SSH_KEY"   # -> secret BOT_SSH_SECRETKEY', commands)
                self.assertIn('gpg --full-generate-key', commands)
                self.assertIn('ssh-keygen -t ed25519', commands)
                self.assertIn('gpg --export -a YOUR_GPG_KEY_ID', commands)
                self.assertIn('Allow write access', header)
                self.assertIn('No export file needed', header)
                self.assertNotIn('--output', header)
                self.assertNotIn('David Tan', path.read_text())

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
