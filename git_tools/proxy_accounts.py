"""The proxy's account groups and accounts, inside the CLIProxyAPI model picker (``git-tools settings provider cliproxyapi`` and **Main model**).

A port of agent-cli's ``agent_cli/ui/shell/slash/proxy_accounts.py``: the same levels, rows, texts and rules, asked through agent-cli's own pickers (ported in ``git_tools.picker``), and synchronous.

After the address and the API key comes the management key, then the window, in levels. All groups: with none yet, create one; otherwise pick one (or create one, or type a model id). One group, opened at once when the current model already runs on it: its models, its accounts, all groups, or delete it (which logs its accounts out). Its accounts: press one (Codex or Claude) to log it out or move it to another group, or log a new one in. Esc goes up a level. A new group goes straight to logging an account into it, and a login goes straight to its group's models.

The window talks to the proxy itself, at the provider's address, through CLIProxyAPI's management API, which agent-proxy's deploy turns on with its management key (``cliproxyapi_sEcr3Tk3Y`` unless agent-proxy.env sets another). So it never needs to know where agent-proxy was deployed from, and it runs none of agent-proxy's scripts: those stay for use without the CLI, with the same rules (every account belongs to a group; deleting a group logs its accounts out).

The proxy is the source of truth for groups and accounts. Accounts are read afresh every time, never kept. git-tools keeps a local copy of the group names (``GIT_TOOLS_CLIPROXYAPI_ACCOUNT_GROUPS``), brought in line with the proxy whenever the accounts are read: a group none of the proxy's accounts is in leaves it, except one made (or logged into) in this window, which lasts while the window is open so its first login can follow. A group is found on its accounts (their ``prefix``), so groups made with agent-proxy's scripts or agent-cli show here as well. The management key (``CLIPROXYAPI_MANAGEMENT_KEY``, once the proxy has not refused it) and the group names are kept in ``~/.git-tools/settings.env`` as soon as they change, as agent-cli keeps them in its provider entry.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from rich.markup import escape as safe_markup

from git_tools.providers.catalog import CatalogFetchResult
from git_tools.providers.cliproxyapi import PROVIDER_ID, split_model_group

#: The provider entry key that keeps the proxy's management key, and the setting it is saved as.
KEY_FIELD = "management_key"
KEY_ENV = "CLIPROXYAPI_MANAGEMENT_KEY"
#: The provider entry key that keeps git-tools' account group names, and the setting they are saved as (comma-separated).
GROUPS_FIELD = "account_groups"
GROUPS_ENV = "GIT_TOOLS_CLIPROXYAPI_ACCOUNT_GROUPS"
#: agent-proxy's management key when its env sets none (like the client API key's default).
DEFAULT_KEY = "cliproxyapi_sEcr3Tk3Y"
#: Group names: lowercase letters, digits and '-', at most 32 characters (agent-proxy's valid_group).
GROUP_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
#: After a login or a move, how long to wait for the proxy to load the account's models, per try.
SETTLE_SECONDS = 1.5
_SETTLE_TRIES = 3
#: After the sign-in address is pasted, how long the proxy may take to finish the login, and how often to ask.
LOGIN_WAIT_SECONDS = 60.0
LOGIN_POLL_SECONDS = 1.0
#: What the model list says the main model is for.
MAIN_MODEL_ABOUT = "Main model: commit messages, issues and pull requests are generated with it."

# The settings screen's colours: a name in the prompt blue, on/new green, off/gone red, a number yellow, a named choice peach, the rest grey.
_BLUE = "1;38;2;135;215;255"
_GREEN = "38;2;74;222;128"
_RED = "38;2;248;113;113"
_YELLOW = "38;2;250;204;21"
_PEACH = "1;38;2;255;175;135"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class Pickers:
    """How the window asks and tells: a list pick, a typed line, a line of Rich markup, and plain text (a sign-in link). ``terminal_pickers`` is agent-cli's pickers and the console; tests pass stubs."""

    pick: Callable[..., int | None]  # pick(labels, *, header, initial=0) -> index, None on Esc
    line: Callable[..., str | None]  # line(prompt, *, password=False, default="") -> text, None on Esc
    say: Callable[[str], None]
    show: Callable[[str], None]


@dataclass(frozen=True)
class ProxyAccount:
    provider: str
    email: str
    state: str
    group: str  # "" for none
    file: str
    modtime: str = ""


@dataclass
class ProxyAccounts:
    """Every group (git-tools' own names, and those found on an account) with its account count, and every account at the proxy."""

    groups: dict[str, int] = field(default_factory=dict)
    accounts: list[ProxyAccount] = field(default_factory=list)

    def in_group(self, group: str) -> list[ProxyAccount]:
        return [account for account in self.accounts if account.group == group]


@dataclass(frozen=True)
class GroupChoice:
    """What the window ended on: a group to choose a model from ("" for the models of accounts in no group), or a typed model id (``group`` None)."""

    group: str | None
    catalog: Any


@dataclass(frozen=True)
class _Provider:
    label: str
    callback: str  # the provider name the management API's oauth-callback takes
    auth_url: str  # the management API path that starts its sign-in
    lands_on: str  # where the browser goes after signing in
    words: tuple[str, ...]  # what its accounts' provider names contain

    def owns(self, account: "ProxyAccount") -> bool:
        return any(word in account.provider.lower() for word in self.words)


_PROVIDERS = (
    _Provider("ChatGPT / Codex", "codex", "codex-auth-url", "http://localhost:1455/auth/callback?code=…", ("codex", "openai")),
    _Provider("Claude", "anthropic", "anthropic-auth-url", "http://localhost:54545/callback?code=…", ("claude", "anthropic")),
)


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


