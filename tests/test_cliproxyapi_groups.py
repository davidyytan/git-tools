"""CLIProxyAPI account groups in the model picker: agent-cli's window (tests/test_cliproxyapi_groups.py there), ported.

The group is chosen first and the model inside it; the window manages the proxy's groups and accounts through its management API. The fake proxy below is agent-cli's.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch

from rich.text import Text

from git_tools import cli, proxy_accounts
from git_tools.generators.base.transport import provider_request_options
from git_tools.providers.catalog import CatalogFetchResult, parse_model_catalog
from git_tools.providers.cliproxyapi import model_not_found_hint, split_model_group
from git_tools.settings import mappings
from git_tools.settings import settings as config

KEY = proxy_accounts.DEFAULT_KEY
BASE = "http://127.0.0.1:8317/v1"
# The proxy's /v1/models with agent-proxy's groups: each group's models as <group>/<model>.
GROUPED = {"object": "list", "data": [
    {"id": "personal/gpt-6.2-sol", "object": "model"},
    {"id": "personal/claude-opus-5-5", "object": "model"},
    {"id": "work/gpt-6.2-sol", "object": "model"},
    {"id": "work/gpt-6-luna", "object": "model"},
]}


def _result(payload) -> CatalogFetchResult:
    return CatalogFetchResult(entries=parse_model_catalog(payload), source="live", fetched_at="2026-11-25T00:00:00+00:00")


class FakeProxy:
    """CLIProxyAPI's management API as the window uses it: the accounts (whose group is only in their file), a group change, a log out, and a browser login finished by pasting the address the browser ended on."""

    def __init__(self, accounts=(), *, key=KEY, off=False, next_login=None):
        self.key = key
        self.off = off
        self.files = {}
        self.clock = 0
        for email, group, *provider in accounts:
            self.add(email, group, provider[0] if provider else "codex")
        self.next_login = next_login or ("new@example.test", "codex")
        self.calls = []
        self.state = None
        self.finished = False

    def add(self, email, group, provider="codex"):
        self.clock += 1
        name = f"{provider}-{email}.json"
        self.files[name] = {"type": provider, "email": email, "prefix": group, "access_token": "SECRET-TOKEN", "modtime": f"t{self.clock}"}
        return name

    def served(self):
        """What /v1/models serves: gpt-6.2-sol for each group with an account, plain for the accounts in no group."""
        ids = sorted({f"{item['prefix']}/gpt-6.2-sol" if item["prefix"] else "gpt-6.2-sol" for item in self.files.values()})
        return {"object": "list", "data": [{"id": model, "object": "model"} for model in ids]}

    def send(self, method, url, headers, body, timeout):
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        data = json.loads(body) if body else None
        path = parts.path.removeprefix("/v0/management/")
        self.calls.append((method, f"{parts.scheme}://{parts.netloc}", path, query, data))
        if self.off:
            return 404, b""
        if headers.get("Authorization") != f"Bearer {self.key}":
            return 401, b'{"error":"invalid management key"}'
        reply = self.handle(method, path, query, data)
        status = reply.pop("_status", 200)
        return status, json.dumps(reply).encode()

    def handle(self, method, path, query, data):
        if (method, path) == ("GET", "auth-files"):
            return {"files": [{"name": name, "email": item["email"], "provider": item["type"], "type": item["type"], "status": "active", "disabled": False, "modtime": item["modtime"]} for name, item in self.files.items()]}
        if (method, path) == ("GET", "auth-files/download"):
            item = self.files[query["name"]]
            return {"type": item["type"], "email": item["email"], "prefix": item["prefix"], "access_token": item["access_token"]}
        if (method, path) == ("PATCH", "auth-files/fields"):
            if data["name"] not in self.files:
                return {"_status": 404, "error": "auth file not found"}
            self.clock += 1
            self.files[data["name"]].update(prefix=data["prefix"], modtime=f"t{self.clock}")
            return {"status": "ok"}
        if (method, path) == ("DELETE", "auth-files"):
            self.files.pop(query["name"])
            return {"status": "ok"}
        if method == "GET" and path in ("codex-auth-url", "anthropic-auth-url"):
            self.state, self.finished = f"state-{len(self.calls)}", False
            return {"status": "ok", "url": f"https://sign-in.example/{path}?state={self.state}", "state": self.state}
        if (method, path) == ("POST", "oauth-callback"):
            pasted = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(data["redirect_url"]).query))
            if not pasted.get("state"):
                return {"_status": 400, "status": "error", "error": "state is required"}
            if pasted["state"] != self.state:
                return {"_status": 404, "status": "error", "error": "unknown or expired state"}
            email, provider = self.next_login
            name = f"{provider}-{email}.json"
            if name in self.files:  # logging in again rewrites the same file, without its group
                self.clock += 1
                self.files[name].update(prefix="", modtime=f"t{self.clock}")
            else:
                self.add(email, "", provider)
            self.finished = True
            return {"status": "ok"}
        if (method, path) == ("GET", "get-auth-status"):
            if query["state"] != self.state:
                return {"status": "error", "error": "unknown or expired state"}
            return {"status": "ok" if self.finished else "wait"}
        raise AssertionError(f"unexpected call {method} {path}")

    def group_of(self, email):
        return next(item["prefix"] for item in self.files.values() if item["email"] == email)

    def made(self, method, path):
        return [call for call in self.calls if call[0] == method and call[2] == path]


class Stub:
    """The window's pickers, answered in order. ``steps`` are (header part, label part) per picker: each picker must show the header part and picks the first label containing the label part (None is Esc). ``keys`` answer the masked prompts, ``lines`` the other typed prompts (answered in place, so a test can fill in an answer the proxy decides once it is known)."""

    def __init__(self, steps=(), *, lines=(), keys=("",)):
        self.steps, self.keys = list(steps), list(keys)
        self.lines = lines if isinstance(lines, list) else list(lines)
        self.shown, self.prompts, self.printed = [], [], []

    def pick(self, labels, *, header="", initial=0):
        header = proxy_accounts.plain(header)
        labels = [proxy_accounts.plain(label) for label in labels]
        self.shown.append((header, labels))
        assert self.steps, f"unexpected picker: {header} {labels}"
        part, choice = self.steps.pop(0)
        assert part in header, (part, header, labels)
        if choice is None:
            return None
        return next(index for index, label in enumerate(labels) if choice in label)

    def line(self, prompt, *, password=False, default=""):
        self.prompts.append(prompt)
        if password:
            # Esc on all groups goes back to the management key: once the scripted keys run out, that prompt is Esc too.
            return self.keys.pop(0) if self.keys else None
        assert self.lines, f"unexpected prompt: {prompt}"
        return self.lines.pop(0)

    def say(self, text):
        self.printed.append(Text.from_markup(text).plain)

    def show(self, text):
        self.printed.append(text)

    @property
    def pickers(self):
        return proxy_accounts.Pickers(pick=self.pick, line=self.line, say=self.say, show=self.show)

    @property
    def text(self):
        return "\n".join(self.printed)

    def done(self, case: unittest.TestCase):
        case.assertFalse(self.steps, f"pickers not shown: {self.steps}")
        case.assertFalse(self.lines, f"prompts not shown: {self.lines}")


