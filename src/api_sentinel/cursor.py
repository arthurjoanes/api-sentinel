import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime

from api_sentinel.errors import Problem


@dataclass(frozen=True, slots=True)
class CursorScope:
    tenant_id: int
    store_id: int
    start: str
    end: str
    dataset_version: str


@dataclass(frozen=True, slots=True)
class SalePosition:
    sold_at: datetime
    item_id: int


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(encoded: str) -> bytes:
    return base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)


def _scope_fields(scope: CursorScope) -> dict[str, str | int]:
    return {
        "v": 1,
        "tenant": scope.tenant_id,
        "store": scope.store_id,
        "start": scope.start,
        "end": scope.end,
        "dataset": scope.dataset_version,
    }


def encode_cursor(scope: CursorScope, position: SalePosition, secret: str) -> str:
    if len(secret) < 32:
        raise ValueError("O segredo de cursor precisa de pelo menos 32 caracteres.")
    payload = {
        **_scope_fields(scope),
        "sold_at": position.sold_at.isoformat(),
        "id": position.item_id,
    }
    body = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_encode(signature)}"


def decode_cursor(cursor: str, scope: CursorScope, secret: str) -> SalePosition:
    invalid = Problem(
        422, "invalid_cursor", "Cursor inválido ou incompatível com loja, período ou versão."
    )
    if len(secret) < 32:
        raise ValueError("O segredo de cursor precisa de pelo menos 32 caracteres.")
    if len(cursor) > 2048:
        raise invalid
    try:
        body, signature = cursor.split(".")
        expected = hmac.new(secret.encode(), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(signature), expected):
            raise invalid
        payload = json.loads(_decode(body))
        if not isinstance(payload, dict) or set(payload) != {
            *_scope_fields(scope),
            "sold_at",
            "id",
        }:
            raise invalid
        if any(payload[key] != value for key, value in _scope_fields(scope).items()):
            raise invalid
        if type(payload["id"]) is not int or payload["id"] <= 0:
            raise invalid
        sold_at = datetime.fromisoformat(payload["sold_at"])
        if sold_at.tzinfo is None:
            raise invalid
        return SalePosition(sold_at=sold_at, item_id=payload["id"])
    except (ValueError, TypeError, UnicodeError, binascii.Error, KeyError) as exc:
        raise invalid from exc
