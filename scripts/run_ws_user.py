"""ユーザ系 WS 購読（fills / orderUpdates / userEvents）。

HL_ADDRESS を .env か環境変数で設定して実行してください。
"""

import argparse
import asyncio
import os
from typing import Any, Dict

from loguru import logger

from hyper_bot.ws_client import WebsocketClient


async def handler(msg: Dict[str, Any]) -> None:
    if not isinstance(msg, dict):
        return
    t = msg.get("type") or msg.get("channel")
    if t in ("userEvents", "userFills", "orderUpdates"):
        logger.info("{}: {}", t, msg)


async def run(address: str) -> None:
    ws = WebsocketClient()
    # Hyperliquid の WS は subscribe ラッパではなく、サブスクリプションオブジェクトをそのまま送る
    ws.add_raw_subscription({"type": "userEvents", "user": address})
    ws.add_raw_subscription({"type": "userFills", "user": address})
    ws.add_raw_subscription({"type": "orderUpdates", "user": address})
    await ws.run(handler)


def main() -> None:
    p = argparse.ArgumentParser(description="ユーザ系 WS 購読")
    p.add_argument("--address", type=str, default=os.getenv("HL_ADDRESS", ""), help="ユーザアドレス（0x...）")
    args = p.parse_args()
    if not args.address:
        raise SystemExit("HL_ADDRESS が未設定です。--address か環境変数で指定してください。")
    asyncio.run(run(args.address))


if __name__ == "__main__":
    main()

