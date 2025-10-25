import asyncio
import json

import pytest

from hyper_bot.ws_client import WebsocketClient


def test_add_subscription_shapes():
    ws = WebsocketClient(ws_url="wss://example/ws")
    ws.add_subscription("candle", symbol="BTC", interval="1h")
    assert {"type": "candle", "coin": "BTC", "interval": "1h"} in ws._subs

    ws.add_subscription("userEvents", user="0xabc")
    assert {"type": "userEvents", "user": "0xabc"} in ws._subs


@pytest.mark.asyncio
async def test_resubscribe_calls_send_json(monkeypatch: pytest.MonkeyPatch):
    ws = WebsocketClient(ws_url="wss://example/ws")
    ws.add_subscription("candle", symbol="ETH", interval="1h")
    sent = []

    async def fake_send_json(payload):
        sent.append(payload)

    monkeypatch.setattr(ws, "send_json", fake_send_json)
    await ws._resubscribe()
    assert any(p.get("type") == "candle" and p.get("coin") == "ETH" for p in sent)

