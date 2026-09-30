"""NR -- observation d'autorisation :8766 en SHADOW (`forge_authz_shadow`).

Ce que ces tests verrouillent, et pourquoi chacun compte :

1. **Aucune route ne devient PUBLIC par defaut.** L'inconnu sort en
   `AUTHZ_UNKNOWN`. C'est la propriete centrale : la surface actuelle est
   ouverte precisement parce que personne n'a jamais eu a declarer l'inverse.
2. **`ring == -1` est un ECHEC d'authentification, pas un privilege.** Le hub
   rend -1 pour « pas d'en-tete / jeton invalide / capability expiree ». Un
   comparateur ecrit a la hate (`ring <= 1` = admin) lirait cet echec comme le
   privilege le plus haut.
3. **`/api/resource/should_spawn` ne doit JAMAIS sortir en DENY** tant que son
   appelant n'est pas identifie : c'est le superviseur, et le refuser
   couperait la regulation du corps.
4. **Un appelant indeterminable reste UNKNOWN**, avec la RAISON. Jamais une
   identite plausible.
5. **Aucun materiau d'authentification dans la trace.**

Deux cas du mandat -- « scope insuffisant » et « ring insuffisant » -- ne sont
PAS decidables a ce stade : la matrice des capabilities par route n'existe pas
encore, elle est justement ce que l'observation doit produire. Les tests
ci-dessous verifient donc qu'ils rendent `AUTHZ_UNKNOWN` plutot qu'un verdict
invente. Fabriquer un seuil maintenant reviendrait a ecrire la matrice au lieu
de la mesurer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_authz_shadow as az  # noqa: E402

# Route SYNTHETIQUE, jamais declaree (2026-09-26). Les exemples reels de « route non tranchee »
# (/api/services/list, /api/sandbox/runtimes) ont ete TRANCHES par la cloture du 24/09 (ce70f4d4e) : ces
# tests rougissaient sur une decision juste. Une route inventee ne peut pas etre tranchee en douce.
_NON_TRANCHEE = "/api/__nr_route_jamais_tranchee__"


def test_la_route_synthetique_n_est_pas_tranchee():
    assert az.authentification_de(_NON_TRANCHEE)[0] not in ("NONE", "REQUIRED")


# --------------------------------------------------------------------------- #
# Classement des routes
# --------------------------------------------------------------------------- #

def test_route_publique_declaree():
    classe, motif = az.classer_route("/health")
    assert classe == "PUBLIC"
    assert motif, "une route publique sans motif est une whitelist qui grossira"


def test_route_inconnue_n_est_jamais_publique():
    classe, _ = az.classer_route("/une/route/jamais/vue")
    assert classe == "UNKNOWN"
    assert classe != "PUBLIC"


def test_la_liste_publique_reste_minuscule():
    """Une whitelist qui grossit « pour que ca marche » rouvre la surface sans
    que personne ne l'ait decide. Si ce test tombe, c'est une DECISION a
    prendre, pas un seuil a relever."""
    assert len(az.PUBLIC_DECLARE) <= 3, sorted(az.PUBLIC_DECLARE)


def test_chaque_route_publique_porte_sa_raison():
    for route, motif in az.PUBLIC_DECLARE.items():
        assert motif.strip(), route


# --------------------------------------------------------------------------- #
# Decision theorique
# --------------------------------------------------------------------------- #

def test_publique_sans_token_est_allow():
    v = az.decider("/health", ring=-1, agent="")
    assert v["decision"] == "SHADOW_ALLOW"


def test_route_non_classee_est_unknown_pas_deny():
    """Une politique jamais tranchee ne peut pas etre « refusee » : un DENY
    affirmerait une decision que personne n'a prise."""
    v = az.decider("/api/mcp/toggle", ring=-1, agent="")
    assert v["decision"] == "AUTHZ_UNKNOWN"


def test_chaque_route_tranchee_porte_sa_mesure():
    """La matrice se remplit de MESURES, jamais de suppositions.

    Elle etait vide par conception jusqu'au 2026-09-02 ; trois routes y sont
    entrees ce jour-la, chacune sur un comptage d'appels reels. L'exigence de
    preuve remplace l'exigence de vacuite : sans elle, la table deviendrait
    l'endroit ou l'on inscrit ce qu'on croit.
    """
    assert az.ADMIN_DECLARE == {}
    for route, motif in az.AUTH_REQUISE.items():
        assert "TRANCHEE" in motif, route
        assert len(motif) > 150, "%s : motif trop court pour porter une mesure" % route
        assert any(c.isdigit() for c in motif), (
            "%s : aucun chiffre dans le motif -- une decision sans comptage" % route)