def _dim(text: str) -> str:
    return f"\x1b[90m{text}\x1b[0m"


def _titled(title: str, about: str) -> str:
    width = max(20, shutil.get_terminal_size().columns - 1)
    lines = textwrap.wrap(about, width) or [""]
    return title + "".join(f"\n\x1b[90m{line}\x1b[0m" for line in lines)


def _title(what: str) -> str:
    return f"\x1b[1;36mcliproxyapi\x1b[0m \x1b[90m· {what}\x1b[0m"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


def plain(text: str) -> str:
    """Text without its colours."""
    return _ANSI.sub("", str(text))


# ---- asking in a terminal: agent-cli's pickers (git_tools.picker) and the shared console ----


def _terminal_pick(labels: list[str], *, header: str = "", initial: int = 0, ask: Callable[[Any], Any] | None = None) -> int | None:
    """agent-cli's picker: the header (title and grey about lines) above numbered rows; long lists page; Esc is None."""
    from git_tools import picker
    from git_tools.navigation import ask_with_back

    answer = (ask or ask_with_back)(picker.pick(labels, header=header, initial=initial))
    return answer if isinstance(answer, int) else None


def _terminal_line(prompt: str, *, password: bool = False, default: str = "", ask: Callable[[Any], Any] | None = None) -> str | None:
    """agent-cli's prompt line (masked for a key), erased when done; Esc is None."""
    from git_tools import picker
    from git_tools.navigation import ask_with_back

    question = picker.password(prompt) if password else picker.text(prompt, default=default)
    answer = (ask or ask_with_back)(question)
    return None if answer is None else str(answer).strip()


def _terminal_say(text: str) -> None:
    from git_tools.generators.base import console

    console.print(text)


def _terminal_show(text: str) -> None:
    from git_tools.generators.base import console

    console.print(text, markup=False, highlight=False, soft_wrap=True)


def terminal_pickers(ask: Callable[[Any], Any] | None = None) -> Pickers:
    """agent-cli's pickers and the console. ``ask`` asks one picker question (Esc is None); git-tools' Esc-aware ``ask_with_back`` unless the caller passes its own."""
    return Pickers(
        pick=lambda labels, **kwargs: _terminal_pick(labels, ask=ask, **kwargs),
        line=lambda prompt, **kwargs: _terminal_line(prompt, ask=ask, **kwargs),
        say=_terminal_say,
        show=_terminal_show,
    )


# ---- the proxy's management API ----


