"""NR — le verbe unique d'introspection doit etre BORNE et HONNETE.

`app/forge_introspect.py` est ne de deux mesures du 2026-08-31 :
  - Nokido porte 21 organes d'introspection, dont 17 ont un consommateur
    externe : ils ne sont pas morts, il n'existe simplement aucun point d'entree
    commun ;
  - les verbes d'introspection pesent 70 appels sur 16 447 resultats d'outils,
    soit 0,4 %. Une capacite qu'il faut savoir NOMMER pour l'atteindre n'est pas
    atteinte.

Ce que ces tests protegent, ce n'est pas « le module repond » mais ses deux
promesses, celles qui le rendent utilisable sans le relire :

  1. il ne rend QUE des symboles qui existent (il n'invente pas de piste) ;
  2. il DECLARE ce qu'il n'a pas consulte. Une reponse d'introspection qui tait
     ses angles morts se lit comme un panorama complet -- c'est ainsi qu'on
     conclut « ca n'existe pas » sur un organe qu'on n'a jamais interroge.

HERMETIQUE : banc dans `tmp_path`, carte du code pointee dessus, index
d'enquetes fourni explicitement. Aucun test ne depend du working tree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# `_voisinage` importe ses organes en TOP-LEVEL : le test doit patcher le MEME
# objet module, donc `app/` doit etre sur le chemin ici aussi.
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "app"))

from app import forge_callgraph_jit as jit  # noqa: E402
from app import forge_introspect as intro  # noqa: E402


@pytest.fixture()
def banc(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod1.py").write_text(
        "class Dog:\n"
        "    def parler_ambigu(self):\n"
        "        return 1\n"
        "\n"
        "class Robot:\n"
        "    def parler_ambigu(self):\n"
        "        return 2\n"
        "\n"
        "def fonction_unique_ici():\n"
        "    return 3\n",
        encoding="utf-8")
    (pkg / "mod2.py").write_text(
        "def usager(o):\n"
        "    o.parler_ambigu()\n"
        "    return fonction_unique_ici()\n",
        encoding="utf-8")
    # Un VRAI consommateur : il importe.
    (pkg / "mod_importeur.py").write_text(
        "import mod1\n"
        "\n"
        "def s_en_sert():\n"
        "    return mod1.Dog()\n",
        encoding="utf-8")
    # Un FAUX consommateur : il ne fait que nommer le module en prose.
    (pkg / "mod_bavard.py").write_text(
        "# Ce module parle de mod1 sans jamais l'utiliser.\n"
        "def rien():\n"
        "    return 0\n",
        encoding="utf-8")
    monkeypatch.setattr(jit, "ROOT", tmp_path)
    monkeypatch.setattr(jit, "_SCAN_ROOTS", ("pkg",))
    jit._DEP_CACHE.clear()
    # `introspect` recoit LE module patche : sans injection il importerait
    # `forge_callgraph_jit` en top-level, un SECOND objet module que ce
    # monkeypatch ne touche pas -- et le test mesurerait le depot reel.
    monkeypatch.setattr(intro, "_JIT_TEST", jit, raising=False)
    # Journal de succes INJECTE : sans cela les tests liraient le journal REEL
    # du depot (197 entrees) et deviendraient dependants de l'historique.
    monkeypatch.setattr(intro, "_OPLOG_TEST", tmp_path / "oplog_absent.jsonl",
                        raising=False)
    # Scan d'imports NEUTRALISE par defaut : le vrai coute 2,26 s (556 modules)
    # et le payer dans chaque test faisait passer la suite de 2 s a 38 s. Un
    # test lent finit par ne plus etre lance, et un test qu'on ne lance plus ne
    # protege rien. Les tests QUI portent sur le voisinage prennent la fixture
    # `graphe`, qui installe un graphe controle.
    import forge_panorama_builder as _P
    monkeypatch.setattr(_P, "scan_forge_modules", lambda *a, **k: {})
    return tmp_path


def _intro(question, **kw):
    kw.setdefault("oplog", getattr(intro, "_OPLOG_TEST", None))
    return intro.introspect(question, jit=getattr(intro, "_JIT_TEST", None), **kw)


def _oplog(chemin, entrees):
    """Journal minimal au format append-only de forge_success_oplog."""
    chemin.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entrees),
                      encoding="utf-8")
    return chemin


# ── promesse 1 : ne rendre que ce qui existe ────────────────────────────────
def test_un_symbole_existant_est_trouve(banc):
    r = _intro("pourquoi fonction_unique_ici echoue ?",
               index_enquetes=banc / "absent.json")
    noms = [s["symbole"] for s in r["symboles_trouves"]]
    assert "fonction_unique_ici" in noms


def test_un_mot_qui_n_est_pas_un_symbole_n_est_pas_INVENTE(banc):
    """Rendre une piste qui n'existe pas coute plus qu'un silence."""
    r = _intro("probleme de latence reseau chez le voisin",
               index_enquetes=banc / "absent.json")
    assert r["symboles_trouves"] == []
    assert r["modules_trouves"] == []
    assert "verdict" in r and "PAS une preuve d'absence" in r["verdict"]


# ── la trace de consultation : la matiere du futur garde ────────────────────
@pytest.fixture()
def trace(tmp_path, monkeypatch):
    """Trace ISOLEE : sans cela les tests ecriraient dans la trace REELLE du
    depot et fausseraient le taux qui decidera du passage au refus."""
    monkeypatch.setattr(intro, "TRACE", tmp_path / "trace.json")
    return tmp_path / "trace.json"


def test_sans_trace_l_etat_est_JAMAIS_pas_RECENTE(trace):
    c = intro.consultation_recente("AGENT_X")
    assert c["vu"] is False and c["etat"] == "JAMAIS" and c["age_s"] is None


def test_une_consultation_rend_l_etat_RECENTE(trace):
    intro.noter_consultation("AGENT_X", "pourquoi le hub tombe")
    c = intro.consultation_recente("AGENT_X")
    assert c["vu"] is True and c["etat"] == "RECENTE"
    assert "hub" in c["question"]


def test_une_consultation_TROP_ANCIENNE_ne_compte_plus(trace):
    """« Perimee » n'est pas « jamais » : l'agent a consulte, mais pour une
    autre tache. Les confondre effacerait une information utile au diagnostic."""
    intro.noter_consultation("AGENT_X")
    c = intro.consultation_recente("AGENT_X", ttl=0.0)
    assert c["vu"] is False and c["etat"] == "PERIMEE"
    assert c["age_s"] is not None


def test_les_deux_cas_d_edition_sont_COMPTES(trace):
    """Sans denominateur, decider de passer au refus serait un pari."""
    intro.noter_edition("AGENT_X", True)
    intro.noter_edition("AGENT_X", False)
    intro.noter_edition("AGENT_Y", False)
    t = intro.taux_consultation()
    assert t["editions"] == 3 and t["avec_consultation"] == 1 and t["sans"] == 2
    assert t["taux_pct"] == pytest.approx(33.3, abs=0.1)


def test_aucun_taux_n_est_invente_sans_edition(trace):
    """Rendre 0 % sur zero edition ferait croire a un probleme mesure."""
    assert intro.taux_consultation()["taux_pct"] is None


def test_une_trace_CORROMPUE_ne_leve_pas_et_avertit_par_defaut(trace):
    """Mode de FAUSSE ALERTE assume et documente : trace illisible -> l'agent
    est averti alors qu'il avait peut-etre consulte. C'est le sens prudent
    tant que le garde n'est qu'un avertissement ; il devra etre revu AVANT
    tout passage au refus, sinon un fichier casse bloquerait les ecritures."""
    trace.write_text("{ceci n est pas du json", encoding="utf-8")
    assert intro.consultation_recente("AGENT_X")["etat"] == "JAMAIS"


# ── Q1 : consulter n'est pas reutiliser ────────────────────────────────────
def test_les_fichiers_proposes_sont_retenus(trace):
    intro.noter_consultation("A", "q", {"procedures_connues": [
        {"fichiers": ["tools/x.py", "app/y.py"]}]})
    assert intro._lire_trace()["A"]["fichiers_proposes"] == ["tools/x.py", "app/y.py"]


def test_ecrire_DANS_la_piste_proposee_compte_comme_reutilisation(trace):
    intro.noter_consultation("A", "q", {"procedures_connues": [
        {"fichiers": ["tools/x.py"]}]})
    intro.noter_edition("A", True, "tools/x.py")
    t = intro.taux_consultation()
    assert t["reutilisations"] == 1 and t["divergences"] == 0
    assert t["taux_reutilisation_pct"] == 100.0


def test_ecrire_AILLEURS_compte_comme_divergence(trace):
    """Le cas que le compteur de consultations seul ne voyait pas : introspect
    trouve une ancienne solution, et l'agent en invente une autre."""
    intro.noter_consultation("A", "q", {"procedures_connues": [
        {"fichiers": ["tools/x.py"]}]})
    intro.noter_edition("A", True, "app/tout_autre.py")
    t = intro.taux_consultation()
    assert t["divergences"] == 1 and t["reutilisations"] == 0


