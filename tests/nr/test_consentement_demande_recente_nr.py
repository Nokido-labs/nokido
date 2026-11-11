"""NR 07/11 -- consentement : le POST accorde EXACTEMENT la demande recue + texte veridique de la page.

RETRAIT d'un correctif mesure 07/11 : `AutoriteLocale.demande_la_plus_recente`
remplacait la demande recue par celle du MEME client dont l'expiration est la
plus tardive. Son hypothese (chat-ui lance deux flux pour un clic et n'utilise
que le dernier) n'a rien regle : la vraie cause etait l'iframe de
huggingface.co/spaces, dans une autre session. Le remplacement detournait meme
le contrat : le POST portant sur la PREMIERE demande accordait la seconde.
CONTRAT : apres la seule verification du code d'appariement, le POST accorde
exactement la demande recue ; les autres demandes du memes client restent en
attente ; code faux = 403 et aucune demande consommee.

DEFAUT 2 MESURE : PAGE annoncait toujours « lecture seule, par les cinq
operations... aucune ecriture n'existe » alors qu'un pair de `outils_par_pair`
(ex. huggingchat) depose des taches en quarantaine. CONTRAT : la page affiche
le client_name (echappe) et la liste reelle des outils permis ; pair sans liste
restreinte : texte historique inchange ; politique illisible : « perimetre
illisible », jamais « lecture seule ».
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app", ROOT):
    sys.path.insert(0, str(_p))

import forge_bridge_oauth as O  # noqa: E402

BON = "bon-code-appariement"


def _client(cid, nom=None):
    return types.SimpleNamespace(client_id=cid, client_name=nom)


def _params(state):
    return types.SimpleNamespace(scopes=None, code_challenge="c",
                                 redirect_uri="https://x.test/cb",
                                 redirect_uri_provided_explicitly=True,
                                 resource=None, state=state)


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

    def nouvelle(client, state):
        url = asyncio.run(a.authorize(client, _params(state)))
        return url.split("demande=")[1]
    return (TestClient(s.streamable_http_app(), base_url="http://127.0.0.1:8793",
                       follow_redirects=False), a, nouvelle, tmp_path)


def _state_du_retour(reponse):
    q = parse_qs(urlparse(reponse.headers["location"]).query)
    return (q.get("state") or [None])[0]


def test_deux_demandes_meme_client_le_post_accorde_exactement_la_demande_recue(banc):
    c, a, nouvelle, tmp = banc
    chat = _client("chat-ui-1", "ChatUI")
    id1 = nouvelle(chat, "premier")
    id2 = nouvelle(chat, "second")
    r = c.post("/consentement", data=dict(demande=id1, code=BON))
    assert r.status_code == 302
    assert _state_du_retour(r) == "premier", "le POST accorde exactement la demande recue"
    assert a.demande(id2) is not None, "la seconde reste en attente"
    journal = (tmp / "j.jsonl").read_text(encoding="utf-8")
    assert "demande_remplacee" not in journal
    assert id1 not in journal and id2 not in journal, "jamais l'identifiant complet"


def test_code_faux_403_et_aucune_demande_consommee(banc):
    c, a, nouvelle, _ = banc
    id1 = nouvelle(_client("chat-ui-1", "ChatUI"), "premier")
    id2 = nouvelle(_client("chat-ui-1", "ChatUI"), "second")
    r = c.post("/consentement", data=dict(demande=id1, code="faux-code"))
    assert r.status_code == 403
    assert a.demande(id1) is not None and a.demande(id2) is not None, "aucune demande n'est consommee"
    r2 = c.post("/consentement", data=dict(demande=id2, code=BON))
    assert r2.status_code == 302


def test_page_huggingchat_liste_reelle_sans_mentir(banc):
    c, a, nouvelle, _ = banc
    hf = _client("hf-1", "HuggingChat – desktop-xxxx.tailXXXX.ts.net")
    ident = nouvelle(hf, "s")
    r = c.get("/consentement", params=dict(demande=ident))
    assert r.status_code == 200
    assert "soumettre_tache" in r.text and "lire_reponses" in r.text
    assert "lecture seule" not in r.text, "un depot de taches n'est pas en lecture seule"
    assert hf.client_name in r.text


def test_page_nom_de_client_html_echappe(banc):
    c, a, nouvelle, _ = banc
    mechant = "<script>alert(1)</script>"
    ident = nouvelle(_client("x-1", mechant), "s")
    r = c.get("/consentement", params=dict(demande=ident))
    assert r.status_code == 200
    assert "<script>" not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text


def test_page_politique_illisible_dit_perimetre_illisible(banc, monkeypatch):
    c, a, nouvelle, _ = banc
    monkeypatch.setattr(O, "_outils_du_pair", lambda nom: ("illisible", ()))
    ident = nouvelle(_client("hf-1", "HuggingChat"), "s")
    r = c.get("/consentement", params=dict(demande=ident))
    assert r.status_code == 200
    assert "perimetre illisible" in r.text
    assert "lecture seule" not in r.text
