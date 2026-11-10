# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

# Push services keep an undelivered message for one day.
PUSH_TTL_SECONDS = 24 * 60 * 60
PUSH_TIMEOUT_SECONDS = 10


# Outcome of one push: delivered to the push service, or failed; gone means the subscription no
# longer exists and should be turned off.
@dataclass
class PushOutcome:
    ok: bool
    gone: bool = False
    detail: str = ""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# Return a new VAPID key pair as base64url strings: the public key as the browser expects it
# (uncompressed P-256 point) and the raw private key, as pywebpush accepts it.
def generate_vapid_keys() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(public_bytes), _b64url(private_bytes)


# Send one push message to one browser subscription.
def send_push(subscription: dict[str, Any], payload: dict[str, Any], *, private_key: str, subject: str) -> PushOutcome:
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=private_key,
            vapid_claims={"sub": subject},
            ttl=PUSH_TTL_SECONDS,
            timeout=PUSH_TIMEOUT_SECONDS,
        )
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        return PushOutcome(False, gone=status in {404, 410}, detail=f"HTTP {status}" if status else str(exc)[:200])
    except Exception as exc:
        return PushOutcome(False, detail=f"{type(exc).__name__}: {exc}"[:200])
    return PushOutcome(True)
