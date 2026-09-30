# -*- coding: utf-8 -*-
"""NR — la commissure memory_keeper -> germe existe, et elle dit quand elle ne lit pas.

__FORGE_COLOR__ = "reproductif/regeneration : non-regression de l afferent de la boucle"

CE QUI A ETE PAYE (2026-09-07). `forge_organ_agents.ORGAN_MAP` declarait la boucle de
regeneration en GAP P1 : « memory_keeper(gaps/lessons) -> evolutionary_engine ». Mesure :

  - `forge_memory_keeper` possede 1,1 Mo de lecons + un index FTS5, et n'exposait que de
    la PROSE (`recall`, `present` -> str) : un recepteur ne peut rien iterer.
  - `evolutionary_engine` tenait SES PROPRES lecons (`experience_feedback.lessons_learned`)
    et ne referencait memory_keeper NULLE PART.
  -> deux memoires, aucune commissure. La declaration de la carte etait JUSTE.

Ce NR verrouille les trois proprietes de la commissure, et le registre :

  1. l'emetteur rend des RECORDS (etat + items), trois etats -- ILLISIBLE n'est pas vide
  2. le recepteur consulte cette source, et NOMME le cas ou il n'a pas pu la lire
  3. le registre du corps porte la sonde : DONE prouvable, l'efferent reste P1
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for d in ("tools", "app"):
    if str(ROOT / d) not in sys.path:
        sys.path.insert(0, str(ROOT / d))

import forge_memory_keeper as mk  # noqa: E402
import forge_organ_agents as oa  # noqa: E402

GERME = ROOT / "tools" / "evolutionary_engine.py"


# --- 1. l'emetteur rend des records ---------------------------------------------------

def test_lessons_rend_des_records_pas_de_la_prose(monkeypatch) -> None:
    import forge_keeper_base as kb
    monkeypatch.setattr(kb, "find", lambda topic, limit=8: [
        {"source": "session:2026-09-01:solution", "preview": "sonde indispensable"},
        {"source": "memory:x", "preview": "autre"},
        {"pas_de_source": True},
    ])
    r = mk.lessons("routes sensibles", limit=3)
    assert r["etat"] == "LU"
    assert [i["source"] for i in r["items"]] == [
        "session:2026-09-01:solution", "memory:x"], "records iterables, entrees sans source ecartees"
    assert isinstance(r["items"][0], dict), "un RECORD, pas une ligne de texte"


def test_un_index_indisponible_est_ILLISIBLE_pas_vide(monkeypatch) -> None:
    """Un index injoignable n'est pas « aucune lecon »."""
    monkeypatch.setitem(sys.modules, "forge_keeper_base", None)   # force ImportError
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_keeper_base", None)   # force ImportError
    r = mk.lessons("x")
    assert r["etat"] == "ILLISIBLE" and r["items"] == []
    assert "indisponible" in r["motif"]


def test_un_index_qui_leve_est_ILLISIBLE_et_ne_casse_pas_le_germe(monkeypatch) -> None:
    import forge_keeper_base as kb

    def _boom(topic, limit=8):
        raise RuntimeError("fts verrouille")
    monkeypatch.setattr(kb, "find", _boom)
    r = mk.lessons("x")
    assert r["etat"] == "ILLISIBLE" and "leve" in r["motif"]


def test_zero_resultat_reste_LU(monkeypatch) -> None:
    """Chercher et ne rien trouver est une MESURE ; ne pas pouvoir chercher n'en est pas une."""
    import forge_keeper_base as kb
    monkeypatch.setattr(kb, "find", lambda topic, limit=8: [])
    r = mk.lessons("sujet sans lecon")
    assert r["etat"] == "LU" and r["items"] == []


def test_recall_est_inchange() -> None:
    """La commissure s'AJOUTE : la vue prose pour un humain garde son contrat."""
    import inspect
    assert inspect.signature(mk.recall).return_annotation in ("str", str)


# --- 2. le recepteur consulte, et dit quand il ne lit pas --------------------------------

def test_le_germe_consulte_la_memoire_du_corps_avant_de_muter() -> None:
    src = GERME.read_text(encoding="utf-8", errors="replace")
    i = src.find("PAST LESSON:")
    assert i > 0, "site des contre-mesures introuvable"
    bloc = src[i:i + 2500]
    assert "from nokido_agent.tools.forge_memory_keeper import lessons" in bloc, (
        "la memoire du corps doit etre consultee AU SITE des contre-mesures")
    assert "PAST LESSON (memory_keeper/" in bloc, "et ses lecons injectees comme les autres"


def test_le_germe_NOMME_une_memoire_illisible() -> None:
    """Le piege de la nuit, une fois de plus : lire « je n'ai pas pu » comme « il n'y a rien »."""
    src = GERME.read_text(encoding="utf-8", errors="replace")
    assert "NON consultees, pas absentes" in src
    assert "dite, pas avalee" in src, "une commissure indisponible se DIT"


def test_le_germe_ne_remplace_pas_ses_propres_lecons() -> None:
    """Consulter, pas substituer : les fiches de feedback du germe restent lues."""
    src = GERME.read_text(encoding="utf-8", errors="replace")
    assert 'fb.get("lessons_learned", [])' in src


# --- 2bis. l'EFFERENT : ce que le germe produit RETOURNE au corps ----------------------
#
# Une commissure a sens unique n'est pas une boucle. Mesure 2026-09-07 avant cablage :
# ZERO reward/punish/hormone dans le germe -- une mutation reussie ou ratee n'emettait
# rien ; et son post-mortem partait en @disco (decouverte), pas dans le canal des lecons.

