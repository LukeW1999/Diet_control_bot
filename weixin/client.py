"""iLink Bot HTTP client.

Tencent's officially opened WeChat bot protocol: plain HTTP/JSON against
`ilinkai.weixin.qq.com`, no SDK and no Node gateway needed.
"""
import json
import logging
import os
import random
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("ILINK_BASE_URL", "https://ilinkai.weixin.qq.com")
_TOKENS = Path(__file__).resolve().parent.parent / "data" / "weixin_tokens.json"


def _headers(token: str | None = None) -> dict:
    head = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        # A fresh uint32 per request; the protocol uses it against replay.
        "X-WECHAT-UIN": b64encode(str(random.getrandbits(32)).encode()).decode(),
    }
    if token:
        head["Authorization"] = f"Bearer {token}"
    return head


def request(path: str, payload: dict | None = None, token: str | None = None,
            timeout: int = 60) -> dict:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(token),
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else {}


def load_tokens() -> dict:
    """{tenant: {token, bot_id, user_id}}. Kept out of `.env` because there is one
    per person and they are rotated by rescanning, not by editing config."""
    if not _TOKENS.exists():
        return {}
    return json.loads(_TOKENS.read_text(encoding="utf-8"))


def save_token(tenant: str, token: str, bot_id: str, user_id: str) -> None:
    tokens = load_tokens()
    tokens[tenant] = {"token": token, "bot_id": bot_id, "user_id": user_id}
    _TOKENS.parent.mkdir(parents=True, exist_ok=True)
    _TOKENS.write_text(json.dumps(tokens, ensure_ascii=False, indent=1), encoding="utf-8")
    _TOKENS.chmod(0o600)


def send_text(token: str, to_user_id: str, context_token: str, text: str) -> dict:
    """`context_token` comes from the message being answered. Without it the reply
    is not tied to the conversation it belongs to.

    A failure here used to be silent, which is the worst way for it to fail: the
    user sees whatever went out first and nothing after.
    """
    result = _send(token, to_user_id, context_token, text)
    if result.get("ret") not in (0, None):
        logger.error("weixin send failed ret=%s errmsg=%s text=%.30s",
                     result.get("ret"), result.get("errmsg"), text)
    return result


def _send(token: str, to_user_id: str, context_token: str, text: str) -> dict:
    return request("ilink/bot/sendmessage", {
        "msg": {
            "to_user_id": to_user_id,
            "message_type": 2,   # from the bot
            "message_state": 2,  # complete message
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        },
    }, token=token)
