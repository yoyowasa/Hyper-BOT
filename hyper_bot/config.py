from __future__ import annotations

"""グローバル設定・定数をまとめたモジュール。

- エンドポイント（REST/WS）
- 手数料の既定値（ベースティア）
- ファンディングのベースレートと上限
- インパクト想定名目額
- レート制限
"""

import os
from dataclasses import dataclass


# エンドポイント
MAINNET_REST = "https://api.hyperliquid.xyz"
TESTNET_REST = "https://api.hyperliquid-testnet.xyz"
MAINNET_WS = "wss://api.hyperliquid.xyz/ws"
TESTNET_WS = "wss://api.hyperliquid-testnet.xyz/ws"


# 手数料（ベースティア）
DEFAULT_FEES = {
    "taker": 0.00045,  # 0.045%
    "maker": 0.00015,  # 0.015%
}

# ファンディング: 8 時間毎 0.01% ベース相当 → 1 時間あたり 0.00125%
FUNDING_HOURLY_BASE = 0.0000125
FUNDING_HOURLY_CAP = 0.04  # 1 日あたりの上限（参考）

# ファンディング計算用のインパクト想定名目額
IMPACT_NOTIONAL_BTC_ETH = 20_000
IMPACT_NOTIONAL_OTHERS = 6_000


# レート制限（例値）
REST_RATE_LIMIT_PER_MIN = 1200
WS_LIMITS = {
    "max_connections": 100,
    "max_subscriptions": 1000,
    "max_msgs_per_min": 2000,
}


@dataclass(frozen=True)
class Endpoints:
    """REST/WS のエンドポイント型。"""

    base_url: str
    ws_url: str


def get_endpoints(network: str | None = None) -> Endpoints:
    """ネットワーク(mainnet|testnet)に応じたエンドポイントを返す。

    備考: HL_BASE_URL / HL_WS_URL が設定されていれば、それらを優先して利用する。
    """

    # 明示オーバーライドがあれば最優先
    env_base = os.getenv("HL_BASE_URL")
    env_ws = os.getenv("HL_WS_URL")
    if env_base or env_ws:
        net_env = (os.getenv("HL_NETWORK", "mainnet")).lower()
        base = env_base or (TESTNET_REST if net_env == "testnet" else MAINNET_REST)
        ws = env_ws or (TESTNET_WS if net_env == "testnet" else MAINNET_WS)
        return Endpoints(base, ws)

    net = (network or os.getenv("HL_NETWORK", "mainnet")).lower()
    if net == "testnet":
        return Endpoints(TESTNET_REST, TESTNET_WS)
    return Endpoints(MAINNET_REST, MAINNET_WS)


def impact_notional_for(symbol: str) -> int:
    """シンボルに応じた想定インパクト名目額を返す。"""

    s = symbol.upper()
    if s.startswith("BTC") or s.startswith("ETH"):
        return IMPACT_NOTIONAL_BTC_ETH
    return IMPACT_NOTIONAL_OTHERS


def min_order_notional() -> float:
    """最小発注名目（USD 換算）を返す。既定は $10。"""

    return 10.0

