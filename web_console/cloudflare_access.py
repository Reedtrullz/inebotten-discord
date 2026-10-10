"""Cloudflare Access JWT validation for the web console."""

from __future__ import annotations

import base64
import json
import logging
import time
import threading
from collections.abc import Callable
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger(__name__)

CERTS_REFRESH_TIMEOUT_SECONDS = 5.0
CERTS_REFRESH_MAX_BYTES = 1024 * 1024
MAX_CERTS_STALENESS_SECONDS = 24 * 3600


class CloudflareAccessError(ValueError):
    """Raised when a Cloudflare Access token cannot be validated."""


CertsFetcher = Callable[[str], dict[str, Any]]


class CloudflareAccessVerifier:
    """Validate Cloudflare Access application tokens from request headers."""

    def __init__(
        self,
        *,
        team_domain: str,
        audiences: list[str],
        allowed_emails: list[str],
        certs_fetcher: CertsFetcher | None = None,
        cache_ttl_seconds: int = 3600,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.team_domain = self._normalize_team_domain(team_domain)
        self.audiences = {aud.strip() for aud in audiences if aud.strip()}
        self.allowed_emails = {email.strip().lower() for email in allowed_emails if email.strip()}
        self.cache_ttl_seconds = max(60, int(cache_ttl_seconds))
        self._certs_fetcher = certs_fetcher or self._fetch_certs
        self._now = now or time.time
        self._cached_certs: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._refresh_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.team_domain and self.audiences and self.allowed_emails)

    def verify_headers(self, headers: dict[str, str]) -> bool:
        token = headers.get("cf-access-jwt-assertion")
        if not token:
            return False
        try:
            self.verify_token(token)
            return True
        except CloudflareAccessError as exc:
            logger.warning("Cloudflare Access authentication failed: %s", exc)
            return False

    def verify_token(self, token: str) -> dict[str, Any]:
        if not self.configured:
            raise CloudflareAccessError("Cloudflare Access verifier is not fully configured")

        header, payload, signature, signed_data = self._decode_token(token)
        if header.get("alg") != "RS256":
            raise CloudflareAccessError("unsupported JWT algorithm")

        key_id = str(header.get("kid") or "")
        public_key = self._public_key_for_kid(key_id)
        try:
            public_key.verify(
                signature,
                signed_data,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except Exception as exc:
            raise CloudflareAccessError("invalid signature") from exc

        self._validate_claims(payload)
        return payload

    def _decode_token(self, token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
        parts = token.split(".")
        if len(parts) != 3:
            raise CloudflareAccessError("invalid JWT shape")
        try:
            header = json.loads(self._b64url_decode(parts[0]))
            payload = json.loads(self._b64url_decode(parts[1]))
            signature = self._b64url_decode(parts[2])
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise CloudflareAccessError("invalid JWT encoding") from exc
        if not isinstance(header, dict) or not isinstance(payload, dict):
            raise CloudflareAccessError("invalid JWT payload")
        return header, payload, signature, f"{parts[0]}.{parts[1]}".encode("ascii")

    def _validate_claims(self, payload: dict[str, Any]) -> None:
        issuer = str(payload.get("iss") or "").rstrip("/")
        if issuer != self.team_domain:
            raise CloudflareAccessError("invalid issuer")

        token_aud = payload.get("aud")
        token_audiences = token_aud if isinstance(token_aud, list) else [token_aud]
        if not any(str(aud) in self.audiences for aud in token_audiences):
            raise CloudflareAccessError("invalid audience")

        now = int(self._now())
        exp = payload.get("exp")
        if not isinstance(exp, int) or exp <= now:
            raise CloudflareAccessError("token expired")
        nbf = payload.get("nbf")
        if isinstance(nbf, int) and nbf > now:
            raise CloudflareAccessError("token not yet valid")

        email = str(payload.get("email") or "").lower()
        if email not in self.allowed_emails:
            raise CloudflareAccessError("email is not allowed")

    def _public_key_for_kid(self, key_id: str) -> rsa.RSAPublicKey:
        certs = self._load_certs(refresh=False)
        key = self._find_jwk(certs, key_id)
        if key is None:
            certs = self._load_certs(refresh=True)
            key = self._find_jwk(certs, key_id)
        if key is None:
            raise CloudflareAccessError("unknown signing key")

        try:
            numbers = rsa.RSAPublicNumbers(
                e=self._b64url_int(str(key["e"])),
                n=self._b64url_int(str(key["n"])),
            )
            return numbers.public_key()
        except Exception as exc:
            raise CloudflareAccessError("invalid signing key") from exc

    def _load_certs(self, *, refresh: bool) -> dict[str, Any]:
        now = self._now()
        if (
            not refresh
            and self._cached_certs is not None
            and now - self._cached_at < self.cache_ttl_seconds
        ):
            return self._cached_certs

        with self._refresh_lock:
            now = self._now()
            cached = self._cached_certs
            if cached is not None:
                age = now - self._cached_at
                if age < self.cache_ttl_seconds and (not refresh or age < 1.0):
                    return cached
            url = f"{self.team_domain}/cdn-cgi/access/certs"
            try:
                certs = self._certs_fetcher(url)
            except Exception as exc:
                if cached is not None and now - self._cached_at < MAX_CERTS_STALENESS_SECONDS:
                    return cached
                if cached is not None:
                    raise CloudflareAccessError("cached Cloudflare Access certs exceeded max staleness") from exc
                raise CloudflareAccessError("could not fetch Cloudflare Access certs") from exc
            if not isinstance(certs, dict):
                raise CloudflareAccessError("invalid Cloudflare Access cert response")
            if not isinstance(certs.get("keys"), list):
                raise CloudflareAccessError("invalid Cloudflare Access cert response")
            self._cached_certs = certs
            self._cached_at = now
            return certs

    def _fetch_certs(self, url: str) -> dict[str, Any]:
        response = requests.get(url, timeout=CERTS_REFRESH_TIMEOUT_SECONDS, stream=True)
        response.raise_for_status()
        try:
            raw = response.raw.read(CERTS_REFRESH_MAX_BYTES + 1, decode_content=True)
        finally:
            response.close()
        if len(raw) > CERTS_REFRESH_MAX_BYTES:
            raise CloudflareAccessError("Cloudflare Access cert response too large")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloudflareAccessError("invalid cert response") from exc
        if not isinstance(data, dict):
            raise CloudflareAccessError("invalid cert response")
        return data

    def _find_jwk(self, certs: dict[str, Any], key_id: str) -> dict[str, Any] | None:
        keys = certs.get("keys")
        if not isinstance(keys, list):
            return None
        for key in keys:
            if not isinstance(key, dict):
                continue
            if key_id and str(key.get("kid")) != key_id:
                continue
            if key.get("kty") == "RSA" and key.get("n") and key.get("e"):
                return key
        return None

    def _normalize_team_domain(self, value: str) -> str:
        domain = value.strip().rstrip("/")
        if domain and not domain.startswith(("https://", "http://")):
            domain = f"https://{domain}"
        return domain

    def _b64url_decode(self, value: str) -> bytes:
        padding_size = (4 - len(value) % 4) % 4
        return base64.urlsafe_b64decode(value + ("=" * padding_size))

    def _b64url_int(self, value: str) -> int:
        return int.from_bytes(self._b64url_decode(value), "big")
