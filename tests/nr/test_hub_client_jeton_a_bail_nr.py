"""NR — le client hub partage presente un jeton A BAIL, resolu par requete.

`forge_hub_client` est le passage oblige de six organes (nokido_core,
forge_services, forge_health_diagnostic, forge_autonomous_loops,
forge_at_dispatch, forge_hub_handlers). Avant le 2026-09-02 il resolvait son
credential UNE FOIS a l'__init__ et le figeait : un credential statique est
permanent, donc ni expirable ni revocable, et un daemon de longue duree ne
pouvait de toute facon pas porter un jeton a bail (1800 s).

Mesures qui fondent ces tests :
  * le ring resolu par le hub est IDENTIQUE par les deux voies (statique et
    bail) pour STATE_ENCODER, SUPERVISOR, CLAUDE_HOOK, OPENAI_PROXY -- la
    bascule ne coute aucun privilege ;
  * la cascade de repli finissait sur `FORGE_MCP_TOKEN`, c'est-a-dire le
    MAITRE, qui peut usurper n'importe quelle identite. Un repli doit se
    NOMMER, sinon il se lit comme un succes et n'est jamais repare.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_agent_credential as fac  # noqa: E402
import forge_hub_client as hc  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    """Un client dont le credential statique est connu et le reseau, jamais touche."""
    monkeypatch.delenv("LAFORGE_HUB_CLIENT_JETON_COURT", raising=False)
    c = hc.HubClient.__new__(hc.HubClient)
    c.agent = "ORGANE_TEST"
    c.token, c.token_src = "statique-permanent", "coffre:FORGE_TOKEN_ORGANE_TEST"
    c._token_explicite = False
    c._src_courante = ""
    return c


def test_un_bail_est_presente_et_nomme(client, monkeypatch):
    monkeypatch.setattr(fac, "jeton_pour", lambda a: "jeton-a-bail-court")
    tok, src = client._jeton_courant()
    assert tok == "jeton-a-bail-court"
    assert src == "bail:ORGANE_TEST", src


def test_le_repli_statique_ne_se_lit_jamais_comme_un_succes(client, monkeypatch):
    """jeton_pour retombe lui-meme sur le statique : il faut que ca SE VOIE."""
    monkeypatch.setattr(fac, "jeton_pour", lambda a: "statique-permanent")
    tok, src = client._jeton_courant()
    assert tok == "statique-permanent"
    assert "repli_statique" in src, src
    assert not src.startswith("bail:")


def test_une_panne_du_pont_est_nommee_pas_avalee(client, monkeypatch):
    def _explose(_a):
        raise RuntimeError("coffre injoignable")

    monkeypatch.setattr(fac, "jeton_pour", _explose)
    tok, src = client._jeton_courant()
    assert tok == "statique-permanent"
    assert "repli:RuntimeError" in src, src


def test_le_desarmement_est_explicite_et_visible(client, monkeypatch):
    """Le durcissement est le DEFAUT ; l'echappatoire doit se declarer."""
    monkeypatch.setenv("LAFORGE_HUB_CLIENT_JETON_COURT", "0")

    def _interdit(_a):
        raise AssertionError("desarme : le pont ne doit pas etre sollicite")

    monkeypatch.setattr(fac, "jeton_pour", _interdit)
    tok, src = client._jeton_courant()
    assert tok == "statique-permanent"
    assert "desarme" in src, src


def test_un_jeton_explicite_n_est_jamais_remplace(client, monkeypatch):
    """Un appelant qui fournit son jeton garde la main (tests, outils, owner)."""
    client._token_explicite = True

    def _interdit(_a):
        raise AssertionError("jeton explicite : le pont ne doit pas etre sollicite")

    monkeypatch.setattr(fac, "jeton_pour", _interdit)
    tok, src = client._jeton_courant()
    assert tok == "statique-permanent"
    assert src == "explicite", src


def test_le_bail_est_resolu_A_CHAQUE_APPEL(client, monkeypatch):
    """GARDE ANTI-REGRESSION : un jeton fige a l'init expire en vol.

    Si quelqu'un remet une resolution unique, ce test tombe -- deux appels
    successifs doivent voir deux valeurs quand le pont en change.
    """
    valeurs = iter(["bail-1", "bail-2"])
    monkeypatch.setattr(fac, "jeton_pour", lambda a: next(valeurs))
    assert client._jeton_courant()[0] == "bail-1"
    assert client._jeton_courant()[0] == "bail-2"


def test_req_ne_presente_pas_le_jeton_fige():
    """GARDE STRUCTUREL : `_req` doit passer par `_jeton_courant`.

    Lecture du CORPS, pas d'une sonde : remettre `self.token` dans l'en-tete
    Authorization desarmerait le renouvellement en silence, sans qu'aucun
    appel n'echoue -- exactement le genre de regression qu'une mesure
    fonctionnelle ne voit pas.
    """
    import inspect

    corps = inspect.getsource(hc.HubClient._req)
    assert "_jeton_courant()" in corps, "le renouvellement a ete court-circuite"
    assert 'Bearer " + self.token' not in corps, "jeton fige remis dans _req"


def test_la_cascade_de_repli_reste_documentee():
    """Le dernier repli est le MAITRE : que ce fait reste ecrit noir sur blanc."""
    import inspect

    corps = inspect.getsource(hc._resoudre_jeton)
    assert "FORGE_MCP_TOKEN" in corps
    assert "maitre" in corps.lower()
