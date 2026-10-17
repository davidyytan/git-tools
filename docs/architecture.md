# Code Layout

[Documentation index](README.md) · [Contributing](contributing.md) · [Style conventions](style.md)

This guide maps the source tree so changes land in the module that owns them. For command behavior and intended policy, use the user-facing guides, including their [configuration limitations](configuration.md#current-limitations) and [versioning limitations](versioning.md#current-limitations). The layout below does not imply that the implementation satisfies every safety contract.

## Top Level

| Path | Role |
| --- | --- |
| `git_tools/cli.py` | Typer application: the `commit`, `issue`, `pr`, `bump`, `init`, and `settings` commands, the interactive menu, and the settings editors |
| `git_tools/settings/settings.py` | Pydantic settings, provider configuration classes, credential checks, and `~/.git-tools/settings.env` persistence |
| `git_tools/providers/` | One module per provider, copied from agent-cli: endpoint, default model, aliases, curated models, and catalog codecs (`catalog.py` is the shared `/models` transport and cache; `copilot.py` is the one git-tools-only module) |
| `git_tools/settings/mappings.py` | Provider registry wrapping `git_tools/providers/` with git-tools' wiring (credential env vars, config classes, picker flags, per-model knobs), and the catalog resolution that calls the modules the way agent-cli's provider flow does |
| `git_tools/utils/io.py` | Atomic JSON helpers the provider package depends on, copied from agent-cli |
| `git_tools/prompts/` | System and user prompt text files, loaded by name |
| `git_tools/templates/` | Commit, issue, and PR output templates with their loader |
| `git_tools/generators/` | One package per command plus the shared `base` package, described below |
| `git_tools/generators/utils/version_sync/` | Stdlib-only text transforms for `pyproject.toml`, `uv.lock`, npm manifests, and Cargo files |
| `git_tools/generators/publish.py` | CI publisher for a version commit and its tag; see [publication](publication.md) |

Each generator package keeps the import path of the module it replaced. `git_tools.generators.bumpgen`, for example, is a package whose `__init__.py` re-exports the public names, so `from git_tools.generators.bumpgen import decide_version_strategy` and `python -m git_tools.generators.bumpgen` work unchanged.

## Generator Packages

A generator class is composed from small mixins plus `BaseGenerator`. Mixins hold methods only; instance state is set in `BaseGenerator.__init__` and the concrete generator's `__init__`. Method names are the contract between mixins, so keep them unique across a package.

### `base/`

| Module | Owns |
| --- | --- |
| `terminal.py` | The shared Rich console, `STYLE_*` constants, `info`/`success`/`warning`/`error`, `print_panel`, and `TYPER_STYLE` |
| `tokens.py` | tiktoken encoder and `count_tokens` |
| `openrouter.py` | OpenRouter `extra_body` provider-routing helpers |
| `prompts.py` | `PROMPTS_DIR` and prompt-template loading |
| `interaction.py` | Questionary prompts and clipboard handoff |
| `models.py` | Provider selection, API-key precheck, model and sampling-parameter resolution |
| `clients.py` | LangChain `ChatOpenAI` construction per provider |
| `diffs.py` | Staged and branch diff retrieval, token budgeting, per-file quotas |
| `display.py` | Quota, token-usage, and reasoning panels |
| `llm.py` | `invoke_llm` with retry handling |
| `generator.py` | `BaseGenerator`, which composes the mixins above |

### `commitgen/`

| Module | Owns |
| --- | --- |
| `sensitive.py` | `SensitiveFileMatch`, the sensitive-path patterns, detection, and the confirmation gate |
| `messages.py` | Commit system prompt, model call, and Conventional Commit parsing |
| `workflow.py` | Fixed-subject commits such as `chore: open release` |
| `generator.py` | `CommitGenerator` and the end-to-end commit flow |

### `issueprgen/`

| Module | Owns |
| --- | --- |
| `contexts.py` | `PromotionPrContext`, `WorkflowPrContext`, and the shared branch and version patterns |
| `azure.py` | Azure DevOps detection, UTF-16 counting, and the PR-description limit retry |
| `branches.py` | Base-branch detection and validation |
| `versions.py` | Version lookups from `.cz.toml` on the current branch or another ref |
| `promotion.py` | Release and hotfix promotion contexts (into `master`) |
| `workflow.py` | Start and backmerge contexts (into `develop`) and target-version inference |
| `modes.py` | Generation type and PR mode selection |
| `commits.py` | Commit range summary, messages, and PR commit log |
| `content.py` | Choosing diffs, commits, or both and assembling the model input |
| `prompts.py` | System and user prompt assembly, model call, and output parsing |
| `titles.py` | Fixed PR titles, their prompt instructions, and output normalization |
| `generator.py` | `IssuePullRequestGenerator` and the end-to-end flow |

### `bumpgen/`

The engine and strategy modules must stay stdlib-only: CI adapters import them from a bare checkout with `PYTHONPATH` set and no dependencies installed. `ui.py` is the one place that imports `base`, inside a guard that falls back to stdlib stubs when Rich, Questionary, or tiktoken is missing; only the interactive `BumpGenerator` needs it.

| Module | Owns |
| --- | --- |
| `errors.py` | `BumpError` and its subclasses |
| `version.py` | `Version` for `semver` and `semver2`, scheme detection, release-line helpers |
| `conventions.py` | Conventional Commit bump rules and Git Flow subject and branch patterns |
| `targets.py` | Version-file adapters for `.cz.toml`, `pyproject.toml`, `uv.lock`, npm, Cargo, and regex entries |
| `config.py` | `BumpConfig`, `.cz.toml` reading, automatic target discovery, tag formatting |
| `git.py` | Git command wrappers and tag-argument construction |
| `repo.py` | Repository-state queries that combine git history with `.cz.toml` |
| `engine.py` | `BumpOptions`, immutable `BumpPlan`, file planning, snapshot validation and apply (with the documented FIFO/file-mode gaps), and `run_bump` |
| `decision.py` | `StrategyDecision` and its GitHub output encoding |
| `rules.py` | Per-branch decisions for `develop`, `release/*`, `hotfix/*`, and `master` |
| `strategy.py` | `decide_version_strategy`: branch validation and dispatch to the rules |
| `ui.py` | Guarded import of `BaseGenerator`, `info`, and `print_panel` |
| `generator.py` | Interactive `BumpGenerator` over the engine |
| `cli.py`, `__main__.py` | Argparse entry point for `python -m git_tools.generators.bumpgen` |

Imports flow one way: `errors` → `version` → `conventions` → `targets` → `config` → `git` → `repo` → `engine`, and `decision` → `rules` → `strategy`. Keep new code on that line rather than importing back toward `engine` or `strategy`.

### `initgen/`

| Module | Owns |
| --- | --- |
| `config.py` | `CzInitOptions`, config discovery, TOML validation, and comment-preserving field updates |
| `detect.py` | Default version and tag format from existing config and tags |
| `generator.py` | Interactive `CommitizenInitGenerator` |

## Where Changes Go

| Change | Edit |
| --- | --- |
| Add or adjust a provider | `providers/<name>.py` (copy agent-cli's module when one exists), its wiring in `settings/mappings.py`, `settings/settings.py`, `base/clients.py`, and the `settings` command in `cli.py` |
| Model picker or default resolution | `base/models.py`; shared picker helpers live in `cli.py` |
| Diff budgeting or truncation | `base/diffs.py`; its panel in `base/display.py` |
| Commit prompt or message parsing | `commitgen/messages.py` and `prompts/commitgen_*.txt` |
| Sensitive-path rules | `commitgen/sensitive.py` |
| A new fixed-title PR mode | A flag in `cli.py`, `issueprgen/modes.py`, a context in `promotion.py` or `workflow.py`, titles in `titles.py`, and `prompts/issuepr_title_instruction_*.txt` |
| PR-description limit behavior | `issueprgen/azure.py` |
| Which commit types bump what | `bumpgen/conventions.py` |
| A new auxiliary version file | A transform in `utils/version_sync/`, an adapter in `bumpgen/targets.py`, discovery in `bumpgen/config.py`, and [versioning](versioning.md) |
| CI branch strategy | `bumpgen/rules.py` for one branch kind, `bumpgen/strategy.py` for validation and dispatch, then the workflow examples and platform guides |
| Init defaults or the written section | `initgen/detect.py` and `initgen/config.py` |

## Testing Conventions

Run `uv run python -m unittest discover -s tests` in an isolated validation environment; see [contributing](contributing.md#validation) for external-effect boundaries. Tests import public names from the package path and patch internals at the submodule that defines them, for example `git_tools.generators.bumpgen.engine.git_tag` rather than `git_tools.generators.bumpgen.git_tag`: a function looks names up in its own module, so patching the package attribute would not reach it.

Keep a submodule's name distinct from any attribute the package re-exports. `mock.patch` resolves a dotted path module-first, which is why the console lives in `base/terminal.py` and `git_tools.generators.base.console` stays the console object.

Auxiliary version-sync warnings log under the `git_tools.generators.bumpgen` logger name regardless of the submodule that emits them.

| Area | Tests |
| --- | --- |
| Bump engine, config, targets | `tests/test_bump.py`, `tests/test_bump_generator.py`, `tests/test_bump_safety.py`, `tests/test_cargo_sync.py` |
| CI strategy and templates | `tests/test_git_flow_strategy.py`, `tests/test_pipeline_safety.py`, `tests/test_publish.py` |
| Commit generation and interaction | `tests/test_commitgen.py`, `tests/test_generation_flow.py` |
| Console spacing and rendered generator flows | `tests/test_cli_spacing.py`, `tests/test_generation_spacing.py` |
| Issue and PR generation | `tests/test_issuepr_prompt.py`, `tests/test_pr_comparison.py`, `tests/test_pr_content_safety.py`, `tests/test_azure_pr_settings.py` |
| Init | `tests/test_initgen.py` |
| Providers, models, settings UI | `tests/test_effective_settings.py`, `tests/test_provider_config.py`, `tests/test_provider_parity.py`, `tests/test_live_models.py`, `tests/test_openrouter_provider_config.py`, `tests/test_cli.py` |
