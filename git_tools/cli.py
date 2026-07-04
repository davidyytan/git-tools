"""Git Tools CLI - Typer-based command line interface.

AI-powered development automation tool that generates conventional commit messages
and comprehensive issue/pull request documentation using LLM providers.
"""

import logging
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
    reload_settings,
    settings,
)
from git_tools.settings.mappings import PROVIDERS, add_user_openrouter_model
from git_tools.generators.base import TYPER_STYLE, console, success, warning, error

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


REASONING_EFFORT_CHOICES = ("xhigh", "high", "medium", "low")

# Providers with an open-ended catalogue: the model picker offers free-text
# entry instead of restricting the user to a fixed list.
OPEN_MODEL_PROVIDERS = ("openrouter",)

# Sentinel Choice value that triggers free-text model entry in the settings menu.
ADD_MODEL_SENTINEL = "__git_tools_add_model__"

# Sentinel Choice value meaning "go up one menu level" in settings menus.
_BACK = "__git_tools_back__"


def _back_choice() -> Choice:
    return Choice("← Back", value=_BACK)


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
    """Return the first configured model name for a provider."""
    provider = normalize_provider_name(provider)
    models = list(PROVIDERS[provider]["models"].values())
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
        # Open-ended providers (OpenRouter) honor any configured slug as-is.
        if provider in OPEN_MODEL_PROVIDERS:
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


def _effective_effort(
    provider: str,
    model: str | None,
    configured_effort: str | None,
) -> str | None:
    """Resolve the effort shown in config: explicit override, then model default."""
    model_effort = _model_effort(provider, model)
    if not model_effort:
        return None

    if configured_effort:
        return configured_effort.strip().lower() or None

    return model_effort


def _format_model_choice(model_config: dict[str, Any]) -> str:
    """Format a model menu item, including effort only when the model has it."""
    model_name = model_config["model_name"]
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


def _build_model_choices(provider: str) -> list[Choice]:
    """Build model choices with per-model effort visible when present.

    Open-ended providers (OpenRouter) also get an "enter a new model" option so
    users can type any slug rather than pick from a fixed list.
    """
    provider = normalize_provider_name(provider)
    choices = [
        Choice(_format_model_choice(model_config), value=model_config["model_name"])
        for model_config in PROVIDERS[provider]["models"].values()
    ]
    if provider in OPEN_MODEL_PROVIDERS:
        choices.append(Choice("Enter a new model…", value=ADD_MODEL_SENTINEL))
    return choices


def _build_effort_choices(
    provider: str,
    model: str | None,
    configured_effort: str | None,
) -> list[Choice]:
    """Build reasoning-effort choices for effort-capable models."""
    model_effort = _model_effort(provider, model)
    choices = []

    if model_effort:
        choices.append(Choice(f"Model default ({model_effort})", value=""))
    else:
        choices.append(Choice("Unset", value=""))

    effort_values = []
    for effort in (configured_effort, model_effort, *REASONING_EFFORT_CHOICES):
        if effort:
            normalized = str(effort).strip().lower()
            if normalized and normalized not in effort_values:
                effort_values.append(normalized)

    choices.extend(Choice(effort, value=effort) for effort in effort_values)
    return choices


