from __future__ import annotations

"""共通ユーティリティ。

- 時刻（UTC ミリ秒）
- 価格/サイズの丸め（Tick・小数桁）
- JSON 保存/読込
"""

import json
import math
import time
from decimal import Decimal, ROUND_DOWN, getcontext
from pathlib import Path
from typing import Any


getcontext().prec = 28


def utc_ms() -> int:
    """現在の UTC 時刻（ミリ秒）を返す。"""

    return int(time.time() * 1000)


def round_price(value: float, tick_size: float) -> float:
    """価格を Tick に従って切り下げ丸めする。"""

    if tick_size <= 0:
        return float(value)
    steps = math.floor(value / tick_size)
    return float(steps * tick_size)


def round_size_by_decimals(value: float, sz_decimals: int) -> float:
    """サイズを資産ごとの小数桁（szDecimals）に従って切り下げ丸めする。"""

    q = Decimal(10) ** -sz_decimals
    return float(Decimal(value).quantize(q, rounding=ROUND_DOWN))


def save_json(path: Path, payload: Any) -> None:
    """JSON を UTF-8 で保存する。親ディレクトリが無い場合は作成する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


def load_json(path: Path) -> Any:
    """JSON ファイルを読み込み、Python オブジェクトを返す。"""

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
