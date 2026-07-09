import asyncio
import logging
import os
import threading

from flask import Blueprint, request, make_response
from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.enterprise import parse_message

callback_bp = Blueprint("wecom", __name__)
logger = logging.getLogger(__name__)


def _crypto():
    return WeChatCrypto(
        token=os.getenv("WECOM_TOKEN"),
        encoding_aes_key=os.getenv("WECOM_ENCODING_AES_KEY"),
        corp_id=os.getenv("WECOM_CORP_ID"),
    )


@callback_bp.route("/wecom/callback", methods=["GET"])
def verify():
    """WeCom URL verification handshake."""
    try:
        echo = _crypto().check_signature(
            request.args.get("msg_signature", ""),
            request.args.get("timestamp", ""),
            request.args.get("nonce", ""),
            request.args.get("echostr", ""),
        )
        return make_response(echo)
    except Exception as e:
        logger.error("WeCom verify failed: %s", e)
        return make_response("error", 403)


@callback_bp.route("/wecom/callback", methods=["POST"])
def receive():
    """Receive and dispatch WeCom messages."""
    try:
        xml = _crypto().decrypt_message(
            request.data,
            request.args.get("msg_signature", ""),
            request.args.get("timestamp", ""),
            request.args.get("nonce", ""),
        )
    except Exception as e:
        logger.error("WeCom decrypt failed: %s", e)
        return make_response("", 200)

    msg = parse_message(xml)
    # Auto-save user_id for scheduled messages
    _save_user_id(msg.source)

    thread = threading.Thread(target=_run, args=(msg,), daemon=True)
    thread.start()
    return make_response("", 200)


def _save_user_id(user_id: str) -> None:
    """Persist the first seen user_id so cron jobs can use it."""
    if not user_id or os.getenv("WECOM_USER_ID"):
        return
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nWECOM_USER_ID={user_id}\n")
        os.environ["WECOM_USER_ID"] = user_id
        logger.info("Saved WECOM_USER_ID=%s", user_id)
    except Exception:
        pass


def _run(msg) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_dispatch(msg))
    finally:
        loop.close()


async def _dispatch(msg) -> None:
    from wecom.handlers import handle_text, handle_image
    if msg.type == "text":
        await handle_text(msg.source, msg.content)
    elif msg.type == "image":
        await handle_image(msg.source, msg.media_id)