class ManagementError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def management_base(base_url: str) -> str:
    """The proxy's own address: the provider's base URL without its ``/v1``."""
    base = base_url.strip().rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _send(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
    """One HTTP request: (status, body). Raises OSError when nothing answers. Tests replace it."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


#: Why a refused key is not tried again.
REFUSED = "the proxy refused the management key ({}); it is not sent again from this window, since after 5 wrong keys the proxy refuses this machine for a while. Reopen this window and type the right key"


@dataclass
class Management:
    base: str
    key: str
    #: Set by the first 401: from then on nothing is sent with this key.
    refused: str = ""

    def call(self, method: str, path: str, *, params: dict[str, str] | None = None, body: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        if self.refused:
            raise ManagementError(REFUSED.format(self.refused), 401)
        url = f"{self.base}/v0/management/{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            status, raw = _send(method, url, headers, data, timeout)
        except (OSError, http.client.HTTPException, ValueError) as exc:  # nothing answered, or not as HTTP (a wrong address), or an unusable URL
            raise ManagementError(f"the proxy at {self.base} did not answer ({exc or type(exc).__name__})") from exc
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace")) if raw.strip() else None
        except ValueError:
            payload = None
        if status == 200:
            if not isinstance(payload, dict):
                # Not the proxy's answer (a web page at that address, say): never read as "no accounts".
                raise ManagementError(f"{self.base} answered, but not as CLIProxyAPI's management API: check the address", status)
            return payload
        if not isinstance(payload, dict):
            payload = {}
        message = str(payload.get("error") or "").strip()
        if status == 404 and not payload:
            raise ManagementError("the proxy's management API is off: deploy agent-proxy again (its deploy turns the API on with the management key)", status)
        if status == 401:
            self.refused = message or "HTTP 401"
            raise ManagementError(REFUSED.format(self.refused), status)
        raise ManagementError(message or f"HTTP {status}", status)


#: The port agent-proxy publishes on unless told otherwise (deploy.sh --port), taken when an address is typed without one.
DEFAULT_PORT = 8317
#: A host name or IPv4 address; "_" is allowed, as Docker service names use it.
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


def proxy_address(text: str) -> str | None:
    """The proxy's base URL from what was typed: a URL (http or https; ``/v1`` added when it has no path), or a host or IP with an optional port (8317 when left out). None when it cannot be one."""
    typed = text.strip()
    if not typed or any(char.isspace() for char in typed):
        return None
    bare = "://" not in typed
    try:
        parts = urllib.parse.urlsplit(f"http://{typed}" if bare else typed)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or parts.query or parts.fragment or parts.username or parts.password:
        return None
    if ":" in host:  # IPv6, kept in brackets
        host = f"[{host}]"
    elif not _HOST.fullmatch(host):
        return None
    if port is None and bare:
        port = DEFAULT_PORT
    if port is not None and not 1 <= port <= 65535:
        return None
    path = parts.path.rstrip("/") or "/v1"
    return urllib.parse.urlunsplit((parts.scheme, host + (f":{port}" if port is not None else ""), path, "", ""))


def ask_address(current: str, pickers: Pickers) -> str | None:
    """Where the proxy is, asked before the keys: blank keeps the current address (this machine's 127.0.0.1:8317 unless changed); an IP or host with a port, or a URL, reaches a proxy on another machine. None when cancelled. git-tools saves it with the rest of the provider setup, when that completes."""
    current = current or f"http://127.0.0.1:{DEFAULT_PORT}/v1"
    while True:
        typed = pickers.line(f"cliproxyapi address (blank keeps {current}; or ip:port, or a url)> ")
        if typed is None:
            return None
        address = proxy_address(typed) if typed.strip() else current
        if address is not None:
            return address
        pickers.say(f"[yellow]{safe_markup(typed.strip())} is not an address: type an IP or host with a port (192.168.1.20:8317), or a url (http://proxy.local:8317/v1).[/yellow]")


def saved_groups(entry: dict[str, Any]) -> list[str]:
    """git-tools' own group names, valid and once each, in the order they were made."""
    names = entry.get(GROUPS_FIELD)
    out: list[str] = []
    for name in names if isinstance(names, list) else []:
        if isinstance(name, str) and GROUP_NAME.fullmatch(name) and name not in out:
            out.append(name)
    return out


def load_entry() -> dict[str, Any]:
    """The saved management key and group names, as agent-cli's provider entry holds them."""
    from git_tools.settings.settings import effective_value

    key = (effective_value(KEY_ENV)[0] or "").strip()
    groups = [name.strip() for name in (effective_value(GROUPS_ENV)[0] or "").split(",") if name.strip()]
    return {KEY_FIELD: key, GROUPS_FIELD: groups}


def _save_entry(entry: dict[str, Any], **values: Any) -> None:
    """Keep values in the entry now, and in git-tools' settings file."""
    from git_tools.settings.settings import save_settings

    entry.update(values)
    updates: dict[str, str | None] = {}
    if KEY_FIELD in values:
        updates[KEY_ENV] = str(values[KEY_FIELD] or "") or None
    if GROUPS_FIELD in values:
        updates[GROUPS_ENV] = ",".join(values[GROUPS_FIELD]) or None
    save_settings(updates)


def _state(item: dict[str, Any]) -> str:
    if item.get("disabled"):
        return "disabled"
    if item.get("unavailable"):
        return "unavailable"
    return str(item.get("status") or "active")


def _file_group(api: Management, name: str) -> str | None:
    """An account's group: the listing does not say it, its file does. Only "prefix" is kept; the rest (its tokens) is dropped here. None when the account went away meanwhile."""
    try:
        credential = api.call("GET", "auth-files/download", params={"name": name})
    except ManagementError as exc:
        if exc.status == 404:
            return None
        raise
    return str(credential.get("prefix") or "").strip()


def load_accounts(api: Management, groups: list[str]) -> ProxyAccounts:
    listing = api.call("GET", "auth-files")
    if not isinstance(listing.get("files"), list):
        raise ManagementError(f"{api.base} answered, but not with CLIProxyAPI's account list: check the address")
    files = [item for item in listing["files"] if isinstance(item, dict) and item.get("name") and not item.get("runtime_only")]
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(files)))) as pool:
        found = list(pool.map(lambda item: _file_group(api, str(item["name"])), files))
    accounts = [
        ProxyAccount(
            provider=str(item.get("provider") or item.get("type") or "?"),
            email=str(item.get("email") or item.get("account") or item.get("label") or item["name"]),
            state=_state(item),
            group=group,
            file=str(item["name"]),
            modtime=str(item.get("modtime") or ""),
        )
        for item, group in zip(files, found)
        if group is not None
    ]
    counts = {name: 0 for name in groups}
    for account in accounts:
        if account.group:
            counts[account.group] = counts.get(account.group, 0) + 1
    accounts.sort(key=lambda account: (account.group == "", account.group, account.email))
    return ProxyAccounts(counts, accounts)


def _set_group(api: Management, account: ProxyAccount, group: str) -> None:
    api.call("PATCH", "auth-files/fields", body={"name": account.file, "prefix": group})


# ---- the window ----


