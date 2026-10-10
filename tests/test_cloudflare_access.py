import base64
import json
import threading
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import web_console.cloudflare_access as cf_module
from web_console.cloudflare_access import CloudflareAccessError, CloudflareAccessVerifier

from web_console.cloudflare_access import CloudflareAccessVerifier


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_int(value: int) -> str:
    byte_length = (value.bit_length() + 7) // 8
    return _b64url(value.to_bytes(byte_length, "big"))


def _make_key_and_jwks() -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    return private_key, {
        "keys": [
            {
                "kid": "test-key",
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "n": _b64url_int(numbers.n),
                "e": _b64url_int(numbers.e),
            }
        ]
    }


def _make_token(private_key: rsa.RSAPrivateKey, payload: dict[str, object]) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": "test-key"}
    signing_input = ".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    ).encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return signing_input.decode("ascii") + "." + _b64url(signature)


def _make_verifier(jwks: dict[str, object]) -> CloudflareAccessVerifier:
    return CloudflareAccessVerifier(
        team_domain="https://example.cloudflareaccess.com",
        audiences=["console-aud"],
        allowed_emails=["reidar@example.com"],
        certs_fetcher=lambda _url: jwks,
        now=lambda: 1_700_000_000,
    )


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "iss": "https://example.cloudflareaccess.com",
        "aud": ["console-aud"],
        "email": "reidar@example.com",
        "exp": 1_700_000_600,
    }
    payload.update(overrides)
    return payload


def test_cloudflare_access_verifier_accepts_valid_token():
    private_key, jwks = _make_key_and_jwks()
    verifier = _make_verifier(jwks)
    token = _make_token(private_key, _payload())

    assert verifier.verify_headers({"cf-access-jwt-assertion": token}) is True


def test_cloudflare_access_verifier_rejects_wrong_audience():
    private_key, jwks = _make_key_and_jwks()
    verifier = _make_verifier(jwks)
    token = _make_token(private_key, _payload(aud=["wrong-aud"]))

    assert verifier.verify_headers({"cf-access-jwt-assertion": token}) is False


def test_cloudflare_access_verifier_rejects_disallowed_email():
    private_key, jwks = _make_key_and_jwks()
    verifier = _make_verifier(jwks)
    token = _make_token(private_key, _payload(email="someone@example.com"))

    assert verifier.verify_headers({"cf-access-jwt-assertion": token}) is False


def test_cloudflare_access_verifier_rejects_expired_token():
    private_key, jwks = _make_key_and_jwks()
    verifier = _make_verifier(jwks)
    token = _make_token(private_key, _payload(exp=1_699_999_999))

    assert verifier.verify_headers({"cf-access-jwt-assertion": token}) is False


def test_cloudflare_access_verifier_rejects_invalid_signature():
    private_key, jwks = _make_key_and_jwks()
    other_private_key, _ = _make_key_and_jwks()
    verifier = _make_verifier(jwks)
    token = _make_token(other_private_key, _payload())

    assert verifier.verify_headers({"cf-access-jwt-assertion": token}) is False


def test_unknown_kid_refresh_failure_serves_stale_then_fails_closed():
    private_key, jwks = _make_key_and_jwks()
    clock = {"now": 1_700_000_000.0}
    verifier = CloudflareAccessVerifier(
        team_domain="https://example.cloudflareaccess.com",
        audiences=["console-aud"],
        allowed_emails=["reidar@example.com"],
        certs_fetcher=lambda _url: jwks,
        now=lambda: clock["now"],
    )
    token = _make_token(private_key, _payload())

    assert verifier.verify_headers({"cf-access-jwt-assertion": token}) is True

    def _fail(_url: str) -> dict[str, object]:
        raise CloudflareAccessError("provider unavailable")

    verifier._certs_fetcher = _fail
    clock["now"] += 2.0
    unknown_key, _ = _make_key_and_jwks()
    unknown_token = _make_token(unknown_key, _payload())

    assert verifier.verify_headers({"cf-access-jwt-assertion": unknown_token}) is False

    clock["now"] += cf_module.MAX_CERTS_STALENESS_SECONDS + 10.0

    assert verifier.verify_headers({"cf-access-jwt-assertion": unknown_token}) is False

    with pytest.raises(CloudflareAccessError):
        verifier._load_certs(refresh=True)


def test_repeated_unknown_kid_produces_one_refresh():
    private_key, jwks = _make_key_and_jwks()
    fetch_count = {"value": 0}
    fetch_lock = threading.Lock()

    def _counting_fetch(_url: str) -> dict[str, object]:
        with fetch_lock:
            fetch_count["value"] += 1
        time.sleep(0.05)
        return jwks

    verifier = CloudflareAccessVerifier(
        team_domain="https://example.cloudflareaccess.com",
        audiences=["console-aud"],
        allowed_emails=["reidar@example.com"],
        certs_fetcher=_counting_fetch,
        now=lambda: 1_700_000_000,
    )
    unknown_key, _ = _make_key_and_jwks()
    token = _make_token(unknown_key, _payload())
    barrier = threading.Barrier(5)
    results: list[bool] = []

    def _verify() -> None:
        barrier.wait()
        results.append(verifier.verify_headers({"cf-access-jwt-assertion": token}))

    threads = [threading.Thread(target=_verify) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(result is False for result in results)
    assert fetch_count["value"] == 1


class _FakeCertRaw:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int, decode_content: bool = True) -> bytes:
        return self._payload[:size]


class _FakeCertResponse:
    def __init__(self, payload: bytes) -> None:
        self.raw = _FakeCertRaw(payload)

    def raise_for_status(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_oversized_cert_response_is_rejected_without_cache(monkeypatch):
    payload = b"x" * (cf_module.CERTS_REFRESH_MAX_BYTES + 1)
    monkeypatch.setattr(
        cf_module.requests,
        "get",
        lambda *_args, **_kwargs: _FakeCertResponse(payload),
    )
    verifier = CloudflareAccessVerifier(
        team_domain="https://example.cloudflareaccess.com",
        audiences=["console-aud"],
        allowed_emails=["reidar@example.com"],
        now=lambda: 1_700_000_000,
    )

    with pytest.raises(CloudflareAccessError) as excinfo:
        verifier._load_certs(refresh=True)

    assert "too large" in str(excinfo.value.__cause__)
    assert verifier._cached_certs is None


def test_malformed_cert_response_is_rejected_then_valid_refresh_succeeds():
    private_key, jwks = _make_key_and_jwks()
    responses: list[dict[str, object] | Exception] = [
        CloudflareAccessError("bad payload"),
        jwks,
    ]

    def _fetch(_url: str) -> dict[str, object]:
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    verifier = CloudflareAccessVerifier(
        team_domain="https://example.cloudflareaccess.com",
        audiences=["console-aud"],
        allowed_emails=["reidar@example.com"],
        certs_fetcher=_fetch,
        now=lambda: 1_700_000_000,
    )
    token = _make_token(private_key, _payload())

    assert verifier.verify_headers({"cf-access-jwt-assertion": token}) is False
    assert verifier.verify_headers({"cf-access-jwt-assertion": token}) is True
    assert verifier._cached_certs == jwks
