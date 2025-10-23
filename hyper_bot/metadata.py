from __future__ import annotations

"""メタデータ解決（asset_id / szDecimals / 価格刻み など）。

metaAndAssetCtxs のレスポンスはバージョンで形が揺れる可能性があるため、
存在チェックを丁寧に行い、得られる情報だけを安全に返す。
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from loguru import logger

from .rest_client import HyperliquidREST


@dataclass
class AssetMeta:
    symbol: str
    asset_id: int
    sz_decimals: int
    px_decimals: Optional[int] = None
    tick_size: Optional[float] = None
    mid_px: Optional[float] = None
    oracle_px: Optional[float] = None


class MetadataResolver:
    """シンボルから AssetMeta を取得するヘルパ。"""

    def __init__(self, rest: Optional[HyperliquidREST] = None) -> None:
        self.rest = rest or HyperliquidREST()
        self._raw: Optional[Dict[str, Any]] = None
        self._index: Dict[str, AssetMeta] = {}

    def refresh(self) -> None:
        """/info metaAndAssetCtxs を取得して内部インデックスを更新。"""

        raw = self.rest.meta_and_asset_ctxs()
        self._raw = raw if isinstance(raw, dict) else {}
        self._index.clear()

        # 代表的な形: { "assetCtxs": [ { "name": "BTC", "szDecimals": 3, "pxDecimals": 1, "id": 1, ... }, ... ] }
        asset_ctxs = None
        for key in ("assetCtxs", "assets", "universe"):
            if isinstance(self._raw.get(key), list):
                asset_ctxs = self._raw[key]
                break
        if not asset_ctxs:
            logger.warning("metaAndAssetCtxs に資産配列が見当たりません: keys={}", list(self._raw.keys()))
            return

        for entry in asset_ctxs:
            if not isinstance(entry, dict):
                continue
            sym = entry.get("name") or entry.get("symbol") or entry.get("asset")
            if not isinstance(sym, str):
                continue
            # asset_id を代表的なキー候補から取得
            aid = entry.get("id") or entry.get("assetId") or entry.get("a")
            try:
                aid = int(aid)
            except Exception:
                logger.debug("asset_id が解決できませんでした: {}", entry)
                continue
            sz_dec = entry.get("szDecimals")
            try:
                sz_dec = int(sz_dec) if sz_dec is not None else 0
            except Exception:
                sz_dec = 0
            px_dec = entry.get("pxDecimals")
            try:
                px_dec = int(px_dec) if px_dec is not None else None
            except Exception:
                px_dec = None
            tick = None
            if px_dec is not None:
                try:
                    tick = 10 ** (-px_dec)
                except Exception:
                    tick = None

            # 価格の補助情報（ある場合のみ）
            mid_px = entry.get("midPx")
            oracle_px = entry.get("oraclePx") or entry.get("indexPx")

            meta = AssetMeta(
                symbol=sym.upper(),
                asset_id=aid,
                sz_decimals=sz_dec,
                px_decimals=px_dec,
                tick_size=tick,
                mid_px=mid_px if isinstance(mid_px, (int, float)) else None,
                oracle_px=oracle_px if isinstance(oracle_px, (int, float)) else None,
            )
            self._index[meta.symbol] = meta

    def get(self, symbol: str) -> Optional[AssetMeta]:
        """シンボル（大文字小文字無視）から AssetMeta を返す。未取得なら refresh。"""

        if not self._index:
            self.refresh()
        if not symbol:
            return None
        key = symbol.upper()
        return self._index.get(key)

    def require(self, symbol: str) -> AssetMeta:
        """AssetMeta を取得できなければ例外。"""

        meta = self.get(symbol)
        if meta is None:
            raise ValueError(f"メタデータが見つかりません: {symbol}")
        return meta

