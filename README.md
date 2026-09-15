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
                │   └── install.sh         # uv tool install --upgrade sparki-cli + doctor
                └── references/
                    └── sparki-reference.md  # full styles / status / error tables
```

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) on PATH (used to install the CLI)
- A Sparki API key from https://sparki.io/claude-code-skill

## Install

```bash
# 1. Register this repo as a marketplace source (clones the repo):
codex plugin marketplace add \
  'https://github.com/sparki-ai/sparki-video-editor.git' \
  --ref 'main' \
  --sparse '.agents/plugins' \
  --sparse 'plugins'

# 2. Browse and install the plugin:
codex plugin list
codex plugin add sparki-video-editor@sparki-marketplace

# 3. Install the engine and verify:
bash plugins/sparki-video-editor/skills/sparki-video-editor/scripts/install.sh

# 4. Configure your key (or export SPARKI_API_KEY):
sparki setup --api-key <YOUR_KEY>
sparki doctor
```

## Usage

Once installed, just ask Codex to edit a video — the skill triggers on
mentions of vlog / clip / short / reel / caption / montage / TikTok, etc.

```
> Edit ./raw/trip.mp4 into a vertical travel highlight reel
```

Codex runs `sparki doctor` first, confirms editing preferences, then
`sparki run ... --output ./sparki-output/<task_id>.mp4`.

## What changed vs. the OpenClaw/Telegram skill

The engine (`sparki-cli`) and instruction logic are unchanged. Only the
environment glue was swapped:

| OpenClaw/Telegram | Codex |
|---|---|
| Output left at legacy default `~/.openclaw/workspace/sparki/videos/` | Skill always passes `--output ./sparki-output/...` into the working dir |
| Config at `~/.openclaw/config/` (OpenClaw-managed) | Same path (hardcoded in CLI) — but does NOT require OpenClaw installed; just a legacy dir name |
| API key from Telegram bot | API key from https://sparki.io/claude-code-skill (or `SPARKI_API_KEY` env) |
| `sparki upload-tg` / Mini App upload (Mode B) | removed — upload local file paths directly |
| `--reference-tg` for style-clone | removed — use `--reference-url` / `--reference-file` |
| `delivery_hint: telegram_direct/link_only` | local output path + optional `result_url` |
| `/topup` via Telegram bot | top up at https://sparki.io billing |
| `clawdbot:` frontmatter block | `.codex-plugin/plugin.json` manifest |

## License

MIT-0
