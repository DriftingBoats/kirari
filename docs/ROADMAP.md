# Kirari roadmap

## Product baseline

Kirari now owns the companion runtime. Hermes is no longer a dependency. Model inference runs through a locally authenticated Codex CLI and therefore uses ChatGPT/Codex subscription allowance rather than API-key billing.

## Capability benchmark

Current companion products consistently emphasize:

1. Stable persona and relationship customization.
2. Short-, medium-, and long-term memory with user correction or pinning.
3. Cross-session continuity and reflection/diary surfaces.
4. Optional proactive contact with user-controlled frequency.
5. Voice and image understanding/generation.
6. Activities, reminders, coaching, or shared rituals.
7. Multiple companions or group conversations.
8. Clear privacy, export, deletion, and safety controls.

Kirari's differentiator is a readable, local-first memory source of truth with reviewable AI changes.

## Shipped in the runtime restart

- [x] Direct Codex CLI subscription adapter with API-key fallback disabled.
- [x] Native Windows `codex.exe` resolution.
- [x] Local Telegram long polling and optional webhook mode.
- [x] Per-chat serialization, webhook deduplication, typing heartbeat, and long-message splitting.
- [x] Local web chat sharing the same identity and long-term memory.
- [x] Structured reply output and review items for memories, boundaries, reminders, and events.
- [x] User-controlled message pinning.
- [x] Scheduled dream/feel reflection with a strict output schema.
- [x] Optional proactive check-ins with inactivity, cooldown, and quiet hours.
- [x] Reminder recurrence and snooze.
- [x] Memory edit/delete API, file version history, and rollback.

## Next priorities

### 1. Memory quality and portability

- Add conflict detection and supersession instead of accumulating contradictory facts.
- Add a first-class memory-bank UI for edit, resolve, and delete.
- Add encrypted export/import with a dry-run preview.
- Add memory budget visualization and automatic compaction.

### 2. Safer autonomy

- Add per-capability consent controls in the UI.
- Add a proactive-message history and per-day cap.
- Add delivery receipts and retry policy for Telegram failures.
- Add audit events for every state-changing AI proposal and user approval.

### 3. Multimodal continuity

- Add Telegram voice-note transcription and optional text-to-speech through a separate provider.
- Add image understanding with explicit retention choices.
- Keep media optional so the subscription-only text path remains usable.

### 4. Multiple identities

- Move identity and memory paths behind a companion ID.
- Add independent SOUL, PINNED, memory, and conversation scopes.
- Add group scenes only after isolation tests prevent cross-companion memory leakage.

### 5. Operations

- Add a Windows service/task setup script and a systemd unit.
- Add health checks that do not consume Codex allowance.
- Add CI for unit tests, dependency auditing, and secret scanning.
- Add backup/restore documentation for `data/`.

## Non-goals

- Treating a ChatGPT subscription as a general OpenAI API credential.
- Shipping or copying Codex account tokens into public hosting.
- Silent edits to identity, boundaries, reminders, or external systems.
- Opaque vector storage as the only memory source of truth.
