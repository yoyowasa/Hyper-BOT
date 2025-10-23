from __future__ import annotations

"""ノンス管理（最新 100 個・UTC ミリ秒・単調増加）。"""

import time
from collections import deque
from typing import Deque


MS_PER_DAY = 86_400_000


class NonceManager:
    """署名に用いるノンスを管理する小さなヘルパ。

    - 直近 100 個のノンスを保存して重複送信を防止
    - プロセス内で単調増加を保証
    - (T−2 日, T+1 日) の有効ウィンドウ判定
    """

    def __init__(self) -> None:
        self._recent: Deque[int] = deque(maxlen=100)
        self._last: int = 0

    def now_ms(self) -> int:
        """現在の UTC ミリ秒を返す。"""

        return int(time.time() * 1000)

    def next(self) -> int:
        """次に使用する単調増加ノンスを生成して記録する。"""

        n = self.now_ms()
        if n <= self._last:
            n = self._last + 1
        self._last = n
        self._recent.append(n)
        return n

    def record(self, nonce: int) -> None:
        """外部から受け取ったノンスを記録（last の更新を含む）。"""

        self._last = max(self._last, nonce)
        self._recent.append(nonce)

    def within_valid_window(self, nonce: int) -> bool:
        """ノンスが (T−2 日, T+1 日) の範囲内かを判定する。"""

        now = self.now_ms()
        return (now - 2 * MS_PER_DAY) < nonce < (now + 1 * MS_PER_DAY)

    def seen(self, nonce: int) -> bool:
        """直近 100 個に含まれる（既出）かを返す。"""

        return nonce in self._recent
