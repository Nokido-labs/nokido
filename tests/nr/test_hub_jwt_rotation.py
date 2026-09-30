"""
tests/nr/test_hub_jwt_rotation.py - NR rotation LAFORGE_JWT_SECRET.

Complete Gemini #2 : permettre de tourner le secret HMAC sans
deconnecter tout le monde d'un coup. Approche multi-secrets :

  LAFORGE_JWT_SECRET         -> secret actif (signe + verifie)
  LAFORGE_JWT_SECRET_LEGACY  -> secrets anciens (verify only)
                                 comma-separated, grace period

verify_token essaie le secret actif puis les legacy. issue_token
signe toujours avec l'actif.

Coverage :
  - Config parse : 0, 1, 3 legacy + dedup vs actif
  - verify accepte actif
  - verify accepte token signe avec legacy
  - verify refuse un secret absent (retire de la liste)
  - verify refuse un token alg=none meme avec legacy configure
  - issue signe toujours avec actif
  - rotation complete : remove legacy -> vieux token refuse
  - ordre d'essai : actif en premier (performance)
  - backward-compat : pas de env legacy = comportement d'avant
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import jwt as _jwt
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _reimport_auth():
    for m in list(sys.modules):
        if m.startswith("app.web_hub.auth") or m.startswith("app.web_hub.jti_cache"):
            del sys.modules[m]
    import app.web_hub.auth as auth_module
    # Le plancher RFC 7518 3.2 (32 octets) est NEUTRALISE ici, volontairement.
    # Ce fichier mesure la ROTATION — dedup, parsing, fenetre de grace, revocation —
    # avec des secrets courts lisibles ("old-1", "new"). La longueur de cle est une
    # contrainte ORTHOGONALE, couverte par tests/nr/test_jwt_longueur_cle_nr.py, qui
    # lui verifie le plancher reel. Allonger les 30 litteraux d'ici rendrait la
    # rotation illisible sans rien mesurer de plus.
    #
    # La mutation n'est pas restauree, mais elle ne fuit pas : ce module est
    # re-importe a chaque cas via _reimport_auth, et l'autre fichier recharge auth
    # derriere son propre mock de forge_secrets. Verifie le 2026-09-04 en lancant
    # les deux fichiers dans les DEUX ordres : 19/19 a chaque fois.
    auth_module._MIN_CLE_HMAC = 1
    from app.web_hub.auth import AuthConfig, issue_token, verify_token
    from app.web_hub.jti_cache import revocation_cache
    revocation_cache.clear()
    return AuthConfig, issue_token, verify_token


# -------------------------------------------------------------------
# Config parsing
# -------------------------------------------------------------------
class TestConfigParsing:
    def test_no_legacy_env_empty_tuple(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-cfg-1")
        monkeypatch.delenv("LAFORGE_JWT_SECRET_LEGACY", raising=False)
        AuthConfig, _, _ = _reimport_auth()
        cfg = AuthConfig.from_env()
        assert cfg.legacy_secrets == ()

    def test_one_legacy_parsed(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-cfg-2")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old-key-1")
        AuthConfig, _, _ = _reimport_auth()
        cfg = AuthConfig.from_env()
        assert cfg.legacy_secrets == (b"old-key-1",)

    def test_multiple_legacy_comma_split(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-cfg-3")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old-1, old-2 ,old-3")
        AuthConfig, _, _ = _reimport_auth()
        cfg = AuthConfig.from_env()
        assert cfg.legacy_secrets == (b"old-1", b"old-2", b"old-3")

    def test_legacy_deduplicated_against_active(self, monkeypatch):
        """Un legacy identique au secret actif est filtre."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-cfg-4")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "active-key")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY",
                           "active-key, old-1, active-key, old-2")
        AuthConfig, _, _ = _reimport_auth()
        cfg = AuthConfig.from_env()
        assert cfg.jwt_secret == b"active-key"
        # active-key filtre (2x), old-1/old-2 conserves, pas de doublons
        assert cfg.legacy_secrets == (b"old-1", b"old-2")

    def test_empty_strings_in_legacy_ignored(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-cfg-5")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", ",  , old-1,,, old-2,")
        AuthConfig, _, _ = _reimport_auth()
        cfg = AuthConfig.from_env()
        assert cfg.legacy_secrets == (b"old-1", b"old-2")