def test_une_consultation_SANS_proposition_n_est_PAS_jugeable(trace):
    """Ni reutilisation ni divergence : introspect n'avait rien a proposer.
    La compter comme une divergence accuserait l'agent d'un tort inexistant."""
    intro.noter_consultation("A", "q", {"procedures_connues": []})
    intro.noter_edition("A", True, "app/quelconque.py")
    t = intro.taux_consultation()
    assert t["editions_jugeables"] == 0
    assert t["taux_reutilisation_pct"] is None
    assert t["editions"] == 1, "l'edition reste comptee pour le garde"


def test_une_edition_SANS_consultation_n_est_pas_jugee_non_plus(trace):
    intro.noter_consultation("A", "q", {"procedures_connues": [
        {"fichiers": ["tools/x.py"]}]})
    intro.noter_edition("A", False, "tools/x.py")
    assert intro.taux_consultation()["editions_jugeables"] == 0


# ── Q2 : le classement structurel par question ─────────────────────────────
_GRAPHE = {
    "forge_sujet": ["forge_dep"],          # le sujet depend de forge_dep
    "forge_dep": [],
    "forge_appelant": ["forge_sujet"],     # forge_appelant depend du sujet
    "forge_lointain": [],
    "forge_pendant": [],                   # n'importe rien : noeud pendant
}


