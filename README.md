# Sparki Video Editor — Codex Plugin

AI video editing for creators, ported from the OpenClaw/Telegram Sparki skill
to run as a **Codex CLI plugin**. All rendering happens server-side on the
cloud-hosted Sparki API (`agent-api.sparki.io`) via `sparki-cli` — no ffmpeg,
no local rendering, no host-environment coupling.

## Layout

```
sparki-video-editor/                       # marketplace repo
├── .agents/plugins/
│   └── marketplace.json                   # marketplace index (discovered by `codex plugin marketplace add`)
└── plugins/
    └── sparki-video-editor/               # the plugin bundle
        ├── .codex-plugin/
        │   └── plugin.json                # plugin manifest
        └── skills/
            └── sparki-video-editor/
                ├── SKILL.md               # instructions + metadata (loaded on demand)
                ├── scripts/
                │   └── install.sh         # install the CLI and verify its executable
                └── references/
                    └── sparki-reference.md  # full styles / status / error tables
```

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) on PATH (used to install the CLI)
- A Sparki account; first-time setup opens https://sparki.io for approval

If `uv` is missing, prefer an existing trusted package manager: `brew install
uv` on macOS, `winget install --id=astral-sh.uv -e` on Windows, or `pipx
install uv` on any supported platform with pipx. Otherwise follow the official
[uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)
and inspect any standalone installer before running it.

## Install

```bash
# 1. Register this repo as a marketplace source:
codex plugin marketplace add https://github.com/sparki-ai/sparki-video-editor.git --ref main --sparse .agents/plugins --sparse plugins

# 2. Browse and install the plugin:
codex plugin list
codex plugin add sparki-video-editor@sparki-marketplace

# 3. Install the engine and verify:
uv tool install --upgrade sparki-cli
sparki --help

# If sparki is not yet on PATH, verify it without restarting the shell:
uv tool run --from sparki-cli sparki --help

# 4. Connect your account (or export SPARKI_API_KEY and SPARKI_CHANNEL=codex):
sparki config-status --channel codex
sparki login --channel codex  # only when configured is false
sparki doctor --channel codex
```

When the direct `sparki` command is not yet available after a fresh install,
replace the leading `sparki` in the setup, doctor, and editing commands with
`uv tool run --from sparki-cli sparki`. This runs the installed tool immediately
without depending on a shell restart.

## Usage

Once installed, just ask Codex to edit a video — the skill triggers on
mentions of vlog / clip / short / reel / caption / montage / TikTok, etc.

```
> Edit ./raw/trip.mp4 into a vertical travel highlight reel
```

Codex runs `sparki doctor --channel codex` first, confirms editing preferences,
then runs `sparki run ... --output ./sparki-output/<output-name>.mp4`. In a
local desktop environment it adds `--reveal`; browser and remote environments
report the absolute output file and containing directory instead.

## What changed vs. the OpenClaw/Telegram skill

The cloud editing engine remains the same, while Codex-specific setup and
local delivery behavior differ:

| OpenClaw/Telegram | Codex |
|---|---|
| Output left at legacy default `~/.openclaw/workspace/sparki/videos/` | Skill always passes `--output ./sparki-output/...` into the working dir |
| Config at `~/.openclaw/config/` (OpenClaw-managed) | Cross-platform `Path.home()/.sparki/config/config.json`; legacy config is read-only fallback |
| API key from Telegram bot | Browser authorization with `sparki login --channel codex` (or `SPARKI_API_KEY` with `SPARKI_CHANNEL=codex`) |
| `sparki upload-tg` / Mini App upload (Mode B) | removed — upload local file paths directly |
| `--reference-tg` for style-clone | removed — use `--reference-url` / `--reference-file` |
| `delivery_hint: telegram_direct/link_only` | absolute local output path + optional native file reveal; temporary URLs are not presented to the user |
| `/topup` via Telegram bot | top up at https://sparki.io billing |
| `clawdbot:` frontmatter block | `.codex-plugin/plugin.json` manifest |

## License

MIT-0
