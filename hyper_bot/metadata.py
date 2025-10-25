from __future__ import annotations

"""Metadata utilities to resolve asset_id/decimals/ticks/prices."""

from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

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
    """Resolve AssetMeta for a given symbol via /info metaAndAssetCtxs.

    Accepts both dict and list-wrapped responses, and falls back to using the
    list index as asset_id when explicit ids are not present. If both universe
    (names/decimals) and assetCtxs (prices) are present as aligned lists, they
    are joined by index.
    """

    def __init__(self, rest: Optional[HyperliquidREST] = None) -> None:
        self.rest = rest or HyperliquidREST()
        self._raw: Optional[Dict[str, Any]] = None
        self._index: Dict[str, AssetMeta] = {}

    def _extract_blocks(self, raw: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]]]:
        """Return (universe, asset_ctxs) lists when available."""

        universe: Optional[List[Dict[str, Any]]] = None
        asset_ctxs: Optional[List[Dict[str, Any]]] = None

        def from_dict(d: Dict[str, Any]) -> None:
            nonlocal universe, asset_ctxs
            u = d.get("universe")
            if isinstance(u, list):
                universe = u
            a = d.get("assetCtxs")
            if isinstance(a, list):
                asset_ctxs = a

        if isinstance(raw, dict):
            from_dict(raw)
        elif isinstance(raw, list):
            for elem in raw:
                if isinstance(elem, dict):
                    from_dict(elem)
                elif isinstance(elem, list) and elem and isinstance(elem[0], dict):
                    # Heuristic: list of asset contexts (has pricing fields)
                    if any(k in elem[0] for k in ("midPx", "oraclePx", "indexPx", "markPx")):
                        asset_ctxs = elem

        return universe, asset_ctxs

    def refresh(self) -> None:
        """Fetch and (re)build the in-memory index."""

        raw = self.rest.meta_and_asset_ctxs()
        uni, ctxs = self._extract_blocks(raw)
        if uni is None and isinstance(raw, dict):
            # Some variants may use alternate keys
            alt = raw.get("assets") or raw.get("assetCtxs")
            if isinstance(alt, list):
                uni = alt
        if uni is None:
            logger.warning("metaAndAssetCtxs did not include universe; keys={} type={}", list(raw.keys()) if isinstance(raw, dict) else type(raw))
            self._raw = {}
            self._index.clear()
            return

        self._raw = {"universe": uni}
        if ctxs is not None:
            self._raw["assetCtxs"] = ctxs
        self._index.clear()

        for idx, entry in enumerate(uni):
            if not isinstance(entry, dict):
                continue
            sym = entry.get("name") or entry.get("symbol") or entry.get("asset")
            if not isinstance(sym, str):
                continue
            # Prefer explicit id, else fallback to index
            aid = entry.get("id") or entry.get("assetId") or entry.get("a")
            try:
                asset_id = int(aid)
            except Exception:
                asset_id = idx

            # Decimals and tick size
            try:
                sz_dec = int(entry.get("szDecimals") if entry.get("szDecimals") is not None else 0)
            except Exception:
                sz_dec = 0
            try:
                px_dec = entry.get("pxDecimals")
                px_dec = int(px_dec) if px_dec is not None else None
            except Exception:
                px_dec = None
            tick = None
            if px_dec is not None:
                try:
                    tick = 10 ** (-px_dec)
                except Exception:
                    tick = None

            # Prices (from ctxs if available)
            mid_px = None
            oracle_px = None
            if isinstance(ctxs, list) and idx < len(ctxs) and isinstance(ctxs[idx], dict):
                c = ctxs[idx]
                mid_px = c.get("midPx") if isinstance(c.get("midPx"), (int, float)) else None
                oracle_px = c.get("oraclePx") or c.get("indexPx")
                if not isinstance(oracle_px, (int, float)):
                    oracle_px = None

            meta = AssetMeta(
                symbol=str(sym).upper(),
                asset_id=asset_id,
                sz_decimals=sz_dec,
                px_decimals=px_dec,
                tick_size=tick,
                mid_px=mid_px,
                oracle_px=oracle_px,
            )
            self._index[meta.symbol] = meta

    def get(self, symbol: str) -> Optional[AssetMeta]:
        if not self._index:
            self.refresh()
        if not symbol:
            return None
        return self._index.get(symbol.upper())

    def require(self, symbol: str) -> AssetMeta:
        meta = self.get(symbol)
        if meta is None:
            raise ValueError(f"Asset metadata not found: {symbol}")
        return meta
