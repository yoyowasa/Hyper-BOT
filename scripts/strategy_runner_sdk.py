"""Minimal strategy runner using Hyperliquid official SDK + WS.

Signals: premium = (mid - oracle) / oracle
- premium > +threshold -> short (sell)
- premium < -threshold -> long (buy)

Orders: IOC limit with slippage bps around mid. One position per symbol.
Risk controls:
- min interval between trades per symbol
- size floor (~$10 notion if --size=0)
- ReduceOnly when closing/opposite signal

Usage examples:
  HL_NETWORK=testnet HL_PRIVATE_KEY=0x... \
  python scripts/strategy_runner_sdk.py --symbols BTC,ETH --threshold 0.002 --slip-bps 50 --poll-sec 5

Outputs:
- logs in logs/strategy_<YYYYMMDD>.log
- per-trade CSV append in runs/trades_<YYYYMMDD>.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import time
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from eth_account import Account
from loguru import logger

from hyperliquid.exchange import Exchange

from hyper_bot.ws_client import WebsocketClient

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

MAINNET = "https://api.hyperliquid.xyz"
TESTNET = "https://api.hyperliquid-testnet.xyz"


def base_url() -> str:
    return TESTNET if os.getenv("HL_NETWORK", "mainnet").lower() == "testnet" else MAINNET


def utc_iso(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp((ts or time.time()), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dirs(logs_dir: Optional[str] = None, runs_dir: Optional[str] = None) -> Dict[str, Path]:
    logs = Path(logs_dir or "logs"); logs.mkdir(parents=True, exist_ok=True)
    runs = Path(runs_dir or "runs"); runs.mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().strftime("%Y%m%d")
    return {
        "log_path": logs / f"strategy_{today}.log",
        "trades_csv": runs / f"trades_{today}.csv",
    }


@dataclass
class SymState:
    last_trade_ts: float = 0.0
    last_premium: float = 0.0
    live_mid: Optional[float] = None


class Strategy:
    def __init__(
        self,
        ex: Exchange,
        symbols: List[str],
        threshold: float,
        slip_bps: float,
        poll_sec: int,
        min_interval_sec: int,
        default_size: float,
        dry_run: bool,
        trades_csv: Path,
    ) -> None:
        self.ex = ex
        self.symbols = [s.upper() for s in symbols]
        self.threshold = float(threshold)
        self.slip = float(slip_bps) / 10_000.0
        self.poll_sec = int(poll_sec)
        self.min_interval_sec = int(min_interval_sec)
        self.default_size = float(default_size)
        self.dry_run = bool(dry_run)
        self.trades_csv = trades_csv

        self.state: Dict[str, SymState] = {s: SymState() for s in self.symbols}

        # CSV header
        if not self.trades_csv.exists():
            with self.trades_csv.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["time","symbol","side","action","size","limit_px","premium","response"])    

        # Build universe maps
        # name_to_coin/asset/decimals via ex.info
        self.name_to_coin: Dict[str, int] = self.ex.info.name_to_coin
        self.coin_to_asset: Dict[int, int] = self.ex.info.coin_to_asset
        self.asset_to_sz_decimals: Dict[int, int] = self.ex.info.asset_to_sz_decimals

    def _premium_snapshot(self) -> Dict[str, Dict[str, Optional[float]]]:
        # meta_and_asset_ctxs returns [ {'universe': [...]}, [ctxs...] ]
        raw = self.ex.info.meta_and_asset_ctxs()
        universe = []
        ctxs = []
        if isinstance(raw, list) and raw:
            for elem in raw:
                if isinstance(elem, dict) and isinstance(elem.get("universe"), list):
                    universe = elem["universe"]
                elif isinstance(elem, list):
                    ctxs = elem
        # Build mapping by index
        out: Dict[str, Dict[str, Optional[float]]] = {}
        for idx, u in enumerate(universe):
            try:
                name = str(u.get("name"))
            except Exception:
                continue
            if name not in self.symbols:
                continue
            mid = None
            oracle = None
            if idx < len(ctxs) and isinstance(ctxs[idx], dict):
                mid = ctxs[idx].get("midPx")
                oracle = ctxs[idx].get("oraclePx") or ctxs[idx].get("indexPx")
                if not isinstance(mid, (int, float)):
                    mid = None
                if not isinstance(oracle, (int, float)):
                    oracle = None
            out[name] = {"mid": mid, "oracle": oracle}
        return out

    def _size_for(self, sym: str, mid: float) -> float:
        asset = self.coin_to_asset[self.name_to_coin[sym]]
        dec = int(self.asset_to_sz_decimals[asset])
        if self.default_size > 0:
            size = self.default_size
        else:
            # ~$10 notion floor
            size = max(10.0 / float(mid), 10 ** (-dec))
        # round down to decimals
        s = f"{size:.12f}"
        if dec >= 0:
            parts = s.split(".")
            s = parts[0] + ("." + parts[1][:dec] if dec > 0 else "")
        try:
            return max(0.0, float(s))
        except Exception:
            return size

    def _log_trade(self, symbol: str, side: str, action: str, size: float, limit_px: float, premium: float, response: Any) -> None:
        row = [utc_iso(), symbol, side, action, size, limit_px, premium, str(response)]
        with self.trades_csv.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

    async def run(self) -> None:
        # Start WS to keep mid updates flowing (1m candles)
        ws = WebsocketClient()
        for s in self.symbols:
            ws.add_subscription("candle", symbol=s, interval="1m")

        async def handler(msg: Dict[str, Any]) -> None:
            if isinstance(msg, dict) and msg.get("channel") == "candle":
                data = msg.get("data")
                if isinstance(data, dict):
                    sym = str(data.get("symbol"))
                    close = data.get("c")
                    if sym in self.state and isinstance(close, (int, float)):
                        self.state[sym].live_mid = float(close)

        trader_task = asyncio.create_task(self._trader_loop())
        try:
            await ws.run(handler)
        finally:
            trader_task.cancel()
            with asyncio.CancelledError:
                pass

    async def _trader_loop(self) -> None:
        while True:
            try:
                snap = self._premium_snapshot()
                mids = self.ex.info.all_mids()
                # user state
                address = self.ex.wallet.address
                ust = self.ex.info.user_state(address)
                pos_map: Dict[str, float] = {}
                for entry in ust.get("assetPositions", []) or []:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("name") or entry.get("asset")
                    position = entry.get("position") or {}
                    # position has fields like szi (signed size)
                    szi = position.get("szi") if isinstance(position, dict) else None
                    if isinstance(name, str) and szi is not None:
                        try:
                            pos_map[str(name).upper()] = float(szi)
                        except Exception:
                            pass

                for sym in self.symbols:
                    st = self.state[sym]
                    mid = st.live_mid or snap.get(sym, {}).get("mid")
                    oracle = snap.get(sym, {}).get("oracle")
                    if not isinstance(mid, (int, float)):
                        # fallback to Info mids
                        coin = self.name_to_coin.get(sym)
                        if coin is not None:
                            try:
                                mid = float(mids[coin])
                            except Exception:
                                mid = None
                    if not (isinstance(mid, (int, float)) and isinstance(oracle, (int, float)) and oracle):
                        continue
                    premium = (float(mid) - float(oracle)) / float(oracle)
                    st.last_premium = premium

                    now = time.time()
                    if now - st.last_trade_ts < self.min_interval_sec:
                        continue

                    curr = pos_map.get(sym, 0.0)
                    want_side: Optional[str] = None
                    if premium > self.threshold:
                        want_side = "sell"  # short
                    elif premium < -self.threshold:
                        want_side = "buy"   # long

                    if want_side is None:
                        continue

                    # If already positioned in same direction, skip. If opposite, close.
                    if curr != 0.0:
                        if (curr > 0 and want_side == "buy") or (curr < 0 and want_side == "sell"):
                            # same direction
                            continue
                        # opposite -> close using reduceOnly equal to abs(curr)
                        side_is_buy = curr < 0  # if short, need buy to close
                        limit_px = self.ex._slippage_price(sym, side_is_buy, self.slip, px=float(mid))
                        size = abs(curr)
                        if self.dry_run:
                            logger.info("DRY close {} {} size={} px={} prem={}", sym, "buy" if side_is_buy else "sell", size, limit_px, premium)
                        else:
                            resp = self.ex.order(sym, side_is_buy, size, limit_px, {"limit": {"tif": "Ioc"}}, reduce_only=True)
                            logger.info("Close {} {} size={} px={} resp={}", sym, "buy" if side_is_buy else "sell", size, limit_px, resp)
                            self._log_trade(sym, "buy" if side_is_buy else "sell", "close", size, limit_px, premium, resp)
                            st.last_trade_ts = now
                        continue

                    # Open new position
                    side_is_buy = want_side == "buy"
                    limit_px = self.ex._slippage_price(sym, side_is_buy, self.slip, px=float(mid))
                    size = self._size_for(sym, float(mid))
                    if self.dry_run:
                        logger.info("DRY open {} {} size={} px={} prem={}", sym, want_side, size, limit_px, premium)
                    else:
                        resp = self.ex.order(sym, side_is_buy, size, limit_px, {"limit": {"tif": "Ioc"}})
                        logger.info("Open {} {} size={} px={} resp={}", sym, want_side, size, limit_px, resp)
                        self._log_trade(sym, want_side, "open", size, limit_px, premium, resp)
                        st.last_trade_ts = now

            except Exception as e:
                logger.exception("trader loop error: {}", e)

            await asyncio.sleep(self.poll_sec)


def main() -> None:
    p = argparse.ArgumentParser(description="Strategy runner (premium threshold)")
    p.add_argument("--config", type=str, default=None, help="Path to YAML config (default: configs/strategy.yaml if exists)")
    p.add_argument("--symbols", default="BTC,ETH", help="Comma list of symbols, e.g. BTC,ETH")
    p.add_argument("--threshold", type=float, default=0.002, help="Premium abs threshold (e.g. 0.002=0.2%)")
    p.add_argument("--slip-bps", type=float, default=50.0, help="IOC slippage in bps (50=0.5%)")
    p.add_argument("--size", type=float, default=0.0, help="Fixed size per trade (0 => ~$10 notion)")
    p.add_argument("--poll-sec", type=int, default=5, help="Polling seconds for decision loop")
    p.add_argument("--min-interval-sec", type=int, default=15, help="Min seconds between trades per symbol")
    p.add_argument("--dry-run", action="store_true", help="No actual orders; log only")
    args = p.parse_args()

    # Load YAML config if provided or default path exists
    cfg_path = args.config or ("configs/strategy.yaml" if Path("configs/strategy.yaml").exists() else None)
    cfg: Dict[str, Any] = {}
    if cfg_path:
        if yaml is None:
            raise SystemExit("PyYAML not available. Please install PyYAML or remove --config.")
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise SystemExit("strategy config must be a YAML mapping")
            cfg = data

    # Determine which CLI flags were explicitly set (to let CLI override config)
    argv = " ".join(sys.argv[1:])
    def flag_set(key: str) -> bool:
        return (f"--{key} ") in argv or (f"--{key}=") in argv or (f"--{key}\n") in argv

    # Resolve settings with precedence: CLI explicit > config > CLI default
    def resolve(key: str, default_val):
        if flag_set(key.replace("_", "-")):
            return getattr(args, key)
        if key in cfg:
            return cfg[key]
        return getattr(args, key) if hasattr(args, key) else default_val

    symbols_val = resolve("symbols", "BTC,ETH")
    threshold_val = float(resolve("threshold", 0.002))
    slip_bps_val = float(resolve("slip_bps", 50.0))
    size_val = float(resolve("size", 0.0))
    poll_sec_val = int(resolve("poll_sec", 5))
    min_interval_val = int(resolve("min_interval_sec", 15))
    dry_run_val = bool(resolve("dry_run", False))
    logs_dir = cfg.get("logs_dir")
    runs_dir = cfg.get("runs_dir")

    paths = ensure_dirs(logs_dir=logs_dir, runs_dir=runs_dir)
    logger.add(paths["log_path"], rotation="1 day", retention=7)

    # Load .env if available
    if load_dotenv is not None:
        # ENV_FILE can override .env path if set
        env_file = os.getenv("ENV_FILE")
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

    pk = os.getenv("HL_PRIVATE_KEY")
    if not pk:
        raise SystemExit("HL_PRIVATE_KEY not set. Provide testnet key for placing orders.")
    acct = Account.from_key(pk)
    ex = Exchange(acct, base_url=base_url())

    syms_src = symbols_val if isinstance(symbols_val, str) else ",".join(symbols_val)
    syms = [s.strip().upper() for s in syms_src.split(",") if s.strip()]
    strat = Strategy(
        ex,
        syms,
        threshold=threshold_val,
        slip_bps=slip_bps_val,
        poll_sec=poll_sec_val,
        min_interval_sec=min_interval_val,
        default_size=size_val,
        dry_run=dry_run_val,
        trades_csv=paths["trades_csv"],
    )

    logger.info(
        "Runner start: symbols={} threshold={} slip_bps={} size={} dryRun={} config_path={} logs={} runs={}",
        syms, threshold_val, slip_bps_val, size_val, dry_run_val, cfg_path, str(paths["log_path"]), str(paths["trades_csv"]) 
    )
    asyncio.run(strat.run())


if __name__ == "__main__":
    main()