def test_le_germe_emet_les_DEUX_hormones_ensemble() -> None:
    """Du cortisol sans dopamine ne remet jamais failure_count a zero et derive vers
    dead_end : la pathologie deja payee (cortisol survivant au restart, 471 spawns
    refuses a RAM 60 %). Reward et punish se cablent ENSEMBLE ou pas du tout."""
    src = GERME.read_text(encoding="utf-8", errors="replace")
    i = src.find('results["efferent"]')
    assert i > 0, "bloc efferent introuvable"
    bloc = src[i:i + 2000]
    assert "from nokido_agent.app.forge_motivation import punish, reward" in bloc, (
        "meme organe, memes fonctions que endocrine_to_gate -- pas une autre voie")
    assert 'reward("evolution"' in bloc and 'punish("evolution"' in bloc


def test_la_duree_est_MESUREE_et_son_attribution_NOMMEE() -> None:
    """compute_elegance fait de time_s=0 une dopamine MAXIMALE : passer 0.0 serait une
    mesure inventee. Le germe ne chronometre pas par mutation ; la seule duree reelle
    est celle de la generation, et l'attribution doit le DIRE."""
    src = GERME.read_text(encoding="utf-8", errors="replace")
    i = src.find('results["efferent"]')
    bloc = src[i:i + 2000]
    assert 'time_s=float(results["elapsed"])' in bloc, "la duree MESUREE, pas 0.0"
    assert "time_s_attribution" in bloc and "GENERATION" in bloc, (
        "l'attribution approximative est NOMMEE dans le resultat")


def test_la_decision_de_punish_est_CONSERVEE() -> None:
    """punish REND action_recommended / dead_end : c'est la retroaction. La jeter,
    c'est emettre une hormone que personne ne lit."""
    src = GERME.read_text(encoding="utf-8", errors="replace")
    i = src.find('results["efferent"]')
    bloc = src[i:i + 2000]
    assert '"action_recommended": _d.get("action_recommended")' in bloc
    assert '"dead_end": bool(_d.get("dead_end"))' in bloc


def test_un_endocrinien_indisponible_est_DIT_et_ne_bloque_pas_le_germe() -> None:
    src = GERME.read_text(encoding="utf-8", errors="replace")
    i = src.find('results["efferent"]')
    bloc = src[i:i + 2000]
    assert 'results["efferent"]["etat"] = "INDISPONIBLE' in bloc
    assert "dit, pas avale" in bloc


def test_le_post_mortem_ecrit_dans_le_canal_des_LECONS(monkeypatch, tmp_path) -> None:
    """Comportement, pas relecture : on capture ce qui part reellement a memory_keeper.

    Avant : refine_and_anchor(collection="disco") -- une pepite de DECOUVERTE. Le germe
    ecrivait dans un canal et lisait dans l'autre (lessons()) : boucle irrefermable."""
    import evolutionary_engine as ee
    vu = {}
    monkeypatch.setattr(mk, "remember",
                        lambda **kw: vu.update(kw) or {"ok": True})
    # l'ancien canal (@disco) ne doit ni sortir ni toucher le RAG pendant le test
    try:
        import forge_unified_discovery as ud
        monkeypatch.setattr(ud, "refine_and_anchor", lambda *a, **k: {})
    except Exception:  # noqa: BLE001 — module absent : l'appel est deja protege
        pass
    monkeypatch.setattr(ee.RAGEnricher, "RAG_INDEX", tmp_path)
    ee.RAGEnricher.generate_postmortem(filepath="app/inexistant_pour_test.py",
                                       agent="agent_test", error="boom de test", gen=7)
    assert vu.get("domain") == "evolution", "la lecon est rangee dans SON domaine"
    assert "agent_test" in vu.get("problem", "") and "boom de test" in vu.get("solution", "")
    assert (tmp_path / "experience_memory.jsonl").exists(), (
        "le journal du germe est TOUJOURS ecrit : la commissure s'ajoute, ne remplace pas")


def test_l_efferent_est_DONE_et_sa_sonde_mord() -> None:
    prio = {n: p for p, n, _w in oa.ESSENTIAL_WIRINGS}
    assert prio.get("regeneration_efferent") == "DONE"
    r = oa.probe("regeneration_efferent")
    assert r["etat"] == "present", "un DONE se PROUVE dans le code : %r" % r


# --- 3. le registre du corps -------------------------------------------------------------

def test_la_commissure_est_DONE_et_sa_sonde_mord() -> None:
    prio = {n: p for p, n, _w in oa.ESSENTIAL_WIRINGS}
    assert prio.get("regeneration_afferent") == "DONE"
    r = oa.probe("regeneration_afferent")
    assert r["etat"] == "present", "un DONE se PROUVE dans le code : %r" % r


def test_la_boucle_entiere_n_est_PAS_declaree_close() -> None:
    """Un afferent cable n'est pas une boucle close : l'efferent (quality_gate ->
    integration) reste a faire. Declarer DONE ce qui ne l'est pas est exactement le
    registre perime que ce module a deja paye sur cortisol_to_throttle."""
    prio = {n: p for p, n, _w in oa.ESSENTIAL_WIRINGS}
    assert prio.get("regeneration_loop") == "P1"
    assert "regeneration_loop" not in oa.WIRING_PROBES, (
        "pas de sonde sur un cablage non fait : elle mordrait a tort ou rendrait absent")
    texte = {n: w for _p, n, w in oa.ESSENTIAL_WIRINGS}["regeneration_loop"]
    assert "EFFERENT" in texte, "le texte dit ce qui RESTE, pas ce qui est fait"
