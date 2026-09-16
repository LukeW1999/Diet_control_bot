"""WeChat adapter.

A reply spends the `context_token` of the message it answers, and there is only
one per inbound message. So progress notes are dropped and the real answer is the
single thing that goes out.
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

    def send(reply: str, progress: bool = False) -> None:
        if progress:
            return
        client.send_text(token, msg["from_user_id"], msg.get("context_token", ""),
                         reply, reply_to=msg)

    await router.handle_text(tenant_key, send, text)
