# Sparki Reference — Styles, Status Lifecycle, Error Codes

Progressive-disclosure reference. Load this only when you need the full
tables; the SKILL.md summarizes the common cases.

## Editing Modes

| Mode | When to use | Required option |
|---|---|---|
| `style-guided` | User names a recognizable style / format | `--style category/sub-style` |
| `prompt-driven` | User gives free-form instructions | `--prompt "<text>"` |
| `style-clone` | User wants to replicate a reference video's style | `--reference-url` or `--reference-file` |

## Style Namespace

Styles are `category/sub-style`. Use `--style category` alone only for
single-style categories.

| Style | Best for |
|---|---|
| `vlog/daily` | Day-in-the-life vlogs, event recaps, BTS |
| `vlog/travel` | Vacations, road trips, city breaks |
| `vlog/sports` | Game highlights, match recaps, performance reels |
| `vlog/chill-vibe` | Morning routines, slow living, aesthetic content |
| `clips/long-to-short` | Turn a long video's best moments into a short |
| `clips/highlight-reel` | Beat-synced montage of best moments |
| `narrative/podcast-interview` | Trim filler/pauses from podcasts, interviews, panels |
| `narrative/funny-commentary` | Write & voice hilarious commentary |
| `narrative/master-storyteller` | Dramatic arcs & emotional narration |
| `tools/ai-captions` | Timed, styled captions from dialogue |
| `tools/ai-translation` | Captions in a target language from dialogue |

## Aspect Ratio by Platform

| Platform | `--aspect-ratio` |
|---|---|
| TikTok / Reels / Shorts | `9:16` (default) |
| Instagram post | `1:1` |
| YouTube | `16:9` |

## Status Lifecycle

Standard: `INIT → CHAT → PLAN → QUEUED → EXECUTOR → COMPLETED / FAILED`

Style-clone (shorter): `INIT → EXECUTOR → COMPLETED / FAILED / CANCEL`

The local CLI can poll with `sparki status --task-id <id>`. The web runner
polls automatically during `run`. If it returns a `task_id` and later times
out or cannot download, create a new browser authorization and call `resume`
with the returned `task_id`, `mode`, and `output`. Never repeat `run` for that
project. Processing usually takes 5–20 min.

## Multi-Input Semantics

| User intent | Pattern |
|---|---|
| One combined output | Single call, all inputs positional: `sparki run a.mp4 b.mp4 ...` |
| N separate outputs | Loop, one input per call |
| Ambiguous | Ask before running |

## Full Error Code Table

Local Codex configuration lives at `Path.home()/.sparki/config/config.json` on
macOS, Linux, and Windows. Run `sparki connect --channel codex --timeout 540`
to reuse or create local authorization and run doctor. Browser Codex uses the
bundled web runner instead: it stores temporary PKCE state in the working
directory, keeps the exchanged key in memory only, and removes the state after
exchange.

| Code | Meaning | Action |
|---|---|---|
| `AUTHORIZATION_PENDING` / `SLOW_DOWN` | Browser approval is not complete | Reuse the same URL and state; retry only after approval |
| `AUTHORIZATION_EXPIRED` / `ACCESS_DENIED` | Browser request cannot continue | Create one new authorization |
| `AUTH_FAILED` | API key invalid | Web runner: create a new authorization; local CLI: run `sparki connect --channel codex --force --timeout 540` |
| `QUOTA_EXCEEDED` | Out of credits | Top up at https://sparki.io/ (Billing), retry |
| `STORAGE_FULL` | Asset storage quota exceeded | Browser: manage assets at sparki.io; local CLI: inspect/delete assets after confirmation |
| `FILE_TOO_LARGE` | File > 3GB | Compress/trim before uploading |
| `CONCURRENT_LIMIT` | Too many active projects | Run `sparki history`, wait/cancel |
| `INVALID_FILE_FORMAT` | Not mp4/mov | Convert to mp4 or mov |
| `INVALID_STYLE` | Unknown style | Show Style Reference |
| `INVALID_MODE` | Unknown mode | Suggest style-guided/prompt-driven/style-clone |
| `INVALID_REFERENCE` | style-clone missing reference | Provide `--reference-url` or `--reference-file` |
| `UPLOAD_FAILED` | Upload error | Retry; on partial, reuse `assets`, retry `failures` |
| `RENDER_TIMEOUT` | Processing timed out | Browser with `task_id`: authorize and `resume`; local CLI: inspect status/download before creating another project |
| `TASK_NOT_FOUND` | Unknown task id | `sparki history` |
| `NETWORK_ERROR` | Can't reach servers | Check connection |
| `CONFIRMATION_REQUIRED` | Required explicit approval is missing | Web runner: confirm potential charges and add `--confirm-charge`; destructive local CLI commands use `--yes` |
| `NO_MATCH` | `--name` matched no asset | `--name` takes hashed `file_name` from `assets list`, not original name |
| `DOCTOR_FAILED` | Self-check failed | Inspect `checks[]`, follow each `action` |

## Constraints

- Formats: mp4, mov only. Max file size: 3GB.
- API rate limit: 3s between requests (server-enforced).
- Result URLs expire after 24h.
- Long videos (30+ min): `--timeout 7200`.
