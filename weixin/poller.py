"""One long-poll loop per bound account.

Scanning the QR mints a separate bot each time, so each person has their own
token and their own loop. That also settles tenancy: whichever loop receives a
message, that is whose data it belongs to.
"""
import asyncio
import json
import logging

from utils import tenant
from weixin import client, handlers

logger = logging.getLogger(__name__)

async def _loop(tenant_key: str, cfg: dict) -> None:
    token = cfg["token"]
    buf = cfg.get("updates_buf") or ""
    try:
        logger.info("notifystart %s → %s", tenant_key,
                    await asyncio.to_thread(client.notify_start, token))
    except Exception:
        logger.exception("notifystart failed for %s", tenant_key)
    logger.info("weixin loop started for %s", tenant_key)
    while True:
        try:
            resp = await asyncio.to_thread(
                client.request, "ilink/bot/getupdates",
                {"get_updates_buf": buf, "base_info": client.base_info()},
                token, 60)
        except Exception:
            logger.exception("getupdates failed for %s", tenant_key)
            await asyncio.sleep(5)
            continue

        new_buf = resp.get("get_updates_buf")
        if new_buf and new_buf != buf:
            buf = new_buf
            _remember_cursor(tenant_key, buf)

        for msg in resp.get("msgs") or []:
            # message_type 1 is the human; the bot's own messages come back too.
            if msg.get("message_type") != 1:
                continue
            logger.info("weixin msg %s", json.dumps(
                {k: (v[:24] if isinstance(v, str) else v)
                 for k, v in msg.items() if k != "item_list"}, ensure_ascii=False)[:300])
            _remember(tenant_key, "last_context", msg.get("context_token", ""))
            _remember(tenant_key, "last_from", msg.get("from_user_id", ""))
            tenant.set_current(tenant_key)
            try:
                await handlers.handle_message(tenant_key, token, msg)
            except Exception:
                logger.exception("handling failed for %s", tenant_key)


def _remember_cursor(tenant_key: str, buf: str) -> None:
    """Persist it, or a restart replays whatever the server still holds."""
    _remember(tenant_key, "updates_buf", buf)


def _remember(tenant_key: str, field: str, value: str) -> None:
    """Keeping the last context token makes a failed reply retryable; without it a
    send that goes nowhere cannot even be tried again."""
    tokens = client.load_tokens()
    if tenant_key in tokens:
        tokens[tenant_key][field] = value
        client._TOKENS.write_text(json.dumps(tokens, ensure_ascii=False, indent=1),
                                  encoding="utf-8")


async def run() -> None:
    tokens = client.load_tokens()
    if not tokens:
        logger.warning("no bound WeChat accounts; nothing to poll")
        return
    await asyncio.gather(*(_loop(k, v) for k, v in tokens.items()))
