# Runtime Hermes Patches

Kirari currently uses Hermes Gateway as the live Telegram responder. These
patches document local runtime changes applied to the installed Hermes copy.

## Telegram Paragraph Split

`hermes-telegram-paragraph-split.patch` changes
`gateway/platforms/telegram.py` so multi-paragraph assistant replies are sent as
multiple Telegram messages in order. Fenced code blocks stay intact.

The live environment also sets:

```env
TELEGRAM_REPLY_TO_MODE=off
```

That disables ordinary Telegram reply quoting. Hermes can still use reply
anchors where Telegram requires them for special routing, such as DM topics.
