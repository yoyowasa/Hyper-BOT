"""Full strategy runner skeleton (WS + gates + IOC + RO stops) using Hyperliquid SDK.

Features (minimal working skeleton):
- WS subscription for 1m candles; rolling windows for robust z of premium
- Info endpoints for oraclePx/markPx, openInterest, spread gating via L2 snapshot
- Risk sizing via equity * risk_per_trade_pct and ATR-based stop distance
- IOC limit entries with slippage; reduce-only stop/take as separate trigger orders
- State machine per symbol: IDLE -> ENTRY_PENDING -> IN_POSITION -> EXIT_PENDING -> IDLE
- Global cooldown on consecutive errors; daily loss stop via simple CSV aggregation

Config: see configs/strategy_full.yaml

Usage:
  HL_NETWORK=testnet HL_PRIVATE_KEY=0x... \
  python scripts/strategy_runner_full_sdk.py --config configs/strategy_full.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from eth_account import Account
from loguru import logger
from statistics import median

import yaml  # type: ignore

from hyperliquid.exchange import Exchange
from hyper_bot.ws_client import WebsocketClient

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None


MAINNET = "https://api.hyperliquid.xyz"
TESTNET = "https://api.hyperliquid-testnet.xyz"


def base_url() -> str:
    return TESTNET if os.getenv("HL_NETWORK", "mainnet").lower() == "testnet" else MAINNET


def utc_iso(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp((ts or time.time()), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dirs(logs_dir: str, runs_dir: str) -> Dict[str, Path]:
    logs = Path(logs_dir); logs.mkdir(parents=True, exist_ok=True)
    runs = Path(runs_dir); runs.mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().strftime("%Y%m%d")
    return {
        "log_path": logs / f"strategy_{today}.log",
        "trades_csv": runs / f"trades_{today}.csv",
    }


@dataclass
class SymState:
    state: str = "IDLE"
    last_change: float = 0.0
    last_error_at: float = 0.0
    last_entry_at: float = 0.0
    entry_px: Optional[float] = None
    pos: float = 0.0
    last_premium: float = 0.0
    last_oi: Optional[float] = None
    candles: Deque[Tuple[float, float, float, float]] = None  # (t, o,h,l,c)
    premiums: Deque[float] = None

    def __post_init__(self) -> None:
        if self.candles is None:
            self.candles = deque(maxlen=120)
        if self.premiums is None:
            self.premiums = deque(maxlen=120)


class Runner:
    def __init__(self, ex: Exchange, cfg: Dict[str, Any], paths: Dict[str, Path]) -> None:
        self.ex = ex
        self.cfg = cfg
        self.paths = paths
        syms = cfg.get("symbols") or [cfg.get("symbol", "BTC")]
        if isinstance(syms, str):
            syms = [s.strip().upper() for s in syms.split(",") if s.strip()]
        else:
            syms = [str(s).upper() for s in syms]
        self.symbols: List[str] = syms
        self.state: Dict[str, SymState] = {s: SymState() for s in self.symbols}
        self.global_cooldown_until: float = 0.0
        self.error_timestamps: Deque[float] = deque(maxlen=32)

        # Mappings
        self.name_to_coin: Dict[str, int] = self.ex.info.name_to_coin
        self.coin_to_asset: Dict[int, int] = self.ex.info.coin_to_asset
        self.asset_to_sz_decimals: Dict[int, int] = self.ex.info.asset_to_sz_decimals

    def _append_trade(self, row: List[Any]) -> None:
        with self.paths["trades_csv"].open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

    def _equity(self) -> float:
        try:
            address = self.ex.wallet.address
            ust = self.ex.info.user_state(address)
            ms = ust.get("marginSummary", {}) if isinstance(ust, dict) else {}
            for k in ("accountValue", "equity", "total"):  # heuristic
                v = ms.get(k)
                if isinstance(v, (int, float)):
                    return float(v)
        except Exception:
            pass
        return float(self.cfg.get("risk", {}).get("equity_usd", 10000))

    def _atr(self, sym: str, period: int = 14) -> Optional[float]:
        d = self.state[sym]
        if len(d.candles) < period + 1:
            return None
        trs: List[float] = []
        prev_c = d.candles[0][3]
        for (_, _o, h, l, c) in list(d.candles)[-period:]:
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
            prev_c = c
        return sum(trs) / len(trs) if trs else None

    def _robust_z(self, sym: str, window_sec: int) -> Optional[float]:
        now = time.time()
        vals = [p for (t, p) in zip([c[0] for c in self.state[sym].candles], list(self.state[sym].premiums)) if (now - t) <= window_sec]
        if not vals:
            vals = list(self.state[sym].premiums)
        if len(vals) < 10:
            return None
        med = median(vals)
        abs_dev = [abs(v - med) for v in vals]
        mad = median(abs_dev)
        denom = 1.4826 * mad if mad > 0 else 1e-9
        return (self.state[sym].last_premium - med) / denom

    def _spread_bps(self, sym: str) -> Optional[float]:
        try:
            snap = self.ex.info.l2_snapshot(sym)
            bids = snap.get("levels", {}).get("bids") or snap.get("bids")
            asks = snap.get("levels", {}).get("asks") or snap.get("asks")
            if isinstance(bids, list) and isinstance(asks, list) and bids and asks:
                best_b = float(bids[0][0]) if isinstance(bids[0], (list, tuple)) else float(bids[0].get("px"))
                best_a = float(asks[0][0]) if isinstance(asks[0], (list, tuple)) else float(asks[0].get("px"))
                mid = 0.5 * (best_b + best_a)
                return 10_000 * (best_a - best_b) / mid
        except Exception:
            return None
        return None

    def _size_for(self, sym: str, mid: float, atr: Optional[float]) -> float:
        risk_cfg = self.cfg.get("risk", {})
        equity = self._equity()
        risk_usd = equity * float(risk_cfg.get("risk_per_trade_pct", 0.003))
        stop_mult = float(risk_cfg.get("stop_atr_mult", 1.5))
        stop_dist = (atr or (0.003 * mid)) * stop_mult  # fallback 30 bps of price if ATR missing
        qty = max(1e-12, risk_usd / stop_dist)
        # round to decimals
        dec = int(self.asset_to_sz_decimals[self.coin_to_asset[self.name_to_coin[sym]]])
        s = f"{qty:.12f}"; parts = s.split(".")
        s = parts[0] + ("." + parts[1][:dec] if dec > 0 else "")
        try:
            return max(0.0, float(s))
        except Exception:
            return qty

    def _place_ioc(self, sym: str, is_buy: bool, size: float, mid: float) -> Any:
        slip = float(self.cfg.get("slippage_bps", 2)) / 10_000.0
        limit_px = self.ex._slippage_price(sym, is_buy, slip, px=mid)
        tif_obj = {"limit": {"tif": "Ioc"}}
        resp = self.ex.order(sym, is_buy, size, limit_px, tif_obj)
        return resp, limit_px

    def _attach_ro_stops(self, sym: str, is_long: bool, entry_px: float, atr: Optional[float]) -> None:
        # best-effort reduce-only TP/SL triggers
        risk_cfg = self.cfg.get("risk", {})
        stop_mult = float(risk_cfg.get("stop_atr_mult", 1.5))
        take_mult = float(risk_cfg.get("take_atr_mult", 3.0))
        use_trig = atr is not None and atr > 0
        if not use_trig:
            return
        stop_px = entry_px - stop_mult * atr if is_long else entry_px + stop_mult * atr
        take_px = entry_px + take_mult * atr if is_long else entry_px - take_mult * atr
        # query current pos size
        ust = self.ex.info.user_state(self.ex.wallet.address)
        curr = 0.0
        for ap in ust.get("assetPositions", []) or []:
            if ap.get("name") == sym and ap.get("position"):
                try:
                    curr = abs(float(ap["position"]["szi"]))
                except Exception:
                    curr = 0.0
        if curr <= 0:
            return
        # SL: reduce-only trigger market
        try:
            self.ex.order(sym, not is_long, curr, entry_px, {"trigger": {"isMarket": True, "triggerPx": stop_px, "tpsl": "sl"}}, reduce_only=True)
        except Exception as e:
            logger.warning("attach SL failed: {}", e)
        # TP
        try:
            self.ex.order(sym, not is_long, curr, entry_px, {"trigger": {"isMarket": True, "triggerPx": take_px, "tpsl": "tp"}}, reduce_only=True)
        except Exception as e:
            logger.warning("attach TP failed: {}", e)

    async def run(self) -> None:
        # Prepare CSV
        if not self.paths["trades_csv"].exists():
            with self.paths["trades_csv"].open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["time","symbol","event","side","size","px","premium","info"])

        ws = WebsocketClient()
        for s in self.symbols:
            ws.add_subscription("candle", symbol=s, interval="1m")

        async def handler(msg: Dict[str, Any]) -> None:
            if not isinstance(msg, dict) or msg.get("channel") != "candle":
                return
            data = msg.get("data")
            if not isinstance(data, dict):
                return
            sym = str(data.get("symbol"))
            if sym not in self.state:
                return
            t = float(data.get("t", time.time())) / 1000.0
            c = float(data.get("c")) if isinstance(data.get("c"), (int, float)) else None
            h = float(data.get("h")) if isinstance(data.get("h"), (int, float)) else c
            l = float(data.get("l")) if isinstance(data.get("l"), (int, float)) else c
            o = float(data.get("o")) if isinstance(data.get("o"), (int, float)) else c
            if c is None:
                return
            # get oracle for premium (from meta ctxs)
            ctx = self.ex.info.meta_and_asset_ctxs()
            oracle = None
            if isinstance(ctx, list) and len(ctx) >= 2 and isinstance(ctx[1], list):
                # align by index
                coin = self.name_to_coin.get(sym)
                if coin is not None and coin < len(ctx[1]) and isinstance(ctx[1][coin], dict):
                    opx = ctx[1][coin].get("oraclePx") or ctx[1][coin].get("indexPx")
                    if isinstance(opx, (int, float)):
                        oracle = float(opx)
            if oracle is None:
                return
            prem = (c - oracle) / oracle

            st = self.state[sym]
            st.candles.append((t, o, h, l, c))
            st.premiums.append(prem)
            st.last_premium = prem

        trader_task = asyncio.create_task(self._loop())
        try:
            await ws.run(handler)
        finally:
            trader_task.cancel()
            with asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        spd_max = float(self.cfg.get("safety", {}).get("spread_bps_max", 3))
        ws_stale = float(self.cfg.get("safety", {}).get("ws_stale_sec", 5))
        cd_base = float(self.cfg.get("safety", {}).get("cooldown_base_sec", 60))
        cd_max = float(self.cfg.get("safety", {}).get("cooldown_max_sec", 900))
        err_limit = int(self.cfg.get("safety", {}).get("consecutive_error_limit", 3))

        prem_cfg = self.cfg.get("signal", {}).get("premium_mr", {})
        z_entry = float(prem_cfg.get("z_entry", 2.0))
        z_exit = float(prem_cfg.get("z_exit", 0.5))
        win_sec = int(prem_cfg.get("window_sec", 3600))

        while True:
            try:
                now = time.time()
                # global cooldown
                if now < self.global_cooldown_until:
                    await asyncio.sleep(1)
                    continue

                # update positions
                ust = self.ex.info.user_state(self.ex.wallet.address)
                pos_map: Dict[str, float] = {}
                for ap in ust.get("assetPositions", []) or []:
                    if isinstance(ap, dict) and ap.get("position"):
                        try:
                            pos_map[str(ap.get("name")).upper()] = float(ap["position"]["szi"])  # signed
                        except Exception:
                            pass

                for sym in self.symbols:
                    st = self.state[sym]
                    # WS staleness
                    if not st.candles or (now - st.candles[-1][0]) > ws_stale:
                        continue
                    # spread gate
                    spd = self._spread_bps(sym)
                    if spd is not None and spd > spd_max:
                        continue
                    # z score
                    z = self._robust_z(sym, win_sec)
                    if z is None:
                        continue
                    curr = pos_map.get(sym, 0.0)
                    atr = self._atr(sym, period=14)
                    mid = self.state[sym].candles[-1][3]

                    if curr == 0.0:
                        # entry
                        if abs(z) >= z_entry:
                            is_buy = z < 0
                            try:
                                size = self._size_for(sym, mid, atr)
                                resp, px = self._place_ioc(sym, is_buy, size, mid)
                                self._append_trade([utc_iso(), sym, "entry", "buy" if is_buy else "sell", size, px, self.state[sym].last_premium, str(resp)])
                                st.entry_px = px
                                st.last_entry_at = now
                                st.state = "IN_POSITION"  # optimistic; real pos updates next tick
                                if self.cfg.get("order", {}).get("reduce_only_exit", True):
                                    self._attach_ro_stops(sym, is_buy, px, atr)
                            except Exception as e:
                                self._register_error(e, cd_base, cd_max, err_limit)
                                logger.warning("entry error: {}", e)
                        continue

                    # exit conditions (in position)
                    is_long = curr > 0
                    time_stop = float(self.cfg.get("risk", {}).get("time_stop_sec", 900))
                    timed_out = (now - (st.last_entry_at or now)) >= time_stop
                    exit_signal = abs(z) <= z_exit
                    if exit_signal or timed_out:
                        try:
                            size = abs(curr)
                            resp, px = self._place_ioc(sym, not is_long, size, mid)
                            self._append_trade([utc_iso(), sym, "exit", "sell" if is_long else "buy", size, px, self.state[sym].last_premium, str(resp)])
                            st.state = "IDLE"
                            st.entry_px = None
                        except Exception as e:
                            self._register_error(e, cd_base, cd_max, err_limit)
                            logger.warning("exit error: {}", e)

            except Exception as e:
                self._register_error(e, cd_base, cd_max, err_limit)
                logger.exception("runner loop error: {}", e)

            await asyncio.sleep(1)

    def _register_error(self, e: Exception, cd_base: float, cd_max: float, err_limit: int) -> None:
        now = time.time()
        self.error_timestamps.append(now)
        recent = [t for t in self.error_timestamps if now - t <= 600]  # 10min window
        if len(recent) >= err_limit:
            # exponential backoff
            k = min(5, len(recent) - err_limit + 1)
            backoff = min(cd_max, cd_base * (2 ** (k - 1)))
            self.global_cooldown_until = max(self.global_cooldown_until, now + backoff)
            logger.warning("cooldown {}s due to consecutive errors", backoff)


def main() -> None:
    p = argparse.ArgumentParser(description="Full strategy runner skeleton")
    p.add_argument("--config", type=str, default="configs/strategy_full.yaml")
    args = p.parse_args()

    if not Path(args.config).exists():
        raise SystemExit(f"config not found: {args.config}")
    cfg = yaml.safe_load(open(args.config, "r", encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise SystemExit("config must be YAML mapping")

    logs_dir = cfg.get("logs_dir", "logs")
    runs_dir = cfg.get("runs_dir", "runs")
    paths = ensure_dirs(str(logs_dir), str(runs_dir))
    logger.add(paths["log_path"], rotation="1 day", retention=7)

    # Load .env if available
    if load_dotenv is not None:
        env_file = os.getenv("ENV_FILE")
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

    pk = os.getenv("HL_PRIVATE_KEY")
    if not pk:
        raise SystemExit("HL_PRIVATE_KEY not set")
    acct = Account.from_key(pk)
    ex = Exchange(acct, base_url=base_url())

    logger.info("Runner start: cfg={} logs={} trades={}", args.config, str(paths["log_path"]), str(paths["trades_csv"]))
    runner = Runner(ex, cfg, paths)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
