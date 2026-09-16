"""WeChat adapter.

A reply has to carry the `context_token` of the message it answers, so `send` is
bound per inbound message rather than per user.
"""
from utils import router
from weixin import client


async def handle_message(tenant_key: str, token: str, msg: dict) -> None:
    text = ""
    for item in msg.get("item_list") or []:
        if item.get("type") == 1:
            text = (item.get("text_item") or {}).get("text") or ""
            break
    if not text.strip():
        return

    def send(reply: str) -> None:
        client.send_text(token, msg["from_user_id"], msg.get("context_token", ""), reply)

    await router.handle_text(tenant_key, send, text)
