# -*- coding: utf-8 -*-
"""
tests/nr/test_reliability_kernel_nr.py
======================================
NOYAU DE FIABILITE — les invariants que la journee du 2026-08-14 a payes.

Prolonge `test_behavior_nr.py` (usurpation, escalade de ring, flood) avec six
proprietes qui ont TOUTES ete violees en production ce jour-la. Aucune n'est un
voeu : chacune correspond a un trou mesure, avec son chiffre.

Regle de ce fichier : on verifie une PROPRIETE OBSERVABLE du systeme, jamais une
implementation. Un refactor a le droit de tout changer dessous ; il n'a pas le
droit de rendre ces phrases fausses.

  1. Aucun client en ring 0            — NETCFG et LLAMACPP y etaient.
  2. Un en-tete sans jeton ne franchit pas le plancher — sinon l'identite
     s'auto-declare.
  3. Un acteur = UNE boite             — 98 + 43 + 9 messages d'AGY dormaient
                                          dans trois boites separees.
  4. Aucune mission en vol sans progression — une tache `running` depuis 22 JOURS.
  5. Aucun correctif perdu             — deux gardes anti-sawtooth Docker
                                          emportes par un revert, symptome revenu
                                          des semaines plus tard.
  6. Le RAG ne se degrade pas          — 60,2 % de sources pointent vers des
                                          fichiers disparus (detecteur propose par
                                          ANTIGRAVITY). Invariant de NON-AGGRAVATION :
                                          une dette connue ne doit pas grandir.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "app"))
sys.path.insert(0, str(_ROOT / "tools"))

_REGISTRE = _ROOT / "config" / "agent_identities.json"
_TASKS = _ROOT / "sandbox" / "tasks.db"

# DEUX MESURES, DEUX CHIFFRES — ne jamais les confondre (erreur commise ici meme
# le 2026-08-14, premiere version de ce test) :
#   * mesure RAFFINEE, sur toutes les extensions et avec resolution des noms nus
#     par index des basenames du depot -> 7 910 fantomes sur 13 141 = 60,2 %.
#     C'est le chiffre a citer pour parler de la DETTE REELLE.
#   * mesure CONVENTIONNELLE de ce test : echantillon `.py`, simple
#     Path.exists() sans resolution -> 90,6 %. Elle compte comme fantome tout
#     chemin non resolvable tel quel, y compris un nom nu parfaitement valide.
# La seconde est plus severe et beaucoup moins chere (pas d'os.walk complet).
# On la garde POUR SA STABILITE, et on calibre le plafond SUR ELLE : un seuil
# calibre sur une autre methode ne mesure rien. L'invariant interdit d'EMPIRER,
# il n'exige pas d'avoir deja repare (regle owner : marquer [PERIME], jamais
# supprimer).
_RAG_FANTOMES_PLAFOND_PCT = 92.0
_RAG_FANTOMES_REFERENCE_PCT = 90.6      # mesure conventionnelle du 2026-08-14


def _registre() -> dict:
    return json.loads(_REGISTRE.read_text(encoding="utf-8"))


# =============================================================================
# 1 — PRIVILEGE : personne ne dort en ring 0
# =============================================================================
class TestAucunRing0:
    """Le ring 0 est le rang MASTER. Un backend d'inference et un agent
    d'equipement reseau y etaient declares (NETCFG, LLAMACPP), pour UN appel
    chacun sur 228 955 journalises."""

    def test_aucune_identite_en_ring_0(self):
        agents = _registre().get("agents", {})
        assert agents, "registre d'identites vide ou illisible"
        fautifs = {n: e.get("ring") for n, e in agents.items() if e.get("ring") == 0}
        assert not fautifs, (
            f"identite(s) en ring 0 (rang MASTER) : {fautifs}. "
            "Un client ne persiste jamais en ring 0."
        )

    def test_les_hooks_restent_untrusted(self):
        """Un hook s'execute sans surveillance : il ne merite pas mieux que 4."""
        agents = _registre().get("agents", {})
        hooks = {n: e.get("ring") for n, e in agents.items() if e.get("kind") == "hook"}
        mauvais = {n: r for n, r in hooks.items() if r != 4}
        assert not mauvais, f"hook(s) au-dessus d'UNTRUSTED : {mauvais}"


# =============================================================================
# 2 — IDENTITE : un en-tete ne s'auto-declare pas
# =============================================================================
class TestAntiSpoof:
    """Sans jeton apparie, se nommer ANTIGRAVITY ne doit RIEN accorder. La
    resolution doit DEGRADER l'identite, jamais l'etablir."""

    @pytest.mark.parametrize("nom", ["ANTIGRAVITY", "CLAUDE", "NETCFG", "MASTER_TOKEN"])
    def test_entete_sans_jeton_plafonne(self, nom):
        import forge_videur as V

        ident = V.resolve_identity(nom, "", local=True)
        assert ident["ring"] >= V._HEADER_FLOOR_RING, (
            f"{nom} obtient ring {ident['ring']} sur simple en-tete "
            f"(plancher attendu {V._HEADER_FLOOR_RING})"
        )


