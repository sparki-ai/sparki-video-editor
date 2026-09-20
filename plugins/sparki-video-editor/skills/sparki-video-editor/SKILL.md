---
name: sparki-video-editor
description: AI video editor for creators. Transform raw footage into polished vlogs, talking-head videos, or social media content (TikTok/Shorts/Reels). From cloning a reference style to natural language editing, simply describe your vision and let Sparki handle the rest. Runs on the cloud-hosted Sparki API — no local rendering, no ffmpeg.
metadata:
  version: "1.1.6"
---

# Sparki Video Editor

Use this skill whenever the user asks to edit, clip, caption, translate, or
reformat video. Sparki renders in the cloud; never use ffmpeg or a local video
renderer.

## 1. Choose one runtime

Do this before setup or editing:

- **Codex browser / hosted cloud workspace:** use the bundled Web Runner. Do
  not install `uv`, pip packages, or `sparki-cli`.
- **Codex desktop app / local terminal:** use the Local CLI.
- **Uncertain:** a chat attachment under a disposable workspace means Web
  Runner. Otherwise ask one short question before installing software.

Always write results to `./sparki-output/<name>.mp4` in the current working
directory. A browser workspace is not the user's computer: attach the finished
MP4 to the conversation and also report its `local_path` and
`output_directory`.

## 2. Browser / hosted Codex

Resolve `scripts/sparki_web_runner.py` relative to this `SKILL.md`. Use
`python3 -B`, or `python -B` only when it is Python 3. Never guess or copy the
runner path.

### Connect

```bash
python3 -B <skill-dir>/scripts/sparki_web_runner.py probe
python3 -B <skill-dir>/scripts/sparki_web_runner.py authorize --channel codex --state ./sparki-output/.sparki-web-auth.json
```

Show the returned `authorization_url`. Ask the user to sign in at Sparki and
approve access. Never ask for an API key. Reuse the same state and URL while it
is unexpired; do not add `--force` for a pending authorization. The runner keeps
the exchanged key in memory only and removes the state after exchange.

If `probe` fails, explain that the hosted environment cannot reach
`agent-api.sparki.io`; installing packages is not a workaround.

### Confirm and edit

Browser approval grants account access but does not authorize a paid editing
task. Before `run`, ask the user to approve creating the potentially paid
project. Add `--confirm-charge` only after they agree.

Choose one mode:

- `style-guided`: a known format; requires `--style`.
- `prompt-driven`: free-form instructions; requires `--prompt`.
- `style-clone`: copy one reference; requires exactly one of
  `--reference-url` or `--reference-file`.

Examples:

```bash
python3 -B <runner> run input.mp4 --state ./sparki-output/.sparki-web-auth.json --mode style-guided --style clips/highlight-reel --aspect-ratio 9:16 --output ./sparki-output/highlight.mp4 --confirm-charge
python3 -B <runner> run input.mp4 --state ./sparki-output/.sparki-web-auth.json --mode prompt-driven --prompt "Create a concise vertical travel reel" --aspect-ratio 9:16 --output ./sparki-output/travel.mp4 --confirm-charge
python3 -B <runner> run input.mp4 --state ./sparki-output/.sparki-web-auth.json --mode style-clone --reference-file reference.mp4 --aspect-ratio 9:16 --output ./sparki-output/cloned.mp4 --confirm-charge
```

Multiple positional inputs create one combined output. To create separate
outputs, run one authorized project per input. Ask if intent is ambiguous.

### Recover without duplicate charges

If `run` returns `AUTHORIZATION_PENDING`, show the same returned URL and retry
the same command only after approval.

If an error after project creation contains `task_id`, `mode`, and `output`, do
not run the full edit again. Create a fresh browser authorization, have the
user approve it, then resume the existing project:

```bash
python3 -B <runner> authorize --channel codex --state ./sparki-output/.sparki-web-auth.json
python3 -B <runner> resume --state ./sparki-output/.sparki-web-auth.json --task-id <task-id> --mode <mode> --output <output-path>
```

