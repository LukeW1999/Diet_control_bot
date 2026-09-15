"""Create the WeCom app's bottom menu. Run once, and again after changing it.

The menu keys are the bot's own commands, so a tap and a typed command reach the
same handler and there is no second mapping to keep in step.
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

MENU = {"button": [
    {"name": "🍎 记食物", "sub_button": [
        {"type": "click", "name": "开始记食物", "key": "/food"},
        {"type": "click", "name": "食物库", "key": "/foods"},
    ]},
    {"name": "📊 数据", "sub_button": [
        {"type": "click", "name": "今日数据", "key": "/today"},
        {"type": "click", "name": "本周汇总", "key": "/week"},
        {"type": "click", "name": "身体成分", "key": "/body"},
        {"type": "click", "name": "生成周报", "key": "/report"},
        {"type": "click", "name": "👀 看对方", "key": "/ta"},
    ]},
    {"name": "⚙️ 模式", "sub_button": [
        {"type": "click", "name": "教练", "key": "/mode 教练"},
        {"type": "click", "name": "聊天", "key": "/mode 聊天"},
        {"type": "click", "name": "自动", "key": "/mode 自动"},
    ]},
]}


def main() -> None:
    token = requests.get(
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
        params={"corpid": os.getenv("WECOM_CORP_ID"),
                "corpsecret": os.getenv("WECOM_SECRET")},
        timeout=10).json()["access_token"]
    r = requests.post(
        "https://qyapi.weixin.qq.com/cgi-bin/menu/create",
        params={"access_token": token, "agentid": os.getenv("WECOM_AGENT_ID")},
        json=MENU, timeout=10).json()
    print("menu/create ->", r)


if __name__ == "__main__":
    main()
