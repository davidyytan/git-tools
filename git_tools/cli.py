"""Git Tools CLI - Typer-based command line interface.

AI-powered development automation tool that generates conventional commit messages
and comprehensive issue/pull request documentation using LLM providers.
"""

import logging
import os
import sys
from enum import Enum
from typing import Annotated, Any, Callable, Optional

import questionary
import typer
import typer.rich_utils
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from questionary import Choice
from rich.console import Console
from git_tools.settings.settings import (
    GitToolsSettings,
    normalize_provider_name,
    provider_api_key_env,
    provider_label,
    reload_settings,
    settings,
)
from git_tools.providers.kimi_code import KimiCodeModelEntry, default_choice_index, thinking_choices
from git_tools.providers.openrouter import OpenRouterEndpoint
from git_tools.settings.mappings import (
    LIVE_MODEL_PROVIDERS,
    PROVIDERS,
    get_live_model_refresh_error,
    is_openai_reasoning_model,
    provider_allows_manual_model,
    refresh_live_models,
    restore_provider_catalog,
    snapshot_provider_catalog,
)
from git_tools.generators.base import (
    TYPER_STYLE, console, success, warning, error,
    fmt_current, fmt_dim, fmt_ok, fmt_primary, fmt_warn, styled,
)

# Override Typer's console with configurable width offset for terminal border wrapping
_typer_width = Console(force_terminal=True).width
_width_offset = settings.console_width_offset
typer.rich_utils.MAX_WIDTH = _typer_width + _width_offset if _typer_width else 80

# ============================================================================
# CLI Application
# ============================================================================

