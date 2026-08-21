from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any


class InvalidToken(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_payload(token: str, secret: str, *, now: int | None = None) -> dict[str, Any]:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(supplied_signature), expected_signature):
            raise InvalidToken("signature mismatch")
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise InvalidToken("malformed signed payload") from exc

    if not isinstance(payload, dict):
        raise InvalidToken("signed payload must be an object")
    current = int(time.time()) if now is None else now
    if not isinstance(payload.get("exp"), int) or payload["exp"] < current:
        raise InvalidToken("signed payload expired")
    return payload


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def new_nonce() -> str:
    return secrets.token_urlsafe(32)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
