"""Place a minimal IOC order on Hyperliquid testnet using the official SDK.

Usage examples:
  python scripts/place_ioc_sdk.py --symbol BTC --side buy --size 0.001
  python scripts/place_ioc_sdk.py --symbol ETH --side sell --slip-bps 10

Notes:
- Requires HL_PRIVATE_KEY in environment (0x + 64 hex). Address is derived.
- Uses HL_NETWORK to choose base URL (defaults to mainnet; set testnet explicitly).
"""

from __future__ import annotations

import argparse
import os
from decimal import Decimal, ROUND_DOWN

from eth_account import Account
from loguru import logger

from hyperliquid.exchange import Exchange


MAINNET = "https://api.hyperliquid.xyz"
TESTNET = "https://api.hyperliquid-testnet.xyz"


def _base_url() -> str:
    net = os.getenv("HL_NETWORK", "mainnet").lower()
    if net == "testnet":
        return TESTNET
    return MAINNET


def _round_down(value: float, decimals: int) -> float:
    q = Decimal(10) ** -decimals
    return float(Decimal(value).quantize(q, rounding=ROUND_DOWN))


def main() -> None:
    p = argparse.ArgumentParser(description="Place IOC via official Hyperliquid SDK")
    p.add_argument("--symbol", required=True, help="Symbol name (e.g., BTC, ETH)")
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--size", type=float, default=0.0, help="Order size; if 0, compute minimal ~$10")
    p.add_argument("--slip-bps", type=float, default=10.0, help="Slippage basis points for IOC limit px")
    p.add_argument("--reduce-only", action="store_true", help="Set ReduceOnly to avoid flipping position")
    args = p.parse_args()

    # Load .env if present
    if load_dotenv is not None:
        env_file = os.getenv("ENV_FILE")
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

    priv = os.getenv("HL_PRIVATE_KEY")
    if not priv:
        raise SystemExit("HL_PRIVATE_KEY is not set in environment")
    acct = Account.from_key(priv)

    base_url = _base_url()
    if base_url != TESTNET:
        logger.warning("HL_NETWORK != testnet. You are targeting mainnet endpoints.")

    ex = Exchange(acct, base_url=base_url)

    name = args.symbol.upper()
    is_buy = args.side == "buy"

    # Minimal size (~$10 notion) when not specified
    size = float(args.size)
    coin = ex.info.name_to_coin.get(name)
    if coin is None:
        raise SystemExit(f"Unknown symbol: {name}")
    mid = float(ex.info.all_mids()[coin])
    asset_id = ex.info.coin_to_asset[coin]
    sz_decimals = int(ex.info.asset_to_sz_decimals[asset_id])
    if size <= 0:
        size = max(10.0 / mid, 10 ** (-sz_decimals))
        size = _round_down(size, sz_decimals)

    # Build IOC limit price around mid with slippage
    slip = args.slip_bps / 10_000.0
    # Use SDK's internal slippage price helper for proper rounding
    try:
        limit_px = ex._slippage_price(name, is_buy, slip, px=mid)
    except Exception:
        # Fallback simple calc
        limit_px = mid * (1.0 + slip if is_buy else 1.0 - slip)

    order_type = {"limit": {"tif": "Ioc"}}
    logger.info("Send IOC {} {} size={} px~{} (decimals={})", name, args.side, size, limit_px, sz_decimals)
    resp = ex.order(name, is_buy, size, limit_px, order_type, reduce_only=bool(args.reduce_only))
    logger.info("/exchange response: {}", resp)


if __name__ == "__main__":
    main()
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None
