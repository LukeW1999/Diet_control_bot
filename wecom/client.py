import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

_token_cache: dict = {"token": "", "expires_at": 0.0}


def get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    r = requests.get(
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
        params={
            "corpid": os.getenv("WECOM_CORP_ID"),
            "corpsecret": os.getenv("WECOM_SECRET"),
        },
        timeout=10,
    )
    data = r.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom token error: {data}")
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 7200)
    logger.info("WeCom access token refreshed")
    return _token_cache["token"]


def send_text(user_id: str, content: str) -> None:
    token = get_access_token()
    r = requests.post(
        "https://qyapi.weixin.qq.com/cgi-bin/message/send",
        params={"access_token": token},
        json={
            "touser": user_id,
            "msgtype": "text",
            "agentid": int(os.getenv("WECOM_AGENT_ID", "0")),
            "text": {"content": content},
        },
        timeout=10,
    )
    result = r.json()
    if result.get("errcode") != 0:
        logger.error("WeCom send_text failed: %s", result)


def download_media(media_id: str) -> bytes:
    token = get_access_token()
    r = requests.get(
        "https://qyapi.weixin.qq.com/cgi-bin/media/get",
        params={"access_token": token, "media_id": media_id},
        timeout=30,
    )
    return r.content
