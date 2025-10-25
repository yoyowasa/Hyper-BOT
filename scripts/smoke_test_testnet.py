"""Testnet smoke test for placing a tiny IOC order safely.

Usage examples:
  python scripts/smoke_test_testnet.py --symbol BTC --side buy --confirm
  python scripts/smoke_test_testnet.py --symbol ETH --side sell --size 0.01 --confirm --dms 10

Safety:
- Requires HL_NETWORK=testnet, otherwise exits.
- Requires HL_PRIVATE_KEY/HL_ADDRESS in environment only when --confirm is present.
- Without --confirm, runs a dry-run and prints the would-be payload.
"""

import argparse
import os
import sys
from typing import Optional

from loguru import logger

from hyper_bot.metadata import MetadataResolver
from hyper_bot.orders import OrderSpec, build_order, notional_ok
from hyper_bot.rest_client import HyperliquidREST


def main() -> None:
    p = argparse.ArgumentParser(description="Testnet IOC smoke test")
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--size", type=float, default=0.0, help="Size; if 0, compute minimal by $10 notion")
    p.add_argument("--market", action="store_true", default=True, help="Use market IOC (default)")
    p.add_argument("--confirm", action="store_true", help="Actually send the order to testnet")
    p.add_argument("--dms", type=int, default=0, help="Schedule DMS cancel seconds from now (0=off)")
    p.add_argument("--offline", action="store_true", help="Do not fetch metadata; use placeholder formatting values (DRY RUN only)")
    args = p.parse_args()

    # Load .env
    if load_dotenv is not None:
        env_file = os.getenv("ENV_FILE")
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

    if os.getenv("HL_NETWORK", "mainnet").lower() != "testnet":
        logger.error("HL_NETWORK must be testnet for this smoke test")
        sys.exit(2)

    rest = HyperliquidREST()
    am = None
    if not args.offline:
        meta = MetadataResolver(rest)
        am = meta.require(args.symbol)

    # Determine price reference for min notional check
    px_ref: Optional[float] = None
    if am is not None:
        px_ref = am.mid_px or am.oracle_px

    size = float(args.size)
    if size <= 0:
        if am is not None and px_ref is not None:
            size = max(10.0 / float(px_ref), 10 ** (-am.sz_decimals))
        else:
            # fallback when price is unavailable (e.g., limited meta on testnet)
            decimals = am.sz_decimals if am is not None else 3
            size = max(0.001, 10 ** (-decimals))

    asset_id = am.asset_id if am is not None else 0
    sz_decimals = am.sz_decimals if am is not None else 3
    tick_size = am.tick_size if am is not None else None

    spec = OrderSpec(
        asset_id=asset_id,
        is_buy=(args.side == "buy"),
        px=None,  # market
        sz=size,
        tif="IOC",
        typ="market",
    )
    order = build_order(spec, tick_size, sz_decimals)

    if not args.confirm:
        logger.info("DRY RUN (no order sent). Set --confirm to send.")
        logger.info("order payload: {}", order)
        return

    # Ensure key present only when sending
    if not os.getenv("HL_PRIVATE_KEY"):
        logger.error("HL_PRIVATE_KEY not set; refusing to send even on testnet")
        sys.exit(4)

    resp = rest.post_orders([order])
    logger.info("/exchange response: {}", resp)

    if args.dms and args.dms >= 5:
        d = rest.schedule_cancel(args.dms)
        logger.info("scheduleCancel response: {}", d)


if __name__ == "__main__":
    main()
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None
