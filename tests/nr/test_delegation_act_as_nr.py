"""NR -- delegation explicite « act-as » du videur (esprit RFC 8693).

PROBLEME RESOLU, 2026-09-02. La passerelle OpenAI-compatible (:7777) relaie des
clients reels et doit conserver LEUR identite cote hub. Pour y parvenir, elle
portait le jeton MAITRE -- le seul qui conserve l'agent declare et son ring.
C'est le CONFUSED DEPUTY : toute requete atteignant :7777 choisissait son
identite ET heritait du ring correspondant, administration comprise. Le port
est local, mais « local » n'est pas « de confiance ».

Le privilege de deleguer est desormais CONFINE dans le videur -- la source de
verite -- au lieu d'etre eparpille sous forme de jetons maitres en peripherie.
La passerelle prouve SA propre identite ; le registre lui accorde le droit BORNE
de declarer un autre nom.

Ce que ces tests verrouillent, et chaque point a ete mesure avant d'etre ecrit :
1. la delegation FONCTIONNE (sans quoi les clients tombent au plancher) ;
2. elle est BORNEE -- eprouvee en injectant une identite ring 0, ramenee a 1 ;
3. elle n'est PAS accordee a qui n'a pas la regle au registre ;
4. elle se VOIT dans la trace (`via=delegated:<qui>`), sans quoi on rouvrirait
   l'angle mort qu'on vient de fermer ;
5. elle est STRICTEMENT moins puissante que l'authentification directe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_videur as V  # noqa: E402

REGISTRE = ROOT / "config" / "agent_identities.json"
FAUX_PROXY = "jeton-derive-de-la-passerelle-pour-test"
FAUX_AUTRE = "jeton-derive-d-un-agent-sans-droit-de-delegation"
FAUX_MASTER = "jeton-maitre-pour-test"


@pytest.fixture
def toks():
    return {"OPENAI_PROXY": FAUX_PROXY, "STATE_ENCODER": FAUX_AUTRE}


def _r(nom, tok, toks):
    return V.resolve_identity(nom, tok, local=True, agent_tokens=toks,
                              hub_token=FAUX_MASTER)


# --------------------------------------------------------------------------- #
# 1. La delegation fonctionne
# --------------------------------------------------------------------------- #

def test_le_delegateur_peut_declarer_un_autre_agent(toks):
    r = _r("CLAUDE", FAUX_PROXY, toks)
    assert r["agent"] == "CLAUDE"
    assert r["via"] == "delegated:OPENAI_PROXY"


def test_le_client_delegue_garde_son_ring(toks):
    """Sans ca, tous les clients de la passerelle tombent au plancher et la
    fonction est perdue -- c'est ce qui rendait le jeton maitre necessaire."""
    r = _r("CLAUDE", FAUX_PROXY, toks)
    assert r["ring"] <= 3, r["ring"]


# --------------------------------------------------------------------------- #
# 2. Elle est BORNEE -- le coeur du dispositif
# --------------------------------------------------------------------------- #

def test_la_delegation_n_atteint_jamais_le_ring_zero(toks):
    """Eprouve en INJECTANT une identite ring 0 : sans cette injection le garde
    ne se declencherait jamais (aucun agent n'est ring 0 aujourd'hui) et on
    aurait une protection non eprouvee -- une dette, pas une securite."""
    V._SEED_RING["AGENT_ROOT_FICTIF"] = 0
    try:
        r = _r("AGENT_ROOT_FICTIF", FAUX_PROXY, toks)
        assert r["ring"] >= 1, "la delegation a atteint le ring d'administration"
        assert r["via"] == "delegated:OPENAI_PROXY"
    finally:
        V._SEED_RING.pop("AGENT_ROOT_FICTIF", None)


# --------------------------------------------------------------------------- #
# PERSPECTIVE EDGE : ce qui vaut sur loopback ne vaut pas a travers un reseau
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# CONFORMITE RFC 8693 : delegation != impersonation
# --------------------------------------------------------------------------- #