def sign_in_address(proxy, *earlier, during=None):
    """The typed answers: ``earlier`` ones, then the address the browser ended on, filled in once the proxy has started the sign-in; ``during`` runs as the login lands (a token refresh, say)."""
    lines = [*earlier, "PLACEHOLDER"]
    original = proxy.handle

    def handle(method, path, query, data):
        if path == "oauth-callback" and during:
            during()
        reply = original(method, path, query, data)
        if path in ("codex-auth-url", "anthropic-auth-url"):
            port, route = ("1455", "auth/callback") if path == "codex-auth-url" else ("54545", "callback")
            lines[-1] = f"http://localhost:{port}/{route}?code=c&state={proxy.state}"
        return reply

    proxy.handle = handle
    return lines


def refresh_tokens(proxy, email):
    """What the proxy does to a file every 15 minutes: new tokens, so a new modification time; its group stays."""
    proxy.clock += 1
    next(item for item in proxy.files.values() if item["email"] == email)["modtime"] = f"t{proxy.clock}"


class IsolatedSettings(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.user = self.root / "settings.env"
        for patcher in (
            patch.dict(os.environ, {}, clear=True),
            patch.object(config, "DEFAULT_SETTINGS_PATH", self.user),
            patch.object(config, "_get_env_file_paths", return_value=[self.root / "git-tools.env", self.user]),
            patch.object(proxy_accounts, "SETTLE_SECONDS", 0),
            patch.object(proxy_accounts, "LOGIN_POLL_SECONDS", 0),
            patch.object(proxy_accounts, "LOGIN_WAIT_SECONDS", 0),
            patch.dict(proxy_accounts._KEYS_IN_USE, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def proxy(self, **kwargs) -> FakeProxy:
        fake = FakeProxy(**kwargs)
        patcher = patch.object(proxy_accounts, "_send", fake.send)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def with_groups(self, *groups, management_key=None):
        updates = {proxy_accounts.GROUPS_ENV: ",".join(groups) or None}
        if management_key:
            updates[proxy_accounts.KEY_ENV] = management_key
        config.save_settings(updates)

    def saved(self, field):
        return proxy_accounts.load_entry()[field]

    def drive(self, stub: Stub, *, proxy: FakeProxy | None = None, current_model="gpt-6.2-sol", catalog=None, base_url=BASE):
        """Run the CLIProxyAPI picker (management key, window, model) as the Main Model row does; returns the chosen model."""
        fetch = catalog or (lambda: _result(proxy.served() if proxy else GROUPED))
        model = proxy_accounts.choose_model(
            base_url=base_url, entry=proxy_accounts.load_entry(), current_model=current_model,
            catalog=fetch(), refetch=fetch, pickers=stub.pickers,
        )
        stub.done(self)
        return model


class GroupThenModelTests(IsolatedSettings):
    def test_the_group_is_picked_then_a_model_inside_it(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("you@example.test", "work")])
        stub = Stub([("account group", "work"), ("· group work", "models…"), ("main model · group work", "gpt-6-luna")])
        model = self.drive(stub, proxy=proxy, catalog=lambda: _result(GROUPED))
        self.assertEqual(model, "work/gpt-6-luna")
        group_header, group_labels = stub.shown[0]
        self.assertIn("main account group", group_header)
        # All groups: the groups, then create a group and a typed model id.
        self.assertEqual([label.split(" ·")[0] for label in group_labels[:2]], ["personal", "work"])
        self.assertEqual(group_labels[1], "work · 1 account: you@example.test · 2 models")
        self.assertTrue(group_labels[-2].startswith("create a group…"))
        self.assertTrue(group_labels[-1].startswith("type a model id"))
        level_header, level_labels = stub.shown[1]
        self.assertTrue(level_header.startswith("cliproxyapi · main · group work"))
        self.assertEqual([label.split(" ·")[0] for label in level_labels], ["models…", "accounts…", "all groups…", "delete group…"])
        # Inside the group, the models are shown without it; the header names it.
        model_header, model_labels = stub.shown[2]
        self.assertIn("group work", model_header)
        self.assertEqual(sorted(model_labels[:2]), ["gpt-6-luna", "gpt-6.2-sol"])
        self.assertFalse(any(label.startswith(("personal/", "work/")) for label in model_labels))
        self.assertEqual(model_labels[-1], "(type a model id manually)")
        # The management key prompt, as agent-cli asks it: blank is agent-proxy's default.
        self.assertEqual(stub.prompts, ["cliproxyapi management key (blank = cliproxyapi_sEcr3Tk3Y)> "])

    def test_a_model_typed_inside_a_group_gets_the_group(self):
        proxy = self.proxy(accounts=[("you@example.test", "work")])
        stub = Stub([("account group", "work"), ("· group work", "models…"), ("main model · group work", "(type a model id manually)")], lines=["gpt-7-preview"])
        self.assertEqual(self.drive(stub, proxy=proxy), "work/gpt-7-preview")

    def test_a_proxy_without_groups_offers_the_models_of_the_accounts_in_no_group(self):
        proxy = self.proxy(accounts=[("old@example.test", "")])
        bare = {"object": "list", "data": [{"id": "gpt-6.2-sol"}, {"id": "gpt-6-luna"}]}
        stub = Stub([("account group", "(no group)"), ("· no group", "models…"), ("main model", "gpt-6-luna")])
        model = self.drive(stub, proxy=proxy, catalog=lambda: _result(bare))
        self.assertTrue(stub.shown[0][1][0].startswith("(no group) · 2 models"))
        self.assertNotIn("group", stub.shown[2][0].split("\n")[0])
        self.assertEqual(model, "gpt-6-luna")

    def test_esc_on_the_model_list_goes_back_to_its_group_not_out(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("you@example.test", "work")])
        steps = [
            ("account group", "work"), ("· group work", "models…"), ("main model · group work", None),
            ("· group work", "all groups…"), ("account group", "personal"), ("· group personal", "models…"),
            ("main model · group personal", "gpt-6.2-sol"),
        ]
        stub = Stub(steps)
        self.assertEqual(self.drive(stub, proxy=proxy), "personal/gpt-6.2-sol")
        # The management key was asked once, and the accounts were not re-read for the step back.
        self.assertEqual(len([prompt for prompt in stub.prompts if "management key" in prompt]), 1)
        self.assertEqual(len(proxy.made("GET", "auth-files")), 1)

    def test_esc_on_all_groups_goes_back_to_the_management_key(self):
        proxy = self.proxy(accounts=[("you@example.test", "work")])
        stub = Stub([("account group", None), ("account group", "work"), ("· group work", "models…"), ("main model · group work", "gpt-6.2-sol")], keys=["", ""])
        self.assertEqual(self.drive(stub, proxy=proxy), "work/gpt-6.2-sol")
        self.assertEqual([prompt for prompt in stub.prompts if "management key" in prompt], ["cliproxyapi management key (blank = cliproxyapi_sEcr3Tk3Y)> "] * 2)

    def test_back_from_the_next_step_reopens_the_groups_model_list(self):
        proxy = self.proxy(accounts=[("you@example.test", "work")])
        self.drive(Stub([("account group", "work"), ("· group work", "models…"), ("main model · group work", "gpt-6.2-sol")]), proxy=proxy)
        # As the wizard does when Esc on the effort step goes back: no management key, straight to the group's list.
        stub = Stub([("main model · group work", None), ("· group work", "models…"), ("main model · group work", "gpt-6.2-sol")], keys=[])
        model = proxy_accounts.choose_model(base_url=BASE, entry=proxy_accounts.load_entry(), current_model="work/gpt-6.2-sol",
                                            catalog=_result(proxy.served()), refetch=lambda: _result(proxy.served()), pickers=stub.pickers, resume=True)
        self.assertEqual(model, "work/gpt-6.2-sol")
        self.assertFalse([prompt for prompt in stub.prompts if "management key" in prompt])

    def test_esc_on_a_typed_model_id_goes_back_to_all_groups(self):
        proxy = self.proxy(accounts=[("you@example.test", "work")])
        stub = Stub([("account group", "type a model id"), ("account group", None)], lines=[None])
        self.assertIsNone(self.drive(stub, proxy=proxy))

    def test_the_current_model_comes_first_marked_current(self):
        proxy = self.proxy(accounts=[("you@example.test", "work")])
        stub = Stub([("· group work", "models…"), ("main model · group work", "gpt-6-luna")])
        self.drive(stub, proxy=proxy, current_model="work/gpt-6-luna", catalog=lambda: _result(GROUPED))
        self.assertEqual(stub.shown[1][1][0], "gpt-6-luna (current)")


class WindowTests(IsolatedSettings):
    def test_all_groups_shows_each_group_with_its_accounts_and_models(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("old@example.test", "")])
        self.with_groups("personal", "work")
        stub = Stub([("account group", None)])
        self.assertIsNone(self.drive(stub, proxy=proxy))
        labels = stub.shown[0][1]
        self.assertEqual(labels[0], "personal · 1 account: me@example.test · 1 model")
        self.assertTrue(labels[1].startswith("(no group) · 1 model on the accounts in no group (old@example.test); move them into a group"))
        self.assertEqual([label.split(" ·")[0] for label in labels[2:]], ["create a group…", "type a model id…"])
        # The proxy is the truth: "work" has no account there, so it left git-tools' list too.
        self.assertEqual(self.saved("account_groups"), ["personal"])
        # The window talked to the proxy at the provider's address, never to a folder or a script.
        self.assertEqual({call[1] for call in proxy.calls}, {"http://127.0.0.1:8317"})
        self.assertEqual({(call[0], call[2]) for call in proxy.calls}, {("GET", "auth-files"), ("GET", "auth-files/download")})
        # An account file's tokens are read for its group only, and never shown.
        self.assertNotIn("SECRET-TOKEN", stub.text)

    def test_a_proxy_on_another_machine_is_reached_at_its_address(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal")])
        self.drive(Stub([("account group", None)]), proxy=proxy, base_url="http://192.168.1.20:9000/v1")
        self.assertEqual({call[1] for call in proxy.calls}, {"http://192.168.1.20:9000"})

    def test_a_group_the_proxy_no_longer_has_leaves_git_tools(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("you@example.test", "work")])
        self.with_groups("personal", "work")
        self.drive(Stub([("account group", None)]), proxy=proxy)
        self.assertEqual(self.saved("account_groups"), ["personal", "work"])
        # work's account was logged out somewhere else (another machine, agent-proxy's scripts): next time, work is gone.
        proxy.files.pop("codex-you@example.test.json")
        stub = Stub([("account group", None)])
        self.drive(stub, proxy=proxy)
        self.assertEqual([label.split(" ·")[0] for label in stub.shown[0][1]], ["personal", "create a group…", "type a model id…"])
        self.assertEqual(self.saved("account_groups"), ["personal"])

    def test_nothing_is_pruned_when_the_accounts_cannot_be_read(self):
        proxy = self.proxy(off=True)
        self.with_groups("personal", "work")
        stub = Stub([("account group", None)])
        self.drive(stub, proxy=proxy, catalog=CatalogFetchResult)  # an empty model list: the rows can come only from the saved list
        # Unknown is not empty: the list stays as it was.
        self.assertEqual(self.saved("account_groups"), ["personal", "work"])
        self.assertEqual([label.split(" ·")[0] for label in stub.shown[0][1][:2]], ["personal", "work"])

    def test_an_address_that_does_not_speak_http_is_reported_not_a_crash(self):
        import http.client

        self.with_groups("personal")

        def ssh_port(method, url, headers, body, timeout):
            raise http.client.BadStatusLine("SSH-2.0-OpenSSH_9.6")

        with patch.object(proxy_accounts, "_send", ssh_port):
            stub = Stub([("account group", None)])
            self.drive(stub)
        self.assertTrue(any("accounts could not be read" in line and "did not answer" in line for line in stub.printed))
        self.assertEqual(self.saved("account_groups"), ["personal"])

    def test_a_web_page_at_the_address_is_never_read_as_no_accounts(self):
        for reply in (b"<!doctype html><title>login</title>", b'{"hello": "world"}'):
            with self.subTest(reply=reply):
                self.with_groups("personal", "work")
                with patch.object(proxy_accounts, "_send", lambda method, url, headers, body, timeout, reply=reply: (200, reply)):
                    stub = Stub([("account group", None)])
                    self.drive(stub)
                self.assertTrue(any("CLIProxyAPI" in line and "check the address" in line for line in stub.printed), reply)
                # Not the proxy's answer, so nothing is pruned.
                self.assertEqual(self.saved("account_groups"), ["personal", "work"])

    def test_with_no_groups_the_choice_is_to_create_one(self):
        proxy = self.proxy()
        stub = Stub([("account group", None)])
        self.drive(stub, proxy=proxy)
        header, labels = stub.shown[0]
        self.assertEqual([label.split(" ·")[0] for label in labels], ["create a group…", "type a model id…"])
        self.assertIn("No account groups yet: create one", header)

    def test_a_current_model_in_a_group_opens_on_that_group(self):
        proxy = self.proxy(accounts=[("me@example.test", "work"), ("you@example.test", "personal")])
        self.with_groups("personal", "work")
        stub = Stub([("· group work", "all groups…"), ("account group", "personal"), ("· group personal", None), ("account group", None)])
        self.drive(stub, proxy=proxy, current_model="work/gpt-6.2-sol")
        header, labels = stub.shown[0]
        # Straight into the group the current model runs on: its models (with the current one), its accounts, all groups, delete.
        self.assertTrue(header.startswith("cliproxyapi · main · group work"))
        self.assertEqual(labels, ["models… · 1 model · now gpt-6.2-sol", "accounts… · 1 account: me@example.test", "all groups…", "delete group… · logs out its accounts"])
        self.assertTrue(stub.shown[2][0].startswith("cliproxyapi · main · group personal"))

    def test_the_levels_are_coloured(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal")])
        self.with_groups("personal")
        seen, answers = [], [0, None, None]

        def pick(labels, *, header="", initial=0):
            seen.append(labels)
            return answers.pop(0)

        keys = ["", None]  # the management key, then Esc when Esc on all groups goes back to it
        pickers = proxy_accounts.Pickers(pick=pick, line=lambda *a, **k: keys.pop(0), say=lambda text: None, show=lambda text: None)
        proxy_accounts.choose_model(base_url=BASE, entry=proxy_accounts.load_entry(), current_model="", catalog=_result(proxy.served()), refetch=lambda: _result(proxy.served()), pickers=pickers)
        groups, level = seen[0], seen[1]
        self.assertIn("\x1b[1;38;2;255;175;135mpersonal\x1b[0m", groups[0])  # a group name in peach
        self.assertIn("\x1b[38;2;74;222;128m1 model\x1b[0m", groups[0])  # its models in green
        self.assertTrue(groups[1].startswith("\x1b[38;2;74;222;128mcreate a group…"))
        self.assertTrue(level[0].startswith("\x1b[38;2;74;222;128mmodels…"))
        self.assertTrue(level[1].startswith("\x1b[1;38;2;135;215;255maccounts…"))
        self.assertTrue(level[3].startswith("\x1b[38;2;248;113;113mdelete group…"))

    def test_a_refused_api_key_is_said_as_such_not_as_an_empty_group(self):
        self.proxy(accounts=[("me@example.test", "personal")])
        self.with_groups("personal")
        refused = CatalogFetchResult(entries=(), source="none", error_kind="auth", error="invalid api key", status=401)
        stub = Stub([("· group personal", "models…"), ("· group personal", None), ("account group", None)])
        self.drive(stub, current_model="personal/gpt-6.2-sol", catalog=lambda: refused)
        header, labels = stub.shown[0]
        # The current group opens with the real reason: the API key, not "log an account in".
        self.assertEqual(labels[0], "models… · the proxy refused the API key")
        self.assertIn("it must match agent-proxy's CLIPROXYAPI_API_KEY", header)
        self.assertIn("The proxy refused the API key", stub.text)
        self.assertEqual(stub.shown[1][1][0], "models… · the proxy refused the API key")
        header, labels = stub.shown[2]
        self.assertEqual(labels[0], "personal · 1 account: me@example.test · models unknown (current)")
        self.assertIn("The proxy refused the API key", header)

    def test_type_a_model_id_from_the_window_when_the_proxy_serves_nothing(self):
        self.proxy()
        down = CatalogFetchResult(entries=(), source="none", error_kind="network", error="connection refused")
        stub = Stub([("account group", "type a model id")], lines=["work/gpt-6.2-sol"])
        self.assertEqual(self.drive(stub, catalog=lambda: down), "work/gpt-6.2-sol")
        self.assertIn("did not answer (connection refused)", stub.shown[0][0])
        self.assertEqual(stub.prompts[-1], "cliproxyapi model> ")


class ManagementKeyTests(IsolatedSettings):
    def test_a_typed_management_key_is_kept_and_used(self):
        proxy = self.proxy(key="my-own-key", accounts=[("me@example.test", "personal")])
        self.with_groups("personal")
        self.drive(Stub([("account group", None)], keys=["my-own-key"]), proxy=proxy)
        self.assertEqual(self.saved("management_key"), "my-own-key")
        self.assertIn('CLIPROXYAPI_MANAGEMENT_KEY="my-own-key"', self.user.read_text())
        self.assertEqual(self.saved("account_groups"), ["personal"])
        # Next time, blank keeps it.
        stub = Stub([("account group", None)])
        self.drive(stub, proxy=proxy)
        self.assertEqual(stub.prompts[0], "cliproxyapi management key (blank keeps current)> ")
        self.assertNotIn("refused", stub.text)

    def test_an_exported_management_key_that_shadows_the_typed_one_is_said(self):
        proxy = self.proxy(key="my-own-key", accounts=[("me@example.test", "personal")])
        with patch.dict(os.environ, {"CLIPROXYAPI_MANAGEMENT_KEY": "stale-exported"}):
            stub = Stub([("account group", None)], keys=["my-own-key"])
            self.drive(stub, proxy=proxy)
        self.assertIn('CLIPROXYAPI_MANAGEMENT_KEY="my-own-key"', self.user.read_text())
        self.assertIn("CLIPROXYAPI_MANAGEMENT_KEY is exported in this shell and is used instead next time", stub.text)

    def test_a_typed_management_key_the_proxy_refuses_is_not_kept(self):
        proxy = self.proxy(key="the-real-one", accounts=[("me@example.test", "personal")])
        self.with_groups("personal", management_key="the-real-one")
        self.drive(Stub([("account group", None)], keys=["a-typo"]), proxy=proxy)
        # The typo was refused, so the saved key stays the one that works: the next window does not send the typo again.
        self.assertEqual(self.saved("management_key"), "the-real-one")

    def test_a_wrong_management_key_is_reported_once_never_retried(self):
        proxy = self.proxy(key="the-real-one", accounts=[("me@example.test", "personal")])
        self.with_groups("personal")
        stub = Stub([("account group", "create a group"), ("account group", "personal"), ("· group personal", "accounts…"), ("· group personal", "delete group"), ("· group personal", None), ("account group", None)])
        self.drive(stub, proxy=proxy)
        self.assertIn("refused the management key", stub.text)
        self.assertIn("after 5 wrong keys", stub.text)
        self.assertEqual(stub.text.count("refused the management key (invalid management key)"), 1)
        self.assertIn("Nothing was changed: the management key was refused. Reopen this window and type the right key", stub.text)
        # Each wrong key counts toward the proxy's lockout: one request per window, however many actions follow.
        self.assertEqual(len(proxy.calls), 1)

    def test_a_proxy_with_its_management_api_off_says_to_deploy_again(self):
        proxy = self.proxy(off=True)
        self.with_groups("personal")
        stub = Stub([("account group", "create a group"), ("account group", None)])
        self.drive(stub, proxy=proxy)
        self.assertIn("management API is off: deploy agent-proxy again", stub.text)
        self.assertIn("Nothing was changed", stub.text)


class GroupAndAccountTests(IsolatedSettings):
    def test_a_group_without_models_says_so(self):
        proxy = self.proxy()
        steps = [("account group", "create a group"), ("· group work · log in", None), ("· group work", "models…"), ("· group work", None), ("account group", "work · no accounts yet"), ("· group work", None), ("account group", None)]
        stub = Stub(steps, lines=["work"])
        self.drive(stub, proxy=proxy)
        self.assertEqual(stub.shown[2][1][:2], ["models… · none yet: log an account in", "accounts… · none yet: log one in"])
        self.assertIn("Group work serves no models yet", stub.text)

    def test_a_new_group_whose_login_was_cancelled_is_gone_next_time(self):
        proxy = self.proxy()
        steps = [("account group", "create a group"), ("· group work · log in", None), ("· group work", "models…"), ("· group work", None), ("account group", None)]
        stub = Stub(steps, lines=["work"])
        self.drive(stub, proxy=proxy)
        self.assertGreaterEqual(len(proxy.made("GET", "auth-files")), 2)  # it was read again inside the window
        self.assertEqual(self.saved("account_groups"), ["work"])  # kept while that window was open
        self.assertTrue(stub.shown[-1][1][0].startswith("work"))
        self.drive(Stub([("account group", None)]), proxy=proxy)
        self.assertEqual(self.saved("account_groups"), [])

    def test_create_a_group_then_log_in_then_choose_its_model(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal")], next_login=("me@work.test", "codex"))
        self.with_groups("personal")
        lines = sign_in_address(
            proxy,
            "Bad Name", "personal", "work",  # the new group's name: refused, taken, then taken up
            "http://localhost:1455/auth/callback?code=c&state=someone-elses",  # an address from another sign-in
            "",  # blank: has it finished by itself? (no)
        )
        # A new group goes straight to logging an account in, and the login straight to the group's models.
        steps = [("account group", "create a group…"), ("· group work · log in", "ChatGPT"), ("main model · group work", "gpt-6.2-sol")]
        stub = Stub(steps, lines=lines)
        self.assertEqual(self.drive(stub, proxy=proxy), "work/gpt-6.2-sol")
        self.assertIn("Use lowercase letters", stub.text)
        self.assertIn("Group personal already exists", stub.text)
        self.assertIn("Created group work", stub.text)
        # The sign-in link is printed whole, for copying; a wrong address is explained, and the login waits for the right one.
        self.assertTrue(any(line.startswith("https://sign-in.example/codex-auth-url?state=") for line in stub.printed))
        self.assertIn("That address was not taken: unknown or expired state", stub.text)
        self.assertIn("Still waiting for the sign-in", stub.text)
        self.assertIn("me@work.test is logged in, in group work", stub.text)
        self.assertEqual(proxy.group_of("me@work.test"), "work")
        self.assertEqual(proxy.made("POST", "oauth-callback")[-1][4]["provider"], "codex")
        self.assertEqual(self.saved("account_groups"), ["personal", "work"])

    def test_the_first_group_and_a_claude_login(self):
        proxy = self.proxy(next_login=("me@example.test", "claude"))
        lines = sign_in_address(proxy, "personal")
        stub = Stub([("account group", "create a group"), ("· group personal · log in", "Claude"), ("main model · group personal", None), ("· group personal", None), ("account group", None)], lines=lines)
        self.assertIsNone(self.drive(stub, proxy=proxy))
        self.assertEqual(self.saved("account_groups"), ["personal"])
        self.assertEqual(proxy.group_of("me@example.test"), "personal")
        self.assertEqual(proxy.made("POST", "oauth-callback")[-1][4]["provider"], "anthropic")

    def test_log_in_a_new_account_from_a_groups_accounts(self):
        proxy = self.proxy(accounts=[("me@example.test", "work")], next_login=("two@example.test", "codex"))
        self.with_groups("work")
        lines = sign_in_address(proxy)
        steps = [("account group", "work"), ("· group work", "accounts…"), ("· group work · accounts", "log in a new account"), ("· group work · log in", "ChatGPT"), ("main model · group work", None), ("· group work", None), ("account group", None)]
        stub = Stub(steps, lines=lines)
        self.drive(stub, proxy=proxy)
        self.assertEqual([label.split(" ·")[0] for label in stub.shown[2][1]], ["me@example.test", "log in a new account…"])
        self.assertEqual(proxy.group_of("two@example.test"), "work")

    def test_logging_in_again_keeps_the_account_in_its_group(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("w@example.test", "work")], next_login=("me@example.test", "codex"))
        self.with_groups("personal", "work")
        lines = sign_in_address(proxy)
        steps = [("account group", "work"), ("· group work", "accounts…"), ("· group work · accounts", "log in a new account"), ("· group work · log in", "ChatGPT"), ("main model · group personal", None), ("· group personal", None), ("account group", None)]
        stub = Stub(steps, lines=lines)
        self.drive(stub, proxy=proxy)
        # The same rule as agent-proxy's login.sh: a login never moves an account; its group is put back, and its models follow.
        self.assertIn("me@example.test was already in group personal: it stays there", stub.text)
        self.assertEqual(proxy.group_of("me@example.test"), "personal")

    def test_a_token_refresh_during_a_new_login_moves_nothing_else(self):
        proxy = self.proxy(accounts=[("loose@example.test", ""), ("w@example.test", "work")], next_login=("me@work.test", "codex"))
        self.with_groups("work")
        lines = sign_in_address(proxy, during=lambda: refresh_tokens(proxy, "loose@example.test"))
        steps = [("account group", "work"), ("· group work", "accounts…"), ("· group work · accounts", "log in a new account"), ("· group work · log in", "ChatGPT"), ("main model · group work", None), ("· group work", None), ("account group", None)]
        self.drive(Stub(steps, lines=lines), proxy=proxy)
        self.assertEqual(proxy.group_of("me@work.test"), "work")
        self.assertEqual(proxy.group_of("loose@example.test"), "")

    def test_a_login_again_while_another_account_refreshes_guesses_nothing(self):
        proxy = self.proxy(accounts=[("me@example.test", ""), ("loose@example.test", ""), ("claude@example.test", "", "claude"), ("w@example.test", "work", "claude")], next_login=("me@example.test", "codex"))
        self.with_groups("work")

        def refresh_others():
            refresh_tokens(proxy, "loose@example.test")
            refresh_tokens(proxy, "claude@example.test")

        lines = sign_in_address(proxy, during=refresh_others)
        steps = [("account group", "work"), ("· group work", "accounts…"), ("· group work · accounts", "log in a new account"), ("· group work · log in", "ChatGPT"), ("· group work · accounts", None), ("· group work", None), ("account group", None)]
        stub = Stub(steps, lines=lines)
        self.drive(stub, proxy=proxy)
        # Two ChatGPT files changed (the login's and a refresh): neither is guessed at. The Claude account's refresh never counted.
        self.assertIn("2 ChatGPT / Codex accounts changed at the same time", stub.text)
        self.assertEqual({proxy.group_of(email) for email in ("me@example.test", "loose@example.test", "claude@example.test")}, {""})
        self.assertEqual(proxy.made("PATCH", "auth-files/fields"), [])

    def test_an_account_gone_between_the_listing_and_its_file_is_left_out(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("gone@example.test", "work")])
        original = proxy.handle

        def handle(method, path, query, data):
            if path == "auth-files/download" and query["name"] == "codex-gone@example.test.json":
                return {"_status": 404, "error": "auth file not found"}
            return original(method, path, query, data)

        proxy.handle = handle
        accounts = proxy_accounts.load_accounts(proxy_accounts.Management("http://127.0.0.1:8317", KEY), [])
        self.assertEqual([(account.email, account.group) for account in accounts.accounts], [("me@example.test", "personal")])

    def test_press_an_account_to_log_it_out(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("two@example.test", "work")])
        self.with_groups("personal", "work")
        steps = [
            ("account group", "work"), ("· group work", "accounts…"),
            ("· group work · accounts", "two@example.test"), ("· two@example.test", "back"),
            ("· group work · accounts", "two@example.test"), ("· two@example.test", "log out two@example.test"),
            ("· group work · accounts", None), ("· group work", None), ("account group", None),
        ]
        stub = Stub(steps)
        self.drive(stub, proxy=proxy)
        # The account's choices: log out, move, back.
        self.assertEqual(stub.shown[3][1], ["log out two@example.test", "move it to another group…", "back"])
        self.assertEqual([item["email"] for item in proxy.files.values()], ["me@example.test"])
        self.assertEqual([call[3] for call in proxy.made("DELETE", "auth-files")], [{"name": "codex-two@example.test.json"}])
        # That was work's last account: the group goes with it, here and in git-tools' list.
        self.assertIn("That was group work's last account, so the group is gone too", stub.text)
        self.assertEqual(self.saved("account_groups"), ["personal"])
        self.assertFalse(any(label.startswith("work") for label in stub.shown[-1][1]))

    def test_a_delete_that_stops_partway_shows_what_is_left(self):
        proxy = self.proxy(accounts=[("me@example.test", "work"), ("two@example.test", "work")])
        self.with_groups("work")
        original = proxy.handle

        def handle(method, path, query, data):
            if method == "DELETE" and query["name"] == "codex-two@example.test.json":
                return {"_status": 500, "error": "disk full"}
            return original(method, path, query, data)

        proxy.handle = handle
        steps = [("account group", "work"), ("· group work", "delete group"), ("delete group work", "yes, delete group work"), ("· group work", None), ("account group", None)]
        stub = Stub(steps)
        self.drive(stub, proxy=proxy)
        self.assertIn("disk full", stub.text)
        self.assertIn("Group work was kept, since not all of its accounts were logged out", stub.text)
        self.assertEqual(self.saved("account_groups"), ["work"])
        self.assertEqual(stub.shown[3][1][1], "accounts… · 1 account: two@example.test")

    def test_no_group_offers_no_login(self):
        proxy = self.proxy(accounts=[("old@example.test", "")])
        steps = [("account group", "(no group)"), ("· no group", "accounts…"), ("· no group · accounts", None), ("· no group", None), ("account group", None)]
        stub = Stub(steps)
        self.drive(stub, proxy=proxy)
        self.assertEqual(stub.shown[1][1], ["models… · 1 model · now gpt-6.2-sol", "accounts… · 1 account: old@example.test", "all groups…"])
        self.assertEqual([label.split(" ·")[0] for label in stub.shown[2][1]], ["old@example.test"])

    def test_press_an_account_in_no_group_to_move_it(self):
        proxy = self.proxy(accounts=[("old@example.test", "")])
        self.with_groups("personal", "work")
        steps = [
            ("account group", "(no group)"), ("· no group", "accounts…"),
            ("· no group · accounts", "old@example.test"), ("· old@example.test", "move it to another group"),
            ("move to group", "create a group…"),
            ("· no group", None), ("account group", None),
        ]
        stub = Stub(steps, lines=["personal"])
        self.drive(stub, proxy=proxy)
        # The saved groups had no account at the proxy, so they are gone: the only choice is a new group.
        self.assertEqual(stub.shown[4][1], ["create a group…"])
        self.assertEqual(proxy.group_of("old@example.test"), "personal")
        self.assertEqual(proxy.made("PATCH", "auth-files/fields")[0][4], {"name": "codex-old@example.test.json", "prefix": "personal"})
        self.assertIn("old@example.test is in group personal now", stub.text)
        self.assertEqual(stub.shown[-1][1][0], "personal · 1 account: old@example.test · 1 model")

    def test_deleting_a_group_logs_its_accounts_out(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("two@example.test", "personal"), ("other@example.test", "work")])
        self.with_groups("personal", "work")
        steps = [
            ("account group", "create a group"), ("· group spare · log in", None),
            ("· group spare", "delete group"), ("delete group spare", "no, change nothing"),
            ("· group spare", "delete group"), ("delete group spare", "yes, delete group spare"),
            ("account group", "personal"), ("· group personal", "delete group"),
            ("delete group personal", "yes, delete group personal and log out 2 accounts: me@example.test, two@example.test"),
            ("account group", None),
        ]
        stub = Stub(steps, lines=["spare"])
        self.drive(stub, proxy=proxy)
        self.assertIn("Deleted group spare", stub.text)
        self.assertIn("Deleted group personal", stub.text)
        self.assertIn("Logged out me@example.test", stub.text)
        self.assertIn("Logged out two@example.test", stub.text)
        self.assertEqual(self.saved("account_groups"), ["work"])
        self.assertEqual([item["email"] for item in proxy.files.values()], ["other@example.test"])