`resume` only polls and downloads; it never creates another editing project.
After success, attach the MP4 using `local_path`. Never claim that browser
Codex opened the user's native file manager.

## 3. Codex desktop / local terminal

### Install the engine

Check `uv --version`. If missing, install it only with user authorization and
an already trusted package manager:

- macOS: `brew install uv`
- Windows: `winget install --id=astral-sh.uv -e`
- Any supported system with pipx: `pipx install uv`

Otherwise send the user to the official uv installation guide. Do not silently
execute a downloaded installer.

```bash
uv tool install --upgrade sparki-cli
uv tool run --from sparki-cli sparki --help
```

Use `sparki` when it is on `PATH`. Until a shell restart makes it available,
replace it with `uv tool run --from sparki-cli sparki`.

### Connect once

```bash
sparki config-status --channel codex
```

When `configured` is false, run `sparki login --channel codex`. The CLI opens
`sparki.io`; the user can sign in by email verification code, Google, or Apple
and approve access. For headless environments use `--no-browser` and show the
one-time URL while the same command keeps polling. Never request or expose the
API key.

Configuration is shared cross-platform at
`Path.home()/.sparki/config/config.json`. `SPARKI_API_KEY` and
`SPARKI_CHANNEL=codex` may override it in managed environments.

Then verify:

```bash
sparki doctor --channel codex
```

If the stored credential is invalid, use `sparki login --channel codex
--force`, then run doctor again.

### Run and deliver

Inspect `sparki run --help` when constructing a command. Typical commands are:

```bash
sparki run input.mp4 --mode style-guided --style clips/highlight-reel --aspect-ratio 9:16 --output ./sparki-output/highlight.mp4
sparki run input.mp4 --mode prompt-driven --prompt "Create a concise vertical travel reel" --aspect-ratio 9:16 --output ./sparki-output/travel.mp4
sparki run input.mp4 --mode style-clone --reference-file reference.mp4 --aspect-ratio 9:16 --output ./sparki-output/cloned.mp4
```

Use `--reveal` only when the command runs on the user's computer and native GUI
apps are available. Omit it for containers, SSH, and headless hosts. Always
report the absolute `local_path` and `output_directory`; if native reveal fails,
tell the user exactly where the output is stored.

Ask for explicit confirmation before destructive asset deletion or retrying a
failed edit as a new potentially paid project. A status/download retry for an
existing `task_id` is not a new project.

## 4. Editing choices

When the user has not specified the intended result, ask only for the missing
choices: mode/style or prompt, aspect ratio, approximate duration, and whether
multiple inputs should become one output.

Common styles:

- Vlog: `vlog/daily`, `vlog/travel`, `vlog/sports`, `vlog/chill-vibe`
- Clips: `clips/long-to-short`, `clips/highlight-reel`
- Narrative: `narrative/podcast-interview`,
  `narrative/funny-commentary`, `narrative/master-storyteller`
- Tools: `tools/ai-captions`, `tools/ai-translation`

Aspect ratios: `9:16` for TikTok/Reels/Shorts, `1:1` for square posts, and
`16:9` for YouTube/landscape.

## 5. Error handling

- `QUOTA_EXCEEDED`: ask the user to top up at `https://sparki.io/`.
- `STORAGE_FULL`: browser users manage assets on `https://sparki.io/`; local
  users may inspect and delete assets with the CLI after confirmation.
- `CONCURRENT_LIMIT`: wait for an active project to finish.
- `AUTHORIZATION_PENDING`: reuse the current URL and state.
- `RENDER_TIMEOUT` or `DOWNLOAD_FAILED` with a browser `task_id`: use `resume`;
  never create another project automatically.
- `NETWORK_ERROR`: retry safe reads; never automatically retry project-creation
  POST requests.

Load [references/sparki-reference.md](references/sparki-reference.md) only when
you need the complete style, status, command, or error tables.