@dataclass
class _Window:
    """The window's state: the proxy's models and accounts as last read, refreshed after every change."""

    name: str
    slot: str
    entry: dict[str, Any]
    api: Management
    pickers: Pickers
    catalog: Any
    refetch: Callable[[], Any]
    current_model: str
    accounts: ProxyAccounts | None = None
    #: Groups made (or logged into) in this window that may have no account yet: kept while the window is open, so creating a group can go on to its first login.
    pending: set[str] = field(default_factory=set)

    def save(self, **values: Any) -> None:
        _save_entry(self.entry, **values)

    def add_group(self, group: str, *, pending: bool = False) -> None:
        if pending:
            self.pending.add(group)
        groups = saved_groups(self.entry)
        if group not in groups:
            self.save(**{GROUPS_FIELD: [*groups, group]})

    def forget_group(self, group: str) -> None:
        self.pending.discard(group)
        self.save(**{GROUPS_FIELD: [name for name in saved_groups(self.entry) if name != group]})

    def sync_groups(self, accounts: ProxyAccounts) -> ProxyAccounts:
        """The proxy is the truth: a saved group none of its accounts is in (logged out elsewhere, deleted, never logged into) leaves git-tools' list, unless it is pending in this window."""
        held = {account.group for account in accounts.accounts if account.group}
        saved = saved_groups(self.entry)
        kept = [group for group in saved if group in held or group in self.pending]
        if kept != saved:
            self.save(**{GROUPS_FIELD: kept})
        accounts.groups = {group: count for group, count in accounts.groups.items() if group in held or group in self.pending}
        return accounts

    def say(self, text: str) -> None:
        self.pickers.say(text)

    def report(self, exc: ManagementError) -> None:
        self.say(f"[red]{safe_markup(str(exc))}[/red]")

    def models_in(self, group: str) -> list[str]:
        """The model ids a group serves ("" for the accounts in no group)."""
        return [item.id for item in self.catalog.entries if (split_model_group(item.id, self.name)[0] or "") == group]

    def groups(self) -> list[str]:
        """Every group. Once the accounts are read they decide (the groups on them, and pending ones); the model list, which can lag behind a delete, fills in only when they could not be read."""
        names = set(saved_groups(self.entry))
        if self.accounts is not None:
            return sorted(names | set(self.accounts.groups))
        return sorted(names | {group for group in (split_model_group(item.id, self.name)[0] for item in self.catalog.entries) if group})

    def refresh(self, wait_for: str | None = None) -> None:
        self.catalog = _settle(self.name, self.refetch, wait_for) if wait_for else self.refetch()
        self.accounts = _load(self)

    def readable(self) -> bool:
        """Whether the accounts could be read; when not, says why nothing can be changed."""
        if self.accounts is not None:
            return True
        if self.api.refused:
            self.say("[yellow]Nothing was changed: the management key was refused. Reopen this window and type the right key (agent-proxy's CLIPROXYAPI_MANAGEMENT_KEY).[/yellow]")
        else:
            self.say("[yellow]Nothing was changed: the proxy's accounts could not be read. Deploy agent-proxy, or check the management key (asked first in this flow), then try again.[/yellow]")
        return False


@dataclass
class _Row:
    label: str
    kind: str  # group · create · manual (all groups); models · accounts · groups · delete (a group); account · login (its accounts)
    group: str = ""
    account: ProxyAccount | None = None


def _catalog_problem(catalog: Any) -> tuple[str, str]:
    """Why the model list is missing, as (a short note for a row, a sentence for a header); empty when it was read."""
    if not getattr(catalog, "error", None):
        return "", ""
    if getattr(catalog, "error_kind", None) == "auth":
        return "the proxy refused the API key", "The proxy refused the API key: it must match agent-proxy's CLIPROXYAPI_API_KEY (the API key is asked in the provider setup, before this window). "
    return "the model list could not be read", f"The proxy did not answer ({catalog.error}): deploy it with agent-proxy, or type a model id. "


def _account_names(accounts: list[ProxyAccount], limit: int = 2) -> str:
    names = [account.email for account in accounts[:limit]]
    more = len(accounts) - limit
    return ", ".join(names) + (f" +{more}" if more > 0 else "")


def _group_rows(window: _Window) -> list[_Row]:
    """All groups: each with its accounts and models (the current one first), the accounts in no group, then a new group and a typed model id."""
    accounts = window.accounts
    current = split_model_group(window.current_model, window.name)[0] if window.current_model else None
    ordered = window.groups()
    if current in ordered:
        ordered.remove(current)
        ordered.insert(0, current)
    rows = []
    unread = bool(_catalog_problem(window.catalog)[0])
    for group in ordered:
        count = len(window.models_in(group))
        parts = [_c(_GREEN if group == current else _PEACH, group)]
        members = accounts.in_group(group) if accounts is not None else []
        if accounts is not None:
            parts.append(f"{_plural(len(members), 'account')}: {_account_names(members)}" if members else _c(_YELLOW, "no accounts yet"))
        if count:
            parts.append(_c(_GREEN, _plural(count, "model")))
        elif unread:
            parts.append(_c(_YELLOW, "models unknown"))
        elif accounts is None or members:
            parts.append(_c(_YELLOW, "no models yet"))
        label = f" {_dim('·')} ".join(parts)
        if group == current:
            label += f" {_dim('(current)')}"
        rows.append(_Row(label, "group", group))
    loose = accounts.in_group("") if accounts is not None else []
    bare = len(window.models_in(""))
    if bare or loose:
        text = f"(no group) · {_plural(bare, 'model')} on the accounts in no group"
        if loose:
            text += f" ({_account_names(loose)}); move them into a group"
        rows.append(_Row(_c(_YELLOW, text), "group", ""))
    rows.append(_Row(f"{_c(_GREEN, 'create a group…')} {_dim('· name it, then log an account into it')}", "create"))
    rows.append(_Row(_dim("type a model id…"), "manual"))
    return rows


def ask_key(entry: dict[str, Any], pickers: Pickers, name: str = PROVIDER_ID) -> tuple[str, bool] | None:
    """The management key, asked like the API key: blank keeps the saved one, or agent-proxy's default. (key, newly typed), or None when cancelled."""
    stored = str(entry.get(KEY_FIELD) or "")
    line = pickers.line(f"{name} management key (blank {'keeps current' if stored else f'= {DEFAULT_KEY}'})> ", password=True)
    if line is None:
        return None
    key = line.strip()
    return (key, True) if key and key != stored else (stored or DEFAULT_KEY, False)


#: What a level returns when Esc (or "all groups…") goes back up to the list of groups.
_UP = "up"


#: The management key each proxy took in this process (one it did not refuse), so stepping back into the window does not ask for it again.
_KEYS_IN_USE: dict[str, str] = {}


