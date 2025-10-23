from __future__ import annotations

"""Hyperliquid の REST クライアント。

- /info 系 API のラッパ
- /exchange 系 API（注文・取消・DMS）のラッパ
- ノンス管理と署名コールバックの受け口
"""

import json
import os
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

from . import config
from .nonce_manager import NonceManager


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

    def post_orders(self, orders: List[Dict[str, Any]], signature_cb=None) -> Any:
        """注文をバッチ送信。

        署名が必要な場合は `signature_cb(payload, nonce) -> signature` を渡してください。
        API ウォレット（エージェント）による署名が必須です。
        """

        body: Dict[str, Any] = {
            "type": "order",
            "orders": orders,
        }
        if signature_cb is not None:
            nonce = self.nonce_mgr.next()
            sig = signature_cb(body, nonce)
            body["nonce"] = nonce
            body["signature"] = sig
        logger.debug("POST /exchange 送信: {}", body)
        return self._post("/exchange", body)

    def cancel(self, oid: int, signature_cb=None) -> Any:
        """注文 ID を指定してキャンセル。"""

        body: Dict[str, Any] = {"type": "cancel", "oid": oid}
        if signature_cb is not None:
            nonce = self.nonce_mgr.next()
            sig = signature_cb(body, nonce)
            body["nonce"] = nonce
            body["signature"] = sig
        return self._post("/exchange", body)

    def cancel_by_cloid(self, cloid: str, signature_cb=None) -> Any:
        """クライアント ID（cloid）を指定してキャンセル。"""

        body: Dict[str, Any] = {"type": "cancelByCloid", "cloid": cloid}
        if signature_cb is not None:
            nonce = self.nonce_mgr.next()
            sig = signature_cb(body, nonce)
            body["nonce"] = nonce
            body["signature"] = sig
        return self._post("/exchange", body)

    def schedule_cancel(self, seconds_from_now: int, signature_cb=None) -> Any:
        """DMS（Dead Man's Switch）を予約する。

        現在時刻 +5 秒以上、1 日 10 回まで（UTC 00:00 リセット）。
        """

        body: Dict[str, Any] = {"type": "scheduleCancel", "secs": seconds_from_now}
        if signature_cb is not None:
            nonce = self.nonce_mgr.next()
            sig = signature_cb(body, nonce)
            body["nonce"] = nonce
            body["signature"] = sig
        return self._post("/exchange", body)