def test_ring_moins_un_est_un_echec_pas_un_privilege(monkeypatch):
    """-1 signifie « authentification echouee ». Le lire comme un ring tres bas
    donnerait le privilege maximal a un appel sans jeton."""
    monkeypatch.setitem(az.AUTH_REQUISE, "/x/admin", "tranchee pour ce test")
    assert az.decider("/x/admin", ring=-1, agent="")["decision"] == "SHADOW_DENY"
    assert az.decider("/x/admin", ring=0, agent="CLAUDE",
                      via="capability_token")["decision"] == "SHADOW_ALLOW"


def test_deny_seulement_sur_une_politique_tranchee(monkeypatch):
    """SHADOW_DENY n'a de sens que si la route est classee AUTH ou ADMIN."""
    assert az.decider("/pas/classee", -1, "")["decision"] == "AUTHZ_UNKNOWN"
    monkeypatch.setitem(az.AUTH_REQUISE, "/pas/classee", "tranchee")
    assert az.decider("/pas/classee", -1, "")["decision"] == "SHADOW_DENY"


def test_token_valide_ne_suffit_pas_si_la_politique_n_est_pas_tranchee():
    """Changement de modele du 2026-09-02 : etre authentifie n'autorise pas une
    route dont l'authentification n'a jamais ete decidee. Auparavant, une
    identite prouvee suffisait -- ce qui autorisait implicitement les 35 routes
    classees LOCAL sur la seule foi d'un appelant observe."""
    v = az.decider(_NON_TRANCHEE, ring=1, agent="CLAUDE", via="capability_token")
    assert v["decision"] == "AUTHZ_UNKNOWN"


def test_token_valide_autorise_une_route_tranchee(monkeypatch):
    monkeypatch.setitem(az.AUTH_REQUISE, "/api/services/list", "tranchee")
    v = az.decider("/api/services/list", ring=1, agent="CLAUDE", via="capability_token")
    assert v["decision"] == "SHADOW_ALLOW"


def test_mauvais_token_est_traite_comme_absence_d_identite(monkeypatch):
    """Le hub rend (-1, 'bad_token'). Un jeton refuse ne vaut pas mieux qu'aucun."""
    monkeypatch.setitem(az.AUTH_REQUISE, "/api/mcp/flags", "tranchee")
    assert az.decider("/api/mcp/flags", ring=-1,
                      agent="bad_token")["decision"] == "SHADOW_DENY"


def test_identite_usurpee_reste_au_plancher(monkeypatch):
    """Un `X-Agent-Name` non adosse a un jeton DEGRADE l'identite (plancher
    anti-spoof ring 4) : se nommer CLAUDE ne suffit pas. Le hub rend alors -1,
    et se nommer ne doit rien changer au verdict."""
    monkeypatch.setitem(az.AUTH_REQUISE, "/x", "tranchee")
    anonyme = az.decider("/x", ring=-1, agent="", via="anonyme")
    usurpe = az.decider("/x", ring=-1, agent="CLAUDE", via="header")
    assert usurpe["decision"] == anonyme["decision"] == "SHADOW_DENY"


def test_appel_interne_legitime_n_est_pas_refuse():
    """Un appelant interne OBSERVE mais dont l'authentification n'a pas encore
    ete tranchee ne doit pas etre refuse : il faut d'abord l'identifier.

    L'exemple etait `/api/resource/should_spawn` jusqu'au 2026-09-02 ; depuis
    que le superviseur porte son identite, cette route est TRANCHEE (REQUIRED)
    et sort donc en DENY sans jeton -- c'est le comportement voulu. On prend
    une route encore non tranchee pour continuer a couvrir le cas.
    """
    v = az.decider(_NON_TRANCHEE, ring=-1, agent="")
    assert v["decision"] == "AUTHZ_UNKNOWN"
    assert v["decision"] != "SHADOW_DENY"


