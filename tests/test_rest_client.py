from typing import Any, Dict, List

import os
import pytest

from hyper_bot.rest_client import HyperliquidREST


def _fake_sig():
    return {"r": "0x" + "00" * 32, "s": "0x" + "11" * 32, "v": 27}


def test_post_orders_uses_signature_cb(monkeypatch: pytest.MonkeyPatch):
    rest = HyperliquidREST(base_url="http://example.com")
    calls: List[Dict[str, Any]] = []

    def fake_post(path: str, body: Dict[str, Any]):
        calls.append({"path": path, "body": body})
        return {"ok": True}

    monkeypatch.setenv("HL_NETWORK", "testnet")
    monkeypatch.setattr(rest, "_post", fake_post)

    order = {"a": 1, "b": True, "s": 1.0, "t": "market", "TIF": "IOC", "grouping": "na"}
    resp = rest.post_orders([order], signature_cb=lambda action, nonce: _fake_sig())
    assert resp == {"ok": True}
    assert calls
    assert calls[0]["path"] == "/exchange"
    body = calls[0]["body"]
    assert "action" in body and "nonce" in body and "signature" in body
    assert body["action"]["orders"][0]["a"] == 1


def test_cancel_and_dms_use_cb(monkeypatch: pytest.MonkeyPatch):
    rest = HyperliquidREST(base_url="http://example.com")
    seen: List[str] = []

    def fake_post(path: str, body: Dict[str, Any]):
        seen.append(path)
        return {"ok": True}

    monkeypatch.setattr(rest, "_post", fake_post)

    rest.cancel_by_cloid("CID-1", signature_cb=lambda a, n: _fake_sig())
    rest.schedule_cancel(5, signature_cb=lambda a, n: _fake_sig())
    assert "/exchange" in seen
    assert seen.count("/exchange") >= 2

