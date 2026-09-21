#!/usr/bin/env bash
# Install / upgrade the sparki-cli engine that powers this skill.
# The CLI is a thin HTTP client for the cloud-hosted Sparki API
# (agent-api.sparki.io) — no local rendering. Optional result reveal uses the
# host operating system's native file manager.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "error: 'uv' is required but not found. Install it from https://docs.astral.sh/uv/ first." >&2
  exit 1
fi

echo "Installing / upgrading sparki-cli..."
uv tool install --upgrade sparki-cli

echo
echo "Verifying the CLI executable..."
if command -v sparki >/dev/null 2>&1; then
  sparki_command=(sparki)
else
  sparki_command=(uv tool run --from sparki-cli sparki)
fi
"${sparki_command[@]}" --help >/dev/null
echo
echo "sparki-cli installed. Connect and verify the account with:"
printf '  %s connect --channel codex --timeout 540\n' "${sparki_command[*]}"
