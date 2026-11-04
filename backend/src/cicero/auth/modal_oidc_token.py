"""Emit Modal's injected OIDC token for Google executable-sourced credentials.

Google Auth invokes this module as a subprocess. It must write only the
executable-sourced credential response JSON to stdout. Diagnostic messages go
to stderr and must never include the token itself.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any

TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id_token"


def _jwt_expiration(token: str) -> int | None:
    """Read exp for cache metadata; Google STS remains responsible for validation."""
    try:
        payload_segment = token.split(".")[1]
        payload_segment += "=" * (-len(payload_segment) % 4)
        payload: dict[str, Any] = json.loads(
            base64.urlsafe_b64decode(payload_segment.encode("ascii"))
        )
        expiration = payload.get("exp")
        return int(expiration) if expiration is not None else None
    except (IndexError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return None


def main() -> int:
    token = os.environ.get("MODAL_IDENTITY_TOKEN")
    if not token:
        print(
            json.dumps(
                {
                    "version": 1,
                    "success": False,
                    "code": "401",
                    "message": "MODAL_IDENTITY_TOKEN is not available in this Modal function.",
                }
            )
        )
        return 1

    response: dict[str, Any] = {
        "version": 1,
        "success": True,
        "token_type": TOKEN_TYPE,
        "id_token": token,
    }
    expiration = _jwt_expiration(token)
    if expiration is not None:
        response["expiration_time"] = expiration

    print(json.dumps(response, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