def _open(
    *,
    name: str,
    slot: str,
    base_url: str,
    entry: dict[str, Any],
    current_model: str,
    catalog: CatalogFetchResult,
    refetch: Callable[[], CatalogFetchResult],
    pickers: Pickers,
    key: str | None = None,
) -> _Window | None:
    """The management key (asked unless given), then the proxy's accounts, read once the window opens. None when the key prompt is cancelled."""
    typed = False
    if key is None:
        asked = ask_key(entry, pickers, name)
        if asked is None:
            return None
        key, typed = asked
    window = _Window(name, slot, entry, Management(management_base(base_url), key), pickers, catalog, refetch, current_model)
    window.accounts = _load(window)
    if not window.api.refused:
        _KEYS_IN_USE[window.api.base] = key
    if typed and not window.api.refused:
        # Kept once the proxy has not refused it: a mistyped key would otherwise be sent again by every later window, each one counting toward its lockout.
        _save_entry(entry, **{KEY_FIELD: key})
        exported = os.environ.get(KEY_ENV, "").strip()
        if exported and exported != key:
            # git-tools' rule: the environment beats the settings file. Said now, since blank in the next window would send the exported key.
            pickers.say(f"[yellow]Saved the management key, but {KEY_ENV} is exported in this shell and is used instead next time. Unset it (or update it) to use the saved key.[/yellow]")
    return window


def _start_group(window: _Window) -> str | None:
    """The group the window opens on: the current model's, when the proxy still has it; else all groups (None)."""
    current = split_model_group(window.current_model, window.name)[0] if window.current_model else None
    return current if current is not None and current in window.groups() else None


def _run(window: _Window, group: str | None) -> GroupChoice | None:
    """The window's levels, from ``group`` (None: all groups). Ends on a group to choose the model from, or a typed model id; None when cancelled."""
    while True:
        if group is None:
            picked = _all_groups(window)
            if picked is None or isinstance(picked, GroupChoice):
                return picked
            group, sign_in = picked
            if sign_in:
                choice = _sign_in(window, group)
                if choice is not None:
                    return choice
        result = _group(window, group)
        if isinstance(result, GroupChoice):
            return result
        group = None


def choose_group(
    *,
    name: str = PROVIDER_ID,
    slot: str = "main",
    base_url: str,
    entry: dict[str, Any],
    current_model: str,
    catalog: CatalogFetchResult,
    refetch: Callable[[], CatalogFetchResult],
    pickers: Pickers,
) -> GroupChoice | None:
    """The cliproxyapi window, in levels: all groups; one group (its models and accounts), opened at once when the current model already runs on it; and that group's accounts. Esc goes up a level. Ends on a group to choose the model from, or a typed model id; None when cancelled."""
    window = _open(name=name, slot=slot, base_url=base_url, entry=entry, current_model=current_model, catalog=catalog, refetch=refetch, pickers=pickers)
    return None if window is None else _run(window, _start_group(window))


#: What the model list returns when Esc goes back up into the window.
_BACK_TO_WINDOW = object()


def choose_model(
    *,
    name: str = PROVIDER_ID,
    slot: str = "main",
    base_url: str,
    entry: dict[str, Any],
    current_model: str,
    catalog: CatalogFetchResult,
    refetch: Callable[[], CatalogFetchResult],
    pickers: Pickers,
    about: str = MAIN_MODEL_ABOUT,
    resume: bool = False,
) -> str | None:
    """The management key, the window, then the model inside the chosen group, as agent-cli's provider flow asks them. A model typed inside a group gets the group in front. None when cancelled.

    git-tools' Esc goes back one level, so the levels are: management key, all groups, a group, its model list. Esc on the model list goes back to the group (a typed id's prompt, to all groups) without asking the management key again, and Esc on all groups goes back to the management key. In agent-cli, Esc on the model list or on all groups ends the flow. ``resume`` (back from the step after the model) opens the current model's group's list straight away, with the key the proxy already took in this process.
    """
    remembered = _KEYS_IN_USE.get(management_base(base_url)) if resume else None
    while True:
        window = _open(name=name, slot=slot, base_url=base_url, entry=entry, current_model=current_model, catalog=catalog, refetch=refetch, pickers=pickers, key=remembered)
        if window is None:
            return None
        group = _start_group(window)
        # Back from the step after the model: straight to the list it was chosen from.
        direct = remembered is not None and group is not None and bool(window.models_in(group))
        remembered = None
        while True:
            if direct:
                choice, direct = GroupChoice(group, window.catalog), False
            else:
                choice = _run(window, group)
                if choice is None:
                    break  # Esc on all groups: back to the management key
            model_id = _pick_model(name, slot, current_model, choice, pickers, about)
            if model_id is not _BACK_TO_WINDOW:
                return model_id
            group = choice.group


