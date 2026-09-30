"""
tests/nr/test_hub_jti_revoke.py - NR revocation jti (anti-replay).

Resout le trou Gemini #2 : un token reste valide jusqu'a exp meme
apres logout. Ce module verifie que :

  - revoke_jti enregistre
  - is_jti_revoked detecte
  - verify_token refuse un token dont le jti est revoque
  - logout HTTP revoque effectivement : meme token refuse apres
  - purge auto des jti expires
  - thread-safety basique
  - limite memoire respectee (fail-closed au plafond)
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# -------------------------------------------------------------------
# Fixtures : cache propre + client auth
# -------------------------------------------------------------------
@pytest.fixture
def admin_token():
    return "super-secret-admin-token-jti"


@pytest.fixture
def fresh_cache():
    """Cache jti vide et isole pour chaque test."""
    # Reimport propre pour repartir de zero
    for m in list(sys.modules):
        if m.startswith("app.web_hub.jti_cache"):
            del sys.modules[m]
    from app.web_hub.jti_cache import revocation_cache
    revocation_cache.clear()
    yield revocation_cache
    revocation_cache.clear()


@pytest.fixture
def client_auth_on(monkeypatch, admin_token):
    """Client HTTP avec auth ON, et jti cache reset."""
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    monkeypatch.setenv("LAFORGE_JWT_TTL", "3600")
    monkeypatch.delenv("LAFORGE_JWT_SECRET", raising=False)
    # Force reimport complet de app.web_hub pour recreer AUTH_CFG
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    from app.web_hub.auth import login_rate_limiter
    from app.web_hub.jti_cache import revocation_cache
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    revocation_cache.clear()
    return TestClient(app)


# -------------------------------------------------------------------
# Unit : cache standalone
# -------------------------------------------------------------------
class TestCacheUnit:
    def test_revoke_then_is_revoked(self, fresh_cache):
        future = time.time() + 60
        assert fresh_cache.revoke("abc123", future) is True
        assert fresh_cache.is_revoked("abc123") is True

    def test_unknown_jti_not_revoked(self, fresh_cache):
        assert fresh_cache.is_revoked("never-added") is False

    def test_empty_jti_never_revoked(self, fresh_cache):
        assert fresh_cache.is_revoked("") is False
        assert fresh_cache.is_revoked(None) is False  # type: ignore[arg-type]

    def test_revoke_empty_jti_noop(self, fresh_cache):
        assert fresh_cache.revoke("", time.time() + 60) is False

    def test_already_expired_is_noop(self, fresh_cache):
        past = time.time() - 10
        # Deja expire : la methode retourne True (considere revoque de facto)
        # mais ne stocke rien.
        fresh_cache.revoke("past-jti", past)
        assert fresh_cache.is_revoked("past-jti") is False
        assert fresh_cache.size() == 0

    def test_expired_entry_purged_on_check(self, fresh_cache):
        # On insere avec exp tres proche
        fresh_cache.revoke("short-lived", time.time() + 0.05)
        assert fresh_cache.is_revoked("short-lived") is True
        time.sleep(0.15)
        # Apres expiration, check doit retourner False ET purger
        assert fresh_cache.is_revoked("short-lived") is False

    def test_sweep_purges_multiple(self, fresh_cache):
        now = time.time()
        fresh_cache.revoke("keep1", now + 60)
        fresh_cache.revoke("keep2", now + 60)
        fresh_cache.revoke("gone1", now + 0.05)
        fresh_cache.revoke("gone2", now + 0.05)
        time.sleep(0.15)
        purged = fresh_cache.sweep()
        assert purged == 2
        assert fresh_cache.size() == 2

    def test_clear_empties_everything(self, fresh_cache):
        fresh_cache.revoke("a", time.time() + 60)
        fresh_cache.revoke("b", time.time() + 60)
        fresh_cache.clear()
        assert fresh_cache.size() == 0

    def test_thread_safety_concurrent_revoke(self, fresh_cache):
        """10 threads x 100 revocations uniques : tout doit passer sans race."""
        def worker(start: int) -> None:
            for i in range(100):
                fresh_cache.revoke(f"t{start}-{i}", time.time() + 60)
        threads = [threading.Thread(target=worker, args=(k,)) for k in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 1000 jti uniques au total
        assert fresh_cache.size() == 1000

    def test_max_entries_fails_closed(self, fresh_cache):
        """Au plafond, revoke refuse (mieux que OOM)."""
        from app.web_hub.jti_cache import JtiRevocationCache
        small = JtiRevocationCache(max_entries=5)
        for i in range(5):
            assert small.revoke(f"j{i}", time.time() + 60) is True
        # 6eme est refuse
        assert small.revoke("overflow", time.time() + 60) is False


# -------------------------------------------------------------------
# Integration : verify_token consulte le cache
# -------------------------------------------------------------------
class TestVerifyTokenWithRevocation:
    def _setup(self, monkeypatch, admin_token):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, issue_token, verify_token
        from app.web_hub.jti_cache import revocation_cache, revoke_jti
        revocation_cache.clear()
        cfg = AuthConfig.from_env()
        return cfg, issue_token, verify_token, revoke_jti, revocation_cache

    def test_fresh_token_accepted(self, monkeypatch, admin_token):
        cfg, issue, verify, _, _ = self._setup(monkeypatch, admin_token)
        tok = issue(cfg, subject="admin")
        assert verify(cfg, tok) is not None

    def test_revoked_token_refused(self, monkeypatch, admin_token):
        cfg, issue, verify, revoke, _ = self._setup(monkeypatch, admin_token)
        tok = issue(cfg, subject="admin")
        payload = verify(cfg, tok)
        assert payload is not None
        # Revoque par son jti
        assert revoke(payload["jti"], float(payload["exp"])) is True
        # Meme token : rejet
        assert verify(cfg, tok) is None

    def test_only_that_jti_refused(self, monkeypatch, admin_token):
        """Revoquer un jti ne tue pas les autres tokens."""
        cfg, issue, verify, revoke, _ = self._setup(monkeypatch, admin_token)
        tok_a = issue(cfg, subject="admin")
        tok_b = issue(cfg, subject="admin")
        payload_a = verify(cfg, tok_a)
        assert payload_a is not None
        revoke(payload_a["jti"], float(payload_a["exp"]))
        assert verify(cfg, tok_a) is None
        # tok_b a un jti different, doit rester valide
        assert verify(cfg, tok_b) is not None


# -------------------------------------------------------------------
# E2E HTTP : /auth/logout revoque effectivement
# -------------------------------------------------------------------
class TestLogoutRevokesToken:
    def test_logout_then_bearer_refused(self, client_auth_on, admin_token):
        """Flux complet : login, capture token, logout, reessai Bearer -> 401."""
        r = client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        assert r.status_code == 200
        token = r.json()["token"]
        # Token marche avant logout
        r1 = client_auth_on.get("/status",
                                headers={"Authorization": f"Bearer {token}"})
        assert r1.status_code == 200
        # Logout (utilise le cookie session pose par login)
        r2 = client_auth_on.post("/auth/logout")
        assert r2.status_code == 200
        # Reessai avec le MEME token en Bearer : doit etre refuse
        client_auth_on.cookies.clear()
        r3 = client_auth_on.get("/status",
                                headers={"Authorization": f"Bearer {token}"})
        assert r3.status_code == 401

    def test_double_logout_idempotent(self, client_auth_on, admin_token):
        client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        r1 = client_auth_on.post("/auth/logout")
        assert r1.status_code == 200
        # Deuxieme logout sans cookie : pas d'erreur, juste ok
        r2 = client_auth_on.post("/auth/logout")
        assert r2.status_code == 200

    def test_logout_without_token_safe(self, client_auth_on):
        """Logout sans session : ne crash pas, ne revoque rien."""
        r = client_auth_on.post("/auth/logout")
        assert r.status_code == 200
        from app.web_hub.jti_cache import revocation_cache
        assert revocation_cache.size() == 0

    def test_new_login_after_logout_fresh_jti(self, client_auth_on, admin_token):
        """Apres logout, relogin emet un NOUVEAU jti non revoque."""
        # 1er login
        r1 = client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        t1 = r1.json()["token"]
        # logout
        client_auth_on.post("/auth/logout")
        # 2e login
        r2 = client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        assert r2.status_code == 200
        t2 = r2.json()["token"]
        # t1 doit etre refuse, t2 accepte
        assert t1 != t2
        client_auth_on.cookies.clear()
        r_old = client_auth_on.get("/status",
                                   headers={"Authorization": f"Bearer {t1}"})
        assert r_old.status_code == 401
        r_new = client_auth_on.get("/status",
                                   headers={"Authorization": f"Bearer {t2}"})
        assert r_new.status_code == 200


# -------------------------------------------------------------------
# Regression : pas d'impact sur les tokens legacy sans jti
# -------------------------------------------------------------------
class TestBackwardCompat:
    def test_token_without_jti_still_accepted(self, monkeypatch, admin_token):
        """Legacy : si un token n'a pas de jti, il passe quand meme
        (decouple du mecanisme de revocation)."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, verify_token
        import jwt as _jwt
        cfg = AuthConfig.from_env()
        now = int(time.time())
        # Token sans jti
        tok = _jwt.encode(
            {"sub": "admin", "iat": now, "nbf": now, "exp": now + 60},
            cfg.jwt_secret, algorithm="HS256",
        )
        assert verify_token(cfg, tok) is not None
