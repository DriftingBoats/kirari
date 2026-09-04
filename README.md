# Kirari

Kirari is a private, Telegram-first companion agent powered by the Codex CLI login included with a ChatGPT plan. It does not use Hermes or an OpenAI API key. An optional Gemini API key is used only for semantic memory embeddings.

The project deliberately separates the companion product from the model runtime:

```text
Telegram / local web chat
          ↓
Kirari (conversation, memory, reviews, schedules, safety)
          ↓
Codex CLI (`codex exec`, ChatGPT account login)
```

## What is included

- Stable, user-editable identity and relationship boundaries in Markdown.
- Recent conversation context plus searchable long-term memory.
- Pin any message into durable memory.
- Daily `dream`/`feel` consolidation with structured output validation.
- Review queue for inferred facts, promises, boundaries, reminders, and calendar events.
- Optional proactive Telegram check-ins with idle time, cooldown, and quiet hours.
- One-time and daily/weekly/monthly reminders, plus snooze.
- Telegram Mini App/control panel and a local web chat.
- Telegram long polling for a fully local setup; webhook mode remains available.
- Local SQLite history, memory-file versioning, and rollback.

Voice, image generation, avatars, and multiple companions are intentionally not in the core yet. The common companion foundations—identity, continuity, memory control, initiative, and user-visible governance—come first.

## Codex subscription runtime

Kirari starts `codex exec` in non-interactive, ephemeral, read-only mode. It reuses the login saved by `codex login`. Before each invocation Kirari removes inherited `OPENAI_API_KEY` and `CODEX_API_KEY` values so it cannot silently fall back to API billing.

This mode is appropriate for a private agent on a machine you control. Do not copy `~/.codex/auth.json` into a public deployment or commit it: it contains account access tokens. ChatGPT/Codex subscription usage and OpenAI API billing are separate products.

## Requirements

- Python 3.10+
- Codex CLI
- A ChatGPT account with Codex access
- Optional: a Telegram bot from BotFather

Verify subscription login:

```bash
codex login
codex login status
```

The status should say `Logged in using ChatGPT`. On Windows, Kirari prefers the native `codex.exe` over an older npm shim. You can always set `CODEX_BIN` to an explicit executable path.

## Install

```bash
git clone https://github.com/DriftingBoats/kirari.git
cd kirari
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS/Linux:

```bash
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Minimum `.env` for local web chat:

```dotenv
APP_DATA_DIR=./data
KIRARI_ACCESS_KEY=choose-a-long-random-value
APP_TIMEZONE=Asia/Shanghai

CODEX_BIN=codex
CODEX_REASONING_EFFORT=low
```

Start Kirari:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Open <http://127.0.0.1:8080/>. The control panel shows whether Codex is installed and logged in with ChatGPT.

## Telegram: local polling (recommended)

Add these values to `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_ALLOWED_USER_IDS=123456789
TELEGRAM_MODE=polling
```

Restart Kirari. It removes an existing webhook and receives messages using Telegram long polling, entirely from this machine. Restrict `TELEGRAM_ALLOWED_USER_IDS`; an empty allowlist permits anyone who discovers the bot to use your Codex allowance.

Do not run polling and a webhook consumer for the same bot at the same time.

## Telegram: webhook mode

Use this only when Kirari is running behind a public HTTPS URL on a machine where your Codex account is safely logged in:

```dotenv
BASE_URL=https://example.com
TELEGRAM_MODE=webhook
TELEGRAM_WEBHOOK_SECRET=replace-with-a-long-random-secret
```

Then register the webhook:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=$BASE_URL/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

## Memory model

The readable source of truth defaults to `./data/memory/`:

- `SOUL.md` — identity, voice, values, and relationship style; user controlled.
- `PINNED.md` — promises, boundaries, and non-negotiable rules; user controlled.
- `USER.md` — stable facts about the user.
- `MEMORY.md` — durable shared history.
- `FEEL.md` — first-person relationship reflection, not objective fact.
- `DREAM.md` — daily consolidation logs.
- `BOARD.md` — message-board and proactive-message archive.

Set `KIRARI_MEMORY_DIR` to store these elsewhere. Every prompt reads the current files, so edits take effect on the next reply without restarting a gateway.

Long-term event memory is stored as one Markdown bucket per record under `memory/buckets/{active,archive,tombstone}/{domain}/`. YAML frontmatter contains emotional coordinates, importance, activation, source message IDs, lineage, and footprints; the body preserves the memory text. These bucket files are canonical. SQLite, FTS, and vectors are disposable projections rebuilt from them at startup. Legacy SQLite-only memories are exported automatically without deleting their original rows.

Semantic memory follows an Ombre-Brain-style hybrid design. A disposable SQLite vector projection is generated by `gemini-embedding-001`. Documents use `RETRIEVAL_DOCUMENT`, queries use `RETRIEVAL_QUERY`, and 768-dimensional vectors are normalised before cosine comparison. Ranking combines Gemini cosine similarity, FTS5/BM25, Chinese bigrams, RapidFuzz, topic matches, importance, and memory vitality. Advanced queries can filter domain, tags, dates, minimum importance, and archive inclusion. If Gemini is unavailable, Kirari falls back to Codex subscription reranking and then local hybrid lexical retrieval.

