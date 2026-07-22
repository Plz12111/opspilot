import base64
import hashlib
import hmac
import json
import time
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class FeishuSecurityError(ValueError):
    pass


class FeishuRequestVerifier:
    def __init__(
        self,
        verification_token: str,
        encrypt_key: str,
        max_age_seconds: int = 300,
    ) -> None:
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key
        self.max_age_seconds = max_age_seconds

    def verify_signature(
        self, raw_body: bytes, timestamp: str | None, nonce: str | None, signature: str | None
    ) -> None:
        if not self.encrypt_key:
            return
        if not timestamp or not nonce or not signature:
            raise FeishuSecurityError("missing Feishu signature headers")
        try:
            request_time = int(timestamp)
        except ValueError as exc:
            raise FeishuSecurityError("invalid Feishu timestamp") from exc
        if abs(int(time.time()) - request_time) > self.max_age_seconds:
            raise FeishuSecurityError("stale Feishu callback")
        signed = timestamp.encode() + nonce.encode() + self.encrypt_key.encode() + raw_body
        expected = hashlib.sha256(signed).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise FeishuSecurityError("invalid Feishu signature")

    def decode_body(self, raw_body: bytes) -> dict[str, Any]:
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise FeishuSecurityError("invalid JSON body") from exc
        if "encrypt" not in body:
            return body
        if not self.encrypt_key:
            raise FeishuSecurityError("encrypted payload received without encrypt key")
        return self._decrypt(body["encrypt"])

    def verify_token(self, body: dict[str, Any]) -> None:
        if not self.verification_token:
            return
        token = body.get("token") or body.get("header", {}).get("token")
        if not token or not hmac.compare_digest(str(token), self.verification_token):
            raise FeishuSecurityError("invalid Feishu verification token")

    def _decrypt(self, encrypted: str) -> dict[str, Any]:
        try:
            key = hashlib.sha256(self.encrypt_key.encode()).digest()
            encrypted_bytes = base64.b64decode(encrypted)
            decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
            padded = decryptor.update(encrypted_bytes) + decryptor.finalize()
            padding = padded[-1]
            if padding < 1 or padding > 16:
                raise FeishuSecurityError("invalid encrypted payload padding")
            plaintext = padded[:-padding]
            return json.loads(plaintext)
        except (ValueError, json.JSONDecodeError) as exc:
            raise FeishuSecurityError("cannot decrypt Feishu payload") from exc