@pytest.fixture()
def graphe(monkeypatch):
    import forge_panorama_builder as P
    monkeypatch.setattr(P, "scan_forge_modules", lambda *a, **k: dict(_GRAPHE))
    return _GRAPHE


def test_l_amont_donne_ce_qu_une_modification_casserait(graphe):
    v = intro._voisinage(["forge_sujet"], [])
    assert [m["module"] for m in v["amont"]][:1] == ["forge_appelant"]


def test_l_aval_donne_ce_dont_le_sujet_depend(graphe):
    v = intro._voisinage(["forge_sujet"], [])
    assert [m["module"] for m in v["aval"]][:1] == ["forge_dep"]


def test_un_noeud_PENDANT_ne_fabrique_pas_un_faux_classement(graphe):
    """Le defaut MESURE le 2026-08-31 : un module qui n'importe aucun forge_*
    renvoie toute la masse a la graine, tous les autres restent a 0.0, et le
    classement sortait les premiers DANS L'ORDRE ALPHABETIQUE avec l'air d'une
    reponse. Un classement de zeros est du bruit deguise."""
    v = intro._voisinage(["forge_pendant"], [])
    assert v["aval"] == []
    assert all(m["score"] > 0 for m in v["amont"])


def test_un_sujet_hors_graphe_est_DECLARE_pas_silencieux(graphe):
    nc = []
    v = intro._voisinage(["module_inconnu_xyz"], nc)
    assert v["seeds"] == [] and v["aval"] == []
    assert any("voisinage" in x["organe"] for x in nc)


def test_le_voisinage_tombe_en_premier_sous_budget(banc, graphe):
    """Le voisinage est du CONTEXTE ; une procedure connue est une REPONSE."""
    log = _oplog(banc / "oplog.jsonl", [
        {"commit": "aaaa", "date": "2026-08-01", "etat": "PROUVE",
         "symptome": "parler_ambigu casse", "jetons": ["parler_ambigu"]}])
    r = _intro("parler_ambigu", budget_tokens=1, oplog=log)
    assert r["voisinage_structurel"] == {}
    assert r["budget"]["tronque"] is True


# ── le bilan d'adoption : mesurer ce que la reutilisation evite ─────────────
def test_une_base_illisible_ne_rend_PAS_zero(trace, tmp_path):
    """« Je n'ai pas pu compter » n'est pas « aucun appel ». Rendre 0 ferait
    conclure a une absence d'adoption sur une base absente."""
    c = intro._compter_appels(tmp_path / "pas_de_base.db")
    assert c["lisible"] is False
    assert "absente" in c["raison"]


