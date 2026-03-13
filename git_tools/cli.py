"""Git Tools CLI - Typer-based command line interface.

AI-powered development automation tool that generates conventional commit messages
and comprehensive issue/pull request documentation using LLM providers.
"""

import logging
import sys
from enum import Enum
from typing import Annotated, Optional

import questionary
import typer
import typer.rich_utils
from questionary import Choice
from rich.console import Console
from git_tools.config.config import settings
from git_tools.generators.base import TYPER_STYLE, console, warning, error

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


class BumpVersionSource(str, Enum):
    auto = "auto"
    commitizen = "commitizen"
    pyproject = "pyproject"


class CzConfigFile(str, Enum):
    dot_cz_toml = ".cz.toml"
    cz_toml = "cz.toml"
    pyproject = "pyproject.toml"


class CzVersionProvider(str, Enum):
    commitizen = "commitizen"
    pep621 = "pep621"
    uv = "uv"


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


# ============================================================================
# Main Callback
# ============================================================================


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Show interactive menu when no subcommand is provided."""
    _setup_logging()

    if ctx.invoked_subcommand is None:
        if not _has_interactive_terminal():
            typer.echo(ctx.get_help())
            raise typer.Exit(0)

        try:
            choice = questionary.select(
                "Select command:",
                choices=[
                    Choice("commit", value="commit"),
                    Choice("issue", value="issue"),
                    Choice("pr", value="pr"),
                    Choice("bump", value="bump"),
                    Choice("init", value="init"),
                    Choice("config", value="config"),
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

        # Invoke the selected command with interactive=True
        command_map = {
            "commit": commit,
            "issue": issue,
            "pr": pr,
            "bump": bump,
            "init": init_command,
            "config": config,
        }
        if choice == "config":
            ctx.invoke(command_map[choice])
        elif choice in {"bump", "init"}:
            ctx.invoke(command_map[choice], interactive=True)
        else:
            ctx.invoke(command_map[choice], interactive=True)


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
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", hidden=True, help="Run in interactive mode"),
    ] = False,
) -> None:
    """Generate a conventional commit message from staged changes.

    Examples:
        git-tools commit
        git-tools commit --model anthropic/claude-sonnet-4
        git-tools commit --no-scope --no-footer --commit
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
            "--release-pr/--develop-pr",
            help="Use release-promotion PR guidance instead of the default develop/squash Conventional Commit PR guidance",
        ),
    ] = None,
    hotfix_pr: Annotated[
        Optional[bool],
        typer.Option(
            "--hotfix-pr/--no-hotfix-pr",
            help="Use hotfix-promotion PR guidance for PRs such as hotfix/* -> master",
        ),
    ] = None,
    sync_pr: Annotated[
        Optional[bool],
        typer.Option(
            "--sync-pr/--no-sync-pr",
            help="Use branch-sync PR guidance for PRs such as sync/* -> develop after a release or hotfix",
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
        git-tools pr --base master --release-pr
        git-tools pr --base master --hotfix-pr
        git-tools pr --base develop --sync-pr
    """
    from .generators.issueprgen import IssuePullRequestGenerator

    try:
        if sum(1 for flag in (release_pr, hotfix_pr, sync_pr) if flag) > 1:
            error("Use only one of --release-pr, --hotfix-pr, or --sync-pr.")
            raise typer.Exit(1)

        generator = IssuePullRequestGenerator(
            generation_type="pr",
            base_branch=base,
            input_source=source,
            release_pr=release_pr,
            hotfix_pr=hotfix_pr,
            sync_pr=sync_pr,
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
    version_source: Annotated[
        BumpVersionSource,
        typer.Option("--version-source", help="Choose the source for the current version"),
    ] = BumpVersionSource.auto,
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
    """Bump version from Conventional Commits and create the matching tag.

    Examples:
        git-tools bump
        git-tools bump --dry-run
        git-tools bump --increment MINOR --prerelease alpha --gpg-sign
        git-tools bump --prerelease alpha --default-increment PATCH --gpg-sign
        git-tools bump --get-next
    """
    from .bump import BumpError
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
            annotated_tag=annotated_tag,
            gpg_sign=gpg_sign,
            annotated_tag_message=annotated_tag_message,
            respect_git_config=respect_git_config,
            version_source=version_source.value,
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
        typer.Option("--config-file", help="Choose the Commitizen config file to create or update"),
    ] = None,
    version: Annotated[
        Optional[str],
        typer.Option("--version", help="Initial semver2 version to write"),
    ] = None,
    version_provider: Annotated[
        Optional[CzVersionProvider],
        typer.Option("--version-provider", help="Compatibility hint for where the version is managed"),
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
        git-tools init --config-file pyproject.toml --version-provider uv
    """
    from .generators.initgen import CommitizenInitGenerator, CzInitError

    use_interactive = interactive

    try:
        generator = CommitizenInitGenerator(
            config_file=config_file.value if config_file else None,
            version=version,
            version_provider=version_provider.value if version_provider else None,
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
# Config Command
# ============================================================================


@app.command()
def config() -> None:
    """Configure git-tools settings interactively.

    Settings will be saved to ~/.config/git-tools/config.env
    """
    from .config.config import (
        check_api_key_configured, setup_api_key, save_setting,
    )
    from .generators.base import success, TYPER_STYLE
    from .config.mappings import PROVIDERS

    if not _has_interactive_terminal():
        error("git-tools config requires an interactive terminal.")
        raise typer.Exit(1)

    def provider_default_model(provider: str) -> str:
        models = list(PROVIDERS[provider]["models"].values())
        return models[0]["model_name"] if models else ""

    def resolve_current_model(provider: str, configured_model: str | None) -> str:
        provider_model_names = [
            model["model_name"] for model in PROVIDERS[provider]["models"].values()
        ]
        if configured_model in provider_model_names:
            return configured_model
        return provider_default_model(provider)

    # Defaults for reference
    DEFAULTS = {
        "provider": "openrouter",
        "temperature": 0.2,
        "max_tokens": 8000,
        "max_retries": 1,
    }

    # Track current state locally (settings object is loaded once at startup)
    is_api_configured, _ = check_api_key_configured(settings.default_provider)
    current = {
        "provider": settings.default_provider,
        "model": resolve_current_model(
            settings.default_provider, settings.default_model
        ),
        "temperature": settings.default_temperature,
        "max_tokens": settings.default_max_tokens,
        "max_retries": settings.default_max_retries,
    }

    def build_choices():
        api_status = "configured" if is_api_configured else "not set"
        return [
            Choice(f"Provider: {current['provider']}", value="provider"),
            Choice(f"API Key ({current['provider']}): {api_status}", value="api_key"),
            Choice(f"Model: {current['model']}", value="model"),
            Choice(f"Temperature: {current['temperature']}", value="temperature"),
            Choice(f"Max Tokens: {current['max_tokens']}", value="max_tokens"),
            Choice(f"Max Retries: {current['max_retries']}", value="max_retries"),
            Choice("Done", value="done"),
        ]

    try:
        while True:
            choice = questionary.select(
                "Select setting to edit:",
                choices=build_choices(),
                style=TYPER_STYLE,
                qmark="❯",
                pointer="›",
                instruction="",
            ).ask()

            if choice is None or choice == "done":
                break

            if choice == "provider":
                providers = list(PROVIDERS.keys())
                provider_choice = questionary.select(
                    f"Select provider (current: {current['provider']}, default: {DEFAULTS['provider']}):",
                    choices=providers,
                    default=current["provider"] if current["provider"] in providers else DEFAULTS["provider"],
                    style=TYPER_STYLE,
                    qmark="❯",
                    pointer="›",
                    instruction="",
                ).ask()
                if provider_choice:
                    save_setting("GIT_TOOLS_PROVIDER", provider_choice)
                    current["provider"] = provider_choice
                    is_api_configured, _ = check_api_key_configured(provider_choice)
                    current["model"] = resolve_current_model(
                        provider_choice, current["model"]
                    )
                    console.print()
                    success(f"Provider set to {provider_choice}")

            elif choice == "api_key":
                if setup_api_key(current["provider"]):
                    console.print()
                    success("API key saved.")
                    is_api_configured = True

            elif choice == "model":
                provider_models = PROVIDERS[current["provider"]]["models"]
                model_choices = list(provider_models.keys())
                default_model = current["model"]
                if default_model not in [m["model_name"] for m in provider_models.values()]:
                    default_model = provider_default_model(current["provider"])
                model_choice = questionary.select(
                    f"Select model (current: {current['model']}, default: {provider_default_model(current['provider'])}):",
                    choices=[model["model_name"] for model in provider_models.values()],
                    default=default_model,
                    style=TYPER_STYLE,
                    qmark="❯",
                    pointer="›",
                    instruction="",
                ).ask()
                if model_choice:
                    save_setting("GIT_TOOLS_DEFAULT_MODEL", model_choice)
                    current["model"] = model_choice
                    console.print()
                    success(f"Model set to {model_choice}")

            elif choice == "temperature":
                temp_input = questionary.text(
                    f"Temperature (current: {current['temperature']}, default: {DEFAULTS['temperature']}):",
                    default=str(current["temperature"]),
                    style=TYPER_STYLE,
                    qmark="❯",
                    instruction="",
                ).ask()
                if temp_input:
                    try:
                        temp = float(temp_input)
                        if 0.0 <= temp <= 2.0:
                            save_setting("GIT_TOOLS_DEFAULT_TEMPERATURE", str(temp))
                            current["temperature"] = temp
                            console.print()
                            success(f"Temperature set to {temp}")
                        else:
                            console.print()
                            warning("Temperature must be between 0.0 and 2.0")
                    except ValueError:
                        console.print()
                        warning("Invalid temperature value.")

            elif choice == "max_tokens":
                tokens_input = questionary.text(
                    f"Max tokens (current: {current['max_tokens']}, default: {DEFAULTS['max_tokens']}):",
                    default=str(current["max_tokens"]),
                    style=TYPER_STYLE,
                    qmark="❯",
                    instruction="",
                ).ask()
                if tokens_input:
                    try:
                        tokens = int(tokens_input)
                        if tokens > 0:
                            save_setting("GIT_TOOLS_DEFAULT_MAX_TOKENS", str(tokens))
                            current["max_tokens"] = tokens
                            console.print()
                            success(f"Max tokens set to {tokens}")
                        else:
                            console.print()
                            warning("Max tokens must be greater than 0")
                    except ValueError:
                        console.print()
                        warning("Invalid max tokens value.")

            elif choice == "max_retries":
                retries_input = questionary.text(
                    f"Max retries (current: {current['max_retries']}, default: {DEFAULTS['max_retries']}):",
                    default=str(current["max_retries"]),
                    style=TYPER_STYLE,
                    qmark="❯",
                    instruction="",
                ).ask()
                if retries_input:
                    try:
                        retries = int(retries_input)
                        if retries >= 0:
                            save_setting("GIT_TOOLS_DEFAULT_MAX_RETRIES", str(retries))
                            current["max_retries"] = retries
                            console.print()
                            success(f"Max retries set to {retries}")
                        else:
                            console.print()
                            warning("Max retries must be 0 or greater")
                    except ValueError:
                        console.print()
                        warning("Invalid max retries value.")

            console.print()
    except KeyboardInterrupt:
        warning("Operation cancelled by user.")
        raise typer.Exit(0)


if __name__ == "__main__":
    app()
