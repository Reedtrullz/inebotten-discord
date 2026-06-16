import base64
import json
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

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