def _pick_model(name: str, slot: str, current_model: str, choice: GroupChoice, pickers: Pickers, about: str) -> Any:
    """The model inside the chosen group (agent-cli's provider-flow list): the model id, None when none was given, or _BACK_TO_WINDOW on Esc."""
    catalog, model_group = choice.catalog, choice.group
    # A typed model id (group None) skips the list; a group shows only its own models.
    available = [] if model_group is None else [item for item in catalog.entries if (split_model_group(item.id, name)[0] or "") == model_group]
    model_id = ""
    if available:
        current = next((item for item in available if item.id == current_model), None)
        if current is not None:  # current model first, cursor on it
            available = [current, *(item for item in available if item.id != current_model)]
        labels = []
        for item in available:
            # Within a chosen account group the group is said once, in the header, not on every line.
            label = split_model_group(item.id, name)[1] if model_group and item.label == item.id else item.label
            if item.display_name and item.display_name != item.id:
                label = f"{item.display_name} \x1b[90m({item.id})\x1b[0m"
            if item.id == current_model:
                label = f"\x1b[1;32m{label}\x1b[0m \x1b[90m(current)\x1b[0m"
            labels.append(label)
        labels.append("\x1b[90m(type a model id manually)\x1b[0m")
        header = f"\x1b[1;36m{name}\x1b[0m \x1b[90m· {slot} model\x1b[0m"
        if model_group:
            header += f" \x1b[90m· group\x1b[0m \x1b[1;36m{model_group}\x1b[0m"
        if getattr(catalog, "source", None) == "cache":
            header += " \x1b[33m· stale cache\x1b[0m"
        idx = pickers.pick(labels, header=_titled(header, about))
        if idx is None:
            return _BACK_TO_WINDOW
        if idx < len(available):
            model_id = available[idx].id
    if not model_id:
        line = pickers.line(f"{name} model> ", default=current_model)
        if line is None:
            return _BACK_TO_WINDOW
        model_id = line.strip() or current_model
        if model_group and model_id and split_model_group(model_id, name)[0] is None:
            # Typed inside a chosen group: the group goes in front, as the proxy serves it.
            model_id = f"{model_group}/{model_id}"
    if not model_id:
        pickers.say("[yellow]no model chosen — nothing changed[/yellow]")
        return None
    return model_id


def _all_groups(window: _Window) -> GroupChoice | tuple[str, bool] | None:
    """The list of groups: a group to open (with whether to log an account in first: a new group), a typed model id, or None when cancelled."""
    while True:
        rows = _group_rows(window)
        has_groups = any(row.kind == "group" for row in rows)
        about = "Pick a group for its models and accounts, or create one." if has_groups else "No account groups yet: create one, then log an account into it."
        about = _catalog_problem(window.catalog)[1] + about
        idx = window.pickers.pick([row.label for row in rows], header=_titled(f"\x1b[1;36m{window.name}\x1b[0m \x1b[90m· {window.slot} account group\x1b[0m", about))
        if idx is None:
            return None
        row = rows[idx]
        if row.kind == "manual":
            return GroupChoice(None, window.catalog)
        if row.kind == "group":
            return row.group, False
        if not window.readable():
            continue
        group = _new_group_name(window)
        if group is not None:
            window.add_group(group, pending=True)
            window.say(f"[green]Created group {safe_markup(group)}.[/green] [dim]It lasts once an account is in it.[/dim]")
            return group, True


def _load(window: _Window) -> ProxyAccounts | None:
    """The proxy's accounts, read afresh (they are never kept locally), with git-tools' group list brought in line with them. When they cannot be read, nothing is changed."""
    if window.api.refused:  # said once already, when it was refused
        return None
    try:
        accounts = load_accounts(window.api, saved_groups(window.entry))
    except ManagementError as exc:
        window.say(f"[yellow]The proxy's accounts could not be read: {safe_markup(str(exc))}[/yellow]")
        return None
    return window.sync_groups(accounts)


def _settle(name: str, refetch: Callable[[], Any], group: str) -> Any:
    """Refetch the models after a login or a move, giving the proxy a moment to load the group's new account."""
    catalog = refetch()
    for _ in range(_SETTLE_TRIES):
        if any(split_model_group(item.id, name)[0] == group for item in catalog.entries):
            break
        time.sleep(SETTLE_SECONDS)
        catalog = refetch()
    return catalog


def _account_label(account: ProxyAccount) -> str:
    state = "" if account.state == "active" else f" {_c(_YELLOW, account.state)}"
    return f"{account.email}{state} {_dim(f'· {account.provider} · {account.file}')}"


def _group_title(window: _Window, group: str, *more: str) -> str:
    where = f"group\x1b[0m \x1b[1;38;2;255;175;135m{group}\x1b[0m" if group else "no group\x1b[0m"
    return f"\x1b[1;36m{window.name}\x1b[0m \x1b[90m· {window.slot} · {where}" + "".join(f" \x1b[90m· {part}\x1b[0m" for part in more)


def _group(window: _Window, group: str) -> GroupChoice | str:
    """One group: its models, its accounts, all groups, or delete it. Ends on the group to choose the model from; _UP goes back to all groups."""
    while True:
        members = window.accounts.in_group(group) if window.accounts is not None else []
        models = window.models_in(group)
        current = split_model_group(window.current_model, window.name)[1] if window.current_model in models else ""
        # "No group" takes no login: its hints say only what is there. A model list that could not be read is said as such, not as an empty group.
        problem, problem_sentence = _catalog_problem(window.catalog)
        no_models, no_accounts = ("none yet: log an account in", "none yet: log one in") if group else ("none served", "none")
        if problem:
            no_models = problem
        rows = [
            _Row(f"{_c(_GREEN, 'models…')} {_dim('· ' + _plural(len(models), 'model') + (f' · now {current}' if current else ''))}" if models else f"models… {_c(_YELLOW, '· ' + no_models)}", "models"),
            _Row(f"{_c(_BLUE, 'accounts…')} {_dim('· ' + (_plural(len(members), 'account') + ': ' + _account_names(members) if members else no_accounts))}" if window.accounts is not None else f"{_c(_BLUE, 'accounts…')} {_c(_YELLOW, '· could not be read')}", "accounts"),
            _Row(_dim("all groups…"), "groups"),
        ]
        if group:
            rows.append(_Row(f"{_c(_RED, 'delete group…')} {_dim('· logs out its accounts')}", "delete"))
        about = problem_sentence + ("Choose the model, or manage the group's accounts: log one out, move it, or log a new one in." if group else "Accounts in no group serve the plain model names: open accounts to move each into a group.")
        idx = window.pickers.pick([row.label for row in rows], header=_titled(_group_title(window, group), about))
        if idx is None or rows[idx].kind == "groups":
            return _UP
        kind = rows[idx].kind
        if kind == "models":
            if models:
                return GroupChoice(group, window.catalog)
            if problem:
                window.say(f"[yellow]{safe_markup(problem_sentence.strip())}[/yellow]")
                window.refresh()
                continue
            window.say(f"[yellow]{'Group ' + safe_markup(group) + ' serves' if group else 'The accounts in no group serve'} no models yet: log an account in under accounts…, or wait a moment for the proxy to load one.[/yellow]")
            window.refresh()
        elif kind == "accounts":
            choice = _accounts(window, group)
            if choice is not None:
                return choice
        elif kind == "delete":
            gone = _delete_group(window, group)
            # Refreshed either way: a delete that stopped partway has logged some accounts out already.
            window.refresh()
            if gone:
                return _UP


