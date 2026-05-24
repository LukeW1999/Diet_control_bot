import aiohttp

# Manchester coordinates
LAT = 53.4808
LON = -2.2426

WMO_CODES = {
    0: ("晴天", "☀️"), 1: ("多云转晴", "🌤️"), 2: ("多云", "⛅"), 3: ("阴天", "☁️"),
    45: ("雾", "🌫️"), 48: ("冻雾", "🌫️"),
    51: ("小毛毛雨", "🌦️"), 53: ("毛毛雨", "🌦️"), 55: ("大毛毛雨", "🌧️"),
    61: ("小雨", "🌧️"), 63: ("中雨", "🌧️"), 65: ("大雨", "🌧️"),
    71: ("小雪", "🌨️"), 73: ("中雪", "❄️"), 75: ("大雪", "❄️"),
    80: ("阵雨", "🌦️"), 81: ("中阵雨", "🌧️"), 82: ("强阵雨", "⛈️"),
    95: ("雷暴", "⛈️"), 96: ("雷暴伴冰雹", "⛈️"), 99: ("强雷暴", "⛈️"),
}


async def get_london_weather() -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&current=temperature_2m,apparent_temperature,precipitation,weathercode,windspeed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
        "&timezone=Europe%2FLondon&forecast_days=1"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()

    current = data["current"]
    daily = data["daily"]

    code = current.get("weathercode", 0)
    desc, icon = WMO_CODES.get(code, ("未知", "🌡️"))
    rain_today = daily["precipitation_sum"][0] or 0

    return {
        "icon": icon,
        "desc": desc,
        "temp_now": current["temperature_2m"],
        "feels_like": current["apparent_temperature"],
        "temp_max": daily["temperature_2m_max"][0],
        "temp_min": daily["temperature_2m_min"][0],
        "rain_mm": rain_today,
        "will_rain": rain_today > 0.5,
        "wind_kmh": current.get("windspeed_10m", 0),
    }


def format_weather(w: dict) -> str:
    lines = [
        f"{w['icon']} 曼彻斯特今日天气：{w['desc']}",
        f"🌡️ 现在 {w['temp_now']:.0f}°C（体感 {w['feels_like']:.0f}°C）",
        f"📊 今日 {w['temp_min']:.0f}°C ~ {w['temp_max']:.0f}°C",
    ]
    if w["will_rain"]:
        lines.append(f"☂️ 预计降雨 {w['rain_mm']:.1f}mm，出门带伞")
    if w["wind_kmh"] > 30:
        lines.append(f"💨 风速 {w['wind_kmh']:.0f} km/h，注意大风")
    return "\n".join(lines)
