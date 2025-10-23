Hyper_BOT スキャフォールド

Hyperliquid 仕様に沿った Python 最小構成です。含まれる機能:
- ハートビート・再接続付きの REST/WS クライアント
- 最新 100 個のノンス管理（UTC ミリ秒）
- DMS（Dead Man’s Switch）予約ヘルパ
- metaAndAssetCtxs・candle・funding のデータ取得
- 特徴量スケルトン（premium、funding 移動平均、OI、ボラティリティ）
- コスト（手数料/ファンディング/インパクト）を考慮可能なバックテスト骨格
- Tick/Lot（szDecimals）検証と TIF/ReduceOnly を備えた注文ビルダ

クイックスタート
- Python 3.10+
- pip install -r requirements.txt
- .env.example を .env にコピーして編集

実行例
- スナップショット取得: python scripts/fetch_snapshot.py --assets BTC,ETH --timeframes 1h,1d
- WS 紙トレ: python scripts/run_ws_paper.py --channels candle --assets BTC,ETH

注意
- 実注文には、hyper_bot/signing.py にて Hyperliquid 公式ドキュメント準拠の署名実装が必要です。環境変数 HL_PRIVATE_KEY/HL_ADDRESS を設定してください。

設定
- HL_NETWORK=mainnet|testnet でエンドポイントを切替（config.py）
- 手数料: config.DEFAULT_FEES
- インパクト想定ノーション: BTC/ETH は 20k、その他は 6k（config）
- レート制限: REST 1200/分、WS は config を参照

チェックリスト（本番前）
- 足/特徴量/目的変数の UTC 整合が取れている
- バックテストが手数料/ファンディング/スリッページ控除後でも妥当で、PnL 符号が再現できる
- Tick/Lot と最小 $10 の検証がテスト/ログで確認済み
- ノンスの (T−2d, T+1d) 有効範囲と最新 100 個管理が実装されている
- DMS 常時予約と心拍監視、WS 再接続が動作
- isSnapshot の扱いを含むスナップショット復元が検証済み
- cancel/cancelByCloid のバッチ戦略がレート制限に耐える