def test_l_acteur_est_structurellement_present(toks):
    """RFC 8693, lue a la source (RFC en base) : « principal A still has its
    own identity separate from B [...] any actions taken are being taken by A
    representing B », porte par le claim `act`.

    Nous faisions de l'IMPERSONATION en l'appelant delegation : `agent` valait
    B et l'identite de A ne survivait que dans `via`, un champ de TRACE
    qu'aucun consommateur n'inspecte pour decider.
    """
    r = V.resolve_identity("CLAUDE", FAUX_PROXY, local=True,
                           agent_tokens=toks, hub_token=FAUX_MASTER)
    assert r.get("sujet") == "CLAUDE", "le sujet (B) doit rester nomme"
    assert r.get("acteur") == "OPENAI_PROXY", "l'acteur (A) doit etre expose"


def test_pas_d_acteur_sur_une_authentification_directe(toks):
    """Un appel direct n'est pas une delegation : y poser un acteur ferait
    croire a une chaine qui n'existe pas."""
    r = V.resolve_identity("CLAUDE", "jeton-de-claude", local=True,
                           agent_tokens={"CLAUDE": "jeton-de-claude"},
                           hub_token=FAUX_MASTER)
    assert "acteur" not in r


def test_l_acteur_survit_meme_si_le_via_change(toks):
    """L'identite de l'acteur ne doit pas dependre du parsing d'une chaine :
    `via` est de la trace, `acteur` est de la donnee."""
    r = V.resolve_identity("CLAUDE", FAUX_PROXY, local=True,
                           agent_tokens=toks, hub_token=FAUX_MASTER)
    assert r["acteur"] == r["via"].split(":", 1)[1]
    assert isinstance(r["acteur"], str) and r["acteur"]


def test_la_delegation_est_refusee_hors_local(toks):
    """Mesure du 2026-09-02 : `local=True` et `local=False` rendaient exactement
    le meme resultat -- une passerelle joignable de l'exterieur aurait delegue
    depuis n'importe ou. Ce qui est acceptable entre deux processus d'une meme
    machine ne l'est pas a travers un reseau."""
    r = V.resolve_identity("CLAUDE", FAUX_PROXY, local=False,
                           agent_tokens=toks, hub_token=FAUX_MASTER)
    assert r["via"] == "delegation_refusee_hors_local"


def test_le_refus_hors_local_ramene_au_plancher(toks):
    """Refuser la delegation tout en accordant le ring de l'agent DECLARE
    serait pire que ne rien faire. L'anti-spoof ne plafonne que `via ==
    header` : un `via` explicite laissait donc passer le privilege -- defaut
    trouve par mesure dans le tour meme ou la borne a ete ecrite."""
    r = V.resolve_identity("CLAUDE", FAUX_PROXY, local=False,
                           agent_tokens=toks, hub_token=FAUX_MASTER)
    assert r["ring"] == V._HEADER_FLOOR_RING


def test_l_authentification_directe_distante_reste_intacte(toks):
    """Contre-epreuve : la borne ne doit toucher QUE la delegation. Un agent
    qui prouve son identite depuis une autre machine garde son ring."""
    r = V.resolve_identity("CLAUDE", "jeton-de-claude", local=False,
                           agent_tokens={"CLAUDE": "jeton-de-claude"},
                           hub_token=FAUX_MASTER)
    assert r["via"] == "token" and r["ring"] <= 3


def test_l_ouverture_hors_local_se_declare_au_registre(toks, monkeypatch):
    """L'edge n'est pas interdit -- il est DECIDE. `hors_local` au registre
    ouvre la delegation a distance, explicitement et par agent."""
    monkeypatch.setattr(V, "_delegation_de",
                        lambda n: {"ring_min_delegue": 1, "hors_local": True})
    r = V.resolve_identity("CLAUDE", FAUX_PROXY, local=False,
                           agent_tokens=toks, hub_token=FAUX_MASTER)
    assert r["via"] == "delegated:OPENAI_PROXY"
    assert r["ring"] >= 1, "la borne s'applique aussi hors local"


