"""WeCom adapter. The conversation itself lives in `utils.router`; this only binds
the parts that are specific to WeCom."""
from utils import router
from wecom.client import download_media, send_text


def _sender(user_id: str):
    def send(text: str, progress: bool = False) -> None:
        send_text(user_id, text)
    return send


async def handle_text(user_id: str, text: str) -> None:
    await router.handle_text(user_id, _sender(user_id), text)


async def handle_image(user_id: str, media_id: str) -> None:
    await router.handle_image(user_id, _sender(user_id),
                              lambda: download_media(media_id))
