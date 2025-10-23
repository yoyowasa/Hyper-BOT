"""
WebSocket 紙トレード用の最小サンプルスクリプト。

Hyperliquid の WS に接続し、指定チャンネル（既定: candle）を購読します。
ログは簡潔に出力し、詳細なポジション/約定/ファンディング集計は拡張で対応してください。
"""

import argparse
import asyncio
from typing import Any, Dict

from loguru import logger

from hyper_bot.ws_client import WebsocketClient


async def handler(msg: Dict[str, Any]) -> None:
    """WS メッセージの受信処理（最小版）。

    - candle チャンネルのメッセージのみを抽出し、終値などの要点をログ出力します。
    - 本番運用時は、fills（約定）/funding（ファンディング）/orderUpdates（注文状況）などの
      チャンネルを追加購読し、PnL 集計やフェイルセーフに利用してください。
    """
    if isinstance(msg, dict) and msg.get("channel") == "candle":
        # 冗長なログを避け、必要な情報のみ出力
        data = msg.get("data")
        if data and isinstance(data, dict):
            sym = data.get("symbol")
            tf = data.get("interval")
            ts = data.get("t")
            close = data.get("c")
            logger.info("キャンドル {} {} 時刻={} 終値={}", sym, tf, ts, close)


async def run(channels: str, assets: str) -> None:
    """WS クライアントを起動し、指定チャンネル/銘柄を購読して受信ループを開始します。

    Args:
        channels: カンマ区切りのチャンネル一覧（例: "candle,orderUpdates"）
        assets:   カンマ区切りのシンボル一覧（例: "BTC,ETH"）。candle のみ使用。
    """
    ws = WebsocketClient()
    chs = [c.strip() for c in channels.split(",") if c.strip()]
    syms = [s.strip() for s in assets.split(",") if s.strip()]

    # 指定チャンネルごとに購読を登録
    for ch in chs:
        if ch == "candle":
            for sym in syms:
                # 既定では 1h 足を購読。必要に応じて 1d 等に変更可能。
                ws.add_subscription("candle", symbol=sym, interval="1h")
        else:
            ws.add_subscription(ch)

    # 心拍（ping/pong）や再接続は WebsocketClient にて内部処理
    await ws.run(handler)


def main() -> None:
    """CLI エントリポイント。

    例:
        python scripts/run_ws_paper.py --channels candle --assets BTC,ETH
    """
    p = argparse.ArgumentParser(description="Hyperliquid WS 購読（紙トレ用の簡易ビュー）")
    p.add_argument("--channels", type=str, default="candle", help="購読チャンネルをカンマ区切りで指定")
    p.add_argument("--assets", type=str, default="BTC,ETH", help="対象シンボルをカンマ区切りで指定（candle 用）")
    args = p.parse_args()
    try:
        asyncio.run(run(args.channels, args.assets))
    except KeyboardInterrupt:
        # Ctrl+C での終了を穏当に処理
        logger.info("停止要求（Ctrl+C）を受信。終了します。")


if __name__ == "__main__":
    main()
