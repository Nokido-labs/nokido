"""NR 3/11 — E5 : le 401 de /mcp porte le defi de decouverte OAuth (RFC 9728 §5.1, RFC 6750 §3) quand c'est arme.

C'est par ce defi qu'un client MCP (VS Code...) decouvre SEUL l'autorite : sans lui, il ne lance jamais OAuth.
Eteint : aucun en-tete ajoute (hub inchange). Sans jeton presente : pas de code d'erreur (RFC 6750 §3.1) ;
jeton refuse : error="invalid_token".
"""
from pathlib import Path

from app import forge_oauth_http as H

ISS = "http://127.0.0.1:8766"
SRC = (Path(__file__).resolve().parents[2] / "tools" / "nokido_hub.py").read_text(encoding="utf-8")


def test_eteint_aucun_en_tete(monkeypatch):
    monkeypatch.delenv("NOKIDO_OAUTH_CLIENTS", raising=False)
    assert H.entetes_defi_401(ISS, auth_presente=True) == {}


def test_arme_sans_jeton(monkeypatch):
    monkeypatch.setenv("NOKIDO_OAUTH_CLIENTS", "1")
    d = H.entetes_defi_401(ISS, auth_presente=False)["WWW-Authenticate"]
    assert d.startswith("Bearer ") and "error=" not in d
    assert 'resource_metadata="%s/.well-known/oauth-protected-resource/mcp"' % ISS in d


def test_arme_jeton_refuse(monkeypatch):
    monkeypatch.setenv("NOKIDO_OAUTH_CLIENTS", "1")
    assert 'error="invalid_token"' in H.entetes_defi_401(ISS, auth_presente=True)["WWW-Authenticate"]


def test_mcp_post_pose_le_defi_dans_son_401():
    debut = SRC.find("async def mcp_post(")
    bloc = SRC[debut:SRC.find('return JSONResponse({"error": "Unauthorized"}, status_code=401', debut) + 200]
    assert "import entetes_defi_401 as _defi" in bloc and "_defi(" in bloc   # import puis appel (alias)
    assert 'status_code=401, headers=' in bloc