class WizardTests(IsolatedSettings):
    """The full provider setup: address, API key, management key, window, model, effort, as agent-cli's /settings provider asks them."""

    def run_wizard(self, stub, *, effort="high", key_answer="", address=None):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("you@example.test", "work")])
        fetched = []

        def fetch(base_url, api_key):
            fetched.append((base_url, api_key))
            return _result(proxy.served())

        stub.lines[:0] = address or [""]
        passwords = []
        real_password = cli.picker.password

        def password(message, **kwargs):
            passwords.append(message)
            return real_password(message, **kwargs)

        state = cli._load_settings_state()
        with patch.object(proxy_accounts, "terminal_pickers", return_value=stub.pickers), \
             patch.object(mappings, "_fetch_models_sync", side_effect=fetch), \
             patch("git_tools.cli.picker.password", side_effect=password), \
             patch("git_tools.cli._ask_with_back", side_effect=[key_answer, effort]):
            cli._edit_provider(state, "cliproxyapi", interactive=True)
        stub.done(self)
        return state, fetched, passwords, proxy

    def test_address_keys_window_model_and_effort_are_saved_together(self):
        stub = Stub([("account group", "work"), ("· group work", "models…"), ("main model · group work", "gpt-6.2-sol")], lines=[])
        state, fetched, passwords, _ = self.run_wizard(stub, address=["192.168.1.20"])
        # agent-cli's order: the address (8317 when no port is typed), the API key naming its default, then the management key.
        self.assertEqual(stub.prompts[0], "cliproxyapi address (blank keeps http://127.0.0.1:8317/v1; or ip:port, or a url)> ")
        self.assertEqual(passwords, ["Enter your CLIProxyAPI API key (blank: cliproxyapi_sEcr3Tk3Y):"])
        self.assertEqual(stub.prompts[1], "cliproxyapi management key (blank = cliproxyapi_sEcr3Tk3Y)> ")
        self.assertEqual(fetched, [("http://192.168.1.20:8317/v1", "cliproxyapi_sEcr3Tk3Y")])
        self.assertEqual(state["model"], "work/gpt-6.2-sol")
        self.assertEqual(state["reasoning_effort"], "high")
        saved = self.user.read_text()
        self.assertIn('GIT_TOOLS_PROVIDER="cliproxyapi"', saved)
        self.assertIn('GIT_TOOLS_MODEL_MAIN="work/gpt-6.2-sol"', saved)
        self.assertIn('GIT_TOOLS_API_BASE="http://192.168.1.20:8317/v1"', saved)
        # Groups found only on the proxy's accounts are not copied into git-tools' list by picking one (as in agent-cli).
        self.assertNotIn("GIT_TOOLS_CLIPROXYAPI_ACCOUNT_GROUPS", saved)
        self.assertEqual(config.GitToolsSettings().effective_main_model, "work/gpt-6.2-sol")

    def test_esc_on_effort_goes_back_to_the_groups_model_list(self):
        proxy = self.proxy(accounts=[("me@example.test", "personal"), ("you@example.test", "work")])
        fetch = lambda base_url, api_key: _result(proxy.served())
        stub = Stub([("account group", "work"), ("· group work", "models…"), ("main model · group work", "gpt-6.2-sol"),
                     ("main model · group work", "gpt-6.2-sol")], lines=[""])
        with patch.object(proxy_accounts, "terminal_pickers", return_value=stub.pickers), \
             patch.object(mappings, "_fetch_models_sync", side_effect=fetch), \
             patch("git_tools.cli._ask_with_back", side_effect=["", None, "high"]):  # API key, Esc on effort, then high
            state = cli._load_settings_state()
            cli._edit_provider(state, "cliproxyapi", interactive=True)
        stub.done(self)
        self.assertEqual(len([prompt for prompt in stub.prompts if "management key" in prompt]), 1)
        self.assertEqual((state["model"], state["reasoning_effort"]), ("work/gpt-6.2-sol", "high"))

    def test_cancelling_the_address_changes_nothing(self):
        stub = Stub([], lines=[])
        proxy = self.proxy()
        with patch.object(proxy_accounts, "terminal_pickers", return_value=proxy_accounts.Pickers(
                pick=stub.pick, line=lambda *a, **k: None, say=stub.say, show=stub.show)), \
             patch("git_tools.cli._ask_with_back", side_effect=[None]):  # then Esc at the provider list
            cli._edit_provider(cli._load_settings_state(), "cliproxyapi", interactive=True)
        self.assertFalse(self.user.exists())
        self.assertEqual(proxy.calls, [])

    def test_a_saved_key_is_kept_by_a_blank_answer(self):
        config.save_settings({"CLIPROXYAPI_API_KEY": "my-client-key"})
        stub = Stub([("account group", "personal"), ("· group personal", "models…"), ("main model · group personal", "gpt-6.2-sol")], lines=[])
        _, fetched, passwords, _ = self.run_wizard(stub)
        self.assertEqual(passwords, ["Enter your CLIProxyAPI API key (blank keeps current):"])
        self.assertEqual(fetched, [(BASE, "my-client-key")])


