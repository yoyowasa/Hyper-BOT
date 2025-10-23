from __future__ import annotations

"""署名インタフェース（実装は公式ドキュメントに準拠して追加）。"""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Signature:
    """署名結果。

    - signature: 16 進文字列の署名
    - nonce: 署名に用いたノンス（UTC ms 推奨）
    """

    signature: str
    nonce: int


def sign_exchange_payload(payload: Dict[str, Any], private_key: str, nonce: int) -> Signature:
    """/exchange 用ペイロードに対する署名を作成する（ダミー）。

    注意: ここはプレースホルダです。Hyperliquid の公式仕様に従い、
    マスター口座で承認された API ウォレット（エージェント）の鍵で
    型付きペイロードへ署名する実装を追加してください。
    """

    raise NotImplementedError("実注⽂の前に、公式仕様準拠の署名実装を追加してください。")