app = typer.Typer(
    help="AI-powered tool for commit messages, issue/PR documentation, version bumping, and Commitizen-style init.",
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class BumpIncrement(str, Enum):
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    PATCH = "PATCH"


class BumpPrerelease(str, Enum):
    alpha = "alpha"
    beta = "beta"
    rc = "rc"


class BumpIncrementMode(str, Enum):
    linear = "linear"
    exact = "exact"


class CommitWorkflowKind(str, Enum):
    open_release = "open-release"


class CzConfigFile(str, Enum):
    dot_cz_toml = ".cz.toml"


def _setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for the application."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Set specific log levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def _has_interactive_terminal() -> bool:
    """Return True when stdin and stdout are interactive terminals."""
    return sys.stdin.isatty() and sys.stdout.isatty()


REASONING_EFFORT_CHOICES = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

# Sentinel Choice value that triggers free-text model entry in the settings menu.
ADD_MODEL_SENTINEL = "__git_tools_add_model__"

# Sentinel Choice value meaning "go up one menu level" in settings menus.
_BACK = "__git_tools_back__"


def _back_choice(*, plain: bool = False) -> Choice:
    """The "← Back" row; ``plain`` keeps it a bare string for searchable lists.

    questionary's type-to-filter lowercases every title, so a list that uses
    it cannot contain styled (formatted-text) rows at all.
    """
    return Choice("← Back" if plain else styled(fmt_dim("← Back")), value=_BACK)


def _ask_with_back(question: questionary.Question) -> Any:
    """Ask ``question`` with Esc bound to go back one level.

    Esc makes the prompt return None, which callers treat like "← Back".
    Ctrl+C still raises KeyboardInterrupt and exits the whole command.
    """
    esc_bindings = KeyBindings()

    @esc_bindings.add("escape", eager=True)
    def _cancel(event: Any) -> None:
        event.app.exit(result=None)

    application = question.application
    existing = application.key_bindings
    application.key_bindings = (
        merge_key_bindings([existing, esc_bindings]) if existing else esc_bindings
    )
    return question.unsafe_ask()


def _provider_default_model(provider: str) -> str:
    """The provider module's default model (its curated list leads with it)."""
    provider = normalize_provider_name(provider)
    definition = PROVIDERS[provider]
    if definition.get("default_model"):
        return definition["default_model"]
    models = list(definition["models"].values())
    return models[0]["model_name"] if models else ""


def _find_model_config(provider: str, model: str | None) -> dict[str, Any] | None:
    """Find a model mapping by key or model_name."""
    if not model:
        return None

    provider = normalize_provider_name(provider)
    models = PROVIDERS[provider]["models"]
    if model in models:
        return models[model]

    for model_config in models.values():
        if model_config.get("model_name") == model:
            return model_config

    return None


def _resolve_current_model(provider: str, configured_model: str | None) -> str:
    """Return a provider-valid model name, falling back to the provider default."""
    provider = normalize_provider_name(provider)
    if configured_model:
        # Live/manual providers honor any configured model ID as-is. Their real
        # catalogue is the endpoint's, not the static fallback — displacing a
        # live-only or explicitly entered model here would show the wrong value
        # and persist it on the next provider switch.
        if provider in LIVE_MODEL_PROVIDERS or provider_allows_manual_model(provider):
            return configured_model
        provider_model_names = [
            model["model_name"] for model in PROVIDERS[provider]["models"].values()
        ]
        if configured_model in provider_model_names:
            return configured_model
        if configured_model in PROVIDERS[provider]["models"]:
            return PROVIDERS[provider]["models"][configured_model]["model_name"]
    return _provider_default_model(provider)


def _model_effort(provider: str, model: str | None) -> str | None:
    """Return the per-model reasoning effort if that model declares one."""
    model_config = _find_model_config(provider, model)
    if not model_config:
        return None
    effort = model_config.get("reasoning_effort")
    return str(effort).strip().lower() if effort else None


def _ensure_kimi_catalog(provider: str) -> None:
    """Load the account-aware Kimi catalog once so effort/thinking metadata is current.

    Kimi's valid efforts and thinking modes come from its live ``/models``.
    Without this, a direct ``settings effort`` would validate against the
    built-in entries, which declare none, and the client would reject the
    saved value at generation time. The refresh is memoized per process.
    """
    if provider == "kimicli":
        refresh_live_models(provider)


def _declared_kimi_efforts(provider: str, model: str | None) -> list[str]:
    """Efforts the Kimi catalog declares for ``model``; empty when it declares none.

    The account-aware Kimi catalog is authoritative: when it lists efforts, the
    picker and the direct setter accept exactly those, and the client
    constructor rejects anything else.
    """
    if provider != "kimicli":
        return []
    metadata = _find_model_config(provider, model) or {}
    think_efforts = metadata.get("think_efforts", {})
    declared = think_efforts.get("valid_efforts", []) if isinstance(think_efforts, dict) else []
    if not isinstance(declared, list):
        return []
    return [effort for effort in declared if isinstance(effort, str) and effort.strip()]


def _effective_effort(
    provider: str,
    model: str | None,
    configured_effort: str | None,
) -> str | None:
    """Resolve the effort shown in config: explicit override, then model default."""
    if configured_effort:
        return configured_effort.strip().lower() or None
    return _model_effort(provider, model)


def _format_model_choice(model_config: dict[str, Any]) -> str:
    """Format a model menu item, including effort only when the model has it."""
    model_name = model_config["model_name"]
    display = model_config.get("display_name")
    if isinstance(display, str) and display.strip() and display != model_name:
        model_name = f"{display.strip()} ({model_name})"
    effort = model_config.get("reasoning_effort")
    if effort:
        return f"{model_name} (effort: {str(effort).strip().lower()})"
    return model_name


def _format_model_display(provider: str, model: str | None) -> str:
    """Format the current model value without duplicating the separate effort row."""
    model_config = _find_model_config(provider, model)
    if model_config:
        return model_config["model_name"]
    return model or _provider_default_model(provider)


def _build_provider_choices(current_provider: str) -> list[Choice]:
    """Build provider rows from registry metadata, similar to agent-cli."""
    current_provider = normalize_provider_name(current_provider)
    choices: list[Choice] = []
    for provider, definition in PROVIDERS.items():
        label = str(definition.get("label") or provider)
        endpoint = str(definition.get("default_base_url") or "custom endpoint")
        parts = [fmt_primary(label), fmt_dim(f" [{provider}] — {endpoint}")]
        if provider == current_provider:
            parts.append(fmt_current())
        choices.append(Choice(styled(*parts), value=provider))
    return choices


def _build_model_choices(
    provider: str,
    *,
    current_model: str | None = None,
) -> list[Choice]:
    """Build provider-aware choices with the current model first and marked."""
    provider = normalize_provider_name(provider)
    choices: list[Choice] = []
    current_choice: Choice | None = None
    for model_config in PROVIDERS[provider]["models"].values():
        model_id = model_config["model_name"]
        title = _format_model_choice(model_config)
        choice = Choice(
            f"{title} (current)" if model_id == current_model else title,
            value=model_id,
        )
        if model_id == current_model:
            current_choice = choice
        else:
            choices.append(choice)

    if current_model:
        choices.insert(
            0,
            current_choice or Choice(f"{current_model} (current)", value=current_model),
        )
    if provider_allows_manual_model(provider):
        choices.append(Choice("Enter a model ID manually…", value=ADD_MODEL_SENTINEL))
    return choices


# Catalogs longer than this get type-to-filter on top of the arrow-key list.
_SEARCHABLE_CATALOG_SIZE = 15


def _ask_model_choice(
    provider: str,
    *,
    current_model: str,
    default_model: str,
) -> str | None:
    """Pick a model from a list; large live catalogs add type-to-filter.

    OpenRouter, OpenAI and local proxies can expose hundreds of models, so past
    ``_SEARCHABLE_CATALOG_SIZE`` entries the list gains a search filter: the
    current model starts highlighted, arrows move, typing narrows, Enter picks
    the highlighted entry. A free-text autocomplete was used before, but it
    pre-typed the current model's title, so nothing else matched until the
    whole line was erased. Manual IDs stay reachable through the explicit
    "Enter a model ID manually…" entry.
    """
    model_rows = _build_model_choices(provider, current_model=current_model)
    searchable = len(model_rows) + 1 > _SEARCHABLE_CATALOG_SIZE
    # Every title must stay a plain string when the filter is on (see _back_choice).
    choices = [*model_rows, _back_choice(plain=searchable)]
    prompt = (
        f"Select model (current: {current_model or 'unset'}, "
        f"default: {_provider_default_model(provider)}):"
    )
    default = default_model if any(choice.value == default_model for choice in choices) else None
    selected = _ask_with_back(
        questionary.select(
            prompt,
            choices=choices,
            default=default,
            style=TYPER_STYLE,
            qmark="❯",
            pointer="›",
            use_search_filter=searchable,
            use_jk_keys=not searchable,
            instruction=(
                "(↑↓ move · type to filter · Enter picks · Esc back)"
                if searchable else "(↑↓ move · Enter picks · Esc back)"
            ),
        )
    )
    return None if selected is None or selected == _BACK else str(selected)


def _build_effort_choices(
    provider: str,
    model: str | None,
    configured_effort: str | None,
) -> list[Choice]:
    """Build reasoning-effort choices for effort-capable models."""
    model_effort = _model_effort(provider, model)
    choices = []
    configured = (configured_effort or "").strip().lower()

    def tier(effort: str) -> Choice:
        parts = [fmt_primary(effort)]
        if effort == configured:
            parts.append(fmt_current())
        return Choice(styled(*parts), value=effort)

    declared_efforts = _declared_kimi_efforts(provider, model)
    if declared_efforts:
        return [Choice(styled(fmt_dim("Model default")), value=""),
                *[tier(effort) for effort in declared_efforts]]

    if model_effort:
        choices.append(Choice(styled(fmt_dim(f"Model default ({model_effort})")), value=""))
    else:
        choices.append(Choice(styled(fmt_dim("Unset")), value=""))

    effort_values = []
    for effort in (configured_effort, model_effort, *REASONING_EFFORT_CHOICES):
        if effort:
            normalized = str(effort).strip().lower()
            if normalized and normalized not in effort_values:
                effort_values.append(normalized)

    choices.extend(tier(effort) for effort in effort_values)
    return choices


def _build_settings_choices(
    state: dict[str, Any],
    *,
    done_label: str = "Done",
) -> list[Choice]:
    """Build the top-level settings menu in provider/model/effort/API-key order."""
    provider = normalize_provider_name(state["provider"])
    api_status = fmt_ok("configured") if state["api_configured"] else fmt_warn("not set")
    choices = [
        Choice(styled("Provider: ", fmt_primary(provider)), value="provider"),
        Choice(
            styled("Main Model: ", fmt_primary(_format_model_display(provider, state.get("model")))),
            value="model",
        ),
    ]

    choices.extend([
        Choice(styled("Support Model (unused): ", fmt_dim(state.get("support_model", "follow-main"))),
               value="support-model"),
        Choice(styled("API Endpoint"), value="api-base"),
    ])
    if provider == "openrouter":
        choices.append(Choice(
            styled("OpenRouter upstream routing: ", fmt_primary(state.get("openrouter_provider") or "any")),
            value="openrouter-provider",
        ))
    if provider == "kimicli":
        # Thinking and tier are one row, as in agent-cli's Kimi picker.
        choices.append(Choice(styled("Kimi thinking: ", fmt_primary(_kimi_thinking_summary(state))),
                              value="kimi-thinking"))

    effort = _effective_effort(
        provider,
        state.get("model"),
        state.get("reasoning_effort"),
    )
    # OpenAI only honours a tier on its reasoning families; the row would be a
    # dead setting for gpt-4.x/4o, so it is shown for reasoning models only.
    effort_capable = (
        is_openai_reasoning_model(state.get("model") or "")
        if provider in {"openai", "cliproxyapi"}
        else provider in {"openrouter", "qwen", "acrc", "copilot", "anthropic"}
    )
    if provider != "kimicli" and (effort or effort_capable):
        source = "override" if state.get("reasoning_effort") else "model default"
        choices.append(Choice(
            styled("Effort: ", fmt_primary(effort), fmt_dim(f" ({source})")), value="effort",
        ))

    pr_limit = (
        styled("PR Limit: ", fmt_primary("auto"), fmt_dim(" (enabled only for Azure DevOps)"))
        if state.get("azure_pr_limit", "auto") == "auto"
        else styled("PR Limit: ", fmt_primary("disabled"))
    )
    choices.extend(
        [
            Choice(styled(f"API Key ({provider}): ", api_status), value="api-key"),
            Choice(styled("Temperature: ", fmt_primary(state["temperature"])), value="temperature"),
            Choice(styled("Max Tokens: ", fmt_primary(state["max_tokens"])), value="max-tokens"),
            Choice(styled("Max Retries: ", fmt_primary(state["max_retries"])), value="max-retries"),
            Choice(pr_limit, value="azure-pr-limit"),
            Choice(styled("PR Max Chars: ", fmt_primary(state.get("azure_pr_max_chars", 4000))),
                   value="azure-pr-max-chars"),
            Choice(styled(fmt_dim(done_label) if done_label.startswith("←") else done_label), value="done"),
        ]
    )
    return choices


# ============================================================================
# Main Callback
# ============================================================================


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Show interactive menu when no subcommand is provided."""
    _setup_logging()

    if ctx.invoked_subcommand is not None:
        return
    if not _has_interactive_terminal():
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    while True:
        try:
            choice = questionary.select(
                "Select command:",
                choices=[
                    Choice("commit", value="commit"),
                    Choice("issue", value="issue"),
                    Choice("pr", value="pr"),
                    Choice("bump", value="bump"),
                    Choice("init", value="init"),
                    Choice("settings", value="settings"),
                    Choice("exit", value="exit"),
                ],
                style=TYPER_STYLE,
                qmark="❯",
                pointer="›",
                instruction="",
            ).ask()
        except KeyboardInterrupt:
            warning("Operation cancelled by user.")
            raise typer.Exit(0)

        if choice is None or choice == "exit":
            raise typer.Exit(0)

        # Settings is a detour, not a destination: leaving it lands back here.
        if choice == "settings":
            try:
                _run_settings_menu(done_label="← Back")
            except (KeyboardInterrupt, EOFError):
                warning("Operation cancelled by user.")
                raise typer.Exit(0)
            # Content commands read the settings singleton; pick up any edits.
            reload_settings()
            continue

        # Invoke the selected command with interactive=True
        command_map = {
            "commit": commit,
            "issue": issue,
            "pr": pr,
            "bump": bump,
            "init": init_command,
        }
        ctx.invoke(command_map[choice], interactive=True)
        return


# ============================================================================
# Commit Command
# ============================================================================


@app.command()
def commit(
    model: Annotated[
        Optional[str],
        typer.Option("--model", "-m", help="Model name (e.g., 'anthropic/claude-sonnet-4')"),
    ] = None,
    temperature: Annotated[
        Optional[float],
        typer.Option("--temp", "-t", help="Temperature (0.0-2.0)"),
    ] = None,
    max_tokens: Annotated[
        Optional[int],
        typer.Option("--max-tokens", help="Maximum tokens for completion"),
    ] = None,
    token_limit: Annotated[
        Optional[int],
        typer.Option("--token-limit", "-l", help="Token limit for diff processing"),
    ] = None,
    scope: Annotated[
        Optional[bool],
        typer.Option("--scope/--no-scope", help="Include conventional commit scope"),
    ] = None,
    footer: Annotated[
        Optional[bool],
        typer.Option("--footer/--no-footer", help="Include conventional commit footer"),
    ] = None,
    auto_commit: Annotated[
        Optional[bool],
        typer.Option("--commit/--no-commit", help="Commit changes directly"),
    ] = None,
    copy: Annotated[
        Optional[bool],
        typer.Option("--copy/--no-copy", help="Copy to clipboard"),
    ] = None,
    force_sensitive: Annotated[
        bool,
        typer.Option("--force-sensitive", help="Allow committing sensitive files without confirmation"),
    ] = False,
    workflow_kind: Annotated[
        Optional[CommitWorkflowKind],
        typer.Option(
            "--workflow-kind",
            help="Create the fixed chore: open release commit subject instead of generating a normal Conventional Commit",
        ),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", hidden=True, help="Run in interactive mode"),
    ] = False,
) -> None:
    """Generate a conventional commit message or the release opener subject.

    Examples:
        git-tools commit
        git-tools commit --model anthropic/claude-sonnet-4
        git-tools commit --no-scope --no-footer --commit
        git-tools commit --workflow-kind open-release
    """
    from .generators.commitgen import CommitGenerator

    try:
        generator = CommitGenerator(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            token_limit=token_limit,
            include_scope=scope,
            include_footer=footer,
            auto_commit=auto_commit,
            copy_clipboard=copy,
            force_sensitive=force_sensitive,
            workflow_kind=workflow_kind.value if workflow_kind is not None else None,
            interactive=interactive,
        )
        generator.generate_commit()
    except KeyboardInterrupt:
        warning("Operation cancelled by user.")
        raise typer.Exit(0)
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        error("An unexpected error occurred. Please check the logs.")
        raise typer.Exit(1)


# ============================================================================
# Issue Command
# ============================================================================


@app.command()
def issue(
    base: Annotated[
        Optional[str],
        typer.Option("--base", "-b", help="Base branch to compare against"),
    ] = None,
    source: Annotated[
        Optional[str],
        typer.Option("--source", "-s", help="Input source: 'd' (diffs), 'c' (commits), 'b' (both)"),
    ] = None,
    context: Annotated[
        Optional[str],
        typer.Option("--context", "-c", help="Additional context for generation"),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", "-m", help="Model name"),
    ] = None,
    temperature: Annotated[
        Optional[float],
        typer.Option("--temp", "-t", help="Temperature (0.0-2.0)"),
    ] = None,
    max_tokens: Annotated[
        Optional[int],
        typer.Option("--max-tokens", help="Maximum tokens for completion"),
    ] = None,
    token_limit: Annotated[
        Optional[int],
        typer.Option("--token-limit", "-l", help="Token limit for diff processing"),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", hidden=True, help="Run in interactive mode"),
    ] = False,
) -> None:
    """Generate a GitHub issue from recent commits.

    Examples:
        git-tools issue
        git-tools issue --base develop
        git-tools issue --base main --source b
    """
    from .generators.issueprgen import IssuePullRequestGenerator

    try:
        generator = IssuePullRequestGenerator(
            generation_type="issue",
            base_branch=base,
            input_source=source,
            context=context,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            token_limit=token_limit,
            interactive=interactive,
        )
        generator.generate_issue_pullrequest()
    except KeyboardInterrupt:
        warning("Operation cancelled by user.")
        raise typer.Exit(0)
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        error("An unexpected error occurred. Please check the logs.")
        raise typer.Exit(1)


# ============================================================================
# PR Command
# ============================================================================


@app.command()
def pr(
    base: Annotated[
        Optional[str],
        typer.Option("--base", "-b", help="Base branch to compare against"),
    ] = None,
    source: Annotated[
        Optional[str],
        typer.Option("--source", "-s", help="Input source: 'd' (diffs), 'c' (commits), 'b' (both)"),
    ] = None,
    context: Annotated[
        Optional[str],
        typer.Option("--context", "-c", help="Additional context for generation"),
    ] = None,
    release_pr: Annotated[
        Optional[bool],
        typer.Option(
            "--release-pr/--no-release-pr",
            help="Use release-promotion PR guidance for release/* -> master",
        ),
    ] = None,
    hotfix_pr: Annotated[
        Optional[bool],
        typer.Option(
            "--hotfix-pr/--no-hotfix-pr",
            help="Use hotfix-promotion PR guidance for hotfix/* -> master",
        ),
    ] = None,
    start_pr: Annotated[
        Optional[bool],
        typer.Option(
            "--start-pr/--no-start-pr",
            help="Use fixed-title develop PR guidance for the PR that must land as Start X.Y.Z on develop",
        ),
    ] = None,
    backmerge_release_pr: Annotated[
        Optional[bool],
        typer.Option(
            "--backmerge-release-pr/--no-backmerge-release-pr",
            help="Use fixed-title backmerge guidance for release/* -> develop PRs",
        ),
    ] = None,
    backmerge_hotfix_pr: Annotated[
        Optional[bool],
        typer.Option(
            "--backmerge-hotfix-pr/--no-backmerge-hotfix-pr",
            help="Use fixed-title backmerge guidance for hotfix/* -> develop PRs",
        ),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", "-m", help="Model name"),
    ] = None,
    temperature: Annotated[
        Optional[float],
        typer.Option("--temp", "-t", help="Temperature (0.0-2.0)"),
    ] = None,
    max_tokens: Annotated[
        Optional[int],
        typer.Option("--max-tokens", help="Maximum tokens for completion"),
    ] = None,
    token_limit: Annotated[
        Optional[int],
        typer.Option("--token-limit", "-l", help="Token limit for diff processing"),
    ] = None,
    azure_limit: Annotated[
        Optional[bool],
        typer.Option(
            "--pr-limit/--no-pr-limit",
            "--azure-limit/--no-azure-limit",
            help="Apply the configured PR description limit on any host (auto: Azure on, GitHub/unknown off)",
        ),
    ] = None,
    workflow_version: Annotated[
        Optional[str],
        typer.Option(
            "--workflow-version",
            help="Explicit X.Y.Z tuple for Start/Backmerge modes; required for noninteractive hotfix backmerge (use the already-promoted version)",
        ),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", hidden=True, help="Run in interactive mode"),
    ] = False,
) -> None:
    """Generate a pull request description from recent commits.

    Examples:
        git-tools pr
        git-tools pr --base develop
        git-tools pr --base main --source b
        git-tools pr --release-pr
        git-tools pr --hotfix-pr
        git-tools pr --start-pr --workflow-version 1.7.0
        git-tools pr --backmerge-release-pr --workflow-version 1.6.0
        git-tools pr --backmerge-hotfix-pr --workflow-version 1.6.1
    """
    from .generators.issueprgen import IssuePullRequestGenerator

    try:
        if (
            sum(
                1
                for flag in (
                    release_pr,
                    hotfix_pr,
                    start_pr,
                    backmerge_release_pr,
                    backmerge_hotfix_pr,
                )
                if flag
            )
            > 1
        ):
            error(
                "Use only one of --start-pr, --release-pr, --hotfix-pr, "
                "--backmerge-release-pr, or --backmerge-hotfix-pr."
            )
            raise typer.Exit(1)

        generator = IssuePullRequestGenerator(
            generation_type="pr",
            base_branch=base,
            input_source=source,
            release_pr=release_pr,
            hotfix_pr=hotfix_pr,
            start_pr=start_pr,
            backmerge_release_pr=backmerge_release_pr,
            backmerge_hotfix_pr=backmerge_hotfix_pr,
            workflow_version=workflow_version,
            context=context,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            token_limit=token_limit,
            azure_limit=azure_limit,
            interactive=interactive,
        )
        generator.generate_issue_pullrequest()
    except KeyboardInterrupt:
        warning("Operation cancelled by user.")
        raise typer.Exit(0)
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        error("An unexpected error occurred. Please check the logs.")
        raise typer.Exit(1)


# ============================================================================
# Bump Command
# ============================================================================


@app.command()
def bump(
    increment: Annotated[
        Optional[BumpIncrement],
        typer.Option("--increment", help="Explicit MAJOR, MINOR, or PATCH increment"),
    ] = None,
    default_increment: Annotated[
        Optional[BumpIncrement],
        typer.Option(
            "--default-increment",
            help="Fallback MAJOR, MINOR, or PATCH increment for conventional commit types outside the built-in bump rules",
        ),
    ] = None,
    prerelease: Annotated[
        Optional[BumpPrerelease],
        typer.Option("--prerelease", help="Create or continue an alpha, beta, or rc prerelease"),
    ] = None,
    increment_mode: Annotated[
        BumpIncrementMode,
        typer.Option("--increment-mode", help="Choose linear or exact prerelease bump behavior"),
    ] = BumpIncrementMode.linear,
    allow_no_commit: Annotated[
        bool,
        typer.Option("--allow-no-commit", help="Allow bumping even when no new commits are found"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the computed bump without changing files or git state"),
    ] = False,
    get_next: Annotated[
        bool,
        typer.Option("--get-next", help="Print only the next version"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Treat a missing current-version tag as an initial tag"),
    ] = False,
    create_tag: Annotated[
        bool,
        typer.Option("--tag/--no-tag", help="Create or skip the git tag for this bump"),
    ] = True,
    annotated_tag: Annotated[
        bool,
        typer.Option("--annotated-tag", help="Create an annotated tag"),
    ] = False,
    gpg_sign: Annotated[
        bool,
        typer.Option("--gpg-sign", help="Create a signed tag"),
    ] = False,
    annotated_tag_message: Annotated[
        Optional[str],
        typer.Option("--annotated-tag-message", help="Custom tag message for annotated or signed tags"),
    ] = None,
    respect_git_config: Annotated[
        bool,
        typer.Option(
            "--respect-git-config/--ignore-git-config",
            help="Respect or ignore git config such as tag.gpgSign during tag creation",
        ),
    ] = True,
    check_consistency: Annotated[
        bool,
        typer.Option("--check-consistency/--no-check-consistency", help="Require managed version fields to match before writing"),
    ] = True,
    major_version_zero: Annotated[
        Optional[bool],
        typer.Option("--major-version-zero/--no-major-version-zero", help="Override major-version-zero behavior for this run"),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", hidden=True, help="Run in interactive mode"),
    ] = False,
) -> None:
    """Bump version from Conventional Commits and optionally create the matching tag.

    Examples:
        git-tools bump
        git-tools bump --dry-run
        git-tools bump --increment MINOR --prerelease alpha --gpg-sign
        git-tools bump --prerelease alpha --default-increment PATCH --no-tag
        git-tools bump --prerelease alpha --default-increment PATCH --gpg-sign
        git-tools bump --get-next
    """
    from .generators.bumpgen import BumpError
    from .generators.bumpgen import BumpGenerator

    try:
        generator = BumpGenerator(
            increment=increment.value if increment else None,
            default_increment=default_increment.value if default_increment else None,
            prerelease=prerelease.value if prerelease else None,
            increment_mode=increment_mode.value,
            allow_no_commit=allow_no_commit,
            check_consistency=check_consistency,
            dry_run=dry_run,
            get_next=get_next,
            yes=yes,
            create_tag=create_tag,
            annotated_tag=annotated_tag,
            gpg_sign=gpg_sign,
            annotated_tag_message=annotated_tag_message,
            respect_git_config=respect_git_config,
            major_version_zero=major_version_zero,
            interactive=interactive,
        )
        generator.generate_bump()
    except KeyboardInterrupt:
        warning("Operation cancelled by user.")
        raise typer.Exit(0)
    except BumpError as e:
        error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        error("An unexpected error occurred. Please check the logs.")
        raise typer.Exit(1)


# ============================================================================
# Commitizen-Compatible Init Command
# ============================================================================


@app.command("init")
def init_command(
    config_file: Annotated[
        Optional[CzConfigFile],
        typer.Option("--config-file", help="Choose the Commitizen config file to create or update (.cz.toml only)"),
    ] = None,
    version: Annotated[
        Optional[str],
        typer.Option(
            "--version",
            help=(
                "Initial version to write. Scheme is auto-detected: semver2 "
                "(1.0.0-alpha.0) or semver (1.0.0-a0)."
            ),
        ),
    ] = None,
    tag_format: Annotated[
        Optional[str],
        typer.Option("--tag-format", help="Tag format, for example $version or v$version"),
    ] = None,
    major_version_zero: Annotated[
        Optional[bool],
        typer.Option("--major-version-zero/--no-major-version-zero", help="Treat breaking changes as MINOR while major version is zero"),
    ] = None,
    defaults: Annotated[
        bool,
        typer.Option("--defaults", help="Write config using detected defaults without prompting"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Update the existing Commitizen config in place"),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", hidden=True, help="Run in interactive mode"),
    ] = False,
) -> None:
    """Create a Commitizen-compatible config for git-tools.

    Examples:
        git-tools init
        git-tools init --defaults
        git-tools init --version 0.1.0
    """
    from .generators.initgen import CommitizenInitGenerator, CzInitError

    use_interactive = interactive

    try:
        generator = CommitizenInitGenerator(
            config_file=config_file.value if config_file else None,
            version=version,
            tag_format=tag_format,
            major_version_zero=major_version_zero,
            force=force,
            interactive=use_interactive,
        )
        generator.generate_init()
    except KeyboardInterrupt:
        warning("Operation cancelled by user.")
        raise typer.Exit(0)
    except CzInitError as e:
        error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        error("An unexpected error occurred. Please check the logs.")
        raise typer.Exit(1)


# ============================================================================
# Settings Command
# ============================================================================

# Defaults shown alongside settings prompts, sourced from the pydantic field
# defaults so they cannot drift from what an unset value actually resolves to.
_SETTING_DEFAULTS = {
    "azure_pr_max_chars": GitToolsSettings.model_fields["azure_pr_max_chars"].default,
    "provider": GitToolsSettings.model_fields["default_provider"].default,
    "temperature": GitToolsSettings.model_fields["default_temperature"].default,
    "max_tokens": GitToolsSettings.model_fields["default_max_tokens"].default,
    "max_retries": GitToolsSettings.model_fields["default_max_retries"].default,
}


def _load_settings_state() -> dict[str, Any]:
    """Re-read persisted settings; the import-time singleton would be stale
    when the menu is re-entered after edits in the same session."""
    from .settings.settings import GitToolsSettings, check_api_key_configured

    fresh = GitToolsSettings()
    provider = normalize_provider_name(fresh.default_provider)
    is_api_configured, _ = check_api_key_configured(provider)
    return {
        "provider": provider,
        "model": _resolve_current_model(provider, fresh.effective_main_model),
        "support_model": fresh.support_model,
        "api_base": os.environ.get("GIT_TOOLS_API_BASE", ""),
        "openrouter_provider": fresh.openrouter_provider,
        "kimi_thinking": fresh.kimi_thinking,
        "reasoning_effort": fresh.default_reasoning_effort,
        "temperature": fresh.default_temperature,
        "max_tokens": fresh.default_max_tokens,
        "max_retries": fresh.default_max_retries,
        "api_configured": is_api_configured,
        "azure_pr_limit": fresh.azure_pr_limit,
        "azure_pr_max_chars": fresh.azure_pr_max_chars,
    }


def _prompt_provider_api_key(provider: str) -> tuple[bool, str | None]:
    """Ask for a provider key before catalog discovery.

    Returns ``(proceed, new_key)``. Blank keeps an existing environment/file or
    provider-default key and returns ``None`` as ``new_key``. A typed key is not
    persisted yet: the caller temporarily applies it for discovery and saves it
    only after model selection completes.
    """
    from .settings.settings import check_api_key_configured

    configured, _ = check_api_key_configured(provider)
    label = provider_label(provider)
    suffix = " (blank keeps current)" if configured else ""
    value = _ask_with_back(
        questionary.password(
            f"Enter your {label} API key{suffix}:",
            style=TYPER_STYLE,
            qmark="❯",
        )
    )
    if value is None:
        return False, None

    key = value.strip()
    if key:
        return True, key
    if configured:
        return True, None

    warning(f"{label} needs an API key before models can be detected.")
    return False, None


def _edit_provider(state: dict[str, Any], value: Optional[str] = None,
                   *, interactive: Optional[bool] = None) -> None:
    """Select endpoint before discovery, restoring process state on cancellation."""
    from .settings.settings import save_settings

    interactive_flow = (value is None or _has_interactive_terminal()) if interactive is None else interactive
    if not interactive_flow and value is None:
        error("Non-interactive provider setup requires a provider name.")
        raise typer.Exit(1)
    old_provider = state["provider"]
    selection = normalize_provider_name(value) if value is not None else None
    if selection is None:
        selection = _ask_with_back(questionary.select(
            "Select provider:", choices=[*_build_provider_choices(old_provider), _back_choice()],
            default=old_provider, style=TYPER_STYLE, qmark="❯",
        ))
        if selection in (None, _BACK):
            return
    if selection not in PROVIDERS:
        error(f"Unknown provider: {selection}")
        raise typer.Exit(1)
    changed = selection != old_provider
    old_base = os.environ.get("GIT_TOOLS_API_BASE")
    # A switch applies the provider's own endpoint: the custom one remembered
    # under its key when there is one, else the module default (agent-cli
    # keeps a base URL per provider profile; agent-core never inherits
    # another provider's endpoint).
    endpoint = _provider_endpoint(selection) if changed else _current_api_base(selection)
    if selection == "qwen" and interactive_flow:
        endpoint = _ask_with_back(questionary.text(
            "Qwen API endpoint (exact plan/region URL):", default=endpoint or "",
            style=TYPER_STYLE, qmark="❯",
        ))
        if endpoint is None:
            return
        endpoint = _validate_api_base(endpoint)
    # Explicit provider selection is allowed before Qwen endpoint configuration;
    # generation/discovery will fail safely until the endpoint is supplied.
    os.environ["GIT_TOOLS_API_BASE"] = endpoint or ""
    try:
        if interactive_flow:
            _edit_provider_impl(state, None, selected_provider=selection, endpoint=endpoint)
        else:
            _edit_provider_impl(state, selection, endpoint=endpoint)
        if state["provider"] != selection:
            return
        state["api_base"] = endpoint or ""
        if changed and not interactive_flow:
            state["support_model"] = "follow-main"
            state["openrouter_provider"] = None
    finally:
        if old_base is None:
            os.environ.pop("GIT_TOOLS_API_BASE", None)
        else:
            os.environ["GIT_TOOLS_API_BASE"] = old_base


def _prompt_provider_options(
    provider: str, model: str, state: dict[str, Any], changed: bool,
) -> dict[str, str] | None:
    """Collect the rest of setup without saving partial selections.

    On a provider change the prompts start from that provider's remembered
    profile (agent-cli seeds its flow from the provider's profile the same
    way); otherwise from the current values.
    """
    profile = _remembered_profile(provider) if changed else {}
    current_support = profile.get("support_model") if changed else state.get("support_model")
    support = _ask_with_back(questionary.select(
        "Support model (reserved, unused):",
        choices=[Choice("Follow main dynamically", value="follow-main"),
                 *_build_model_choices(provider, current_model=current_support
                                       if current_support and current_support != "follow-main" else None),
                 _back_choice()], style=TYPER_STYLE, qmark="❯"))
    if support in (None, _BACK):
        return None
    if support == ADD_MODEL_SENTINEL:
        support = _ask_with_back(questionary.text("Support model ID:", style=TYPER_STYLE, qmark="❯"))
        if support is None or not support.strip():
            return None
    updates = {"GIT_TOOLS_MODEL_SUPPORT": support.strip(),
               "GIT_TOOLS_OPENROUTER_PROVIDER": (profile.get("openrouter_provider") or "") if changed
               else state.get("openrouter_provider") or "",
               "GIT_TOOLS_REASONING_EFFORT": (profile.get("reasoning_effort") or "") if changed
               else state.get("reasoning_effort") or "",
               "GIT_TOOLS_KIMI_THINKING": ""}
    if provider == "openrouter":
        from .settings.mappings import fetch_openrouter_endpoints
        from .settings.settings import load_provider_config
        config = load_provider_config(provider)
        endpoints = fetch_openrouter_endpoints(config.base_url, config.api_key, model)
        remembered_pin = updates["GIT_TOOLS_OPENROUTER_PROVIDER"] or "any"
        tags = [entry.tag for entry in endpoints]
        pin = _ask_with_back(questionary.select(
            "OpenRouter upstream for the main model:",
            choices=[_any_upstream_choice(),
                     *[_upstream_choice(entry, remembered_pin) for entry in endpoints],
                     Choice("Enter upstream slug manually", value=ADD_MODEL_SENTINEL), _back_choice()],
            default=remembered_pin if remembered_pin in ("any", *tags) else None,
            style=TYPER_STYLE, qmark="❯"))
        if pin in (None, _BACK):
            return None
        if pin == ADD_MODEL_SENTINEL:
            pin = _ask_with_back(questionary.text("Upstream slug:", style=TYPER_STYLE, qmark="❯"))
            if pin is None or not pin.strip():
                return None
        updates["GIT_TOOLS_OPENROUTER_PROVIDER"] = "" if pin == "any" else pin.strip().lower()
    if provider == "kimicli":
        # Thinking and tier are one choice, from the catalog entry (agent-cli).
        remembered = profile.get("kimi_thinking") if changed else (
            None if state.get("kimi_thinking") is None else str(bool(state.get("kimi_thinking"))).lower())
        current_thinking = {"true": True, "false": False}.get(remembered or "")
        picked = _pick_kimi_thinking(
            provider, model, current_thinking, updates["GIT_TOOLS_REASONING_EFFORT"] or None,
            keep_current=not changed and model == state.get("model"),
        )
        if picked is None:
            return None
        thinking, effort = picked
        updates["GIT_TOOLS_KIMI_THINKING"] = "" if thinking is None else str(thinking).lower()
        updates["GIT_TOOLS_REASONING_EFFORT"] = effort or ""
        return updates
    if provider in {"openai", "cliproxyapi"}:
        effort_capable = is_openai_reasoning_model(model)
    else:
        effort_capable = (provider in {"openrouter", "qwen", "anthropic"}
                          or bool(_model_effort(provider, model))
                          or model.lower().startswith(("gpt-", "o1", "o3", "o4", "codex-")))
    if effort_capable:
        effort = _ask_with_back(questionary.select(
            "Reasoning effort:", choices=[*_build_effort_choices(provider, model, updates["GIT_TOOLS_REASONING_EFFORT"]), _back_choice()],
            style=TYPER_STYLE, qmark="❯"))
        if effort in (None, _BACK):
            return None
        updates["GIT_TOOLS_REASONING_EFFORT"] = effort
    return updates


def _edit_provider_impl(state: dict[str, Any], value: Optional[str] = None,
                        *, selected_provider: Optional[str] = None,
                        endpoint: Optional[str] = None) -> None:
    from .settings.settings import check_api_key_configured, save_setting, save_settings

    providers = list(PROVIDERS.keys())
    interactive_flow = value is None
    if selected_provider is not None:
        selection = selected_provider
    elif value is None:
        selection = _ask_with_back(
            questionary.select(
                f"Select provider (current: {state['provider']}, default: {_SETTING_DEFAULTS['provider']}):",
                choices=[*_build_provider_choices(state["provider"]), _back_choice()],
                default=state["provider"] if state["provider"] in providers else _SETTING_DEFAULTS["provider"],
                style=TYPER_STYLE,
                qmark="❯",
                pointer="›",
                instruction="",
            )
        )
        if selection is None or selection == _BACK:
            return
    else:
        selection = normalize_provider_name(value)
        if selection not in PROVIDERS:
            error(f"Unknown provider: {value}. One of: {', '.join(providers)}")
            raise typer.Exit(1)

    provider_changed = selection != state["provider"]

    if interactive_flow:
        proceed, new_key = _prompt_provider_api_key(selection)
        if not proceed:
            return

        env_var = provider_api_key_env(selection)
        old_env_present = env_var in os.environ
        old_env_value = os.environ.get(env_var)
        catalog_snapshot = snapshot_provider_catalog(selection)
        if new_key is not None:
            # Provider config reads process env first. Apply the candidate key
            # for discovery. On success it remains authoritative in this process;
            # cancellation or an exception restores the caller's old value.
            os.environ[env_var] = new_key
        try:
            # A switch starts from the target provider's remembered model.
            current_model = state["model"] if not provider_changed else (_remembered_profile(selection)["model"] or "")
            new_model = _choose_provider_model(selection, current_model)
            setup_choices = None
            if new_model is not None:
                setup_choices = _prompt_provider_options(selection, new_model, state, provider_changed)
                if setup_choices is None:
                    new_model = None
        except BaseException:
            restore_provider_catalog(selection, catalog_snapshot)
            if new_key is not None:
                if old_env_present:
                    os.environ[env_var] = old_env_value or ""
                else:
                    os.environ.pop(env_var, None)
            raise
        if new_model is None:
            restore_provider_catalog(selection, catalog_snapshot)
            if new_key is not None:
                if old_env_present:
                    os.environ[env_var] = old_env_value or ""
                else:
                    os.environ.pop(env_var, None)
            return

        # Persist provider, optional key, and model in one atomic file replace.
        # A write failure restores the exact process environment used before
        # setup, so the whole operation remains transactional.
        updates: dict[str, str | None] = {
            "GIT_TOOLS_PROVIDER": selection,
            "GIT_TOOLS_DEFAULT_MODEL": new_model,
            "GIT_TOOLS_MODEL_MAIN": new_model,
        }
        if endpoint is not None:
            updates["GIT_TOOLS_API_BASE"] = endpoint
        if provider_changed:
            updates.update({"GIT_TOOLS_MODEL_SUPPORT": "follow-main",
                            "GIT_TOOLS_OPENROUTER_PROVIDER": "",
                            "GIT_TOOLS_REASONING_EFFORT": "",
                            "GIT_TOOLS_KIMI_THINKING": ""})
        updates.update(setup_choices or {})
        if new_key is not None:
            updates = {env_var: new_key, **updates}
        try:
            save_settings(updates)
        except BaseException:
            restore_provider_catalog(selection, catalog_snapshot)
            if new_key is not None:
                if old_env_present:
                    os.environ[env_var] = old_env_value or ""
                else:
                    os.environ.pop(env_var, None)
            raise
        state["provider"] = selection
        state["model"] = new_model
        state["support_model"] = updates["GIT_TOOLS_MODEL_SUPPORT"]
        state["openrouter_provider"] = updates.get("GIT_TOOLS_OPENROUTER_PROVIDER") or None
        state["reasoning_effort"] = updates.get("GIT_TOOLS_REASONING_EFFORT") or None
        thinking = updates.get("GIT_TOOLS_KIMI_THINKING", "")
        state["kimi_thinking"] = None if not thinking else thinking == "true"
        state["api_configured"] = bool(new_key) or check_api_key_configured(selection)[0]
        console.print()
        success(f"Provider set to {selection}")
        if new_key is not None:
            success(f"{provider_label(selection)} API key saved.")
        success(f"Model set to {new_model}")
        return

    # Direct `settings provider <name>` remains non-interactive and preserves
    # the previous behavior: switch immediately and select a valid fallback.
    updates: dict[str, str | None] = {"GIT_TOOLS_PROVIDER": selection}
    if endpoint is not None:
        updates["GIT_TOOLS_API_BASE"] = endpoint
    if provider_changed:
        # The target provider's profile comes back: its remembered model and
        # sub-choices, else the provider default and a clean slate.
        profile = _remembered_profile(selection)
        refresh_live_models(selection)
        model_config = _find_model_config(selection, profile["model"] or state["model"])
        if model_config:
            new_model = model_config["model_name"]
        else:
            new_model = profile["model"] or _provider_default_model(selection)
        updates.update({"GIT_TOOLS_DEFAULT_MODEL": new_model, "GIT_TOOLS_MODEL_MAIN": new_model,
                        "GIT_TOOLS_MODEL_SUPPORT": profile["support_model"] or "follow-main",
                        "GIT_TOOLS_OPENROUTER_PROVIDER": profile["openrouter_provider"] or "",
                        "GIT_TOOLS_REASONING_EFFORT": profile["reasoning_effort"] or "",
                        "GIT_TOOLS_KIMI_THINKING": profile["kimi_thinking"] or ""})
    save_settings(updates)
    state["provider"] = selection
    state["api_configured"], _ = check_api_key_configured(selection)
    if provider_changed:
        state["model"] = new_model
        state["support_model"] = updates["GIT_TOOLS_MODEL_SUPPORT"]
        state["openrouter_provider"] = updates["GIT_TOOLS_OPENROUTER_PROVIDER"] or None
        state["reasoning_effort"] = updates["GIT_TOOLS_REASONING_EFFORT"] or None
        thinking = updates["GIT_TOOLS_KIMI_THINKING"]
        state["kimi_thinking"] = None if not thinking else thinking == "true"
    console.print()
    success(f"Provider set to {selection}")


def _print_model_catalog_status(provider: str, live: bool) -> None:
    """Explain whether the interactive model list is live or a fallback."""
    provider = normalize_provider_name(provider)
    if PROVIDERS[provider].get("curated_models"):
        console.print("[dim]model list: curated choices; manual IDs accepted[/dim]")
        return
    if live:
        console.print("[dim]model list: live from the provider[/dim]")
        return

    failure = get_live_model_refresh_error(provider)
    label = provider_label(provider)
    if failure is None:
        warning(
            f"Could not load {label}'s live model catalog; "
            "showing available saved/fallback models."
        )
        return

    available = (
        "showing the last successful catalog"
        if failure.retained_live_catalog
        else "showing available saved/fallback models"
    )
    if failure.kind == "auth":
        status = f"HTTP {failure.status}" if failure.status else "authentication failed"
        key_env = provider_api_key_env(provider)
        source = " in the process environment" if os.environ.get(key_env) else ""
        warning(
            f"{label} model auto-detection failed ({status}). Check "
            f"{key_env}{source}; {available}."
        )
        return

    status = f"HTTP {failure.status}" if failure.status else failure.kind
    detail = " ".join(failure.message.split())[:160]
    warning(
        f"{label} model auto-detection failed ({status}: {detail}); {available}."
    )


def _choose_provider_model(provider: str, current_model: str) -> str | None:
    """Discover and choose a model for one provider without persisting it."""
    live = refresh_live_models(provider, force=True)
    _print_model_catalog_status(provider, live)
    default_model = current_model or _provider_default_model(provider)
    model_choice = _ask_model_choice(
        provider,
        current_model=current_model,
        default_model=default_model,
    )
    if model_choice is None:
        return None
    if model_choice == ADD_MODEL_SENTINEL:
        new_model = _ask_with_back(
            questionary.text(
                f"Enter {provider} model ID:",
                default=current_model,
                style=TYPER_STYLE,
                qmark="❯",
                instruction="",
            )
        )
        model_choice = new_model.strip() if new_model and new_model.strip() else None
        if not model_choice:
            return None
    # A typed id is remembered only as the saved main model (agent-cli pins the
    # saved model first in the picker; there is no separate list of manual ids).
    return model_choice


def _list_openrouter_endpoints(model: str) -> list[OpenRouterEndpoint]:
    """The upstreams OpenRouter can route ``model`` to, cheapest input first; empty when unknown."""
    from .settings.mappings import fetch_openrouter_endpoints
    from .settings.settings import load_provider_config

    try:
        config = load_provider_config("openrouter")
    except ValueError:
        return []
    return list(fetch_openrouter_endpoints(config.base_url, config.api_key, model))


def _list_openrouter_upstreams(model: str) -> list[str]:
    """Upstream slugs OpenRouter can route ``model`` to; empty when unknown."""
    return [entry.tag for entry in _list_openrouter_endpoints(model)]


def _upstream_choice(entry: OpenRouterEndpoint, current: Optional[str]) -> Choice:
    """One upstream row as agent-cli shows it: name, slug, price, context, caching, uptime."""
    parts = [fmt_primary(entry.label)]
    if entry.tag != entry.label:
        parts.append(fmt_dim(f" [{entry.tag}]"))
    detail = entry.detail_text()
    if detail:
        parts.append(fmt_dim(f" — {detail}"))
    if entry.tag == current:
        parts.append(fmt_current())
    return Choice(styled(*parts), value=entry.tag)


def _any_upstream_choice() -> Choice:
    return Choice(styled(fmt_dim("Any — let OpenRouter choose; caching may reset between turns")), value="any")


def _upstream_serves(pin: str, upstreams: list[str]) -> bool:
    """Whether ``pin`` names one of ``upstreams`` (``deepinfra`` matches ``deepinfra/fp4``)."""
    wanted = pin.strip().lower()
    return any(wanted in {tag.lower(), tag.lower().split("/", 1)[0]} for tag in upstreams)


def _prompt_openrouter_upstream(model: str, current: Optional[str]) -> Optional[str]:
    """Pick which upstream OpenRouter routes ``model`` to.

    Upstream availability is per model, so the list is fetched live for the
    model being configured. Returns the slug, ``""`` to let OpenRouter route,
    or ``None`` when the user backs out. When the list cannot be fetched the
    current pin is still offered rather than silently dropped: an unpinned run
    can migrate between upstreams and lose its prompt cache.
    """
    endpoints = _list_openrouter_endpoints(model)
    manual = "__manual_upstream__"
    choices: list[Choice] = []
    if endpoints:
        choices.extend(_upstream_choice(entry, current) for entry in endpoints)
    else:
        warning(f"Could not list OpenRouter upstreams for {model}.")
        if current:
            choices.append(Choice(
                styled(fmt_current(f"Keep current pin: {current}"), fmt_dim(" (unverified)")), value=current,
            ))
    choices.extend([_any_upstream_choice(),
                    Choice(styled(fmt_dim("Enter upstream slug manually")), value=manual), _back_choice()])
    default = current if current and any(choice.value == current for choice in choices) else None
    value = _ask_with_back(questionary.select(
        f"OpenRouter upstream for {model}:", choices=choices, default=default,
        style=TYPER_STYLE, qmark="❯"))
    if value in (None, _BACK):
        return None
    if value == manual:
        value = _ask_with_back(questionary.text("Upstream slug:", style=TYPER_STYLE, qmark="❯"))
        if value is None:
            return None
    pin = value.strip().lower()
    return "" if pin in {"", "any", "default", "unpinned"} else pin


def _reconcile_openrouter_upstream(model: str, pin: str) -> str:
    """Keep ``pin`` for ``model`` only while it is known to serve it.

    A non-interactive model change cannot ask, so the pin is checked against
    the model's live upstream list. A pin that verifiably does not serve the
    model is cleared, because a pinned request cannot fall back and would fail
    outright; an unverifiable one is kept with a warning rather than dropped.
    """
    upstreams = _list_openrouter_upstreams(model)
    if not upstreams:
        warning(f"Could not verify that upstream {pin} serves {model}; keeping the pin. "
                "Use `git-tools settings openrouter-provider` to change it.")
        return pin
    if _upstream_serves(pin, upstreams):
        return pin
    warning(f"Upstream {pin} does not serve {model}; OpenRouter routing reset to any. "
            "Use `git-tools settings openrouter-provider` to pin one.")
    return ""


def _edit_model(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_settings

    provider = state["provider"]
    current_pin = state.get("openrouter_provider") or None
    pin = current_pin or ""
    if value is None:
        model_choice = _choose_provider_model(provider, state["model"])
        if model_choice is None:
            return
        # Upstream availability is per model (provider > model > upstream), so
        # a new OpenRouter model re-asks the pin instead of inheriting one that
        # may not serve it. Nothing is saved until both are chosen.
        if provider == "openrouter" and model_choice != state["model"]:
            chosen = _prompt_openrouter_upstream(model_choice, current_pin)
            if chosen is None:
                return
            pin = chosen
    else:
        model_choice = value.strip()
        if not model_choice:
            error("Model cannot be empty.")
            raise typer.Exit(1)
        model_config = _find_model_config(provider, model_choice)
        if model_config:
            model_choice = model_config["model_name"]
        elif not provider_allows_manual_model(provider):
            names = ", ".join(
                model["model_name"] for model in PROVIDERS[provider]["models"].values()
            )
            error(f"Unknown model for {provider}: {model_choice}. One of: {names}")
            raise typer.Exit(1)
        if provider == "openrouter" and current_pin and model_choice != state["model"]:
            pin = _reconcile_openrouter_upstream(model_choice, current_pin)

    # Model and routing are saved together so a failed write leaves neither
    # half applied.
    updates = {"GIT_TOOLS_DEFAULT_MODEL": model_choice, "GIT_TOOLS_MODEL_MAIN": model_choice}
    routing_changed = provider == "openrouter" and pin != (current_pin or "")
    if routing_changed:
        updates["GIT_TOOLS_OPENROUTER_PROVIDER"] = pin
    save_settings(updates)
    state["model"] = model_choice
    if routing_changed:
        state["openrouter_provider"] = pin or None
    console.print()
    success(f"Model set to {model_choice}")
    if routing_changed:
        success(f"OpenRouter routing set to {pin or 'any (unpinned)'}")


def _edit_effort(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_setting

    _ensure_kimi_catalog(state["provider"])
    if value is None:
        effective_effort = _effective_effort(
            state["provider"],
            state["model"],
            state["reasoning_effort"],
        )
        choices = _build_effort_choices(state["provider"], state["model"], state["reasoning_effort"])
        # A saved tier the model's catalog no longer declares is not offered;
        # questionary rejects a default outside the list, so fall back to the
        # model default and say why.
        configured = (state["reasoning_effort"] or "").strip().lower()
        default = configured if any(choice.value == configured for choice in choices) else ""
        if configured and default != configured:
            warning(
                f"Saved effort {configured} is not one of this model's tiers; "
                "pick a listed tier or the model default."
            )
        effort_choice = _ask_with_back(
            questionary.select(
                f"Reasoning effort (current: {effective_effort or 'unset'}):",
                choices=[*choices, _back_choice()],
                default=default,
                style=TYPER_STYLE,
                qmark="❯",
                pointer="›",
                instruction="",
            )
        )
        if effort_choice is None or effort_choice == _BACK:
            return
    else:
        effort_choice = value.strip().lower()
        if effort_choice in {"unset", "default"}:
            effort_choice = ""
        # The direct setter accepts exactly what the picker offers: the model's
        # catalog efforts when it declares them, otherwise the global ladder.
        declared_efforts = _declared_kimi_efforts(state["provider"], state["model"])
        if effort_choice and declared_efforts and effort_choice not in declared_efforts:
            error(
                f"Invalid effort for {state['model']}: {value}. "
                f"One of: {', '.join(declared_efforts)} (or 'unset')"
            )
            raise typer.Exit(1)
        if effort_choice and not declared_efforts and effort_choice not in REASONING_EFFORT_CHOICES:
            error(
                f"Invalid effort: {value}. One of: {', '.join(REASONING_EFFORT_CHOICES)} (or 'unset')"
            )
            raise typer.Exit(1)

    save_setting("GIT_TOOLS_REASONING_EFFORT", effort_choice)
    state["reasoning_effort"] = effort_choice or None
    console.print()
    if effort_choice:
        success(f"Effort override set to {effort_choice}")
    else:
        model_effort = _model_effort(state["provider"], state["model"])
        if model_effort:
            success(f"Effort reset to model default ({model_effort})")
        else:
            success("Effort override cleared")


def _edit_api_key(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import provider_api_key_env, provider_label, save_setting

    provider = state["provider"]
    direct = value is not None
    if not direct:
        value = _ask_with_back(
            questionary.password(
                f"Enter your {provider_label(provider)} API key:",
                style=TYPER_STYLE,
                qmark="❯",
            )
        )
        if value is None:
            return

    key = value.strip()
    if not key:
        if direct:
            error("API key cannot be empty.")
            raise typer.Exit(1)
        return

    env_var = provider_api_key_env(provider)
    save_setting(env_var, key)
    # Make the new key authoritative for any model discovery in this process;
    # environment variables otherwise outrank the just-written settings file.
    os.environ[env_var] = key
    state["api_configured"] = True
    console.print()
    success("API key saved.")


def _edit_number(
    state: dict[str, Any],
    *,
    state_key: str,
    env_var: str,
    label: str,
    parse: Callable[[str], Any],
    is_valid: Callable[[Any], bool],
    invalid_message: str,
    range_message: str,
    value: Optional[str] = None,
) -> None:
    from .settings.settings import save_setting

    direct = value is not None
    if not direct:
        value = _ask_with_back(
            questionary.text(
                f"{label} (current: {state[state_key]}, default: {_SETTING_DEFAULTS[state_key]}):",
                default=str(state[state_key]),
                style=TYPER_STYLE,
                qmark="❯",
                instruction="",
            )
        )
        if not value:
            return

    try:
        parsed = parse(value)
    except ValueError:
        if direct:
            error(invalid_message)
            raise typer.Exit(1)
        console.print()
        warning(invalid_message)
        return
    if not is_valid(parsed):
        if direct:
            error(range_message)
            raise typer.Exit(1)
        console.print()
        warning(range_message)
        return

    save_setting(env_var, str(parsed))
    state[state_key] = parsed
    console.print()
    success(f"{label} set to {parsed}")


def _edit_temperature(state: dict[str, Any], value: Optional[str] = None) -> None:
    _edit_number(
        state,
        state_key="temperature",
        env_var="GIT_TOOLS_DEFAULT_TEMPERATURE",
        label="Temperature",
        parse=float,
        is_valid=lambda temp: 0.0 <= temp <= 2.0,
        invalid_message="Invalid temperature value.",
        range_message="Temperature must be between 0.0 and 2.0",
        value=value,
    )


def _edit_max_tokens(state: dict[str, Any], value: Optional[str] = None) -> None:
    _edit_number(
        state,
        state_key="max_tokens",
        env_var="GIT_TOOLS_DEFAULT_MAX_TOKENS",
        label="Max tokens",
        parse=int,
        is_valid=lambda tokens: tokens > 0,
        invalid_message="Invalid max tokens value.",
        range_message="Max tokens must be greater than 0",
        value=value,
    )


def _edit_max_retries(state: dict[str, Any], value: Optional[str] = None) -> None:
    _edit_number(
        state,
        state_key="max_retries",
        env_var="GIT_TOOLS_DEFAULT_MAX_RETRIES",
        label="Max retries",
        parse=int,
        is_valid=lambda retries: retries >= 0,
        invalid_message="Invalid max retries value.",
        range_message="Max retries must be 0 or greater",
        value=value,
    )


def _edit_azure_pr_limit(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_setting

    if value is None:
        value = _ask_with_back(questionary.select(
            "PR limit mode (auto enables limiting only for Azure DevOps):",
            choices=[Choice("auto (enabled only for Azure DevOps)", value="auto"),
                     Choice("false (disabled)", value="false"), _back_choice()],
            default=state["azure_pr_limit"], style=TYPER_STYLE,
        ))
        if value is None or value == _BACK:
            return
    mode = value.strip().lower()
    if mode not in {"auto", "false"}:
        error("PR limit must be auto or false.")
        raise typer.Exit(1)
    save_setting("GIT_TOOLS_AZURE_PR_LIMIT", mode)
    state["azure_pr_limit"] = mode
    success(f"PR limit saved as {mode}")


def _edit_azure_pr_max_chars(state: dict[str, Any], value: Optional[str] = None) -> None:
    _edit_number(
        state, state_key="azure_pr_max_chars", env_var="GIT_TOOLS_AZURE_PR_MAX_CHARS",
        label="PR max chars", parse=int, is_valid=lambda n: 1 <= n <= 4000,
        invalid_message="PR max chars must be an integer.",
        range_message="PR max chars must be between 1 and 4000 UTF-16 units.",
        value=value,
    )


def _current_api_base(provider: str) -> str:
    from .settings.settings import load_provider_config

    try:
        return load_provider_config(provider).base_url or ""
    except ValueError:
        return os.environ.get("GIT_TOOLS_API_BASE", PROVIDERS[provider]["default_base_url"])


def _provider_endpoint(provider: str) -> str:
    """The endpoint a switch to ``provider`` applies: remembered custom, else default."""
    from .settings.settings import saved_provider_base_url

    return saved_provider_base_url(provider) or PROVIDERS[provider]["default_base_url"]


def _remembered_profile(provider: str) -> dict[str, str | None]:
    """The target provider's remembered choices (its profile), to seed a switch."""
    from .settings.settings import saved_provider_profile

    return saved_provider_profile(provider)


def _validate_api_base(value: str) -> str:
    from urllib.parse import urlsplit

    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        error("Endpoint must be an HTTP(S) URL without credentials, query, or fragment.")
        raise typer.Exit(1)
    return value


def _edit_api_base(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_setting

    if value is None:
        value = _ask_with_back(questionary.text(
            "API endpoint:", default=_current_api_base(state["provider"]),
            style=TYPER_STYLE, qmark="❯"))
        if value is None:
            return
    endpoint = _validate_api_base(value)
    save_setting("GIT_TOOLS_API_BASE", endpoint)
    state["api_base"] = endpoint
    success("API endpoint saved.")


def _edit_support_model(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_setting

    if value is None:
        provider = state["provider"]
        live = refresh_live_models(provider, force=True)
        _print_model_catalog_status(provider, live)
        value = _ask_with_back(questionary.select(
            "Support model (reserved, unused):",
            choices=[Choice("Follow main dynamically", value="follow-main"),
                     *_build_model_choices(provider, current_model=state.get("support_model")
                                           if state.get("support_model") != "follow-main" else None),
                     _back_choice()], style=TYPER_STYLE, qmark="❯"))
        if value in (None, _BACK):
            return
        if value == ADD_MODEL_SENTINEL:
            value = _ask_with_back(questionary.text("Support model ID:", style=TYPER_STYLE, qmark="❯"))
            if value is None:
                return
    model = value.strip()
    if not model:
        error("Support model cannot be empty; use follow-main.")
        raise typer.Exit(1)
    save_setting("GIT_TOOLS_MODEL_SUPPORT", model)
    state["support_model"] = model
    success("Support model saved (not used for generation).")


def _edit_openrouter_provider(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_setting

    if value is None:
        pin = _prompt_openrouter_upstream(state["model"], state.get("openrouter_provider") or None)
        if pin is None:
            return
    else:
        pin = value.strip().lower()
        if pin in {"any", "default", "unpinned"}:
            pin = ""
    save_setting("GIT_TOOLS_OPENROUTER_PROVIDER", pin)
    state["openrouter_provider"] = pin or None
    success("OpenRouter routing saved.")


def _kimi_entry(provider: str, model: str) -> KimiCodeModelEntry:
    """The model's catalog record; an empty one when the catalog has none."""
    config = _find_model_config(provider, model) or {}
    return KimiCodeModelEntry.from_payload({**config, "id": model}) or KimiCodeModelEntry(id=model)


def _kimi_thinking_summary(state: dict[str, Any]) -> str:
    """The one-word state of the combined Kimi choice: off, on, a tier, or default."""
    thinking = state.get("kimi_thinking")
    effort = (state.get("reasoning_effort") or "").strip().lower()
    if thinking is False:
        return "off"
    if effort and effort != "none":
        return effort
    if thinking is True:
        return "on"
    return "default"


def _pick_kimi_thinking(
    provider: str, model: str, current_thinking: Optional[bool], current_effort: Optional[str],
    *, keep_current: bool = False,
) -> tuple[Optional[bool], Optional[str]] | None:
    """agent-cli's Kimi picker: one list of off, on, or the declared tiers.

    Returns ``(thinking, effort)``. The catalog decides without asking when
    the model is thinking-only or has no thinking; an incomplete record is
    not guessed from (``keep_current`` keeps the current choice for the same
    model, else nothing is set). ``None`` means the user backed out.
    """
    entry = _kimi_entry(provider, model)
    choices = thinking_choices(entry)
    if entry.supports_thinking_type == "no":
        return (False, None)
    if entry.supports_thinking_type == "only" and not choices:
        return (True, None)
    if not choices:
        return (current_thinking, current_effort) if keep_current else (None, None)
    index = default_choice_index(entry, choices, current_thinking=current_thinking, current_effort=current_effort)
    rows: list[Choice] = []
    for position, (label, _enabled, _effort) in enumerate(choices):
        parts = [fmt_primary(label)]
        if position == index and current_thinking is not None:
            parts.append(fmt_current())
        rows.append(Choice(styled(*parts), value=position))
    picked = _ask_with_back(questionary.select(
        f"Kimi thinking for {model}:", choices=[*rows, _back_choice()], default=rows[index],
        style=TYPER_STYLE, qmark="❯", pointer="›", instruction="",
    ))
    if picked in (None, _BACK):
        return None
    _label, thinking, effort = choices[picked]
    return (thinking, effort)


def _edit_kimi_thinking(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_setting, save_settings

    _ensure_kimi_catalog(state["provider"])
    if value is None:
        picked = _pick_kimi_thinking(
            state["provider"], state["model"], state.get("kimi_thinking"),
            state.get("reasoning_effort"), keep_current=True,
        )
        if picked is None:
            return
        thinking, effort = picked
        rendered = "" if thinking is None else str(thinking).lower()
        save_settings({"GIT_TOOLS_KIMI_THINKING": rendered, "GIT_TOOLS_REASONING_EFFORT": effort or ""})
        state["kimi_thinking"] = thinking
        state["reasoning_effort"] = effort or None
        success("Kimi thinking saved.")
        return
    choice = {"off": "disabled", "on": "enabled"}.get(value.strip().lower(), value.strip().lower())
    if choice in _declared_kimi_efforts(state["provider"], state["model"]):
        # A tier names the thinking choice directly, as in agent-cli's picker.
        save_settings({"GIT_TOOLS_KIMI_THINKING": "true", "GIT_TOOLS_REASONING_EFFORT": choice})
        state["kimi_thinking"] = True
        state["reasoning_effort"] = choice
        success("Kimi thinking saved.")
        return
    metadata = _find_model_config(state["provider"], state["model"]) or {}
    mode = metadata.get("supports_thinking_type")
    if (mode == "only" and choice in {"disabled", "false"}) or (mode == "no" and choice in {"enabled", "true"}):
        error("Thinking choice is not supported by the selected model's catalog.")
        raise typer.Exit(1)
    if choice not in {"default", "enabled", "disabled", "true", "false"}:
        error("Kimi thinking must be default, enabled, or disabled.")
        raise typer.Exit(1)
    rendered = "" if choice == "default" else str(choice in {"enabled", "true"}).lower()
    configured_effort = (state.get("reasoning_effort") or "").strip().lower()
    if rendered == "false" and configured_effort:
        # agent-cli's picker chooses thinking and tier together, so "off" never
        # leaves a tier behind; the split editors here do the same explicitly.
        save_settings({"GIT_TOOLS_KIMI_THINKING": rendered, "GIT_TOOLS_REASONING_EFFORT": ""})
        state["reasoning_effort"] = None
    else:
        save_setting("GIT_TOOLS_KIMI_THINKING", rendered)
    state["kimi_thinking"] = None if not rendered else rendered == "true"
    success("Kimi thinking saved.")
    if rendered == "false" and configured_effort:
        success(f"Effort override {configured_effort} cleared: thinking is off, so no tier is sent.")
    elif rendered == "true" and configured_effort:
        declared = _declared_kimi_efforts(state["provider"], state["model"])
        if declared and configured_effort not in declared:
            warning(
                f"Saved effort {configured_effort} is not one of this model's tiers "
                f"({', '.join(declared)}); set one with `git-tools settings effort` before generating."
            )


# Menu order, and the names accepted by `git-tools settings <name> [value]`.
_SETTINGS_EDITORS: dict[str, Callable[..., None]] = {
    "provider": _edit_provider,
    "model": _edit_model,
    "main-model": _edit_model,
    "support-model": _edit_support_model,
    "sub-model": _edit_support_model,
    "api-base": _edit_api_base,
    "endpoint": _edit_api_base,
    "openrouter-provider": _edit_openrouter_provider,
    "kimi-thinking": _edit_kimi_thinking,
    "effort": _edit_effort,
    "api-key": _edit_api_key,
    "temperature": _edit_temperature,
    "max-tokens": _edit_max_tokens,
    "max-retries": _edit_max_retries,
    "pr-limit": _edit_azure_pr_limit,
    "pr-max-chars": _edit_azure_pr_max_chars,
    "azure-pr-limit": _edit_azure_pr_limit,
    "azure-pr-max-chars": _edit_azure_pr_max_chars,
}


def _run_settings_menu(*, done_label: str = "Done") -> None:
    """Interactive settings menu; Esc or the last row leaves it."""
    state = _load_settings_state()
    while True:
        choice = _ask_with_back(
            questionary.select(
                "Select setting to edit:",
                choices=_build_settings_choices(state, done_label=done_label),
                style=TYPER_STYLE,
                qmark="❯",
                pointer="›",
                instruction="",
            )
        )
        if choice is None or choice == "done":
            return
        _SETTINGS_EDITORS[choice](state)
        console.print()


@app.command(name="settings")
def settings_command(
    name: Annotated[
        Optional[str],
        typer.Argument(
            help="Setting to edit: " + " · ".join(_SETTINGS_EDITORS),
            show_default=False,
        ),
    ] = None,
    value: Annotated[
        Optional[str],
        typer.Argument(help="New value; omit to edit interactively", show_default=False),
    ] = None,
    interactive: Annotated[Optional[bool], typer.Option(
        "--interactive/--non-interactive",
        help="Provider setup: force the wizard or save a named provider without prompts.",
    )] = None,
) -> None:
    """Edit git-tools settings.

    Bare ``git-tools settings`` opens an interactive picker; ``git-tools
    settings <name> [value]`` goes straight to one setting. Values are saved
    to ~/.git-tools/settings.env.
    """
    try:
        if name is not None:
            key = name.strip().lower().replace("_", "-")
            editor = _SETTINGS_EDITORS.get(key)
            if editor is None:
                error(f"Unknown setting: {name}. One of: {' · '.join(_SETTINGS_EDITORS)}")
                raise typer.Exit(1)
            if key == "provider":
                use_wizard = interactive if interactive is not None else (value is None or _has_interactive_terminal())
                if use_wizard and not _has_interactive_terminal():
                    error("Interactive provider setup requires an interactive terminal. Use --non-interactive with a provider name for scripts.")
                    raise typer.Exit(1)
                _edit_provider(_load_settings_state(), value, interactive=use_wizard)
                return
            if interactive is not None:
                error("--interactive/--non-interactive applies to provider setup only.")
                raise typer.Exit(1)
            if value is None and not _has_interactive_terminal():
                error("git-tools settings requires an interactive terminal (or pass a value).")
                raise typer.Exit(1)
            editor(_load_settings_state(), value)
            return

        if not _has_interactive_terminal():
            error("git-tools settings requires an interactive terminal.")
            raise typer.Exit(1)
        _run_settings_menu()
    except (KeyboardInterrupt, EOFError):
        warning("Operation cancelled by user.")
        raise typer.Exit(0)


if __name__ == "__main__":
    app()