class ModelIdTests(unittest.TestCase):
    def test_split_model_group_is_agent_cores(self):
        self.assertEqual(split_model_group("work/gpt-6.2-sol", "cliproxyapi"), ("work", "gpt-6.2-sol"))
        self.assertEqual(split_model_group("gpt-6.2-sol", "cliproxyapi"), (None, "gpt-6.2-sol"))
        # Only a CLIProxyAPI id carries a group: OpenRouter's slash names a vendor.
        self.assertEqual(split_model_group("openai/gpt-5", "openrouter"), (None, "openai/gpt-5"))
        self.assertEqual(split_model_group(" Work/gpt ", "CLIProxyAPI"), ("Work", "gpt"))

    def test_a_grouped_reasoning_model_keeps_its_effort(self):
        def options(model, effort):
            return provider_request_options("cliproxyapi", model, temperature=0.6, effort=effort, session_key="s")

        self.assertEqual(options("work/gpt-6.2-sol", "high")["reasoning_effort"], "high")
        self.assertNotIn("reasoning_effort", options("work/gpt-6.2-sol", "none"))
        self.assertNotIn("reasoning_effort", options("work/gpt-4.1", "high"))
        self.assertNotIn("reasoning_effort", options("personal/deepseek-v4.1-flash", "high"))
        # The id sent stays whole: the group is what routes the request.
        self.assertEqual(options("work/gpt-6.2-sol", "high")["default_headers"], {"Session_id": "s"})

    def test_the_effort_row_reads_the_model_after_the_group(self):
        state = {"provider": "cliproxyapi", "model": "work/gpt-6.2-sol", "api_configured": True, "api_key_source": "",
                 "temperature": 1.0, "max_tokens": 1, "max_retries": 1, "reasoning_effort": None}
        values = [choice.value for choice in cli._build_settings_choices(state)]
        self.assertIn("effort", values)

    def test_model_not_found_explains_the_group(self):
        self.assertIn('no gpt-6.2-sol in the account group "work"', model_not_found_hint("work/gpt-6.2-sol"))
        self.assertIn("`personal/gpt-6.2-sol`", model_not_found_hint("gpt-6.2-sol"))
        self.assertEqual(model_not_found_hint(""), "")

    def test_a_refused_model_says_what_the_group_means(self):
        from git_tools.generators.base import llm

        class NotFound(Exception):
            code = "model_not_found"

        class Client:
            provider_name = "cliproxyapi"
            model_name = "work/gpt-6.2-sol"

            def invoke(self, messages):
                raise NotFound("model not found")

        class Generator(llm.LLMInvocationMixin):
            chatclient = Client()
            logger = __import__("logging").getLogger("test")

        with patch.object(llm, "warning") as warning:
            self.assertIsNone(Generator().invoke_llm([], max_retries=0))
        self.assertIn('account group "work"', warning.call_args.args[0])


