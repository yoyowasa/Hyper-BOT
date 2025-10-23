"""検証用スナップショット取得スクリプト。

- metaAndAssetCtxs
- candleSnapshot（指定シンボル・足）
- fundingHistory
"""

import argparse
from hyper_bot.data.ingest import (
    fetch_candle_snapshots,
    fetch_funding_history,
    fetch_meta_and_asset_ctxs,
)


def main() -> None:
    p = argparse.ArgumentParser(description="Hyperliquid データスナップショット取得")
    p.add_argument("--assets", type=str, default="BTC,ETH", help="対象シンボル（カンマ区切り）")
    p.add_argument("--timeframes", type=str, default="1h,1d", help="対象タイムフレーム（カンマ区切り）")
    p.add_argument("--funding-limit", type=int, default=168, help="fundingHistory の取得件数上限")
    args = p.parse_args()

    assets = [s.strip() for s in args.assets.split(",") if s.strip()]
    tfs = [s.strip() for s in args.timeframes.split(",") if s.strip()]

    fetch_meta_and_asset_ctxs()
    fetch_candle_snapshots(assets, tfs)
    fetch_funding_history(assets, limit=args.funding_limit)


if __name__ == "__main__":
    main()