# =============================================================================
# 3 — COURRIER : un acteur, une boite
# =============================================================================
class TestUneBoiteParActeur:
    """Le 2026-08-14 : agt_gemini 98 non lus + agt_antigravity 9 + agt_worker_code
    43 — un SEUL acteur, coupe en trois par un renommage et une surface
    d'execution. Une surface (hook, relais, executeur) n'a pas de boite propre."""

    @pytest.mark.parametrize("alias", ["agt_antigravity", "AGY", "GEMINI",
                                       "AGY_DAEMON", "GEMINI_RELAY", "WORKER_CODE"])
    def test_les_alias_convergent(self, alias):
        import forge_videur as V

        assert V.canonical(alias) == "ANTIGRAVITY", (
            f"{alias} route vers {V.canonical(alias)} au lieu de ANTIGRAVITY : "
            "le courrier se perdra dans une boite que personne ne releve."
        )

    def test_une_surface_n_a_pas_de_boite_propre(self):
        agents = _registre().get("agents", {})
        fautifs = []
        for nom, e in agents.items():
            if e.get("kind") in ("hook", "relay", "surface"):
                if str(e.get("mailbox") or "").upper() == nom.upper() and e.get("actor") != nom:
                    fautifs.append(nom)
        assert not fautifs, f"surface(s) possedant leur propre boite : {fautifs}"


# =============================================================================
# 4 — MISSIONS : rien ne reste en vol sans progresser
# =============================================================================
class TestAucuneMissionOrpheline:
    """Une tache `running` depuis 525,9 h — vingt-deux jours — et deux `claimed`
    depuis 327,5 h et 24,6 h. Le heartbeat surveillait le WORKER, pas la MISSION."""

    _EN_VOL = ("running", "claimed", "assigned")
    _SEUIL_H = 6.0

    @pytest.mark.skipif(not _TASKS.exists(), reason="bus de taches absent")
    def test_pas_de_mission_en_vol_sans_progression(self):
        con = sqlite3.connect(f"file:{_TASKS.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(tasks)")}
            champ = "COALESCE(progress_at, updated_at, created_at)" if "progress_at" in cols \
                else "COALESCE(updated_at, created_at)"
            marks = ",".join("?" * len(self._EN_VOL))
            limite = time.strftime("%Y-%m-%dT%H:%M:%S",
                                   time.localtime(time.time() - self._SEUIL_H * 3600))
            bloquees = con.execute(
                f"SELECT id, agent, status FROM tasks WHERE status IN ({marks}) "
                f"AND {champ} < ?", (*self._EN_VOL, limite)).fetchall()
        finally:
            con.close()
        assert not bloquees, (
            f"{len(bloquees)} mission(s) en vol sans progression depuis "
            f"{self._SEUIL_H} h : {[dict(r) for r in bloquees][:3]}. "
            "Le bail (reclaim_expired) doit les rendre au bus."
        )

    @pytest.mark.skipif(not _TASKS.exists(), reason="bus de taches absent")
    def test_le_bail_est_cable(self):
        """Sans ces colonnes, une mission morte ne peut structurellement pas
        etre reprise — c'est le trou de 22 jours."""
        con = sqlite3.connect(f"file:{_TASKS.as_posix()}?mode=ro", uri=True)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(tasks)")}
        finally:
            con.close()
        manquantes = {"lease_until", "attempt", "checkpoint", "progress_at"} - cols
        assert not manquantes, f"colonnes de bail absentes : {manquantes}"


# =============================================================================
# 5 — CORRECTIFS : ce qui a ete repare le reste
# =============================================================================
class TestAucunCorrectifPerdu:
    """43dbf555 et fe9f323d (gardes anti-sawtooth Docker) emportes par 3aec1500,
    un revert qui a annule plus que son objet. Ni les tests ni le lint ne le
    voyaient : le defaut n'est pas dans le code present, il est dans ce qui a
    disparu."""

    @pytest.mark.slow
    def test_aucune_ancre_disparue_recemment(self):
        from forge_fix_sentinel import scanner

        res = scanner(limit=25)
        assert res["n_perdus"] == 0, (
            f"{res['n_perdus']} correctif(s) perdu(s) : "
            f"{[p['ancre'] for p in res['perdus']][:5]}. "
            "Restaurer a l'identique via git show, ou documenter le retrait."
        )


# =============================================================================
# 6 — MEMOIRE : la dette du RAG ne grandit pas
# =============================================================================
class TestRagNeSeDegradePas:
    """Detecteur propose par ANTIGRAVITY au tour 9 : une source indexee qui
    pointe vers un fichier disparu empoisonne le contexte du prochain agent, qui
    hallucine alors une architecture morte. Mesure du 2026-08-14 : 60,2 %.
    Invariant de NON-AGGRAVATION — on interdit d'empirer, on n'exige pas d'avoir
    deja repare (regle owner : marquer [PERIME], jamais supprimer)."""

    @pytest.mark.slow
    def test_taux_de_sources_fantomes_borne(self):
        db = _ROOT / "RAG" / "embeddings.db"
        if not db.exists():
            pytest.skip("base RAG absente")
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            rows = [r[0] for r in con.execute(
                "SELECT DISTINCT source FROM rag_chunks WHERE source LIKE '%.py' LIMIT 4000")]
        finally:
            con.close()
        if not rows:
            pytest.skip("aucune source fichier indexee")
        fantomes = 0
        for s in rows:
            p = str(s).split("#")[0].strip()
            if not p:
                continue
            chemin = Path(p) if Path(p).is_absolute() else _ROOT / p
            if not chemin.exists():
                fantomes += 1
        pct = 100.0 * fantomes / len(rows)
        assert pct <= _RAG_FANTOMES_PLAFOND_PCT, (
            f"sources fantomes a {pct:.1f} % (plafond {_RAG_FANTOMES_PLAFOND_PCT} %) : "
            f"la dette de memoire GRANDIT. Marquer les chunks perimes "
            f"(superseded_by / active), ne jamais les supprimer."
        )