class ExpressFlowTests(unittest.TestCase):
    """``git-tools commit`` and friends run on the saved model without a picker, so a group must be chosen in settings first."""

    GROUPED_IDS = ("personal/gpt-6.2-sol", "work/gpt-6.2-sol", "work/gpt-6-luna")

    def select(self, model, served=GROUPED_IDS, *, live=True, cli_model=None):
        from git_tools.generators.base import models as models_module
        from git_tools.generators.issueprgen import IssuePullRequestGenerator

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        generator._cli_model = cli_model
        with patch.dict(mappings.PROVIDERS["cliproxyapi"], {"models": {item: {"model_name": item} for item in served}}), \
             patch.object(models_module, "refresh_live_models", return_value=live), \
             patch.object(models_module.settings, "main_model", model), \
             patch.object(generator, "get_provider_config"), \
             patch("git_tools.cli._print_model_catalog_status"):
            return generator.select_model_params("cliproxyapi")[0]

    def test_a_model_without_a_group_stops_before_anything_is_sent(self):
        with self.assertRaises(ValueError) as caught:
            self.select("gpt-6.2-sol")
        message = str(caught.exception)
        self.assertIn("keeps its accounts in groups (personal, work)", message)
        self.assertIn("git-tools settings provider cliproxyapi", message)
        self.assertIn("--model personal/gpt-6.2-sol", message)
        # An explicit --model is held to the same rule.
        with self.assertRaises(ValueError):
            self.select("work/gpt-6.2-sol", cli_model="gpt-6.2-sol")

    def test_a_group_with_nothing_served_stops_too(self):
        with self.assertRaises(ValueError) as caught:
            self.select("gone/gpt-6.2-sol")
        self.assertIn('serves nothing in the account group "gone"', str(caught.exception))
        self.assertIn("Groups served now: personal, work", str(caught.exception))

    def test_a_chosen_group_or_an_ungrouped_proxy_runs(self):
        self.assertEqual(self.select("work/gpt-6-luna"), "work/gpt-6-luna")
        # A model the group does not list is the proxy's to judge.
        self.assertEqual(self.select("work/gpt-7-preview"), "work/gpt-7-preview")
        # Accounts in no group still serve the plain name.
        self.assertEqual(self.select("gpt-6.2-sol", served=("gpt-6.2-sol", "work/gpt-6.2-sol")), "gpt-6.2-sol")

    def test_an_unreadable_catalog_is_left_to_the_request(self):
        self.assertEqual(self.select("gpt-6.2-sol", served=(), live=False), "gpt-6.2-sol")
        self.assertEqual(self.select("gpt-6.2-sol", served=()), "gpt-6.2-sol")


