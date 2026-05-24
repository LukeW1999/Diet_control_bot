"""
Fetch a random quote from the public hitokoto API.
Returns (text, source) or None on failure.
"""
import aiohttp

_URL = "https://v1.hitokoto.cn/?encode=json"
_TIMEOUT = aiohttp.ClientTimeout(total=6)


async def fetch_hitokoto() -> tuple[str, str] | None:
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(_URL) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
    except Exception:
        return None

    text = (data.get("hitokoto") or "").strip()
    if not text:
        return None

    from_book = (data.get("from") or "").strip()
    from_who = (data.get("from_who") or "").strip()

    if from_who and from_book:
        source = f"{from_who}《{from_book}》"
    elif from_book:
        source = f"《{from_book}》"
    elif from_who:
        source = from_who
    else:
        source = "一言"

    return text, source
