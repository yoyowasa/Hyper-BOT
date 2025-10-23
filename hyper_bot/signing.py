from __future__ import annotations

"""署名インタフェース（Hyperliquid SDK と同等の L1 アクション署名）。

参考: https://github.com/hyperliquid-dex/hyperliquid-python-sdk (utils/signing.py)
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import msgpack  # type: ignore
from eth_account import Account  # type: ignore
from eth_account.messages import encode_typed_data  # type: ignore
from eth_utils import keccak, to_hex  # type: ignore


@dataclass
class Signature:
    """署名結果。

    - r/s: 16 進文字列
    - v: int（27/28 等）
    - nonce: 署名に用いたノンス（UTC ms 推奨）
    """

    r: str
    s: str
    v: int
    nonce: int


def _address_to_bytes(address: Optional[str]) -> bytes:
    if not address:
        return b""
    a = address[2:] if address.startswith("0x") else address
    return bytes.fromhex(a)


def _action_hash(action: Dict[str, Any], vault_address: Optional[str], nonce: int, expires_after: Optional[int]) -> bytes:
    data = msgpack.packb(action)
    data += int(nonce).to_bytes(8, "big")
    if vault_address is None:
        data += b"\x00"
    else:
        data += b"\x01" + _address_to_bytes(vault_address)
    if expires_after is not None:
        data += b"\x00" + int(expires_after).to_bytes(8, "big")
    return keccak(data)


def _construct_phantom_agent(hash_bytes: bytes, is_mainnet: bool) -> Dict[str, Any]:
    return {"source": "a" if is_mainnet else "b", "connectionId": hash_bytes}


def _l1_payload(phantom_agent: Dict[str, Any]) -> Dict[str, Any]:
    # EIP-712 Typed Data
    return {
        "domain": {
            "chainId": 1337,
            "name": "Exchange",
            "verifyingContract": "0x0000000000000000000000000000000000000000",
            "version": "1",
        },
        "types": {
            "Agent": [
                {"name": "source", "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": "Agent",
        "message": phantom_agent,
    }


def _sign_inner(private_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    acct = Account.from_key(private_key)
    structured = encode_typed_data(full_message=data)
    signed = acct.sign_message(structured)
    return {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]}


def sign_exchange_action(
    action: Dict[str, Any],
    private_key: str,
    nonce: int,
    *,
    is_mainnet: bool,
    vault_address: Optional[str] = None,
    expires_after: Optional[int] = None,
) -> Signature:
    """/exchange に送信する action に対する L1 署名を返す。

    引数:
        action: 例) {"type":"order", "orders": [...], "grouping":"na"}
        private_key: エージェント（API ウォレット）の秘密鍵（0x プレフィックスでも可）
        nonce: UTC ミリ秒推奨（最新 100 個集合で管理）
        is_mainnet: True=Mainnet / False=Testnet
        vault_address: 通常 None（usd/send など一部アクションで使用）
        expires_after: タイムアウト（ミリ秒）。通常 None
    戻り値:
        Signature(r/s/v/nonce)
    """

    h = _action_hash(action, vault_address, nonce, expires_after)
    phantom = _construct_phantom_agent(h, is_mainnet)
    payload = _l1_payload(phantom)
    vrs = _sign_inner(private_key, payload)
    return Signature(r=vrs["r"], s=vrs["s"], v=vrs["v"], nonce=nonce)


def build_exchange_payload(
    action: Dict[str, Any],
    signature: Signature,
    *,
    vault_address: Optional[str] = None,
    expires_after: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /exchange のペイロードを構築する。"""

    return {
        "action": action,
        "nonce": signature.nonce,
        "signature": {"r": signature.r, "s": signature.s, "v": signature.v},
        "vaultAddress": vault_address if action.get("type") not in ("usdClassTransfer", "sendAsset") else None,
        "expiresAfter": expires_after,
    }