class UpgradeFromTheOpenRouterDefaultTests(IsolatedSettings):
    """git-tools used to default to OpenRouter; settings that never chose a provider now run on CLIProxyAPI."""

    # What `git-tools settings model …` saved under the old implicit default: the plain keys and their OpenRouter profile mirror.
    OLD = 'OPENROUTER_API_KEY="or-key"\nGIT_TOOLS_MODEL_MAIN="deepseek/deepseek-v4-flash-0731"\nGIT_TOOLS_OPENROUTER_MODEL_MAIN="deepseek/deepseek-v4-flash-0731"\n'

    def notice(self):
        from git_tools.generators.base import models as models_module
        from git_tools.generators.issueprgen import IssuePullRequestGenerator

        with patch.object(models_module, "warning") as warning:
            IssuePullRequestGenerator(generation_type="pr", interactive=False)._note_implicit_cliproxyapi()
        return warning

    def test_settings_from_before_are_told_how_to_keep_openrouter(self):
        self.user.write_text(self.OLD)
        self.assertEqual(config.GitToolsSettings().default_provider, "cliproxyapi")
        warning = self.notice()
        warning.assert_called_once()
        self.assertIn("git-tools settings provider openrouter --non-interactive", warning.call_args.args[0])

    def test_no_notice_once_a_provider_is_chosen_or_without_an_openrouter_key(self):
        self.user.write_text(self.OLD + 'GIT_TOOLS_PROVIDER="cliproxyapi"\n')
        self.notice().assert_not_called()
        self.user.write_text('GIT_TOOLS_MODEL_MAIN="work/gpt-6.2-sol"\n')
        self.notice().assert_not_called()

    def test_choosing_openrouter_brings_back_its_model(self):
        self.user.write_text(self.OLD)
        cli._edit_provider(cli._load_settings_state(), "openrouter", interactive=False)
        fresh = config.GitToolsSettings()
        self.assertEqual(fresh.default_provider, "openrouter")
        self.assertEqual(fresh.effective_main_model, "deepseek/deepseek-v4-flash-0731")