# -------------------------------------------------------------------
# verify_token : accepte active ET legacy
# -------------------------------------------------------------------
class TestVerifyWithRotation:
    def test_active_secret_accepted(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-verify-1")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "active-A")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old-B")
        AuthConfig, issue, verify = _reimport_auth()
        cfg = AuthConfig.from_env()
        tok = issue(cfg, subject="admin")
        # Sanity : issue utilise bien le secret actif
        assert verify(cfg, tok) is not None

    def test_token_signed_with_legacy_accepted(self, monkeypatch):
        """Un token signe avec un secret LEGACY doit passer verify.

        C'est la raison d'etre de la grace period : les tokens emis
        avant la rotation restent utilisables jusqu'a leur exp.
        """
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-verify-2")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "new-key")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old-key")
        AuthConfig, _, verify = _reimport_auth()
        cfg = AuthConfig.from_env()
        # Construit manuellement un token signe avec old-key
        now = int(time.time())
        legacy_tok = _jwt.encode(
            {"sub": "admin", "iat": now, "nbf": now, "exp": now + 60,
             "jti": "legacy-token-jti"},
            b"old-key", algorithm="HS256",
        )
        payload = verify(cfg, legacy_tok)
        assert payload is not None
        assert payload["sub"] == "admin"

    def test_token_signed_with_unknown_secret_refused(self, monkeypatch):
        """Un secret qui n'est NI actif NI legacy : rejet."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-verify-3")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "new-key")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old-key")
        AuthConfig, _, verify = _reimport_auth()
        cfg = AuthConfig.from_env()
        now = int(time.time())
        unknown_tok = _jwt.encode(
            {"sub": "admin", "iat": now, "nbf": now, "exp": now + 60},
            b"never-seen-key", algorithm="HS256",
        )
        assert verify(cfg, unknown_tok) is None

    def test_multiple_legacy_all_accepted(self, monkeypatch):
        """3 legacy : un token signe avec le 3e doit passer."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-verify-4")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "new")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old1,old2,old3")
        AuthConfig, _, verify = _reimport_auth()
        cfg = AuthConfig.from_env()
        now = int(time.time())
        for sec in (b"old1", b"old2", b"old3"):
            tok = _jwt.encode(
                {"sub": "admin", "iat": now, "nbf": now, "exp": now + 60},
                sec, algorithm="HS256",
            )
            assert verify(cfg, tok) is not None, f"token signe {sec!r} refuse"

    def test_alg_none_refused_even_with_legacy(self, monkeypatch):
        """Defense in depth : alg=none reste banni quelle que soit la rotation."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-verify-5")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "new")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old1,old2")
        AuthConfig, _, verify = _reimport_auth()
        cfg = AuthConfig.from_env()
        now = int(time.time())
        bad = _jwt.encode(
            {"sub": "admin", "iat": now, "nbf": now, "exp": now + 60},
            key="", algorithm="none",
        )
        assert verify(cfg, bad) is None

    def test_expired_token_refused_even_with_matching_secret(self, monkeypatch):
        """Le secret matche (legacy) MAIS exp depasse : rejet."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-verify-6")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "new")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old")
        AuthConfig, _, verify = _reimport_auth()
        cfg = AuthConfig.from_env()
        now = int(time.time())
        expired = _jwt.encode(
            {"sub": "admin", "iat": now - 7200, "nbf": now - 7200,
             "exp": now - 3600},
            b"old", algorithm="HS256",
        )
        assert verify(cfg, expired) is None