def test_le_bilan_sur_base_absente_est_NON_MESURABLE(trace, tmp_path):
    b = intro.bilan(db=tmp_path / "pas_de_base.db")
    assert b["verdict"] == "NON MESURABLE"
    assert "adoption_live" in b, "l'indicateur vivant doit rester lisible"


def test_un_denominateur_MORT_est_nomme_et_non_pris_pour_une_stagnation(
        trace, monkeypatch):
    """Mesure du 2026-08-31 : `mcp_result` n'avait pas grandi d'une ligne malgre
    des dizaines d'appels. Un indicateur branche sur un signal sans emetteur
    reste a zero et se lit a tort « aucune adoption »."""
    monkeypatch.setattr(intro, "_compter_appels", lambda db=None: {
        "lisible": True, "appels": intro.POINT_ZERO["appels"],
        "total": intro.POINT_ZERO["total"]})
    b = intro.bilan()
    assert b["verdict"] == "NON MESURABLE"
    assert "emetteur est mort" in b["raison"]


def _bilan_avec(monkeypatch, appels, total):
    monkeypatch.setattr(intro, "_compter_appels", lambda db=None: {
        "lisible": True, "appels": appels, "total": total})
    return intro.bilan()


def test_verdict_STAGNANT_quand_le_taux_marginal_ne_depasse_pas_le_depart(
        trace, monkeypatch):
    z = intro.POINT_ZERO
    b = _bilan_avec(monkeypatch, z["appels"] + 4, z["total"] + 1000)  # 0,4 %
    assert b["verdict"] == "STAGNANT"


def test_verdict_ADOPTE_demande_cinq_fois_le_taux_de_depart(trace, monkeypatch):
    """Seuil DECLARE : sous 5x, une hausse peut n'etre que du bruit."""
    z = intro.POINT_ZERO
    b = _bilan_avec(monkeypatch, z["appels"] + 300, z["total"] + 1000)  # 30 %
    assert b["verdict"] == "ADOPTE"
    assert b["taux_marginal_pct"] == pytest.approx(30.0, abs=0.1)


def test_le_taux_est_MARGINAL_et_non_cumule(trace, monkeypatch):
    """Un cumul sur 16 447 lignes bouge de facon glaciale et masquerait une
    adoption reelle pendant des semaines."""
    z = intro.POINT_ZERO
    b = _bilan_avec(monkeypatch, z["appels"] + 50, z["total"] + 100)
    assert b["taux_marginal_pct"] == pytest.approx(50.0, abs=0.1)
    cumule = 100.0 * (z["appels"] + 50) / (z["total"] + 100)
    assert b["taux_marginal_pct"] > cumule * 10


# ── la memoire des procedures deja reussies ─────────────────────────────────
def test_une_procedure_PROUVEE_passe_devant_une_CONSTATEE_mieux_notee(banc):
    """L'etat epistemique PRIME sur le score lexical.

    Une mesure posterieure vaut mieux qu'une ressemblance de mots : sinon le
    verbe recommanderait la piste la plus VERBEUSE, pas la plus SURE.
    """
    log = _oplog(banc / "oplog.jsonl", [
        {"commit": "aaaa1111", "date": "2026-08-01", "etat": "PROUVE",
         "symptome": "verrou sqlite sur ecriture", "jetons": ["database", "locked"]},
        {"commit": "bbbb2222", "date": "2026-08-02", "etat": "CONSTATE",
         "symptome": "database is locked pendant ecriture concurrente",
         "jetons": ["database", "locked", "ecriture", "concurrente"]},
    ])
    r = _intro("database is locked pendant une ecriture concurrente", oplog=log)
    etats = [p["etat"] for p in r["procedures_connues"]]
    assert etats[0] == "PROUVE", etats
    assert r["procedures_connues"][1]["score"] > r["procedures_connues"][0]["score"]


def test_une_procedure_INFIRMEE_est_signalee_et_jamais_en_tete(banc):
    """Le symptome est revenu apres ce correctif : c'est un « ne refais pas ca »,
    pas une piste. Elle reste VISIBLE, elle ne remonte pas."""
    log = _oplog(banc / "oplog.jsonl", [
        {"commit": "cccc3333", "date": "2026-08-03", "etat": "INFIRME",
         "symptome": "verrou database locked", "jetons": ["database", "locked"]},
        {"commit": "dddd4444", "date": "2026-08-04", "etat": "CONSTATE",
         "symptome": "database locked", "jetons": ["database"]},
    ])
    r = _intro("database locked", oplog=log)
    infirmes = [p for p in r["procedures_connues"] if p["etat"] == "INFIRME"]
    assert infirmes and infirmes[0]["deconseille"] is True
    assert r["procedures_connues"][0]["etat"] != "INFIRME"


