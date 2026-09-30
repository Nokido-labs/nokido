# -*- coding: utf-8 -*-
"""NR — UI_ACCEPTANCE_WITNESS : un temoin qui distingue ce que la journee a confondu.

__FORGE_COLOR__ = "qualite/gate : temoin structure du contrat d acceptation UI"

POURQUOI CE TEMOIN. Le 2026-09-09, le gate ui-acceptance a dit « interface
injoignable » alors que :7400 repondait HTTP 401. Un seul mot recouvrait TROIS etats
distincts -- service absent, navigateur incapable de demarrer, application non
authentifiee -- et cette agregation a coute trois changements de compte et deux
diagnostics annonces comme des causes avant d'etre mesures.

Le temoin existe pour rendre ces trois couches SEPAREMENT lisibles, et pour repondre
apres coup a quatre questions refutables : qu'a-t-on execute, qu'a-t-on PAS execute,
l'application a-t-elle reellement ete jugee, combien de temps cela a-t-il pris.

CE QUI EXISTE DEJA, et qu'on n'invente pas (anti-dup) : `sandbox/ui_campaign/report.json`
porte deja `verdict`, `duree_s`, `route_en_cause`, `routes_non_jugees`,
`couverture_clics`, `pages`, `clicks`. Le temoin AGREGE ce rapport avec ce que seul
`ci_local` connait (identite, selection) et avec les deux couches qui ne sont
mesurees nulle part aujourd'hui : transport et navigateur.

LES QUATRE INVARIANTS, testes ici sur des VALEURS et des TRANSITIONS, pas sur la
presence des clefs :

    transport inconnu       != echec applicatif
    echec navigateur        != service injoignable
    absence de verdict      != PASS
    --only ui-acceptance    != execution des autres gates

Le quatrieme est le moins intuitif et le plus important : un NR a deja montre que
« le bon gate s'execute » ne prouve pas « SEUL le bon gate s'execute ». Si
l'exclusivite est violee, la mesure de duree ne veut plus rien dire -- le temoin doit
donc se declarer FAILED meme quand l'application, elle, a repondu PASS.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent


def _mod():
    """Import tardif : chaque test echoue en NOMMANT le manque, sans casser la collecte."""
    import importlib  # noqa: PLC0415
    chemin = str(RACINE / "tools")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    try:
        return importlib.import_module("forge_ui_temoin")
    except ImportError as e:  # pragma: no cover - chemin rouge du TDD
        raise AssertionError(
            "tools/forge_ui_temoin.py est absent : le temoin doit exister AVANT la "
            "campagne qu'il mesure, sinon on relance un run illisible (paye le "
            "2026-09-09, run 34381575702) — %s" % e) from None


def _obs(**maj):
    """Observations nominales : campagne conforme, exclusivite respectee."""
    base = {
        "identity": {"tested_sha": "963e4519b", "run_id": "34381575702"},
        "selection": {"requested": "ui-acceptance",
                      "selected": ["ui-acceptance"],
                      "non_selected_gates_executed": []},
        "transport": {"service_reachable": True, "http_status": 200},
        "browser": {"executable": "C:/nokido/ms-playwright/firefox-1532",
                    "launched": True, "context_created": True},
        "report": {"verdict": "CONFORME", "duree_s": 200.9,
                   "route_en_cause": [], "routes_non_jugees": []},
    }
    for k, v in maj.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


# --- forme ------------------------------------------------------------------

def test_le_temoin_est_construit_par_une_fonction_pure():
    m = _mod()
    assert hasattr(m, "construire"), (
        "le temoin doit se construire par une fonction NOMMEE et testable sur "
        "donnees synthetiques, pas au fil d'un run")


def test_le_temoin_reprend_la_duree_du_rapport_sans_la_recalculer():
    t = _mod().construire(_obs())
    assert t["timing"]["duration_s"] == 200.9, (
        "deux mesures de duree divergeraient le jour ou l'une est corrigee")


# --- invariant 1 : transport inconnu != echec applicatif --------------------

# ---------------------------------------------------------------------------
# LE TEMOIN DOIT PORTER LES QUATRE ETATS DE LA CAMPAGNE. Cliquet du 2026-09-16.
#
# La campagne rend desormais quatre verdicts de defaut la ou elle n'en rendait
# que deux : VIOLE, INDISPONIBLE, AUTH_FAILURE et DEGRADE. Le temoin, lui, ne
# connait que CONFORME et VIOLE : tout le reste tombe sur UNKNOWN par sa liste
# blanche -- ce qui est le BON defaut, et ce qui reste faux a l'arrivee.
#
# Consequence, sur l'artefact qu'on relit APRES COUP : « le gate n'a pas pu
# s'authentifier » et « je n'ai pas pu lire le rapport de campagne » s'ecrivent
# du meme mot. Or le premier est une panne du gate et le second une panne de
# l'instrument. Un journal qui confond les deux ne permet pas de savoir quoi
# reparer.
#
# ETAT ATTENDU : rouge tant que la table de verdicts ignore ces mots.
# ---------------------------------------------------------------------------


def test_un_login_non_etabli_ne_se_confond_plus_avec_un_rapport_illisible():
    t = _mod().construire(_obs(report={"verdict": "AUTH_FAILURE"}))
    illisible = _mod().construire(_obs(report={"verdict": "UNKNOWN"}))
    assert t["final"] == "AUTH_FAILURE", t
    assert t["final"] != illisible["final"], (
        "une panne du GATE et une panne de l'INSTRUMENT s'ecrivent du meme mot"
    )


def test_le_temoin_porte_la_degradation_et_NOMME_les_routes():
    t = _mod().construire(_obs(report={
        "verdict": "DEGRADE",
        "routes_degradees": ["/anatomy", "/forge/feed"]}))
    assert t["final"] == "DEGRADE", t
    assert "/anatomy" in (t["application"]["reason"] or ""), (
        "la raison ne nomme pas les routes en defaut : illisible depuis un log"
    )


def test_indisponible_reste_distinct_de_l_inconnu():
    t = _mod().construire(_obs(report={"verdict": "INDISPONIBLE"}))
    assert t["final"] == "INDISPONIBLE", t


def test_un_verdict_INCONNU_tombe_TOUJOURS_sur_unknown():
    """La liste blanche ne se transforme pas en liste noire au passage : un mot
    que le temoin ne connait pas reste UNKNOWN, il ne devient jamais sain."""
    t = _mod().construire(_obs(report={"verdict": "VERT_PRESQUE"}))
    assert t["final"] == "UNKNOWN", t


def test_aucun_de_ces_etats_n_est_certifiant():
    for mot in ("AUTH_FAILURE", "DEGRADE", "INDISPONIBLE"):
        t = _mod().construire(_obs(report={"verdict": mot}))
        assert t["final"] != "PROVEN", mot


def test_service_injoignable_donne_UNKNOWN_et_jamais_FAILED():
    t = _mod().construire(_obs(
        transport={"service_reachable": False, "http_status": None},
        browser={"launched": False, "context_created": False},
        report={"verdict": "UNKNOWN"}))
    assert t["application"]["verdict"] == "UNKNOWN"
    assert t["final"] == "UNKNOWN", (
        "ne pas avoir pu juger n'est pas un contrat viole : %s" % t["final"])
    assert t["application"]["reason"], "une absence NOMME ce qu'elle n'a pas pu voir"


def test_HTTP_401_est_un_service_JOIGNABLE():
    """Le defaut exact du 2026-09-09 : 401 lu comme « interface injoignable »."""
    t = _mod().construire(_obs(
        transport={"service_reachable": True, "http_status": 401},
        report={"verdict": "UNKNOWN"}))
    assert t["transport"]["service_reachable"] is True
    assert t["final"] == "UNKNOWN"
    assert "auth" in t["application"]["reason"].lower(), (
        "un 401 sur un service qui repond doit designer l'authentification, pas le "
        "reseau : %r" % t["application"]["reason"])


# --- invariant 2 : echec navigateur != service injoignable ------------------

def test_navigateur_mort_ne_declare_PAS_le_service_injoignable():
    """Trois comptes ont echoue a lancer Playwright pendant que :7400 repondait."""
    t = _mod().construire(_obs(
        browser={"launched": False, "context_created": False},
        report={"verdict": "UNKNOWN"}))
    assert t["transport"]["service_reachable"] is True, (
        "le navigateur et le service sont deux couches : l'une ne juge pas l'autre")
    assert t["browser"]["launched"] is False
    assert t["final"] == "UNKNOWN"
    motif = t["application"]["reason"].lower()
    assert "navigateur" in motif or "browser" in motif, (
        "le motif doit designer la couche fautive : %r" % t["application"]["reason"])


def test_contexte_non_cree_se_distingue_d_un_navigateur_non_lance():
    """`launch` reussi mais `launch_persistent_context` qui pend : deux etats."""
    t = _mod().construire(_obs(
        browser={"launched": True, "context_created": False},
        report={"verdict": "UNKNOWN"}))
    assert t["browser"]["launched"] is True
    assert t["browser"]["context_created"] is False
    assert t["final"] == "UNKNOWN"


# --- invariant 3 : absence de verdict != PASS -------------------------------

def test_absence_de_verdict_ne_devient_JAMAIS_PROVEN():
    t = _mod().construire(_obs(report={"verdict": "UNKNOWN"}))
    assert t["final"] != "PROVEN"


def test_un_contrat_viole_est_FAILED_et_nomme_la_route():
    t = _mod().construire(_obs(report={"verdict": "VIOLE",
                                       "route_en_cause": ["/mcp_lab"]}))
    assert t["final"] == "FAILED"
    assert "/mcp_lab" in t["application"]["reason"]


def test_le_cas_nominal_est_PROVEN():
    t = _mod().construire(_obs())
    assert t["final"] == "PROVEN"
    assert t["application"]["verdict"] == "PASS"


# --- invariant 5 : un temoin dit SUR QUOI il porte --------------------------
#
# MESURE 2026-09-09, run GitHub 34390571371, premier temoin reel :
#     "identity": {"tested_sha": null, "run_id": "34390571371"}
#     "final": "PROVEN"
# Le temoin certifiait sans dire QUOI. `_sha_courant()` avait echoue en silence sur
# le runner et le constructeur ne fabrique rien -- ce qui est correct -- mais rien
# n'empechait `PROVEN` de sortir sur une identite vide. Un certificat anonyme n'est
# pas un certificat.

def test_PROVEN_exige_de_savoir_QUEL_sha_a_ete_teste():
    t = _mod().construire(_obs(identity={"tested_sha": None}))
    assert t["final"] != "PROVEN", (
        "un temoin qui ne nomme pas son sha ne certifie rien")
    assert t["final"] == "UNKNOWN"
    assert "sha" in t["application"]["reason"].lower()


def test_un_sha_present_laisse_PROVEN_intact():
    """Contre-epreuve : le garde ne doit pas rendre PROVEN inatteignable."""
    assert _mod().construire(_obs())["final"] == "PROVEN"


def test_un_contrat_VIOLE_reste_FAILED_meme_sans_sha():
    """L'identite manquante ne doit pas MASQUER un contrat viole en UNKNOWN."""
    t = _mod().construire(_obs(identity={"tested_sha": None},
                               report={"verdict": "VIOLE",
                                       "route_en_cause": ["/mcp_lab"]}))
    assert t["final"] == "FAILED"


