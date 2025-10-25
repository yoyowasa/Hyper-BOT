from hyper_bot.orders import OrderSpec, build_order, notional_ok


def test_build_order_rounding():
    spec = OrderSpec(
        asset_id=1,
        is_buy=True,
        px=50000.123,
        sz=0.123456,
        tif="IOC",
        typ="limit",
        cloid="TEST-123",
        grouping="na",
    )
    order = build_order(spec, px_tick=0.5, sz_decimals=3)
    assert order["a"] == 1
    assert order["b"] is True
    # price floored to nearest tick
    assert order["p"] == 50000.0
    # size rounded down to given decimals
    assert order["s"] == 0.123
    assert order["tif"] == "IOC"
    assert order["t"] == "limit"
    assert order["grouping"] == "na"
    assert order["c"] == "TEST-123"


def test_notional_ok():
    assert notional_ok(1.0, 10.0) is True
    assert notional_ok(0.0001, 100.0) is False
    # price None is considered ok (checked later at runtime)
    assert notional_ok(1.0, None) is True