def test_la_borne_survit_a_toute_elevation_ulterieure():
    """Revue M2M du 2026-09-02, point 1 : le clamp doit etre la DERNIERE
    instruction avant le retour. Il etait pose avant `_maybe_elevate`, donc
    toute elevation ulterieure le franchissait.

    Le contournement n'existait PAS -- uniquement parce que `_RING_DEV` vaut 1,
    exactement la borne. Une egalite fortuite entre deux constantes
    independantes. Ce test FORCE `_RING_DEV` a 0 pour eprouver la propriete
    au lieu de la laisser dependre d'une coincidence.
    """
    orig_dev, orig_ovr = V._RING_DEV, V._DEV_IS_ARMED_OVERRIDE
    V._RING_DEV = 0
    V._DEV_IS_ARMED_OVERRIDE = lambda: (True, 999)
    try:
        r = V.resolve_identity("CLAUDE", FAUX_PROXY, local=True,
                               agent_tokens={"OPENAI_PROXY": FAUX_PROXY},
                               hub_token=FAUX_MASTER)
        assert r["ring"] >= 1, "une elevation ulterieure a franchi la borne"
        assert r["via"] == "delegated:OPENAI_PROXY"
    finally:
        V._RING_DEV, V._DEV_IS_ARMED_OVERRIDE = orig_dev, orig_ovr


def test_l_elevation_dev_reste_intacte_hors_delegation():
    """Contre-epreuve : la borne ne doit pas casser l'elevation legitime d'un
    appel DIRECT. Un garde qui deborde son perimetre se fait desarmer."""
    orig_dev, orig_ovr = V._RING_DEV, V._DEV_IS_ARMED_OVERRIDE
    V._RING_DEV = 0
    V._DEV_IS_ARMED_OVERRIDE = lambda: (True, 999)
    try:
        r = V.resolve_identity("CLAUDE", "jeton-de-claude", local=True,
                               agent_tokens={"CLAUDE": "jeton-de-claude"},
                               hub_token=FAUX_MASTER)
        assert r["ring"] == 0 and r["via"] == "token"
    finally:
        V._RING_DEV, V._DEV_IS_ARMED_OVERRIDE = orig_dev, orig_ovr


def test_la_delegation_est_moins_puissante_que_l_authentification_directe():
    """Contre-epreuve du precedent : le MEME agent, sous SA propre identite,
    conserve son ring 0. La borne ne s'applique qu'a la delegation."""
    V._SEED_RING["AGENT_ROOT_FICTIF"] = 0
    try:
        direct = _r("AGENT_ROOT_FICTIF", FAUX_PROXY,
                    {"AGENT_ROOT_FICTIF": FAUX_PROXY})
        delegue = _r("AGENT_ROOT_FICTIF", FAUX_PROXY, {"OPENAI_PROXY": FAUX_PROXY})
        assert direct["ring"] == 0 and direct["via"] == "token"
        assert delegue["ring"] >= 1
    finally:
        V._SEED_RING.pop("AGENT_ROOT_FICTIF", None)


# --------------------------------------------------------------------------- #
# 3. Elle n'est accordee qu'a qui a la regle
# --------------------------------------------------------------------------- #

def test_un_agent_sans_regle_ne_delegue_pas(toks):
    """STATE_ENCODER porte un jeton derive valide mais n'a aucune `delegation`
    au registre : declarer un autre nom le fait retomber au plancher."""
    r = _r("CLAUDE", FAUX_AUTRE, toks)
    assert r["via"] == "header"
    assert r["ring"] == V._HEADER_FLOOR_RING


