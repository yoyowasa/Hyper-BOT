"""TP/SL（positionTpsl）発注の最小例（テストネット推奨）。

注意:
- まずポジション（片側）を少量持ってから、ReduceOnly の TP/SL を positionTpsl で設定します。
- `HL_NETWORK=testnet` を推奨。本番で実行しないでください。
"""

import argparse
import os
import sys
from typing import Any, Dict

from loguru import logger

from hyper_bot.metadata import MetadataResolver
from hyper_bot.orders import OrderSpec, build_order, notional_ok
from hyper_bot.rest_client import HyperliquidREST


def build_trigger_order(
    asset_id: int,
    is_buy: bool,
    sz: float,
    limit_px: float,
    trigger_px: float,
    tpsl: str,  # "tp" | "sl"
    sz_decimals: int,
) -> Dict[str, Any]:
    """トリガ注文（TP/SL）を OrderWire 形式で構築（ReduceOnly 前提）。"""

    from hyper_bot.utils import round_size_by_decimals

    return {
        "a": asset_id,
        "b": bool(is_buy),
        "p": str(limit_px),
        "s": str(round_size_by_decimals(sz, sz_decimals)),
        "r": True,
        "t": {"trigger": {"triggerPx": str(trigger_px), "isMarket": True, "tpsl": tpsl}},
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Hyperliquid TP/SL サンプル（positionTpsl）")
    p.add_argument("--symbol", required=True, help="シンボル（例: BTC, ETH）")
    p.add_argument("--size", type=float, default=0.001, help="TP/SL サイズ（ポジションサイズと整合するように）")
    p.add_argument("--tp", type=float, required=True, help="TP トリガ価格")
    p.add_argument("--sl", type=float, required=True, help="SL トリガ価格")
    p.add_argument("--px", type=float, required=True, help="注文の指値（トリガ後の実行上限）")
    p.add_argument("--side", choices=["long", "short"], required=True, help="対象ポジションの向き")
    args = p.parse_args()

    if os.getenv("HL_NETWORK", "mainnet").lower() != "testnet":
        logger.warning("本番ネットワークです。テストネットでの実行を推奨します（HL_NETWORK=testnet）。")

    rest = HyperliquidREST()
    meta = MetadataResolver(rest)
    am = meta.require(args.symbol)

    # 事前にポジションがある前提。なければ先に少量建てること。
    if not notional_ok(args.size, am.mid_px or am.oracle_px):
        logger.error("最小注文金額 $10 を満たしません。サイズ/価格を見直してください。")
        sys.exit(1)

    is_position_long = args.side == "long"
    # TP/SL はポジションと逆方向の注文
    tp_is_buy = not is_position_long
    sl_is_buy = not is_position_long

    tp_order = build_trigger_order(
        am.asset_id,
        tp_is_buy,
        args.size,
        args.px,
        args.tp,
        "tp",
        am.sz_decimals,
    )
    sl_order = build_trigger_order(
        am.asset_id,
        sl_is_buy,
        args.size,
        args.px,
        args.sl,
        "sl",
        am.sz_decimals,
    )

    logger.info("TP/SL 発注（positionTpsl）")
    resp = rest.post_orders([tp_order, sl_order], grouping="positionTpsl")
    logger.info("/exchange 応答: {}", resp)


if __name__ == "__main__":
    main()

