"""Cross-process, one-time confirmation tokens for configuration commands."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from core.file_lock import file_lock
from core.paths import BASE_DIR

KEY_PATH = BASE_DIR / "data" / "confirmation.key"
STATE_PATH = BASE_DIR / "data" / "confirmation_tokens.json"
TOKEN_TTL = 120


def _canonical(command: str, transport: str, target: str, session: str) -> str:
    return "\x1f".join((command.strip(), transport.strip(), target.strip(), session.strip()))


def _digest(command: str, transport: str, target: str, session: str) -> str:
    return hashlib.sha256(
        _canonical(command, transport, target, session).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _key() -> bytes:
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(KEY_PATH):
        try:
            value = KEY_PATH.read_bytes()
        except FileNotFoundError:
            value = secrets.token_bytes(32)
            tmp = KEY_PATH.with_name(KEY_PATH.name + ".tmp")
            tmp.write_bytes(value)
            os.replace(tmp, KEY_PATH)
    if len(value) < 32:
        raise RuntimeError("confirmation key is invalid")
    return value


def _sign(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest()
    return body + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


def _decode(token: str) -> dict | None:
    try:
        body, encoded_sig = token.split(".", 1)
        padded = encoded_sig + "=" * (-len(encoded_sig) % 4)
        signature = base64.urlsafe_b64decode(padded)
        expected = hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        raw = body + "=" * (-len(body) % 4)
        value = json.loads(base64.urlsafe_b64decode(raw))
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        return None


def create_request(command: str, transport: str, target: str, session: str,
                   ttl: int = TOKEN_TTL) -> dict:
    request_id = secrets.token_urlsafe(18)
    expires = int(time.time()) + max(1, int(ttl))
    request = {
        "request_id": request_id,
        "command": command.strip(),
        "transport": transport.strip(),
        "target": target.strip(),
        "session": session.strip(),
        "expires": expires,
    }
    with file_lock(STATE_PATH):
        state = _read_json(STATE_PATH, {"requests": {}})
        state.setdefault("requests", {})[request_id] = {
            "digest": _digest(command, transport, target, session),
            "transport": request["transport"],
            "target": request["target"],
            "session": request["session"],
            "expires": expires,
            "approved": False,
            "consumed": False,
        }
        _write_json(STATE_PATH, state)
    return request


def approve_request(request_id: str) -> str | None:
    now = int(time.time())
    with file_lock(STATE_PATH):
        state = _read_json(STATE_PATH, {"requests": {}})
        item = state.get("requests", {}).get(request_id)
        if not item or item.get("consumed") or int(item.get("expires", 0)) < now:
            return None
        item["approved"] = True
        payload = {
            "request_id": request_id,
            "digest": item["digest"],
            "expires": item["expires"],
        }
        _write_json(STATE_PATH, state)
    return _sign(payload)


def consume_token(token: str, command: str, transport: str, target: str,
                  session: str) -> bool:
    payload = _decode(token)
    if not payload or int(payload.get("expires", 0)) < int(time.time()):
        return False
    request_id = str(payload.get("request_id", ""))
    with file_lock(STATE_PATH):
        state = _read_json(STATE_PATH, {"requests": {}})
        item = state.get("requests", {}).get(request_id)
        if not item or item.get("consumed") or not item.get("approved"):
            return False
        if item.get("digest") != _digest(command, transport, target, session):
            return False
        item["consumed"] = True
        _write_json(STATE_PATH, state)
    return True