Add a free-tier Google AI Studio key to `.env` to enable true vector retrieval:

```dotenv
GEMINI_EMBEDDING_API_KEY=replace_me
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_EMBEDDING_DIMENSIONS=768
```

The free tier sends the indexed memory text to Google, and Google currently states that free-tier inputs may be used to improve its products. Do not enable it for memories you are unwilling to send to that service.

New or changed memories are placed in a durable background indexing queue after the canonical bucket is committed. Failures use exponential backoff and survive restarts. Existing memories are reconciled automatically at startup. `POST /api/memory-index/reindex` can rebuild the projection; pass `{ "force": true, "wait": true }` for an immediate full rebuild.

Before creating a normal fact/event/pattern bucket, Kirari searches for a compatible existing memory. Exact or high-confidence matches merge raw text, tags, entities, sources, and lineage instead of creating duplicates. Protected feeling, promise, boundary, plan, letter, pinned, and permanent records never merge implicitly.

Search is deliberately read-only. Companion structured output reports only memory IDs that materially affected the reply; those records are then explicitly reinforced and send a small activation ripple to up to five memories created within 48 hours. After six idle hours a new conversation also receives a bounded no-query resurfacing set containing core, cold-start, recent, vivid, and occasionally older memories.

Natural forgetting is archival, never physical deletion. The Ombre-style score combines importance, activation consolidation, exponential decay, short/long-term time-emotion weighting, resolved/digested factors, and urgency. Pinned, feeling, promise, boundary, plan, letter, and permanent records are protected. Archived records remain searchable and can be restored. `DELETE /api/memories/{id}` creates a recoverable tombstone; there is no public physical-purge endpoint. Automatic decay runs every 24 hours by default and can be disabled with `MEMORY_DECAY_ENABLED=false`.

Dream writes ordinary memories through the same deduplicating bucket pipeline and stores first-person feeling sediment as protected `feel` buckets with source-message provenance. When a new feeling is semantically close to at least two earlier feelings, Kirari creates a review proposal to crystallise the recurring theme into pinned memory.

## Proactive messages

Proactive contact is off by default. Enable it explicitly:

```dotenv
PROACTIVE_ENABLED=true
PROACTIVE_IDLE_HOURS=18
PROACTIVE_COOLDOWN_HOURS=24
PROACTIVE_QUIET_START=23
PROACTIVE_QUIET_END=8
```

Kirari only checks in after inactivity, respects the cooldown and local quiet hours, and instructs the model not to guilt the user or demand a response.

Scheduled daily reflection is also opt-in because it consumes subscription allowance. Set `DREAM_SCHEDULE_ENABLED=true` and choose `DREAM_HOUR=4`; manual reflection remains available from the control panel.

## API overview

- `GET /api/status` — Codex subscription login and scheduler status.
- `POST /api/chat` — local companion chat with persisted context.
- `GET /api/messages` — conversation history; optional `chat_id` filter.
- `POST /api/messages/{id}/pin` — pin a message into memory.
- `POST /api/memories/{id}/reinforce` — explicitly strengthen a useful memory.
- `POST /api/memories/{id}/restore` — restore an archived memory.
- `GET /api/memories/{id}/trace` — inspect source messages, lineage, footprints, and bucket path.
- `GET /api/memories/surface` — preview no-query automatic resurfacing.
- `GET /api/memories/feel/search?q=...` — search protected feeling sediment.
- `POST /api/memories/decay` — preview or apply archival decay.
- `POST /api/memory-index/reindex` — reconcile or rebuild Gemini vectors.
- `GET|PUT /api/files/{name}` — readable companion files and versions.
- `GET|POST|PATCH|DELETE /api/memories` — bucket memory bank; DELETE creates a tombstone.
- `GET|POST /api/reviews` — approve or reject proposed state changes.
- `GET|POST /api/calendar` — life, relationship, and work events.
- `GET|POST|PATCH /api/reminders` — reminders, recurrence, and snooze.
- `POST /api/dream/run` — run reflection now.
- `POST /telegram/webhook` — webhook mode only.

When `KIRARI_ACCESS_KEY` or `TELEGRAM_BOT_TOKEN` is configured, `/api/*` routes require the access key or valid Telegram Mini App init data.

## Test

```bash
python -m pytest -q
python -m compileall app
```

Tests never invoke Codex or consume subscription usage.

## Security

Never commit `.env`, Telegram bot tokens, `~/.codex/auth.json`, private memory files, or the SQLite database. Keep the control panel bound to `127.0.0.1` unless you have configured authentication and HTTPS.

## Documentation

- [Codex CLI](https://developers.openai.com/codex/cli)
- [Codex non-interactive mode](https://developers.openai.com/codex/non-interactive-mode)
- [Using Codex with a ChatGPT plan](https://help.openai.com/en/articles/11369540)

## License

MIT
