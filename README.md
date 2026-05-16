# Kirari

Kirari is a Telegram-first companion project built around
[Hermes Agent](https://github.com/NousResearch/hermes-agent). Hermes stays the
base agent/runtime. This repository adds a small, readable layer for companion
memory, relationship reflection, a Telegram-facing control surface, and
future Mini App workflows.

The current codebase is intentionally small. It is meant to be a practical
starting point for a personal AI companion rather than a large AionHome-style
platform.

## What This Project Does

- Uses Hermes as the underlying agent/model runtime.
- Supports Telegram chat as the primary interaction entry.
- Provides a FastAPI service for webhook-style Telegram integration and Mini App
  pages.
- Keeps memory in readable Markdown files instead of opaque-only vector storage.
- Adds `feel` and `dream` style reflection flows for relationship digestion.
- Includes a message board, calendar-ready data model, and reminder-ready data
  model.
- Keeps high-impact generated memories reviewable before they become durable.
- Avoids committing any real OAuth credentials, bot tokens, local databases, or
  Hermes runtime state.

## Project Status

This is an early personal-companion scaffold. The repository contains the
application layer and documentation, while your local Hermes installation,
Telegram bot token, Codex/OAuth credentials, database, pairing records, and
runtime memories stay outside git.

The production path I use is:

```text
Telegram -> Hermes Gateway -> Hermes Agent / Codex
```

The FastAPI app in this repo is for the companion control surface, Mini App
experiments, webhook-compatible deployments, and the readable memory workflow.

## Architecture

```text
kirari/
├── app/
│   ├── main.py          # FastAPI routes and Mini App API
│   ├── telegram.py      # Telegram webhook handling
│   ├── hermes_client.py # Hermes CLI adapter
│   ├── memory_files.py  # Markdown memory file management
│   ├── dream.py         # dream/feel reflection jobs
│   ├── reminders.py     # reminder scheduling helpers
│   ├── retrieval.py     # lightweight readable-memory retrieval
│   ├── db.py            # SQLite schema and connection helpers
│   ├── schemas.py       # API schemas
│   └── config.py        # environment-driven settings
├── static/
│   ├── index.html       # Mini App/control panel shell
│   ├── app.css
│   └── app.js
├── tests/
│   └── test_memory_files.py
├── .env.example         # safe template only, no secrets
├── pyproject.toml
└── README.md
```

## Memory Model

Kirari keeps important state in plain Markdown files so the system is readable,
auditable, and easy to edit by hand.

Default memory location:

```text
~/.hermes/memories/
```

Recommended files:

- `SOUL.md` - persona, values, tone, relationship boundaries. User-edited only.
- `USER.md` - durable facts about the user.
- `MEMORY.md` - durable shared history and long-term facts.
- `FEEL.md` - first-person emotional sediment from recent interactions.
- `DREAM.md` - daily reflection, consolidation, contradictions, and questions.
- `PINNED.md` - promises, boundaries, hard rules, and never-forget items.
- `BOARD.md` - curated message-board archive.

The intent is to keep the core identity and memory reviewable. Embeddings can
be added later for search quality, but they should not replace the readable
source of truth.

## Dream / Feel Flow

`feel` is the short-cycle reflection layer. It turns recent interaction into
emotional continuity:

- What changed in the relationship?
- What did the user seem to care about?
- What should be held gently next time?
- What should not be overfit into permanent memory?

`dream` is the stronger daily consolidation layer:

- Summarizes the day.
- Detects repeated patterns.
- Proposes durable memories.
- Flags contradictions or risky assumptions.
- Creates review items instead of silently rewriting important identity state.

This keeps Kirari from treating every message as permanent truth while still
allowing the companion to feel continuous over time.

## Telegram Modes

There are two Telegram integration paths:

### 1. Hermes Gateway

This is the recommended base path.

```bash
hermes gateway install
hermes gateway start
hermes gateway status
```

Configure Telegram in your local Hermes environment, usually:

```text
~/.hermes/.env
```

Example keys:

```env
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_ALLOWED_USERS=123456789
GATEWAY_ALLOW_ALL_USERS=false
```

Do not commit `~/.hermes/.env`.

### 2. FastAPI Webhook

This repo also includes a webhook handler if you deploy the FastAPI service
directly:

```text
POST /telegram/webhook
```

After deployment:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=$BASE_URL/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

Use either long polling through Hermes Gateway or a webhook deployment. Do not
run two consumers for the same Telegram bot unless you know exactly how updates
are routed.

## Installation

### Requirements

- Python 3.10+
- Hermes Agent installed and configured
- A Telegram bot created with BotFather
- A model provider configured for Hermes, such as Codex/OAuth or an API-key
  provider

### Install Hermes

Follow the Hermes project documentation. A typical install is:

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
hermes status
```

Configure your model provider locally:

```bash
hermes model
hermes auth status
```

### Install Kirari

```bash
git clone https://github.com/DriftingBoats/kirari.git
cd kirari
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally:

```env
APP_HOST=0.0.0.0
APP_PORT=8080
BASE_URL=https://example.com
APP_DATA_DIR=./data

TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_WEBHOOK_SECRET=

HERMES_BIN=hermes
HERMES_HOME=~/.hermes
HERMES_TIMEOUT_SECONDS=180
HERMES_DRY_RUN=false

DREAM_HOUR=4
RECENT_MESSAGE_LIMIT=24
```

`.env` is ignored by git. Keep all real values there or in `~/.hermes/.env`.

## Running Locally

```bash
. .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Open:

```text
http://127.0.0.1:8080/
```

Health/config endpoint:

```text
GET /api/config
```

## API Surface

Common routes:

- `GET /` - Mini App/control panel shell.
- `GET /api/config` - safe runtime configuration summary.
- `GET /api/memories` - list memory files.
- `GET /api/memories/{name}` - read a memory file.
- `PUT /api/memories/{name}` - update an editable memory file.
- `GET /api/board` - list board messages.
- `POST /api/board` - create a board message.
- `GET /api/reminders` - list reminders.
- `POST /api/reminders` - create a reminder.
- `POST /api/dream/run` - run a dream/feel reflection pass.
- `POST /telegram/webhook` - Telegram webhook endpoint.

## Testing

```bash
python3 -m pytest -q
```

For a quick syntax check:

```bash
python3 -m compileall app
```

## Security

Never commit:

- `.env`
- `~/.hermes/.env`
- `~/.hermes/auth.json`
- Telegram bot tokens
- Codex/OpenAI/Anthropic/OAuth access tokens
- refresh tokens
- local SQLite databases
- pairing records
- real `SOUL.md`, `USER.md`, `MEMORY.md`, `FEEL.md`, or `DREAM.md` files
  containing private personal data

Before publishing, run:

```bash
rg -n --hidden \
  'token|secret|oauth|authorization|api[_-]?key|password|refresh_token|access_token' .
```

This repository includes `.env.example` only as a template. Real values belong
in your local environment.

If a secret is ever pushed by mistake:

1. Revoke or rotate it immediately.
2. Remove it from git history.
3. Force-push only after understanding the impact.
4. Treat the old value as compromised forever.

## Deployment Notes

For personal use, Hermes Gateway as a user service is the simplest option:

```bash
hermes gateway install
hermes gateway start
hermes gateway status
```

For a cloud Mini App or webhook deployment:

- Use HTTPS.
- Set `BASE_URL` to the public URL.
- Set a strong `TELEGRAM_WEBHOOK_SECRET`.
- Keep `TELEGRAM_ALLOWED_USER_IDS` restricted.
- Keep `GATEWAY_ALLOW_ALL_USERS=false` if using Hermes Gateway.
- Store runtime data on persistent storage.

## Roadmap

- Telegram Mini App polish.
- Calendar view for relationship and work dates.
- Reminder delivery through Telegram.
- Review queue UI for proposed memories.
- Optional embedding index for retrieval, while keeping Markdown as truth.
- Safer import/export of memory packs.
- Better SOUL.md editing workflow in the Mini App.

## License

MIT. See [LICENSE](LICENSE).
