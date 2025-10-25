from typing import Any, Dict

import pytest

from hyper_bot.metadata import MetadataResolver, AssetMeta


def test_metadata_resolver_builds_index(monkeypatch: pytest.MonkeyPatch):
    class FakeRest:
        def meta_and_asset_ctxs(self) -> Dict[str, Any]:
            # simulate one of the possible shapes
            return {
                "assetCtxs": [
                    {"name": "BTC", "id": 1, "szDecimals": 3, "pxDecimals": 1, "midPx": 50000.5, "oraclePx": 50010.0},
                    {"symbol": "ETH", "assetId": 2, "szDecimals": 2, "pxDecimals": 2, "indexPx": 2500.12},
                ]
            }

    r = MetadataResolver(rest=FakeRest())
    m_btc = r.require("BTC")
    assert isinstance(m_btc, AssetMeta)
    assert m_btc.asset_id == 1
    assert m_btc.sz_decimals == 3
    assert m_btc.px_decimals == 1
    assert m_btc.tick_size == 0.1
    assert m_btc.mid_px == 50000.5
    assert m_btc.oracle_px == 50010.0

    m_eth = r.require("ETH")
    assert m_eth.asset_id == 2
    assert m_eth.sz_decimals == 2
    assert m_eth.tick_size == 0.01
    # mid may be None when not present
    assert m_eth.mid_px is None
    assert m_eth.oracle_px == 2500.12

