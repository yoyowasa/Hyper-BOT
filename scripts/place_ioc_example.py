"""IOC（成行/指値越え）発注の最小例（テストネット推奨）。

注意:
- 署名実装が未完のため、`hyper_bot/signing.py` を実装しない限り送信は失敗します。
- `HL_NETWORK=testnet` を推奨。本番で実行しないでください。

使い方:
  poetry run python scripts/place_ioc_example.py --symbol BTC --side buy --size 0.001 --market
  poetry run python scripts/place_ioc_example.py --symbol ETH --side sell --size 0.01 --slip-bps 10
"""

import argparse
import os
import sys
import time
import uuid
from typing import Any, Dict

from loguru import logger

from hyper_bot.metadata import MetadataResolver
from hyper_bot.orders import OrderSpec, build_order, notional_ok
from hyper_bot.rest_client import HyperliquidREST
from hyper_bot.signing import sign_exchange_payload


def _cloid(prefix: str = "IOC") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def main() -> None:
    p = argparse.ArgumentParser(description="Hyperliquid IOC 発注サンプル（testnet 推奨）")
    p.add_argument("--symbol", required=True, help="シンボル（例: BTC, ETH）")
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--size", type=float, required=True, help="注文サイズ（現物単位）")
    p.add_argument("--market", action="store_true", help="マーケット（成行）で送信する")
    p.add_argument("--slip-bps", type=float, default=10.0, help="指値越え時の許容 bps（100 bps = 1%）")
    p.add_argument("--dms", type=int, default=0, help="DMS を +秒で予約（0 で無効）")
    args = p.parse_args()

    if os.getenv("HL_NETWORK", "mainnet").lower() != "testnet":
        logger.warning("本番ネットワークです。テストネットでの実行を推奨します（HL_NETWORK=testnet）。")

    rest = HyperliquidREST()
    meta = MetadataResolver(rest)
    am = meta.require(args.symbol)

    # 価格の決定（market なら None、指値なら mid から bps 分だけ跨ぐ）
    px = None
    if not args.market:
        basis = am.mid_px or am.oracle_px
        if basis is None:
            logger.warning("mid/oracle が取得できないため、マーケット注文に切り替えます。")
        else:
            # side に応じてスプレッドを跨ぐ
            sign = 1 if args.side == "buy" else -1
            px = float(basis) * (1.0 + sign * (args.slip_bps / 10_000.0))

    if not notional_ok(args.size, px or am.mid_px or am.oracle_px):
        logger.error("最小注文金額 $10 を満たしません。サイズ/価格を見直してください。")
        sys.exit(1)

    spec = OrderSpec(
        asset_id=am.asset_id,
        is_buy=(args.side == "buy"),
        px=px,
        sz=args.size,
        tif="IOC",
        typ="market" if args.market or px is None else "limit",
        cloid=_cloid(),
    )
    order = build_order(spec, am.tick_size, am.sz_decimals)
    logger.info("送信ペイロード: {}", order)

    # 署名コールバック
    def signer(body: Dict[str, Any], nonce: int) -> str:
        priv = os.getenv("HL_PRIVATE_KEY")
        if not priv:
            raise RuntimeError("HL_PRIVATE_KEY が未設定です。署名実装と鍵設定を行ってください。")
        sig = sign_exchange_payload(body, priv, nonce)
        return sig.signature

    try:
        resp = rest.post_orders([order], signature_cb=signer)
        logger.info("/exchange 応答: {}", resp)
        if args.dms and args.dms >= 5:
            logger.info("DMS を +{} 秒で予約します。", args.dms)
            d = rest.schedule_cancel(args.dms, signature_cb=signer)
            logger.info("scheduleCancel 応答: {}", d)
    except NotImplementedError as e:
        logger.error("署名が未実装です: {}", e)
    except Exception as e:
        logger.exception("発注でエラーが発生しました: {}", e)


if __name__ == "__main__":
    main()