def test_route_connue_mais_identite_prouvee_sur_route_non_classee():
    v = az.decider("/route/non/classee", ring=1, agent="CLAUDE")
    assert v["decision"] == "AUTHZ_UNKNOWN"


def test_scope_et_ring_insuffisants_ne_sont_pas_inventes():
    """La matrice des capabilities n'existe pas encore : un verdict « scope
    insuffisant » serait fabrique, pas mesure."""
    v = az.decider("/route/non/classee", ring=4, agent="AGENT_FAIBLE")
    assert v["decision"] == "AUTHZ_UNKNOWN"
    assert "non classee" in v["reason"]


def test_toute_decision_porte_une_raison():
    for route, ring in (("/health", -1), ("/api/mcp/toggle", -1),
                        ("/api/resource/should_spawn", -1), ("/x", 1)):
        assert az.decider(route, ring, "A")["reason"].strip()


def test_les_decisions_sont_dans_le_vocabulaire():
    for route, ring in (("/health", -1), ("/x", -1), ("/x", 0),
                        ("/api/services/list", 2)):
        assert az.decider(route, ring, "A")["decision"] in (
            "SHADOW_ALLOW", "SHADOW_DENY", "AUTHZ_UNKNOWN")


# --------------------------------------------------------------------------- #
# INVARIANT : le PID prouve la PROVENANCE, jamais le DROIT
# --------------------------------------------------------------------------- #

def test_le_pid_n_entre_pas_dans_la_decision():
    """Garde executable de l'invariant owner : `PID == supervisor.exe -> ALLOW`
    ferait d'un nom de binaire un credential. Un nom de processus s'usurpe, et
    l'usurpateur heriterait du privilege du superviseur. La signature de
    `decider` ne doit donc JAMAIS accepter de provenance."""
    import inspect

    params = set(inspect.signature(az.decider).parameters)
    interdits = {"pid", "process", "parent_pid", "service", "appelant",
                 "processus", "binaire", "exe"}
    fautifs = params & interdits
    assert not fautifs, (
        "la provenance est entree dans la decision d'autorisation : %s" % sorted(fautifs))


def test_le_corps_de_decider_n_interroge_aucune_provenance():
    """Plus fort que la signature : meme lue depuis un global ou un cache, la
    provenance ne doit pas influencer le verdict."""
    import inspect

    corps = inspect.getsource(az.decider)
    # on ignore la docstring, qui PARLE justement de l'invariant
    sans_doc = corps.split('"""')[-1] if corps.count('"""') >= 2 else corps
    for terme in ("resoudre_appelant", ".name()", "supervisor.exe", "psutil"):
        assert terme not in sans_doc, (
            "decider consulte la provenance via %r" % terme)


def test_la_decision_est_identique_quel_que_soit_l_appelant():
    """Deux appels identiques doivent rendre le meme verdict : rien dans la
    provenance ne peut le faire basculer."""
    a = az.decider("/api/mcp/toggle", -1, "")
    b = az.decider("/api/mcp/toggle", -1, "")
    assert a == b


def test_un_appelant_inconnu_reste_unknown_ni_allow_ni_deny():
    """Le troisieme cas du mandat : pid connu mais identite absente sur une
    route interne NON TRANCHEE -> UNKNOWN, jamais un verdict automatique."""
    v = az.decider(_NON_TRANCHEE, ring=-1, agent="")
    assert v["decision"] == "AUTHZ_UNKNOWN"


# --------------------------------------------------------------------------- #
# Resolution de l'appelant -- trois etats
# --------------------------------------------------------------------------- #

def test_pid_indeterminable_sans_port():
    r = az.resoudre_appelant(None)
    assert r["pid"] is None
    assert r["raison"], "un PID absent sans raison est indiscernable d'une panne"


def test_pid_indeterminable_ne_fabrique_pas_d_identite():
    r = az.resoudre_appelant(None)
    for k in ("process", "parent_pid", "service"):
        assert r[k] is None, k


def test_acces_refuse_nest_pas_aucune_connexion(monkeypatch):
    """Un `net_connections` refuse doit se DIRE : sinon un compte sans
    privilege rend « appelant introuvable » pour tout le monde, ce qui se lit
    comme un corps sans appelants."""
    class _Faux:
        @staticmethod
        def net_connections(kind="tcp"):
            raise PermissionError("refuse")

    monkeypatch.setitem(sys.modules, "psutil", _Faux)
    az._CACHE_CONN["ts"] = 0.0
    r = az.resoudre_appelant(54321)
    assert r["pid"] is None
    assert "refuse" in r["raison"].lower()


