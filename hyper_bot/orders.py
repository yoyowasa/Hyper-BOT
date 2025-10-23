from __future__ import annotations

"""注文関連ユーティリティ。"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .utils import round_price, round_size_by_decimals


@dataclass
class OrderSpec:
    """注文仕様（外部入力を想定）。

    - asset_id: 取引対象の資産 ID（/info meta から解決）
    - is_buy: 買いなら True
    - px: 価格（market の場合は None）
    - sz: サイズ（資産ごとの szDecimals で丸め）
    - reduce_only: クローズ専用（ReduceOnly）
    - tif: 時間指定（GTC|IOC|ALO）
    - typ: 注文種別（market|limit|stop|twap）
    - cloid: クライアント ID（任意）
    - grouping: TP/SL のグルーピング（na|normalTpsl|positionTpsl）
    """

    asset_id: int
    is_buy: bool
    px: Optional[float]
    sz: float
    reduce_only: bool = False
    tif: str = "GTC"  # GTC|IOC|ALO
    typ: str = "limit"  # market|limit|stop|twap
    cloid: Optional[str] = None
    grouping: str = "na"  # na|normalTpsl|positionTpsl


def build_order(spec: OrderSpec, px_tick: Optional[float], sz_decimals: int) -> Dict[str, Any]:
    """API 送信用の注文ペイロードを構築する。

    - 価格は Tick に従って切り下げ丸め
    - サイズは szDecimals に従って切り下げ丸め
    - 最小注文金額（$10）や余力チェックは、呼び出し元で実施してください
    """

    px = None if spec.px is None else round_price(spec.px, px_tick or 0.0)
    sz = round_size_by_decimals(spec.sz, sz_decimals)
    order: Dict[str, Any] = {
        "a": spec.asset_id,
        "b": bool(spec.is_buy),
        "s": sz,
        "r": bool(spec.reduce_only),
        "t": spec.typ,
        "TIF": spec.tif,
        "grouping": spec.grouping,
    }
    if px is not None:
        order["p"] = px
    if spec.cloid:
        order["c"] = spec.cloid
    return order


def schedule_cancel_body(seconds_from_now: int) -> Dict[str, Any]:
    """DMS（Dead Man's Switch）予約用のペイロードを返す。"""

    return {"type": "scheduleCancel", "secs": seconds_from_now}