class AddressTests(unittest.TestCase):
    def test_typed_addresses_become_base_urls(self):
        address = proxy_accounts.proxy_address
        self.assertEqual(address("192.168.1.20:9000"), "http://192.168.1.20:9000/v1")
        self.assertEqual(address("192.168.1.20"), "http://192.168.1.20:8317/v1")
        self.assertEqual(address("proxy.local"), "http://proxy.local:8317/v1")
        self.assertEqual(address("[::1]:8317"), "http://[::1]:8317/v1")
        self.assertEqual(address("cli_proxy_api:8317"), "http://cli_proxy_api:8317/v1")  # a Docker service name
        self.assertEqual(address("http://proxy.local:9000"), "http://proxy.local:9000/v1")
        self.assertEqual(address("https://proxy.example.com/"), "https://proxy.example.com/v1")
        self.assertEqual(address("http://h:8317/proxy/v1/"), "http://h:8317/proxy/v1")
        for wrong in ("", "my host", "h:70000", "h:0", "ftp://h", "http://user:pw@h:1", "h:1?x=1", "-bad", "http://"):
            self.assertIsNone(address(wrong), wrong)

    def test_a_typo_is_explained_and_asked_again(self):
        stub = Stub(lines=["192.168.1.20:99999", ""])
        self.assertEqual(proxy_accounts.ask_address("http://192.168.1.20:9000/v1", stub.pickers), "http://192.168.1.20:9000/v1")
        self.assertIn("192.168.1.20:99999 is not an address", stub.text)
        self.assertEqual(stub.prompts[0], "cliproxyapi address (blank keeps http://192.168.1.20:9000/v1; or ip:port, or a url)> ")

    def test_the_management_address_is_the_proxy_without_v1(self):
        self.assertEqual(proxy_accounts.management_base("http://127.0.0.1:8317/v1"), "http://127.0.0.1:8317")
        self.assertEqual(proxy_accounts.management_base("http://127.0.0.1:8317/v1/"), "http://127.0.0.1:8317")
        self.assertEqual(proxy_accounts.management_base("http://proxy.local:9000"), "http://proxy.local:9000")

    def test_saved_group_names_are_valid_and_once_each(self):
        self.assertEqual(proxy_accounts.saved_groups({"account_groups": ["work", "Bad Name", "work", 3, "personal"]}), ["work", "personal"])
        self.assertEqual(proxy_accounts.saved_groups({"account_groups": "work"}), [])
        self.assertEqual(proxy_accounts.saved_groups({}), [])


if __name__ == "__main__":
    unittest.main()
