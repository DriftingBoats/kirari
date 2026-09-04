# Security Policy

Kirari is designed for private companion workflows, so accidental data leakage
is the main risk.

## Do Not Commit

- `.env`
- `~/.codex/auth.json`
- Telegram bot tokens
- ChatGPT/Codex access or refresh tokens
- API keys
- local SQLite databases
- pairing records
- private memory files containing real personal data

## Secret Check

Run this before every public push:

```bash
rg -n --hidden \
  'token|secret|oauth|authorization|api[_-]?key|password|refresh_token|access_token' .
```

Expected matches should only be templates, documentation, or variable names.

## External Embedding Privacy

Enabling Gemini embeddings sends memory text to Google's Gemini API. Free-tier
data may be used to improve Google's products. Leave
`GEMINI_EMBEDDING_ENABLED=false` for memories that must not leave the machine.

## If You Leak A Secret

Revoke or rotate the secret first. Then remove it from git history. Assume any
committed token has been compromised, even if the repository was public only for
a short time.