# --- invariant 6 : NON MESURE ne devient pas NEGATIF ------------------------
#
# MESURE, meme temoin : "service_reachable": false a cote de "verdict": "PASS".
# Contradictoire -- 20 routes avaient ete chargees, le service repondait donc. La
# faute n'etait pas dans la campagne mais dans l'agregateur : `bool(None)` vaut
# False, si bien que « pas mesure » devenait « mesure et negatif ». C'est EXACTEMENT
# la confusion que ce temoin existe pour supprimer, reintroduite a l'etage d'apres.

def test_une_couche_NON_MESUREE_reste_None_et_ne_devient_pas_False():
    t = _mod().construire(_obs(
        transport={"service_reachable": None, "http_status": None},
        browser={"launched": None, "context_created": None}))
    assert t["transport"]["service_reachable"] is None, (
        "bool(None) vaut False : « pas mesure » deviendrait « mesure et negatif »")
    assert t["browser"]["launched"] is None
    assert t["browser"]["context_created"] is None


def test_un_False_EXPLICITE_reste_False():
    """Contre-epreuve : on ne remplace pas un ecrasement par un autre."""
    t = _mod().construire(_obs(
        transport={"service_reachable": False}, report={"verdict": "UNKNOWN"}))
    assert t["transport"]["service_reachable"] is False


