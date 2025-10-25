"""Backtest example for premium-threshold strategy from saved snapshots.

Prerequisites:
  python scripts/fetch_snapshot.py --assets BTC,ETH --timeframes 1h,1d

This script:
- Loads the latest metaAndAssetCtxs_* file for oracle/mid context
- Loads candleSnapshot_{SYMBOL}_{TF}_* for close prices (as mid proxy)
- Builds premium and a simple threshold signal
- Runs walk_forward PnL via hyper_bot.backtest

Usage:
  python scripts/backtest_premium_example.py --symbol BTC --timeframe 1h --threshold 0.002
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from hyper_bot.backtest import walk_forward
from hyper_bot.data.features import compute_premium


def latest_file(pattern: str) -> Optional[Path]:
    files = sorted(Path("data").glob(pattern))
    return files[-1] if files else None


def load_meta_ctxs() -> Dict[str, Any]:
    p = latest_file("metaAndAssetCtxs_*.json")
    if not p:
        raise SystemExit("No metaAndAssetCtxs_*.json found in data/. Run fetch_snapshot first.")
    return json.loads(p.read_text(encoding="utf-8"))


def load_candles(symbol: str, tf: str) -> pd.DataFrame:
    p = latest_file(f"candleSnapshot_{symbol}_{tf}_*.json")
    if not p:
        raise SystemExit(f"No candleSnapshot_{symbol}_{tf}_*.json found in data/. Run fetch_snapshot first.")
    raw = json.loads(p.read_text(encoding="utf-8"))
    # Expected shape: { data: [ { t, o,h,l,c,v }, ... ] }
    arr = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(arr, list):
        raise SystemExit("Unexpected candle snapshot format")
    df = pd.DataFrame(arr)
    if "t" not in df or "c" not in df:
        raise SystemExit("Candle data missing t/c fields")
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.set_index("t").sort_index()
    df = df.rename(columns={"c": "close"})
    return df


def meta_oracle_map(meta: Dict[str, Any]) -> Dict[str, float]:
    universe = []
    ctxs = []
    if isinstance(meta, list):
        for elem in meta:
            if isinstance(elem, dict) and isinstance(elem.get("universe"), list):
                universe = elem["universe"]
            elif isinstance(elem, list):
                ctxs = elem
    out: Dict[str, float] = {}
    for idx, u in enumerate(universe):
        if not isinstance(u, dict):
            continue
        name = u.get("name")
        if not isinstance(name, str):
            continue
        if idx < len(ctxs) and isinstance(ctxs[idx], dict):
            opx = ctxs[idx].get("oraclePx") or ctxs[idx].get("indexPx")
            if isinstance(opx, (int, float)):
                out[name.upper()] = float(opx)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest premium threshold on snapshot data")
    p.add_argument("--symbol", default="BTC")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--threshold", type=float, default=0.002)
    args = p.parse_args()

    candles = load_candles(args.symbol.upper(), args.timeframe)
    meta = load_meta_ctxs()
    oracle_map = meta_oracle_map(meta)
    oracle = oracle_map.get(args.symbol.upper())
    if oracle is None:
        raise SystemExit("No oracle price found for symbol in meta ctxs")

    df = candles.copy()
    df["oraclePx"] = float(oracle)  # static over window in this simple example
    df["midPx"] = df["close"]
    prem = compute_premium(df, perp_col="midPx", oracle_col="oraclePx")
    # simple symmetric threshold
    sig = prem.apply(lambda x: -1 if x > args.threshold else (1 if x < -args.threshold else 0))

    res = walk_forward(df, sig)
    print("events:")
    print(res.head(20))
    print("\nPnL sum:", float(res["pnl"].sum()))


if __name__ == "__main__":
    main()

