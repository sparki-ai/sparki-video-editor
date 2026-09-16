#!/usr/bin/env bash
# Install / upgrade the sparki-cli engine that powers this skill.
# The CLI is a thin HTTP client for the cloud-hosted Sparki API
# (agent-api.sparki.io) — no local rendering, no host-environment coupling.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "error: 'uv' is required but not found. Install it from https://docs.astral.sh/uv/ first." >&2
  exit 1
fi

echo "Installing / upgrading sparki-cli..."
uv tool install --upgrade sparki-cli

echo
echo "Verifying the CLI executable..."
sparki --help >/dev/null
echo
echo "sparki-cli installed. Configure an API key, then verify the connection:"
echo "  sparki setup --api-key <YOUR_KEY> --channel codex"
echo "  sparki doctor --channel codex"