def test_un_journal_de_succes_ABSENT_est_DECLARE(banc):
    """« Aucune procedure connue » et « pas de journal » rendent la meme liste
    vide ; les confondre ferait croire que rien n'a jamais ete repare."""
    r = _intro("n importe quoi", oplog=banc / "jamais_ecrit.jsonl")
    raisons = " ".join(x["raison"] for x in r["non_consulte"])
    assert "journal absent" in raisons
    assert "--backfill" in raisons, "le remede doit etre nomme, pas seulement le manque"


def test_une_procedure_connue_declenche_une_recommandation(banc):
    log = _oplog(banc / "oplog.jsonl", [
        {"commit": "eeee5555", "date": "2026-08-05", "etat": "PROUVE",
         "symptome": "verrou database locked", "jetons": ["database", "locked"]},
    ])
    r = _intro("database locked", oplog=log)
    assert "recommandation" in r
    assert "INSPECTER avant" in r["recommandation"]
    assert "PROUVE" in r["recommandation"]


def test_sans_procedure_aucune_recommandation_n_est_fabriquee(banc):
    log = _oplog(banc / "oplog.jsonl", [
        {"commit": "ffff6666", "date": "2026-08-06", "etat": "PROUVE",
         "symptome": "sujet totalement etranger", "jetons": ["typographie"]},
    ])
    r = _intro("mod1", oplog=log)
    assert r["procedures_connues"] == []
    assert "recommandation" not in r


def test_la_solution_deja_eprouvee_survit_au_budget_avant_les_symboles(banc):
    """Entre un symbole de plus et une solution qui a deja marche, c'est la
    solution qui doit rester."""
    log = _oplog(banc / "oplog.jsonl", [
        {"commit": "9999aaaa", "date": "2026-08-07", "etat": "PROUVE",
         "symptome": "parler_ambigu casse", "jetons": ["parler_ambigu"]},
    ])
    r = _intro("parler_ambigu mod1 fonction_unique_ici", budget_tokens=1, oplog=log)
    assert r["budget"]["tronque"] is True
    if r["symboles_trouves"] or r["modules_trouves"]:
        assert r["procedures_connues"], "les procedures ont ete coupees en premier"


# ── les MODULES, pas seulement les fonctions ────────────────────────────────
def test_un_nom_de_MODULE_est_reconnu(banc):
    """`definitions()` cherche `def <nom>` : un module n'en est jamais un.

    Avant ce correctif, une question sur un module rendait ZERO symbole alors
    que le module existait -- le verbe disait « rien trouve » la ou il fallait
    lire « je n'ai pas cherche ca ».
    """
    r = _intro("mod1 sert-il a quelque chose ?", index_enquetes=banc / "absent.json")
    mods = [m["module"] for m in r["modules_trouves"]]
    assert "mod1" in mods


def test_citer_un_module_n_est_PAS_le_consommer(banc):
    """Faux positif mesure sur le depot reel le jour de la mise en service :
    un module cite dans un COMMENTAIRE ressortait comme consommateur, et un
    organe muet paraissait vivant."""
    r = _intro("mod1", index_enquetes=banc / "absent.json")
    m = [x for x in r["modules_trouves"] if x["module"] == "mod1"][0]
    assert m["importe_par"] == 1
    assert any("mod_importeur" in f for f in m["exemples_import"])
    assert any("mod_bavard" in f for f in m["exemples_mention"])


def test_le_perimetre_de_recherche_des_consommateurs_est_DECLARE(banc):
    """`_grep_files` ne balaie pas tests/ : le taire ferait lire un 0 comme
    « meme pas teste »."""
    r = _intro("mod1", index_enquetes=banc / "absent.json")
    organes = " ".join(x["organe"] for x in r["non_consulte"])
    assert "tests/" in organes


def test_un_module_inexistant_n_est_pas_invente(banc):
    r = _intro("module_qui_nexiste_pas_du_tout",
               index_enquetes=banc / "absent.json")
    assert r["modules_trouves"] == []
    assert "verdict" in r


