from hyper_bot.orders import build_trigger_order


def test_build_trigger_order_shapes_payload():
    od = build_trigger_order(
        asset_id=1,
        is_buy=False,
        sz=0.12345,
        limit_px=50123.45,
        trigger_px=50000.0,
        tpsl="sl",
        sz_decimals=3,
    )
    assert od["a"] == 1
    assert od["b"] is False
    # string encoding of numeric fields
    assert od["p"] == "50123.45"
    # size is rounded down to 3 decimals and string encoded
    assert od["s"] == "0.123"
    assert od["r"] is True
    assert "t" in od and "trigger" in od["t"]
    trg = od["t"]["trigger"]
    assert trg["triggerPx"] == "50000.0"
    assert trg["isMarket"] is True
    assert trg["tpsl"] == "sl"

