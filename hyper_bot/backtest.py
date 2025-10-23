from __future__ import annotations

"""バックテスト骨格（コストモデルの雛形）。"""

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

from .config import DEFAULT_FEES


@dataclass
class CostParams:
    """コストパラメータ。

    - taker/maker 手数料
    - 時間あたりファンディングレート（ベース）
    """

    taker: float = DEFAULT_FEES["taker"]
    maker: float = DEFAULT_FEES["maker"]
    hourly_funding_base: float = 0.0000125


def taker_fee(sz: float, price: float, fee: float) -> float:
    """テイカー手数料（負の PnL）を返す。"""

    return -abs(sz) * price * fee


def maker_fee(sz: float, price: float, fee: float) -> float:
    """メイカー手数料（負の PnL）を返す。"""

    return -abs(sz) * price * fee


def funding_pnl(position: float, oracle_price: float, hours_held: int, hourly_rate: float) -> float:
    """保有に伴うファンディング PnL（正負は銘柄/符号に依存）を返す。"""

    return -position * oracle_price * hourly_rate * hours_held


def impact_slippage(sz: float, mid_price: float, impact_price: float) -> float:
    """インパクト価格によるスリッページコストの近似。

    コスト ≒ (実行価格 - mid) * サイズ
    """

    exec_px = impact_price
    return (exec_px - mid_price) * sz


def walk_forward(
    df: pd.DataFrame,
    signals: pd.Series,
    cost: CostParams = CostParams(),
) -> pd.DataFrame:
    """ウォークフォワード（最小実装）。

    注意: 結果の event 名（"enter"/"exit"/"funding"）は内部使用を想定し英語のままです。

    引数:
        df: mid/oracle/funding/impactPxs など必要列を含む DataFrame
        signals: 時間ごとの +1/-1/0 シグナル
    """

    results: List[dict] = []
    pos = 0.0
    for ts, sig in signals.items():
        row = df.loc[ts]
        mid = row.get("midPx", np.nan)
        oracle = row.get("oraclePx", mid)
        if sig != 0 and pos == 0:
            pos = sig
            fee_cost = taker_fee(sz=1.0, price=mid, fee=cost.taker)
            results.append({"ts": ts, "event": "enter", "pnl": fee_cost})
        elif sig == 0 and pos != 0:
            fee_cost = taker_fee(sz=1.0, price=mid, fee=cost.taker)
            results.append({"ts": ts, "event": "exit", "pnl": fee_cost})
            pos = 0.0
        # ファンディングの積算例（1 時間ごと）
        if pos != 0:
            f_pnl = funding_pnl(position=pos, oracle_price=oracle, hours_held=1, hourly_rate=cost.hourly_funding_base)
            results.append({"ts": ts, "event": "funding", "pnl": f_pnl})
    return pd.DataFrame(results).set_index("ts")
