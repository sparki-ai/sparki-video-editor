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

Poll with `sparki status --task-id <id>`. Processing usually takes 5–20 min.

## Multi-Input Semantics

| User intent | Pattern |
|---|---|
| One combined output | Single call, all inputs positional: `sparki run a.mp4 b.mp4 ...` |
| N separate outputs | Loop, one input per call |
| Ambiguous | Ask before running |

## Full Error Code Table

Codex configuration lives at `Path.home()/.sparki/config/config.json` on
macOS, Linux, and Windows. Run `sparki config-status --channel codex` before
starting login; when it reports `configured: false`, run `sparki login
--channel codex` and let the user approve in the browser. The key is saved
without being displayed or pasted into chat.

| Code | Meaning | Action |
|---|---|---|
| `AUTH_FAILED` | API key invalid | Run `sparki login --channel codex --force`, approve in the browser, then rerun doctor |
| `QUOTA_EXCEEDED` | Out of credits | Top up at https://sparki.io/ (Billing), retry |
| `STORAGE_FULL` | Asset storage quota exceeded | `sparki assets delete ...` or web UI, then retry |
| `FILE_TOO_LARGE` | File > 3GB | Compress/trim before uploading |
| `CONCURRENT_LIMIT` | Too many active projects | Run `sparki history`, wait/cancel |
| `INVALID_FILE_FORMAT` | Not mp4/mov | Convert to mp4 or mov |
| `INVALID_STYLE` | Unknown style | Show Style Reference |
| `INVALID_MODE` | Unknown mode | Suggest style-guided/prompt-driven/style-clone |
| `INVALID_REFERENCE` | style-clone missing reference | Provide `--reference-url` or `--reference-file` |
| `UPLOAD_FAILED` | Upload error | Retry; on partial, reuse `assets`, retry `failures` |
| `RENDER_TIMEOUT` | Processing timed out | Shorter clip or higher `--timeout` |
| `TASK_NOT_FOUND` | Unknown task id | `sparki history` |
| `NETWORK_ERROR` | Can't reach servers | Check connection |
| `CONFIRMATION_REQUIRED` | Destructive op needs `--yes` | Confirm with user, re-run with `--yes` |
| `NO_MATCH` | `--name` matched no asset | `--name` takes hashed `file_name` from `assets list`, not original name |
| `DOCTOR_FAILED` | Self-check failed | Inspect `checks[]`, follow each `action` |

## Constraints

- Formats: mp4, mov only. Max file size: 3GB.
- API rate limit: 3s between requests (server-enforced).
- Result URLs expire after 24h.
- Long videos (30+ min): `--timeout 7200`.
