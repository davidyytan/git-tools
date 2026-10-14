#!/usr/bin/env bash
# Install git-tools from this checkout and enable shell completion.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' 'Error: uv is required. Install it first: https://docs.astral.sh/uv/getting-started/installation/' >&2
    exit 1
fi

uv tool install -e . "$@"

if ! command -v git-tools >/dev/null 2>&1; then
    printf '%s\n' 'Error: git-tools is not on PATH after installation. Run `uv tool update-shell`, restart your shell, then run `git-tools --install-completion`.' >&2
    exit 1
fi

git-tools --install-completion
printf '%s\n' 'Installed git-tools. Restart your shell to activate completion.'
