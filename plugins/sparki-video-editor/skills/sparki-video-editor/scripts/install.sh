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
echo "Verifying install..."
sparki doctor || {
  echo
  echo "doctor reported issues. If api_key is missing, run:" >&2
  echo "  sparki setup --api-key <YOUR_KEY>      # get a key at https://sparki.io/codex-skill" >&2
  echo "or export SPARKI_API_KEY in your environment." >&2
  exit 1
}

echo
echo "sparki-cli ready. 🎬"