def _accounts(window: _Window, group: str) -> GroupChoice | None:
    """A group's accounts: press one to log it out or move it, or log a new one in (then on to the group's models). None goes back to the group."""
    while True:
        if not window.readable():
            return None
        members = window.accounts.in_group(group) if window.accounts is not None else []
        rows = [_Row(_account_label(account), "account", account=account) for account in members]
        if group:
            rows.append(_Row(f"{_c(_GREEN, 'log in a new account…')} {_dim('· ChatGPT / Codex or Claude')}", "login"))
        if not rows:  # no group's accounts all moved or logged out: nothing left here
            return None
        about = "Press an account to log it out or move it to another group." + (" Or log a new one in." if group else "")
        idx = window.pickers.pick([row.label for row in rows], header=_titled(_group_title(window, group, "accounts"), about), initial=0 if members else len(rows) - 1)
        if idx is None:
            return None
        row = rows[idx]
        if row.kind == "login":
            choice = _sign_in(window, group)
            if choice is not None:
                return choice
        elif row.account is not None and _account(window, row.account, group):
            window.refresh()


def _account(window: _Window, account: ProxyAccount, group: str) -> bool:
    """An account's choices: log it out, or move it into another group. True when something changed."""
    labels = [_c(_RED, f"log out {account.email}"), _c(_BLUE, "move it to another group…"), "back"]
    where = f"group {group}" if group else "no group"
    idx = window.pickers.pick(
        labels,
        header=_titled(_group_title(window, group, account.email), f"Logging out removes its saved sign-in from the proxy (it does not revoke the account); sessions using {where} lose it."),
        initial=2,
    )
    if idx == 0:
        try:
            window.api.call("DELETE", "auth-files", params={"name": account.file})
        except ManagementError as exc:
            window.report(exc)
            return False
        window.say(f"[dim]Logged out {safe_markup(account.email)}.[/dim]")
        if group and group not in window.pending and window.accounts is not None and len(window.accounts.in_group(group)) == 1:
            window.say(f"[dim]That was group {safe_markup(group)}'s last account, so the group is gone too.[/dim]")
        return True
    if idx == 1:
        target = _pick_group(window, f"The group {account.email} moves into; sessions using {where} lose it.", skip=group or None)
        if target is None:
            return False
        try:
            _set_group(window.api, account, target)
        except ManagementError as exc:
            window.report(exc)
            return False
        window.say(f"[green]{safe_markup(account.email)} is in group {safe_markup(target)} now.[/green]")
        return True
    return False


def _new_group_name(window: _Window) -> str | None:
    taken = set(window.groups())
    while True:
        line = window.pickers.line("new group name (lowercase letters, digits and '-')> ")
        if line is None or not line.strip():
            return None
        name = line.strip()
        if not GROUP_NAME.fullmatch(name):
            window.say("[yellow]Use lowercase letters, digits and '-', starting with a letter or digit, at most 32 characters.[/yellow]")
        elif name in taken:
            window.say(f"[yellow]Group {safe_markup(name)} already exists; type another name.[/yellow]")
        else:
            return name


def _pick_group(window: _Window, about: str, *, skip: str | None = None) -> str | None:
    """An existing group, or a new one named here; either is kept in git-tools' list of group names."""
    counts = window.accounts.groups if window.accounts is not None else {}
    names = [group for group in window.groups() if group != skip]
    labels = [f"{_c(_PEACH, group)} {_dim('· ' + _plural(counts.get(group, 0), 'account'))}" for group in names]
    labels.append(_c(_GREEN, "create a group…"))
    idx = window.pickers.pick(labels, header=_titled(_title("move to group"), about))
    if idx is None:
        return None
    if idx < len(names):
        window.add_group(names[idx])
        return names[idx]
    name = _new_group_name(window)
    if name is not None:
        window.add_group(name)
        window.say(f"[dim]Created group {safe_markup(name)}.[/dim]")
    return name


def _confirm(pickers: Pickers, title: str, yes: str, about: str) -> bool:
    idx = pickers.pick([_c(_RED, yes), "no, change nothing"], header=_titled(_title(title), about), initial=1)
    return idx == 0


def _delete_group(window: _Window, group: str) -> bool:
    """Delete a group, logging its accounts out first (confirmed). True when it is gone."""
    if not window.readable():
        return False
    members = window.accounts.in_group(group) if window.accounts is not None else []
    yes = f"yes, delete group {group}" + (f" and log out {_plural(len(members), 'account')}: {_account_names(members, limit=len(members))}" if members else "")
    if not _confirm(window.pickers, f"delete group {group}", yes, "Logging out removes each account's saved sign-in from the proxy (it does not revoke the account). Sessions that ask for the group's models get a model-not-found error until they choose another group."):
        return False
    for account in members:
        try:
            window.api.call("DELETE", "auth-files", params={"name": account.file})
        except ManagementError as exc:
            window.report(exc)
            window.say(f"[yellow]Group {safe_markup(group)} was kept, since not all of its accounts were logged out.[/yellow]")
            return False
        window.say(f"[dim]Logged out {safe_markup(account.email)}.[/dim]")
    window.forget_group(group)
    window.say(f"[dim]Deleted group {safe_markup(group)}.[/dim]")
    return True


