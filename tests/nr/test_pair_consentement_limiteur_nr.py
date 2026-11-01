"""NR 22/10 -- limiteur de POST /consentement (rapport_funnel_protection_20261022, Funnel = Internet).

Contrat : N=3 codes faux pour UNE demande l'INVALIDENT (il faut en reemettre une) ; plafond GLOBAL
d'echecs par fenetre -> 429 (meme avec le bon code) ; le refus ne dit jamais si le code etait « proche » ;
chaque echec est ecrit dans pair_consentement.jsonl (journal existant, JAMAIS le code propose).
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app", ROOT):
    sys.path.insert(0, str(_p))

import forge_bridge_oauth as O  # noqa: E402

CLIENT = types.SimpleNamespace(client_id="chatgpt-x", client_name="ChatGPT")
PARAMS = types.SimpleNamespace(scopes=None, code_challenge="c", redirect_uri="https://x.test/cb",
                               redirect_uri_provided_explicitly=True, resource=None, state="s")
BON = "bon-code-appariement"


@pytest.fixture
def banc(tmp_path, monkeypatch):
    from mcp.server.fastmcp import FastMCP
    from starlette.testclient import TestClient
    monkeypatch.setattr(O, "JOURNAL_CONSENTEMENT", tmp_path / "j.jsonl")
    monkeypatch.setattr(O, "ETAT_DEMANDES", tmp_path / "etat.json")
    monkeypatch.delenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", raising=False)
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH_APPARIEMENT", BON)
    a = O.AutoriteLocale()
    s = FastMCP("t")
    O.poser_consentement(s, a)

    def nouvelle():
        return asyncio.run(a.authorize(CLIENT, PARAMS)).split("demande=")[1]
    return TestClient(s.streamable_http_app(), base_url="http://127.0.0.1:8793",
                      follow_redirects=False), nouvelle, tmp_path


def _post(c, ident, code):
    return c.post("/consentement", data=dict(demande=ident, code=code))


def test_trois_codes_faux_invalident_la_demande_meme_avec_le_bon_code(banc):
    c, nouvelle, _ = banc
    ident = nouvelle()
    reponses = [_post(c, ident, "faux%d" % i) for i in range(3)]
    assert [r.status_code for r in reponses] == [403, 403, 403]
    assert len({r.text for r in reponses}) == 1, "meme refus : aucune indication de proximite"
    assert _post(c, ident, BON).status_code == 404, "demande invalidee : le bon code ne passe plus"
    assert _post(c, nouvelle(), BON).status_code == 302, "une demande reemise reste utilisable"


def test_deux_faux_puis_le_bon_passe(banc):
    c, nouvelle, _ = banc
    ident = nouvelle()
    _post(c, ident, "x1")
    _post(c, ident, "x2")
    assert _post(c, ident, BON).status_code == 302


def test_refus_identique_proche_ou_lointain(banc):
    c, nouvelle, _ = banc
    ident = nouvelle()
    r1 = _post(c, ident, BON[:-1])
    r2 = _post(c, ident, "zzz")
    assert (r1.status_code, r1.text) == (r2.status_code, r2.text)


def test_plafond_global_429_meme_avec_le_bon_code(banc, monkeypatch):
    c, nouvelle, _ = banc
    monkeypatch.setattr(O, "PLAFOND_ECHECS_GLOBAL", 4)
    for _i in range(2):
        ident = nouvelle()
        _post(c, ident, "a")
        _post(c, ident, "b")
    r = _post(c, nouvelle(), BON)
    assert r.status_code == 429
    assert BON not in r.text


def test_echecs_journalises_sans_le_code_propose(banc):
    c, nouvelle, tmp = banc
    ident = nouvelle()
    for i in range(3):
        _post(c, ident, "secretfaux%d" % i)
    brut = (tmp / "j.jsonl").read_text(encoding="utf-8")
    ev = [json.loads(x)["evenement"] for x in brut.splitlines()]
    assert ev.count("code_errone") == 3 and "demande_invalidee" in ev
    assert "secretfaux" not in brut and ident not in brut