def test_pid_connu_est_rendu(monkeypatch):
    class _Addr:
        port = 54321

    class _Conn:
        pid = 4242
        laddr = _Addr()

    class _Proc:
        def __init__(self, pid): self.pid = pid
        def name(self): return "python.exe"
        def parent(self): return None

    class _Faux:
        @staticmethod
        def net_connections(kind="tcp"): return [_Conn()]
        Process = _Proc

    monkeypatch.setitem(sys.modules, "psutil", _Faux)
    az._CACHE_CONN["ts"] = 0.0
    r = az.resoudre_appelant(54321)
    assert r["pid"] == 4242
    assert r["process"] == "python.exe"


def test_port_sans_socket_le_dit(monkeypatch):
    class _Faux:
        @staticmethod
        def net_connections(kind="tcp"): return []

    monkeypatch.setitem(sys.modules, "psutil", _Faux)
    az._CACHE_CONN["ts"] = 0.0
    r = az.resoudre_appelant(99999)
    assert r["pid"] is None
    assert r["raison"]


# --------------------------------------------------------------------------- #
# Trace -- aucun secret
# --------------------------------------------------------------------------- #

def _trace_type():
    return az.trace_de("/api/mcp/toggle", "POST", -1, "", "header",
                       {"pid": None, "raison": "port source absent"})


def test_la_trace_porte_les_champs_du_mandat():
    t = _trace_type()
    for k in ("ts", "route", "method", "identity", "ring", "scope", "via",
              "decision", "reason", "pid", "process", "parent_pid", "service"):
        assert k in t, k


def test_aucun_materiau_d_authentification_dans_la_trace():
    t = _trace_type()
    brut = json.dumps(t).lower()
    for interdit in ("bearer", "authorization", "cookie", "jwt", "password",
                     "secret", "api_key", "apikey"):
        assert interdit not in brut, interdit


def test_identite_absente_est_unknown_pas_vide():
    assert _trace_type()["identity"] == "UNKNOWN"


def test_scope_absent_est_unknown():
    assert _trace_type()["scope"] == "UNKNOWN"


def test_observer_ne_leve_jamais(monkeypatch, tmp_path):
    """Un middleware ne doit pas casser une requete pour un journal -- mais
    l'echec est RENDU, pas avale."""
    monkeypatch.setattr(az, "JOURNAL", tmp_path / "sous" / "dossier" / "a.jsonl")
    assert az.observer(_trace_type()) is True


def test_observer_rend_false_si_ecriture_impossible(monkeypatch):
    class _Chemin:
        def __getattr__(self, _n): raise OSError("disque")

    monkeypatch.setattr(az, "JOURNAL", _Chemin())
    assert az.observer(_trace_type()) is False


# --------------------------------------------------------------------------- #
# Matrice et M2M
# --------------------------------------------------------------------------- #

def test_matrice_sans_journal_le_dit(monkeypatch, tmp_path):
    monkeypatch.setattr(az, "JOURNAL", tmp_path / "absent.jsonl")
    m = az.matrice()
    assert m["lues"] == 0
    assert m["raison"], "un agregat vide sans raison se lit comme « aucun appel »"


def test_matrice_compte_le_denominateur(monkeypatch, tmp_path):
    j = tmp_path / "a.jsonl"
    j.write_text(json.dumps(_trace_type()) + "\nCECI N EST PAS DU JSON\n",
                 encoding="utf-8")
    monkeypatch.setattr(az, "JOURNAL", j)
    m = az.matrice()
    assert m["lues"] == 1
    assert m["illisibles"] == 1, "les lignes illisibles doivent etre comptees"


def test_m2m_exige_un_pointeur():
    with pytest.raises(ValueError):
        az.enveloppe_m2m("")


def test_m2m_ne_porte_que_le_pointeur():
    e = az.enveloppe_m2m("bb:authz_shadow_2026_09_02", "3 appelants atypiques")
    assert e["intent"] == "AUTHZ_OBSERVATION"
    assert e["pointer_ref"]
    assert "routes" not in e and "appelants" not in e


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
