"""NR 28/10 : la cle PUBLIQUE des jobs ACP est publiee en JWK (RFC 7517 / 8037), jamais la privee.

Le worker ACP (compte owner) verifie les jobs signes EdDSA par le hub avec la cle publique epinglee ;
`tools/forge_acp_epingler.py` la lit sur `/.well-known/acp-jwks.json`. La route ne doit rendre que
`{kty, crv, alg, use, kid, x}` : la composante privee `d` n'y apparait jamais, et sans cle lisible on rend
une liste VIDE (pas une erreur qui ferait croire a une cle).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")

import forge_acp_hub as H  # noqa: E402


def _cle(monkeypatch, valeur):
    class _J:
        @staticmethod
        def _cle_ed25519():
            return valeur
    monkeypatch.setattr(H, "_importer_jwt", lambda: _J)


def test_jwks_rend_la_publique_seule(monkeypatch):
    priv = ed.Ed25519PrivateKey.generate()
    _cle(monkeypatch, (priv, priv.public_key(), "kid-test"))
    doc = H.jwks()
    assert [set(k) for k in doc["keys"]] == [{"kty", "crv", "alg", "use", "kid", "x"}]
    k = doc["keys"][0]
    assert (k["kty"], k["crv"], k["alg"], k["use"], k["kid"]) == ("OKP", "Ed25519", "EdDSA", "sig", "kid-test")
    assert "d" not in k and len(k["x"]) == 43     # 32 octets en base64url sans remplissage


def test_jwks_sans_cle_rend_une_liste_vide(monkeypatch):
    _cle(monkeypatch, None)
    assert H.jwks() == {"keys": []}
