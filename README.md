# Sparki Video Editor — Codex Plugin

AI video editing for creators, ported from the OpenClaw/Telegram Sparki skill
to run as a **Codex plugin**. All rendering happens server-side on the
cloud-hosted Sparki API (`agent-api.sparki.io`) — no ffmpeg or local rendering.
Local Codex uses `sparki-cli`; browser Codex uses the bundled dependency-free
Python runner and does not download packages from PyPI.

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
                │   ├── install.sh         # install the local CLI
                │   └── sparki_web_runner.py # dependency-free browser runner
                └── references/
                    └── sparki-reference.md  # full styles / status / error tables
```

## Prerequisites

- A Sparki account; first-time setup opens https://sparki.io for approval
- Browser Codex: Python 3 only; no `uv`, pip, or `sparki-cli` installation
- Local Codex: [`uv`](https://docs.astral.sh/uv/) on PATH to install the CLI

For local Codex, if `uv` is missing, prefer an existing trusted package manager: `brew install
uv` on macOS, `winget install --id=astral-sh.uv -e` on Windows, or `pipx
install uv` on any supported platform with pipx. Otherwise follow the official
[uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)
and inspect any standalone installer before running it.

## Install the plugin

```bash
# 1. Register this repo as a marketplace source:
codex plugin marketplace add https://github.com/sparki-ai/sparki-video-editor.git --ref main --sparse .agents/plugins --sparse plugins

# 2. Browse and install the plugin:
codex plugin list
codex plugin add sparki-video-editor@sparki-marketplace

# 3. Local Codex only: install the engine and verify:
uv tool install --upgrade sparki-cli
sparki --help

# If sparki is not yet on PATH, verify it without restarting the shell:
uv tool run --from sparki-cli sparki --help

# 4. Connect your account (or export SPARKI_API_KEY and SPARKI_CHANNEL=codex):
sparki config-status --channel codex
sparki login --channel codex  # only when configured is false
sparki doctor --channel codex
```

Browser Codex stops after step 2. The installed skill automatically selects
its bundled Python runner and must not install `uv` or `sparki-cli` in the
hosted workspace. Codex desktop and terminal sessions continue with the local
engine setup in steps 3 and 4.

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

On a local machine, Codex runs `sparki doctor --channel codex` first, confirms
editing preferences, then runs `sparki run ... --output
./sparki-output/<output-name>.mp4`. In a local desktop environment it adds
`--reveal`.

In browser Codex, the skill resolves the bundled runner relative to `SKILL.md`,
runs `probe`, and creates one browser authorization:

```bash
python3 -B <skill-dir>/scripts/sparki_web_runner.py probe
python3 -B <skill-dir>/scripts/sparki_web_runner.py authorize --channel codex --state ./sparki-output/.sparki-web-auth.json
```

After the user signs in, approves access, and separately authorizes the
potentially paid edit, the skill runs the full streaming workflow:

```bash
python3 -B <skill-dir>/scripts/sparki_web_runner.py run ./trip.mp4 --state ./sparki-output/.sparki-web-auth.json --mode style-guided --style vlog/travel --output ./sparki-output/trip.mp4 --confirm-charge
```

If the runner has already returned a `task_id` and later times out or cannot
download the result, authorize again and resume that exact project. Do not run
the paid edit a second time:

```bash
python3 -B <skill-dir>/scripts/sparki_web_runner.py resume --state ./sparki-output/.sparki-web-auth.json --task-id <task-id> --mode style-guided --output ./sparki-output/trip.mp4
```

The browser runner stores only short-lived PKCE state, keeps the returned API
key in process memory, and deletes the state after exchange. The completed MP4
is attached to the browser conversation when the host supports file delivery.

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
