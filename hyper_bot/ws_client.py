from __future__ import annotations

"""WebSocket クライアント（心拍・再接続・再購読を内蔵）。"""

import asyncio
import json
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional
import contextlib

import websockets
from loguru import logger

from . import config


MessageHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class WebsocketClient:
    """Hyperliquid 向け WS クライアント。

    - 接続/切断/再接続
    - ping/pong による心拍監視（60 秒無通信のチャネルには必須）
    - 既存購読の復元（再接続時）
    """

    # ハートビート設定（必要に応じて調整）
    _HB_PERIOD_SEC = 10.0            # 何秒ごとに監視するか
    _IDLE_PING_THRESHOLD_SEC = 25.0  # この秒数以上無通信なら ping を送る
    _PING_TIMEOUT_SEC = 10.0         # pong を待つ最大秒数

    def __init__(self, ws_url: Optional[str] = None) -> None:
        eps = config.get_endpoints(os.getenv("HL_NETWORK"))
        self.ws_url = ws_url or eps.ws_url
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._subs: List[Dict[str, Any]] = []
        self._last_rx: float = 0.0
        self._last_ping: float = 0.0
        self._stop = asyncio.Event()
        self._reconnect_attempts: int = 0

    async def connect(self) -> None:
        """WS に接続し、既存の購読を復元する。"""

        logger.info("WS 接続: {}", self.ws_url)
        # 自動 ping は無効にして手動で送る
        # 自動 ping は無効にし、close_timeout を短めに設定して終了を早める
        self._ws = await websockets.connect(self.ws_url, ping_interval=None, close_timeout=1)
        loop = asyncio.get_event_loop()
        self._last_rx = loop.time()
        self._last_ping = 0.0
        self._reconnect_attempts = 0
        await self._resubscribe()

    async def close(self) -> None:
        """WS を明示的にクローズする。"""

        self._stop.set()
        if self._ws is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws.close()
            self._ws = None

    async def _resubscribe(self) -> None:
        """登録済みの購読を再送信する（再接続時など）。"""

        for sub in self._subs:
            await self.send_json(sub)

    async def send_json(self, payload: Dict[str, Any]) -> None:
        """WS へ JSON 文字列を送信する。"""

        assert self._ws is not None
        await self._ws.send(json.dumps(payload))

    def add_subscription(self, channel: str, **kwargs: Any) -> None:
        """購読メッセージを登録する（接続後に自動送信）。"""

        sub = {"type": "subscribe", "channel": channel}
        if kwargs:
            sub.update(kwargs)
        self._subs.append(sub)

    async def _send_ping(self) -> None:
        """1 回だけ ping を送り、pong を待つ。成功時は最終受信時刻を更新。"""

        if self._ws is None:
            return
        loop = asyncio.get_event_loop()
        pong_waiter = await self._ws.ping()
        await asyncio.wait_for(pong_waiter, timeout=self._PING_TIMEOUT_SEC)
        self._last_ping = loop.time()
        self._last_rx = self._last_ping

    async def _heartbeat(self) -> None:
        """WS のハートビート監視と ping 実行。"""

        while not self._stop.is_set():
            await asyncio.sleep(self._HB_PERIOD_SEC)
            now = asyncio.get_event_loop().time()
            idle = now - self._last_rx
            if idle >= self._IDLE_PING_THRESHOLD_SEC:
                try:
                    await self._send_ping()
                    logger.debug("WS ping 成功（アイドル {:.1f}s）", idle)
                except Exception as e:
                    logger.warning("WS ping 失敗: {} → 再接続", e)
                    await self._reconnect()

    async def _reconnect(self) -> None:
        """接続を閉じて再接続し、購読を復元する（指数バックオフ）。"""

        try:
            await self.close()
        finally:
            self._stop.clear()
        # バックオフでスパム防止
        delay = min(5.0, 0.5 * (2 ** self._reconnect_attempts))
        if delay > 0:
            logger.info("WS 再接続待機 {:.1f}s ...", delay)
            await asyncio.sleep(delay)
        self._reconnect_attempts += 1
        await self.connect()

    async def run(self, handler: MessageHandler) -> None:
        """受信ループを開始し、各メッセージを handler に渡す。"""

        await self.connect()
        hb_task = asyncio.create_task(self._heartbeat())
        try:
            while not self._stop.is_set():
                assert self._ws is not None
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=60)
                    self._last_rx = asyncio.get_event_loop().time()
                    msg = json.loads(raw)
                    await handler(msg)
                except asyncio.TimeoutError:
                    # 受信無しが続く場合は単発 ping（ハートビートも並行で動作中）
                    try:
                        await self._send_ping()
                        logger.debug("WS アイドル → 単発 ping 実行")
                    except Exception as e:
                        logger.warning("WS 単発 ping 失敗: {} → 再接続", e)
                        await self._reconnect()
                except websockets.ConnectionClosed:
                    logger.warning("WS 接続が切断 → 再接続")
                    await self._reconnect()
        except asyncio.CancelledError:
            logger.info("停止要求（Ctrl+C）を検知。WS を閉じます。")
        finally:
            hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb_task
            await self.close()
