"""GitHub App authentication: JWT signing, installation discovery, token scoping and renewal."""

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ai_sre_agent.github import APP_TOKEN_PERMISSIONS, AppAuth


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return pem, key.public_key()


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeSession:
    """Records calls; mints a new installation token on every access_tokens POST."""

    def __init__(self, installed=True):
        self.calls, self.minted, self.installed = [], 0, installed

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append((method, url, headers, json))
        if url.endswith("/repos/kyle/demo/installation"):
            return Resp(200, {"id": 42}) if self.installed else Resp(404, {"message": "Not Found"})
        if url.endswith("/app/installations/42/access_tokens"):
            self.minted += 1
            return Resp(201, {"token": f"ghs_{self.minted}", "expires_at": "2030-01-01T01:00:00Z"})
        return Resp(500, {})


T0 = 1893456000.0  # 2030-01-01T00:00:00Z


def make(keypair, session, now, installation_id=""):
    return AppAuth("https://api.github.test", "123", keypair[0], "kyle/demo",
                   installation_id=installation_id, session=session, clock=lambda: now[0])


def test_jwt_is_signed_by_app_key(keypair):
    s, now = FakeSession(), [T0]
    make(keypair, s, now).token()
    bearer = s.calls[0][2]["Authorization"].split()[1]
    claims = jwt.decode(bearer, keypair[1], algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False})
    assert claims["iss"] == "123"
    assert claims["exp"] - claims["iat"] <= 600


def test_discovers_installation_and_scopes_token(keypair):
    s, now = FakeSession(), [T0]
    assert make(keypair, s, now).token() == "ghs_1"
    _, _, _, body = s.calls[1]
    assert body == {"repositories": ["demo"], "permissions": APP_TOKEN_PERMISSIONS}


def test_explicit_installation_id_skips_lookup(keypair):
    s, now = FakeSession(), [T0]
    make(keypair, s, now, installation_id="42").token()
    assert len(s.calls) == 1 and s.calls[0][1].endswith("/access_tokens")


def test_token_cached_then_renewed_before_expiry(keypair):
    s, now = FakeSession(), [T0]
    auth = make(keypair, s, now)
    assert auth.token() == "ghs_1"
    now[0] = T0 + 1800
    assert auth.token() == "ghs_1"
    now[0] = T0 + 3600 - 299  # inside the 5-minute renewal window
    assert auth.token() == "ghs_2"


def test_not_installed_is_a_clear_error(keypair):
    with pytest.raises(RuntimeError, match="404"):
        make(keypair, FakeSession(installed=False), [T0]).token()
