# Kirari Development Roadmap

This roadmap keeps Hermes as the base runtime and builds Kirari as the
companion memory, reflection, and Telegram Mini App layer around it.

## Current State

- GitHub repository is public.
- Hermes is installed locally and configured with Codex.
- Telegram Gateway is running through Hermes.
- Kirari has a FastAPI app, Mini App shell, readable memory files, dream/feel
  scaffolding, board, calendar, reminders, and review APIs.
- The first integration gap is being closed: Kirari now imports Hermes Gateway
  Telegram session logs into its own local database for reflection and UI use.

## Development Order

### 1. Conversation Ingestion

Goal: Kirari must see the same Telegram conversation that Hermes Gateway sees.

- Import Hermes Gateway `sessions/*.jsonl` into Kirari's `telegram_messages`.
- Deduplicate imports across repeated syncs.
- Show imported messages in the dashboard.
- Use imported messages as dream/feel input.

Status: shipped for the first pass.

### 2. Readable Memory Core

Goal: make Markdown files the source of truth for companion continuity.

- Stabilize `SOUL.md`, `USER.md`, `MEMORY.md`, `FEEL.md`, `DREAM.md`,
  `PINNED.md`, and `BOARD.md` semantics.
- Add edit history and rollback in the Mini App.
- Make AI-generated high-risk memory changes go through review.
- Keep `SOUL.md` and `PINNED.md` user-controlled.

### 3. Dream / Feel Loop

Goal: daily reflection should improve continuity without hallucinating facts.

- Run dream manually from the Mini App.
- Add scheduled daily dream.
- Split outputs into low-risk memory, review-required memory, feel sediment,
  and board messages.
- Add stricter JSON validation and failure logging.

### 4. Telegram Mini App Productization

Goal: make the Telegram app a real control panel rather than a demo shell.

- Add auth using Telegram WebApp init data.
- Improve mobile layout.
- Add focused screens for SOUL, memory review, board, calendar, and reminders.
- Add empty/loading/error states.

### 5. Calendar And Reminders

Goal: support both relationship dates and work/life dates.

- Add richer calendar views.
- Extract date/reminder intents from chat into pending review.
- Send reminder notifications through Telegram.
- Add repeat rules and snooze.

### 6. Retrieval Upgrade

Goal: improve recall quality while keeping Markdown readable.

- Keep simple text retrieval as baseline.
- Add optional embeddings later.
- Store derived indexes as disposable cache, not as truth.

### 7. Packaging And Deployment

Goal: make setup reproducible for other users.

- Add setup script.
- Add CI tests.
- Add secret scanning in CI.
- Document Hermes Gateway and webhook deployment modes clearly.

## Near-Term Checklist

- [x] Public GitHub repository.
- [x] README and security documentation.
- [x] Hermes + Telegram Gateway local smoke test.
- [x] Basic tests.
- [x] Hermes session importer.
- [x] Dashboard import button.
- [x] Dream/feel using imported Hermes sessions.
- [ ] Memory review workflow polish.
- [ ] Telegram Mini App auth.