def test_le_droit_de_deleguer_vient_du_registre_pas_du_jeton():
    """Un jeton valide n'accorde rien par lui-meme : la regle est declaree."""
    assert V._delegation_de("OPENAI_PROXY"), "la regle a disparu du registre"
    assert V._delegation_de("STATE_ENCODER") == {}
    assert V._delegation_de("AGENT_QUI_N_EXISTE_PAS") == {}


def test_la_regle_du_registre_porte_sa_borne_et_son_motif():
    agents = json.loads(REGISTRE.read_text(encoding="utf-8"))["agents"]
    d = agents["OPENAI_PROXY"]["delegation"]
    assert int(d["ring_min_delegue"]) >= 1, (
        "une borne a 0 rendrait la delegation aussi puissante que le maitre")
    assert len(d.get("motif", "")) > 200, "regle sans motif : indefendable a la relecture"


def test_la_limite_connue_est_declaree():
    """Le degat est BORNE, pas supprime : la passerelle n'authentifie pas ses
    clients entrants, donc un appelant choisit encore son identite -- sans
    pouvoir depasser le plancher. Sans cette declaration, un lecteur prendrait
    la delegation pour une fermeture. C'est le meme principe que `taux=None`
    quand rien n'est mesure : nommer ce qu'on n'a PAS ferme."""
    agents = json.loads(REGISTRE.read_text(encoding="utf-8"))["agents"]
    lim = agents["OPENAI_PROXY"]["delegation"].get("limite_connue", "")
    assert len(lim) > 300, "la limite n'est pas declaree : la regle se lira comme close"
    for mot in ("AUTHENTIFIE PAS", "pass-through", "arbitrage owner"):
        assert mot.lower() in lim.lower(), mot


def test_le_proxy_n_authentifie_toujours_pas_ses_clients():
    """Contre-epreuve VIVANTE de la limite ci-dessus : le jour ou une
    authentification entrante apparait, ce test tombe et la limite doit etre
    relue -- peut-etre levee. Un constat qui ne se reverifie pas se fossilise."""
    src = (ROOT / "tools" / "forge_openai_proxy.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.find("_CLIENT_AGENT.set(")
    assert i > 0, "le point d'entree de l'identite client a bouge : re-mesurer"
    zone = src[max(0, i - 900):i + 400]
    for preuve_d_auth in ("status=401", "verify_api_key", "check_client_key"):
        assert preuve_d_auth not in zone, (
            "une authentification entrante est apparue (%s) : relire "
            "`limite_connue` du registre, elle est peut-etre levee" % preuve_d_auth)


# --------------------------------------------------------------------------- #
# 4. Elle se VOIT
# --------------------------------------------------------------------------- #

def test_la_trace_nomme_le_delegateur(toks):
    """Une delegation indiscernable d'une authentification directe rouvrirait
    l'angle mort que la phase C vient de fermer."""
    r = _r("CLAUDE", FAUX_PROXY, toks)
    assert r["via"].startswith("delegated:")
    assert "OPENAI_PROXY" in r["via"]


def test_l_agent_sous_son_propre_nom_n_est_pas_marque_delegue(toks):
    r = _r("OPENAI_PROXY", FAUX_PROXY, toks)
    assert r["via"] == "token", r["via"]


# --------------------------------------------------------------------------- #
# 5. Fail-closed
# --------------------------------------------------------------------------- #

def test_registre_illisible_refuse_la_delegation(monkeypatch):
    """Sur une lecture ratee on REFUSE, on n'accorde pas. Meme regle que le
    ring : l'illisible ne vaut pas l'autorisation."""
    import builtins

    vrai = Path.read_text

    def _casse(self, *a, **k):
        if self.name == "agent_identities.json":
            raise OSError("illisible")
        return vrai(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _casse)
    assert V._delegation_de("OPENAI_PROXY") == {}


def test_pas_de_delegation_sans_jeton(toks):
    r = _r("CLAUDE", "", toks)
    assert not r["via"].startswith("delegated:")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
