"""NR -- owner 28/10 « reste conforme RFC, n'abaisse pas la securite » : la decision par session cookie se protege du CSRF.

Le cookie de session est SameSite=Lax : il bloque un POST d'un AUTRE site, mais 127.0.0.1:<autre port> est le MEME
site pour un navigateur -- une page servie par n'importe quel service local pourrait poster la decision avec le
cookie de l'owner. Defense : origine exacte (RFC 6454 : schema+hote+port), Fetch Metadata Sec-Fetch-Site
same-origin quand present, Content-Type application/json strict (preflight CORS pour toute autre origine).
Un appelant non navigateur au jeton admin dans Authorization n'est pas concerne.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web_hub import acp_views

PID = "0123456789abcdef0123456789abcdef"
URL = f"/api/acp/permissions/{PID}"


@pytest.fixture
def client(tmp_path, monkeypatch):
    perms = tmp_path / "perms"
    perms.mkdir()
    (perms / f"{PID}.json").write_text(json.dumps({
        "id": PID, "session": "s1", "agent": "claude", "ts": 1.0, "request": {},
        "options": [{"optionId": "allow"}], "etat": "EN_ATTENTE", "decision": None}), encoding="utf-8")
    monkeypatch.setattr(acp_views, "PERMISSIONS_DIR", perms)
    monkeypatch.setattr(acp_views, "_est_admin", lambda request: True)
    import sys
    from pathlib import Path
    tools = str(Path(acp_views.__file__).resolve().parents[2] / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import forge_acp_router as R
    monkeypatch.setattr(R._importer_hub(), "cle_signature", lambda: None)
    monkeypatch.setattr(R, "signer_par_hub", lambda jeton, **k: (lambda payload: "a.b.c"))
    app = FastAPI()
    app.include_router(acp_views.router)
    return TestClient(app)


def _cookie(monkeypatch, oui=True):
    monkeypatch.setattr(acp_views, "_par_cookie", lambda request: oui)


def test_cookie_meme_origine_accepte(client, monkeypatch):
    _cookie(monkeypatch)
    r = client.post(URL, json={"option": "allow"},
                    headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_cookie_autre_port_meme_site_refuse(client, monkeypatch):
    _cookie(monkeypatch)
    r = client.post(URL, json={"option": "allow"}, headers={"Origin": "http://testserver:9999"})
    assert r.status_code == 403


def test_cookie_sans_origin_refuse(client, monkeypatch):
    _cookie(monkeypatch)
    assert client.post(URL, json={"option": "allow"}).status_code == 403


def test_cookie_fetch_metadata_same_site_refuse(client, monkeypatch):
    _cookie(monkeypatch)
    r = client.post(URL, json={"option": "allow"},
                    headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-site"})
    assert r.status_code == 403


def test_content_type_non_json_refuse(client, monkeypatch):
    _cookie(monkeypatch, oui=False)
    r = client.post(URL, content=json.dumps({"option": "allow"}), headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_jeton_en_entete_sans_origin_accepte(client, monkeypatch):
    _cookie(monkeypatch, oui=False)
    assert client.post(URL, json={"option": "allow"}).status_code == 200
