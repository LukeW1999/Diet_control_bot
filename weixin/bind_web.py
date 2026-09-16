"""A binding link that does not go stale.

The QR iLink issues expires in minutes, which is useless for "send this to someone
and let them get to it later". This mints a fresh one on every open instead, so the
link itself never expires. On a phone it redirects straight into WeChat; on a
desktop it draws the QR to scan.
"""
import io
import logging
import threading
import time

from flask import Blueprint, Response, redirect, request

from utils import tenant
from weixin import client

bind_bp = Blueprint("weixin_bind", __name__)
logger = logging.getLogger(__name__)


def _watch(tenant_key: str, qid: str) -> None:
    """Hold the long poll until they confirm, then keep the token."""
    deadline = time.time() + 1800
    while time.time() < deadline:
        try:
            status = client.request(f"ilink/bot/get_qrcode_status?qrcode={qid}", timeout=45)
        except Exception:
            time.sleep(2)
            continue
        if not status:
            continue
        if status.get("bot_token"):
            client.save_token(tenant_key, status["bot_token"],
                              status.get("ilink_bot_id", ""),
                              status.get("ilink_user_id", ""))
            logger.info("weixin bound: tenant=%s bot=%s user=%s", tenant_key,
                        status.get("ilink_bot_id"), status.get("ilink_user_id"))
            return
        if status.get("status") in ("expired", "cancel", "cancelled"):
            return


def _fresh(tenant_key: str) -> str:
    start = client.request("ilink/bot/get_bot_qrcode?bot_type=3", timeout=20)
    threading.Thread(target=_watch, args=(tenant_key, start["qrcode"]), daemon=True).start()
    return start["qrcode_img_content"]


@bind_bp.route("/wx/bind/<tenant_key>")
def bind(tenant_key: str):
    tenant_key = tenant_key.lower()
    if tenant_key not in tenant.known():
        return Response("unknown user", status=404)
    url = _fresh(tenant_key)
    if request.args.get("qr"):
        return Response(_qr_png(url), mimetype="image/png")
    return redirect(url, code=302)


def _qr_png(url: str) -> bytes:
    import qrcode
    buf = io.BytesIO()
    qrcode.make(url).save(buf, format="PNG")
    return buf.getvalue()
