from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


@dataclass(frozen=True)
class TelegramWebAppUser:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class TelegramWebAppAuthError(ValueError):
    pass


def validate_init_data(
    init_data: str,
    *,
    bot_token: str,
    allowed_user_ids: set[int] | None = None,
    max_age_seconds: int = 604800,
    now: int | None = None,
) -> TelegramWebAppUser:
    if not init_data:
        raise TelegramWebAppAuthError("missing init data")
    if not bot_token:
        raise TelegramWebAppAuthError("missing bot token")

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise TelegramWebAppAuthError("invalid init data") from exc
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise TelegramWebAppAuthError("missing hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise TelegramWebAppAuthError("invalid hash")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise TelegramWebAppAuthError("invalid auth date") from exc
    current_time = int(time.time()) if now is None else now
    if auth_date <= 0:
        raise TelegramWebAppAuthError("missing auth date")
    if max_age_seconds > 0 and current_time - auth_date > max_age_seconds:
        raise TelegramWebAppAuthError("expired init data")
    if auth_date - current_time > 300:
        raise TelegramWebAppAuthError("future auth date")

    try:
        user_payload = json.loads(pairs.get("user", "{}"))
        user_id = int(user_payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramWebAppAuthError("invalid user") from exc

    allowed = allowed_user_ids or set()
    if allowed and user_id not in allowed:
        raise TelegramWebAppAuthError("user not allowed")

    return TelegramWebAppUser(
        id=user_id,
        username=user_payload.get("username"),
        first_name=user_payload.get("first_name"),
        last_name=user_payload.get("last_name"),
    )