def test_le_budget_tronque_AUSSI_les_modules(banc):
    """Tronquer les seuls symboles laisserait deborder une reponse qui tient
    surtout dans les modules : une promesse tenue a moitie."""
    r = _intro("mod1 mod2 mod_importeur mod_bavard", budget_tokens=1,
               index_enquetes=banc / "absent.json")
    assert r["budget"]["tronque"] is True
    assert r["modules_trouves"] == [] or r["budget"]["estime"] <= 1


def test_les_mots_vides_ne_declenchent_pas_de_recherche():
    assert "pourquoi" not in intro._candidats("pourquoi ce module echoue")
    assert "comment" not in intro._candidats("comment faire")


def test_un_symbole_forge_passe_devant_un_mot_courant():
    """Le vocabulaire propre du corps est un signal d'intention plus fort."""
    c = intro._candidats("regarde forge_truc et aussi machin")
    assert c[0] == "forge_truc"


# ── promesse 2 : la reserve et les angles morts sont DITS ───────────────────
def test_l_attribution_ambigue_remonte_avec_sa_reserve(banc):
    r = _intro("qui appelle parler_ambigu ?", index_enquetes=banc / "absent.json")
    s = [x for x in r["symboles_trouves"] if x["symbole"] == "parler_ambigu"]
    assert s, "le symbole ambigu doit etre trouve"
    assert s[0]["attribution"] == jit.AMBIGU
    assert s[0]["classes_portant_le_nom"] == 2
    assert "SANS distinguer" in s[0]["reserve"]


def test_les_organes_hors_v1_sont_NOMMES(banc):
    """Leur absence doit etre lisible, sinon la reponse parait exhaustive."""
    r = _intro("fonction_unique_ici", index_enquetes=banc / "absent.json")
    organes = " ".join(x["organe"] for x in r["non_consulte"])
    assert "reachability_ledger" in organes


def test_un_index_d_enquetes_ABSENT_est_declare(banc):
    r = _intro("fonction_unique_ici", index_enquetes=banc / "absent.json")
    raisons = " ".join(x["raison"] for x in r["non_consulte"])
    assert "index absent" in raisons


def test_index_CONSULTE_sans_correspondance_n_est_pas_un_index_absent(banc):
    """Les deux rendent une liste vide ; les confondre fait croire qu'aucune
    enquete anterieure n'existe alors qu'on n'a pas regarde."""
    idx = banc / "enquetes.json"
    idx.write_text(json.dumps({"symptomes": {}}), encoding="utf-8")
    r = _intro("fonction_unique_ici", index_enquetes=idx)
    assert r["enquetes_anterieures"] == []
    assert r["enquetes_consultation"]["index"] == "enquetes.json"
    assert r["enquetes_consultation"]["correspondances"] == 0
    raisons = " ".join(x["raison"] for x in r["non_consulte"])
    assert "index absent" not in raisons


def test_la_trace_de_consultation_ne_survit_pas_a_l_appel_suivant(banc):
    """Un etat de module qui traine ferait rapporter un index consulte alors
    qu'il ne l'a pas ete au tour suivant."""
    idx = banc / "enquetes.json"
    idx.write_text(json.dumps({"symptomes": {}}), encoding="utf-8")
    _intro("fonction_unique_ici", index_enquetes=idx)
    r2 = _intro("fonction_unique_ici", index_enquetes=banc / "jamais.json")
    assert r2["enquetes_consultation"].get("index") in (None, "non consulte")


# ── la borne est une PROMESSE, pas une intention ────────────────────────────
def test_le_budget_est_tenu_et_la_troncature_declaree(banc):
    r = _intro("parler_ambigu fonction_unique_ici usager",
               budget_tokens=1, index_enquetes=banc / "absent.json")
    assert r["budget"]["estime"] <= 1 or r["budget"]["tronque"] is True


def test_un_budget_large_ne_tronque_rien(banc):
    r = _intro("fonction_unique_ici", budget_tokens=100000,
               index_enquetes=banc / "absent.json")
    assert r["budget"]["tronque"] is False


def test_jamais_plus_de_cinq_symboles(banc):
    """La memoire totale est enorme ; seuls quelques elements doivent remonter."""
    r = _intro(" ".join("symbole_%d" % i for i in range(30)) +
               " parler_ambigu fonction_unique_ici usager",
               index_enquetes=banc / "absent.json")
    assert len(r["symboles_trouves"]) <= intro.MAX_SYMBOLES


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