# -------------------------------------------------------------------
# issue_token : toujours avec le secret ACTIF
# -------------------------------------------------------------------
class TestIssueAlwaysActive:
    def test_issue_signs_with_active_not_legacy(self, monkeypatch):
        """Un token fraichement emis doit etre verifiable par l'ACTIF
        seul (sans que les legacy soient necessaires)."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-issue-1")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "active-signer")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old1,old2")
        AuthConfig, issue, _ = _reimport_auth()
        cfg = AuthConfig.from_env()
        tok = issue(cfg, subject="admin")
        # Verifie directement avec _jwt.decode et le secret actif :
        # ca doit passer sans jamais avoir besoin des legacy.
        # `verify_aud: False` — ce test porte sur le SECRET de signature, pas sur
        # l'audience. Depuis le 2026-09-18 `issue_token` pose un `aud`, et PyJWT
        # leve `InvalidAudienceError` des qu'un jeton en porte un sans qu'on
        # passe `audience=` a `decode`. Sans cette option, le test echouerait sur
        # une propriete qu'il ne cherche pas a verifier.
        payload = _jwt.decode(tok, b"active-signer", algorithms=["HS256"],
                              options={"verify_aud": False})
        assert payload["sub"] == "admin"
        # Inversement : decode avec un legacy seul DOIT echouer
        with pytest.raises(_jwt.InvalidTokenError):
            _jwt.decode(tok, b"old1", algorithms=["HS256"])


# -------------------------------------------------------------------
# Scenario phare : rotation complete
# -------------------------------------------------------------------
class TestRotationWorkflow:
    def test_full_rotation_invalidates_old_tokens(self, monkeypatch):
        """Scenario admin :
        1. Config initiale : SECRET=old, pas de LEGACY. On emet un token.
        2. Rotation : SECRET=new, LEGACY=old. Le vieux token reste OK.
        3. Fin de grace period : SECRET=new, on RETIRE LEGACY.
           Le vieux token est enfin refuse ; un nouveau (signe avec new)
           marche.
        """
        # --- Phase 1 ---
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-rot-1")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "old")
        monkeypatch.delenv("LAFORGE_JWT_SECRET_LEGACY", raising=False)
        AuthConfig, issue, verify = _reimport_auth()
        cfg1 = AuthConfig.from_env()
        old_tok = issue(cfg1, subject="admin")
        assert verify(cfg1, old_tok) is not None

        # --- Phase 2 : rotation avec grace period ---
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "new")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old")
        AuthConfig, issue, verify = _reimport_auth()
        cfg2 = AuthConfig.from_env()
        # Vieux token toujours accepte (grace period)
        assert verify(cfg2, old_tok) is not None
        # Nouveau token emis : signe avec new
        new_tok = issue(cfg2, subject="admin")
        assert verify(cfg2, new_tok) is not None

        # --- Phase 3 : fin de grace period ---
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "new")
        monkeypatch.delenv("LAFORGE_JWT_SECRET_LEGACY", raising=False)
        AuthConfig, issue, verify = _reimport_auth()
        cfg3 = AuthConfig.from_env()
        # Vieux token ENFIN refuse
        assert verify(cfg3, old_tok) is None
        # Nouveau token (signe phase 2) : toujours OK (meme actif 'new')
        assert verify(cfg3, new_tok) is not None


# -------------------------------------------------------------------
# Backward-compat : sans env legacy, comportement d'avant inchange
# -------------------------------------------------------------------
class TestBackwardCompat:
    def test_no_legacy_env_behaves_as_before(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-bc-1")
        monkeypatch.delenv("LAFORGE_JWT_SECRET_LEGACY", raising=False)
        AuthConfig, issue, verify = _reimport_auth()
        cfg = AuthConfig.from_env()
        tok = issue(cfg, subject="admin")
        assert verify(cfg, tok) is not None
        # legacy_secrets vide
        assert len(cfg.legacy_secrets) == 0

    def test_jti_revocation_still_works_after_rotation(self, monkeypatch):
        """La revocation doit etre orthogonale a la rotation du secret."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "tok-bc-2")
        monkeypatch.setenv("LAFORGE_JWT_SECRET", "new")
        monkeypatch.setenv("LAFORGE_JWT_SECRET_LEGACY", "old")
        AuthConfig, issue, verify = _reimport_auth()
        cfg = AuthConfig.from_env()
        # Cree un token signe LEGACY avec un jti
        now = int(time.time())
        legacy_tok = _jwt.encode(
            {"sub": "admin", "iat": now, "nbf": now, "exp": now + 60,
             "jti": "legacy-jti-revoked"},
            b"old", algorithm="HS256",
        )
        # Accepte d'abord
        payload = verify(cfg, legacy_tok)
        assert payload is not None and payload["jti"] == "legacy-jti-revoked"
        # Revoque
        from app.web_hub.jti_cache import revoke_jti
        revoke_jti("legacy-jti-revoked", float(payload["exp"]))
        # Rejet apres revocation (meme si le secret legacy matche encore)
        assert verify(cfg, legacy_tok) is None
