Hyper_BOT Scaffold

Hyperliquid の REST/WS クライアントと、データ取得・発注ユーティリティを含む Python スケルトンです。

主な機能
- REST/WS クライアント（再接続・ping/pong 心拍）
- 署名（EIP‑712 相当）と nonce 管理（直近 100 件）
- メタ/スナップショット/ファンディング履歴の取得と保存
- 注文生成（Tick/桁数に応じた丸め、TIF、ReduceOnly、TP/SL grouping）
- 簡易リスク/バックテストの補助関数

要件
- Python 3.10+
- 依存関係: `requirements.txt` または `poetry install`

セットアップ
1) 依存のインストール
   - `pip install -r requirements.txt`
   - または `poetry install`
2) 環境変数
   - `.env.example` を `.env` にコピーして必要箇所を編集（実鍵はコミット禁止）
   - 既定では `HL_NETWORK=testnet` を推奨
   - 上書き用の `HL_BASE_URL` / `HL_WS_URL` を設定すると、ネットワーク既定より優先されます

クイックスタート（Testnet / 読み取り系）
- スナップショット取得: `python scripts/fetch_snapshot.py --assets BTC,ETH --timeframes 1h,1d`
- WS 購読（ローソク足）: `python scripts/run_ws_paper.py --channels candle --assets BTC,ETH`

クイックスタート（Testnet / 発注系）
- 実注文の前に、`.env` へテスト用の `HL_PRIVATE_KEY` と `HL_ADDRESS` を設定してください
- IOC の発注例（マーケット）:
  - `python scripts/place_ioc_example.py --symbol BTC --side buy --size 0.001 --market`
- TP/SL のセット例（positionTpsl）:
  - `python scripts/place_tpsl_example.py --symbol BTC --side long --size 0.001 --px 50000 --tp 50500 --sl 49500`

スモークテスト（Testnet 向け、安全なIOC確認）
- 使い方: `scripts/smoke_test_testnet.py`
  - 事前に `HL_NETWORK=testnet` を設定
  - DRY RUN（発注しない）:
    - `python scripts/smoke_test_testnet.py --symbol BTC --side buy`
  - 実行（発注するには --confirm 必須。環境変数に鍵が必要）:
    - `python scripts/smoke_test_testnet.py --symbol BTC --side buy --confirm`
  - DMS（任意、n秒後にキャンセル予約）:
    - `python scripts/smoke_test_testnet.py --symbol ETH --side sell --confirm --dms 10`
  - 安全策:
    - mainnet では実行不可（testnet 強制）
    - `--confirm` がない限りは発注しません（DRY RUN）

注意
- 本番鍵のコミット禁止（`.env` は `.gitignore` 済）
- `HL_NETWORK` で mainnet/testnet を切替（`hyper_bot/config.py`）
- `HL_BASE_URL` / `HL_WS_URL` を設定すると、コードはそれらを優先して利用します

テスト
- 単体テストの実行: `pytest -q`
- テストはネットワークに依存せず、以下を検証します
  - 注文の丸め/ペイロード生成
  - REST ボディ整形（署名コールバック経由）
  - WS 購読ペイロードの整形

構成
- `hyper_bot/rest_client.py` — /info, /exchange（発注/キャンセル/DMS）
- `hyper_bot/ws_client.py` — WS クライアント（購読、心拍、自動再接続）
- `hyper_bot/signing.py` — 署名（EIP‑712 相当）、`hyper_bot/nonce_manager.py` — nonce 管理
- `hyper_bot/orders.py` — 注文ユーティリティ、`hyper_bot/utils.py` — 共通関数
- `hyper_bot/data/ingest.py` — データ取得の保存ユーティリティ
- `scripts/` — 実行サンプル