def _build_settings_choices(
    state: dict[str, Any],
    *,
    done_label: str = "Done",
) -> list[Choice]:
    """Build the top-level settings menu in provider/model/effort/API-key order."""
    provider = normalize_provider_name(state["provider"])
    api_status = "configured" if state["api_configured"] else "not set"
    choices = [
        Choice(f"Provider: {provider}", value="provider"),
        Choice(
            f"Model: {_format_model_display(provider, state.get('model'))}",
            value="model",
        ),
    ]

    effort = _effective_effort(
        provider,
        state.get("model"),
        state.get("reasoning_effort"),
    )
    if effort:
        source = "override" if state.get("reasoning_effort") else "model default"
        choices.append(Choice(f"Effort: {effort} ({source})", value="effort"))

    choices.extend(
        [
            Choice(f"API Key ({provider}): {api_status}", value="api-key"),
            Choice(f"Temperature: {state['temperature']}", value="temperature"),
            Choice(f"Max Tokens: {state['max_tokens']}", value="max-tokens"),
            Choice(f"Max Retries: {state['max_retries']}", value="max-retries"),
            Choice(done_label, value="done"),
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
    workflow_version: Annotated[
        Optional[str],
        typer.Option(
            "--workflow-version",
            help="Explicit X.Y.Z tuple for Start or Backmerge fixed-title PR modes when the repo state cannot infer it safely",
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
        "model": _resolve_current_model(provider, fresh.default_model),
        "reasoning_effort": fresh.default_reasoning_effort,
        "temperature": fresh.default_temperature,
        "max_tokens": fresh.default_max_tokens,
        "max_retries": fresh.default_max_retries,
        "api_configured": is_api_configured,
    }


def _edit_provider(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import check_api_key_configured, save_setting

    providers = list(PROVIDERS.keys())
    if value is None:
        selection = _ask_with_back(
            questionary.select(
                f"Select provider (current: {state['provider']}, default: {_SETTING_DEFAULTS['provider']}):",
                choices=[*providers, _back_choice()],
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
    save_setting("GIT_TOOLS_PROVIDER", selection)
    state["provider"] = selection
    state["api_configured"], _ = check_api_key_configured(selection)
    console.print()
    success(f"Provider set to {selection}")
    if provider_changed:
        # A model carried over from the old provider is meaningless on the new
        # one; keep it only when the new provider's catalogue knows it, else
        # reset to the provider default — and persist so content commands
        # never send the old provider's slug to the new endpoint.
        model_config = _find_model_config(selection, state["model"])
        new_model = (
            model_config["model_name"] if model_config else _provider_default_model(selection)
        )
        save_setting("GIT_TOOLS_DEFAULT_MODEL", new_model)
        if new_model != state["model"]:
            success(f"Model set to {new_model}")
        state["model"] = new_model


def _edit_model(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_setting

    provider = state["provider"]
    if value is None:
        provider_models = PROVIDERS[provider]["models"]
        default_model = state["model"]
        if default_model not in [m["model_name"] for m in provider_models.values()]:
            default_model = _provider_default_model(provider)
        model_choice = _ask_with_back(
            questionary.select(
                f"Select model (current: {state['model']}, default: {_provider_default_model(provider)}):",
                choices=[*_build_model_choices(provider), _back_choice()],
                default=default_model,
                style=TYPER_STYLE,
                qmark="❯",
                pointer="›",
                instruction="",
            )
        )
        if model_choice is None or model_choice == _BACK:
            return
        if model_choice == ADD_MODEL_SENTINEL:
            new_model = _ask_with_back(
                questionary.text(
                    "Enter model slug (e.g. anthropic/claude-sonnet-4.6):",
                    style=TYPER_STYLE,
                    qmark="❯",
                    instruction="",
                )
            )
            model_choice = new_model.strip() if new_model and new_model.strip() else None
            if not model_choice:
                return
            add_user_openrouter_model(model_choice)
    else:
        model_choice = value.strip()
        if not model_choice:
            error("Model cannot be empty.")
            raise typer.Exit(1)
        if provider in OPEN_MODEL_PROVIDERS:
            add_user_openrouter_model(model_choice)
        else:
            model_config = _find_model_config(provider, model_choice)
            if not model_config:
                names = ", ".join(
                    model["model_name"] for model in PROVIDERS[provider]["models"].values()
                )
                error(f"Unknown model for {provider}: {model_choice}. One of: {names}")
                raise typer.Exit(1)
            model_choice = model_config["model_name"]

    save_setting("GIT_TOOLS_DEFAULT_MODEL", model_choice)
    state["model"] = model_choice
    console.print()
    success(f"Model set to {model_choice}")


def _edit_effort(state: dict[str, Any], value: Optional[str] = None) -> None:
    from .settings.settings import save_setting

    if value is None:
        effective_effort = _effective_effort(
            state["provider"],
            state["model"],
            state["reasoning_effort"],
        )
        effort_choice = _ask_with_back(
            questionary.select(
                f"Reasoning effort (current: {effective_effort or 'unset'}):",
                choices=[
                    *_build_effort_choices(
                        state["provider"],
                        state["model"],
                        state["reasoning_effort"],
                    ),
                    _back_choice(),
                ],
                default=state["reasoning_effort"] or "",
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
        if effort_choice in {"unset", "default", "none"}:
            effort_choice = ""
        if effort_choice and effort_choice not in REASONING_EFFORT_CHOICES:
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

    save_setting(provider_api_key_env(provider), key)
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


# Menu order, and the names accepted by `git-tools settings <name> [value]`.
_SETTINGS_EDITORS: dict[str, Callable[..., None]] = {
    "provider": _edit_provider,
    "model": _edit_model,
    "effort": _edit_effort,
    "api-key": _edit_api_key,
    "temperature": _edit_temperature,
    "max-tokens": _edit_max_tokens,
    "max-retries": _edit_max_retries,
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