def _wait_login(api: Management, state: str, seconds: float) -> tuple[str, str]:
    """The login's status once it is no longer waiting, or after ``seconds``: ("ok" | "wait" | "error", message)."""
    deadline = time.monotonic() + seconds
    while True:
        reply = api.call("GET", "get-auth-status", params={"state": state})
        status = str(reply.get("status") or "")
        if status != "wait":
            return ("ok", "") if status == "ok" else ("error", str(reply.get("error") or status or "unknown"))
        if time.monotonic() >= deadline:
            return "wait", ""
        time.sleep(LOGIN_POLL_SECONDS)


def _sign_in(window: _Window, group: str) -> GroupChoice | None:
    """Log an account into a group, then go on to that group's models. None when it did not get that far (the reason is printed)."""
    # A group with no account yet is kept while this window is open, though the login has not landed; one that has accounts needs no keeping.
    window.add_group(group, pending=window.accounts is None or not window.accounts.in_group(group))
    idx = window.pickers.pick(
        [_c(_BLUE, provider.label) for provider in _PROVIDERS],
        header=_titled(_group_title(window, group, "log in"), "The service the account signs in to, with a browser."),
    )
    if idx is None:
        return None
    provider = _PROVIDERS[idx]
    try:
        before = {account.file: account for account in load_accounts(window.api, saved_groups(window.entry)).accounts}
        start = window.api.call("GET", provider.auth_url)
    except ManagementError as exc:
        window.report(exc)
        return None
    url, state = str(start.get("url") or ""), str(start.get("state") or "")
    if not url or not state:
        window.say("[red]The proxy did not start the sign-in (no sign-in link came back).[/red]")
        return None
    window.say(f"[bold]Sign in to {safe_markup(provider.label)}[/bold], for group [#ffaf87]{safe_markup(group)}[/#ffaf87]. Open this link, best in a private browser window so it does not reuse the account the browser is logged into:")
    window.pickers.show(url)
    window.say(f"[dim]After you sign in, the browser goes to an address like {safe_markup(provider.lands_on)}, which may not load. Copy that address from the browser and paste it here.[/dim]")
    while True:
        line = window.pickers.line("the address the browser ended on (blank: check whether the login finished)> ")
        if line is None:
            window.say("[dim]Login cancelled; no account was changed.[/dim]")
            return None
        pasted = line.strip()
        try:
            if pasted:
                window.api.call("POST", "oauth-callback", body={"provider": provider.callback, "redirect_url": pasted})
                window.say("[dim]Finishing the sign-in…[/dim]")
            status, message = _wait_login(window.api, state, LOGIN_WAIT_SECONDS if pasted else 0.0)
        except ManagementError as exc:
            if exc.status == 401 or exc.status == 0:  # a refused key, or a proxy that stopped answering: pasting again cannot help
                window.report(exc)
                return None
            window.say(f"[yellow]That address was not taken: {safe_markup(str(exc))}. Paste the whole address the browser ended on after this sign-in.[/yellow]")
            continue
        if status == "ok":
            break
        if status == "error":
            window.say(f"[red]The login did not finish: {safe_markup(message)}[/red]")
            return None
        window.say("[dim]Still waiting for the sign-in. Paste the address the browser ended on.[/dim]")
    try:
        after = load_accounts(window.api, saved_groups(window.entry))
        # The login's account: a new file of its provider, else one of its provider's files that changed. The proxy also rewrites a file when it refreshes its tokens (every 15 minutes), so when more than one existing file changed, none is guessed at.
        mine = [account for account in after.accounts if provider.owns(account)]
        new = [account for account in mine if account.file not in before]
        changed = new or [account for account in mine if before[account.file].modtime != account.modtime]
        if not changed:
            window.say("[yellow]The login finished, but no account at the proxy changed.[/yellow]")
            window.refresh()
            return None
        if not new and len(changed) > 1:
            window.say(f"[yellow]The login finished, but {len(changed)} {safe_markup(provider.label)} accounts changed at the same time (a token refresh, most likely), so none was put in a group. Find the one you signed in with under its group's accounts (or no group's) and move it.[/yellow]")
            window.refresh()
            return None
        target = group
        for account in changed:
            previous = before[account.file].group if account.file in before else ""
            keep = previous or group
            if previous and previous != group:
                # The same rule as agent-proxy's login.sh: logging in again never moves an account.
                window.say(f"[yellow]{safe_markup(account.email)} was already in group {safe_markup(previous)}: it stays there. To move it, press it under that group's accounts.[/yellow]")
                target = previous
            if account.group != keep:
                _set_group(window.api, account, keep)
            window.say(f"[green]{safe_markup(account.email)} is logged in, in group {safe_markup(keep)}.[/green]")
    except ManagementError as exc:
        window.report(exc)
        return None
    # Straight on to the group's models, once the proxy serves them.
    window.refresh(wait_for=target)
    if window.models_in(target):
        return GroupChoice(target, window.catalog)
    window.say(f"[yellow]The proxy does not serve group {safe_markup(target)}'s models yet; choose a model in a moment.[/yellow]")
    return None
