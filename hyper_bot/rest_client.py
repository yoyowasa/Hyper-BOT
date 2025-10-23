from __future__ import annotations

"""Hyperliquid の REST クライアント。

- /info 系 API のラッパ
- /exchange 系 API（注文・取消・DMS）のラッパ（L1 署名方式）
- ノンス管理と署名コールバックの受け口
"""

import json
import os
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

from . import config
from .nonce_manager import NonceManager
from .signing import build_exchange_payload, sign_exchange_action


class HyperliquidREST:
    """REST ラッパ。base_url はネットワーク設定から自動解決。"""

    def __init__(self, base_url: Optional[str] = None) -> None:
        eps = config.get_endpoints(os.getenv("HL_NETWORK"))
        self.base_url = base_url or eps.base_url
        self.session = requests.Session()
        self.nonce_mgr = NonceManager()

    def _post(self, path: str, body: Dict[str, Any]) -> Any:
        """POST リクエスト（JSON）を送信し、JSON を返す。"""

        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        resp = self.session.post(url, data=json.dumps(body), headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET リクエストを送信し、JSON を返す。"""

        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # /info endpoints ---------------------------------------------------------

    def info(self, endpoint: str, body: Optional[Dict[str, Any]] = None) -> Any:
        """/info に対する汎用ラッパ。

        実装差により、`{"endpoint": payload}` 形式と
        `{type: endpoint, ...payload}` 形式が存在するため両方を試行。
        """

        payload = body or {}
        try:
            return self._post("/info", {endpoint: payload} if payload else {endpoint: None})
        except requests.HTTPError as e:
            logger.debug("/info フォールバックを適用: {} → {}", endpoint, e)
            shaped = {"type": endpoint}
            shaped.update(payload)
            return self._post("/info", shaped)

    # よく使う /info ヘルパ
    def meta_and_asset_ctxs(self) -> Any:
        """市場メタデータと資産コンテキストを取得。"""

        return self.info("metaAndAssetCtxs")

    def candle_snapshot(self, asset: str, interval: str) -> Any:
        """指定銘柄・足のスナップショットを取得（1h/1d など）。"""

        return self.info("candleSnapshot", {"symbol": asset, "interval": interval})

    def user_funding(self, address: str) -> Any:
        """指定アドレスの最新ファンディング情報を取得。"""

        return self.info("userFunding", {"address": address})

    def funding_history(self, asset: str, limit: int = 168) -> Any:
        """指定銘柄のファンディング履歴を取得。"""

        return self.info("fundingHistory", {"symbol": asset, "limit": limit})

    # /exchange endpoints -----------------------------------------------------

    def post_orders(
        self,
        orders: List[Dict[str, Any]],
        signature_cb=None,
        *,
        grouping: str = "na",
        is_mainnet: Optional[bool] = None,
    ) -> Any:
        """注文をバッチ送信（L1 署名）。

        - orders: 事前に Tick/szDecimals 丸め済みの "OrderWire" 形式を想定（a/b/p/s/r/t/c）。
        - grouping: "na" | "normalTpsl" | "positionTpsl"
        - signature_cb: (action:dict, nonce:int)-> {r,s,v} を返す関数。省略時は環境変数の鍵で署名。
        """

        action: Dict[str, Any] = {"type": "order", "orders": orders, "grouping": grouping}
        network = (os.getenv("HL_NETWORK", "mainnet")).lower()
        is_mainnet_flag = is_mainnet if is_mainnet is not None else (network == "mainnet")
        nonce = self.nonce_mgr.next()
        if signature_cb is None:
            priv = os.getenv("HL_PRIVATE_KEY")
            if not priv:
                raise RuntimeError("HL_PRIVATE_KEY が未設定です。署名コールバックを渡すか、環境変数を設定してください。")
            sig = sign_exchange_action(action, priv, nonce, is_mainnet=is_mainnet_flag)
            body = build_exchange_payload(action, sig)
        else:
            vrs = signature_cb(action, nonce)
            sig = {"r": vrs["r"], "s": vrs["s"], "v": vrs["v"]}
            body = {"action": action, "nonce": nonce, "signature": sig}
        logger.debug("POST /exchange: {}", body)
        return self._post("/exchange", body)

    def cancel(self, oid: int, signature_cb=None) -> Any:
        """注文 ID を指定してキャンセル（L1 署名）。"""

        action: Dict[str, Any] = {"type": "cancel", "oid": oid}
        network = (os.getenv("HL_NETWORK", "mainnet")).lower()
        is_mainnet_flag = network == "mainnet"
        nonce = self.nonce_mgr.next()
        if signature_cb is None:
            priv = os.getenv("HL_PRIVATE_KEY")
            if not priv:
                raise RuntimeError("HL_PRIVATE_KEY が未設定です。署名コールバックを渡すか、環境変数を設定してください。")
            sig = sign_exchange_action(action, priv, nonce, is_mainnet=is_mainnet_flag)
            body = build_exchange_payload(action, sig)
        else:
            vrs = signature_cb(action, nonce)
            body = {"action": action, "nonce": nonce, "signature": vrs}
        return self._post("/exchange", body)

    def cancel_by_cloid(self, cloid: str, signature_cb=None) -> Any:
        """クライアント ID（cloid）を指定してキャンセル（L1 署名）。"""

        action: Dict[str, Any] = {"type": "cancelByCloid", "cloid": cloid}
        network = (os.getenv("HL_NETWORK", "mainnet")).lower()
        is_mainnet_flag = network == "mainnet"
        nonce = self.nonce_mgr.next()
        if signature_cb is None:
            priv = os.getenv("HL_PRIVATE_KEY")
            if not priv:
                raise RuntimeError("HL_PRIVATE_KEY が未設定です。署名コールバックを渡すか、環境変数を設定してください。")
            sig = sign_exchange_action(action, priv, nonce, is_mainnet=is_mainnet_flag)
            body = build_exchange_payload(action, sig)
        else:
            vrs = signature_cb(action, nonce)
            body = {"action": action, "nonce": nonce, "signature": vrs}
        return self._post("/exchange", body)

    def schedule_cancel_at(self, cancel_time_ms: int, signature_cb=None) -> Any:
        """DMS（Dead Man's Switch）を絶対時刻（UTC ミリ秒）で予約（L1 署名）。"""

        action: Dict[str, Any] = {"type": "scheduleCancel", "time": int(cancel_time_ms)}
        network = (os.getenv("HL_NETWORK", "mainnet")).lower()
        is_mainnet_flag = network == "mainnet"
        nonce = self.nonce_mgr.next()
        if signature_cb is None:
            priv = os.getenv("HL_PRIVATE_KEY")
            if not priv:
                raise RuntimeError("HL_PRIVATE_KEY が未設定です。署名コールバックを渡すか、環境変数を設定してください。")
            sig = sign_exchange_action(action, priv, nonce, is_mainnet=is_mainnet_flag)
            body = build_exchange_payload(action, sig)
        else:
            vrs = signature_cb(action, nonce)
            body = {"action": action, "nonce": nonce, "signature": vrs}
        return self._post("/exchange", body)

    def schedule_cancel(self, seconds_from_now: int, signature_cb=None) -> Any:
        """後方互換: 秒指定。内部で現在時刻に加算して schedule_cancel_at を呼ぶ。"""
        import time as _t

        target = int(_t.time() * 1000) + int(seconds_from_now * 1000)
        return self.schedule_cancel_at(target, signature_cb)

