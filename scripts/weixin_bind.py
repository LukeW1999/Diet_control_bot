"""Bind a WeChat account to this bot: show a QR, wait for the scan, keep the token.

Usage: weixin_bind.py <tenant>      e.g. weixin_bind.py sjy
"""
import sys
import time
from pathlib import Path

import qrcode
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from weixin import client


def main() -> None:
    tenant = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if not tenant:
        print(__doc__)
        sys.exit(1)

    start = client.request("ilink/bot/get_bot_qrcode?bot_type=3", timeout=20)
    url, qid = start["qrcode_img_content"], start["qrcode"]

    code = qrcode.QRCode(border=1)
    code.add_data(url)
    code.make(fit=True)
    code.print_ascii(invert=True)
    print(url)
    print(f"\n等待 {tenant} 扫码，最多 10 分钟...\n")

    deadline = time.time() + 600
    while time.time() < deadline:
        try:
            status = client.request(f"ilink/bot/get_qrcode_status?qrcode={qid}", timeout=45)
        except Exception:
            time.sleep(2)
            continue
        if not status:
            continue
        if status.get("bot_token"):
            client.save_token(tenant, status["bot_token"],
                              status.get("ilink_bot_id", ""), status.get("ilink_user_id", ""))
            print("✅ 已绑定")
            print("   tenant  :", tenant)
            print("   bot_id  :", status.get("ilink_bot_id"))
            print("   user_id :", status.get("ilink_user_id"))
            print("   baseurl :", status.get("baseurl"))
            return
        if status.get("status") in ("expired", "cancel", "cancelled"):
            print("❌ 二维码已失效或被取消：", status.get("status"))
            return
    print("⏰ 超时，没人扫")


if __name__ == "__main__":
    main()