def test_un_transport_non_mesure_n_accuse_pas_le_reseau():
    """Le motif ne doit pas designer une couche qu'on n'a pas regardee."""
    t = _mod().construire(_obs(
        transport={"service_reachable": None, "http_status": None},
        report={"verdict": "UNKNOWN"}))
    motif = t["application"]["reason"].lower()
    assert "injoignable" not in motif, (
        "transport NON MESURE n'est pas transport ABSENT : %r"
        % t["application"]["reason"])


# --- invariant 4 : --only n'execute pas les autres gates --------------------

def test_l_exclusivite_violee_rend_FAILED_MEME_si_l_application_passe():
    """Sans ca, une campagne verte masquerait un selecteur qui ne selectionne rien.

    Mesure du 2026-09-09 : `--only X` lancait la campagne UI des que :7400 repondait,
    parce que le garde d'exclusivite etait dans une branche morte. Le gate visait
    juste et le selecteur ne selectionnait pas.
    """
    t = _mod().construire(_obs(selection={
        "non_selected_gates_executed": ["pytest (suite pure)", "bandit"]}))
    assert t["final"] == "FAILED", (
        "une duree mesuree sous exclusivite violee ne veut rien dire")
    assert "pytest (suite pure)" in str(t["selection"]["non_selected_gates_executed"])


def test_le_temoin_compte_les_executions_inattendues():
    t = _mod().construire(_obs(selection={
        "non_selected_gates_executed": ["bandit", "ruff style"]}))
    assert t["selection"]["unexpected_gate_executions"] == 2, (
        "une borne dit COMBIEN, pas seulement TROP")


def test_tout_final_non_PROVEN_porte_une_raison():
    m = _mod()
    for obs in (_obs(report={"verdict": "UNKNOWN"}),
                _obs(report={"verdict": "VIOLE", "route_en_cause": ["/x"]}),
                _obs(selection={"non_selected_gates_executed": ["bandit"]})):
        t = m.construire(obs)
        assert t["final"] in ("UNKNOWN", "FAILED")
        assert t["application"]["reason"], (
            "un verdict non PROVEN sans raison n'est pas diagnosticable")
