from __future__ import annotations

"""リスク指標とサイズ決定の簡易ユーティリティ。"""

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range（ATR）を計算する。"""

    h, l, c = df["high"], df["low"], df["close"].shift(1)
    tr = np.maximum(h - l, np.maximum((h - c).abs(), (l - c).abs()))
    return pd.Series(tr).rolling(period, min_periods=1).mean()


def size_by_risk(
    account_value: float,
    risk_fraction: float,
    entry_price: float,
    stop_price: float,
) -> float:
    """1 トレードあたり損失上限から逆算したサイズを返す。

    account_value × risk_fraction = 許容損失（USD）
    許容損失 /（エントリ価格−ストップ価格） = サイズ（約）
    """

    risk_dollars = account_value * risk_fraction
    per_unit_risk = abs(entry_price - stop_price)
    if per_unit_risk <= 0:
        return 0.0
    return max(0.0, risk_dollars / per_unit_risk)
