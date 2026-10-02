# -*- coding: utf-8 -*-
"""Non-regression — la boucle autonome emprunte le chemin FERME (survit ET ameliore).

Raccordement demande par l'owner le 2026-09-08, apres trois mesures qui en fixaient
l'ordre :

  1. `juger_module_avec_gain` existe, il est CABLE, et sa docstring designe la boucle
     autonome comme son appelant — mais celle-ci empruntait `juger_module`, qui prouve
     la SURVIE et ne dit RIEN du gain. Une mutation qui passe les tests et DEGRADE
     etait donc conservee.
  2. Le raccorder tel quel aurait ete FAUX : sans tests cibles, `juger_gain` rendait
     NEUTRE — l'absence de mesure deguisee en mesure. Corrige d'abord (INDECIDABLE).
  3. Il fallait un PERIMETRE a jouer, sinon tout serait GAIN_INDECIDABLE. D'ou
     `perimetre_mesure`, extrait et elargi a la detection par import.

TROIS BRANCHES, et la troisieme est celle qui compte (formulation owner) :
`GAIN_INDECIDABLE` est un etat TERMINAL de la decision courante, PAS un synonyme de
SURVIT. Le systeme y dit « je ne peux pas encore savoir si c'est meilleur, il me manque
telle mesure » — et cette phrase est une file de travail, pas un echec.

    AMELIORE           -> AWAITING_OWNER_COMMIT  (la promotion reste corticale)
    GAIN_INDECIDABLE   -> PERIMETRE_MANQUANT     (instrumenter, puis rejuger)
    SURVIT_SANS_GAIN   -> REJECTED               (mesure, sans gain : on ne garde pas)
    MEURT              -> REJECTED

Hermetique : le juge est remplace par un double. Aucune mutation, aucun git, aucun test
reellement joue.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_autonomous_loops as AL  # noqa: E402
import forge_mutation_judge as MJ  # noqa: E402


class _JugeDouble:
    """Double du juge : enregistre par quel chemin la boucle est passee."""

    def __init__(self, verdict):
        self.verdict = verdict
        self.appels_fermes = []
        self.appels_ouverts = []

    def evolution_autorisee(self):
        # Ces tests exercent le chemin ARME. La porte de l'evolution (2026-10-01) a son
        # propre NR : test_porte_evolution_nr.
        return {"autorisee": True, "etat": "ARMEE", "motif": ""}

    def juger_module_avec_gain(self, rel, nouveau, tests=None):
        self.appels_fermes.append((rel, list(tests or [])))
        return dict(self.verdict)

    def juger_module(self, rel, nouveau, tests=None):
        self.appels_ouverts.append((rel, list(tests or [])))
        return {"verdict": "SURVIT"}

    def perimetre_mesure(self, rel, racine=None, max_tests=8):
        return MJ.perimetre_mesure(rel, racine=racine, max_tests=max_tests)


def _soumettre(monkeypatch, tmp_path, verdict, tests=None, perimetre=None):
    double = _JugeDouble(verdict)
    if perimetre is not None:
        double.perimetre_mesure = lambda rel, racine=None, max_tests=8: list(perimetre)
    monkeypatch.setitem(sys.modules, "forge_mutation_judge", double)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_mutation_judge", double)
    # ⚠️ LES DEUX CLEFS NE SUFFISENT PAS. `submit_candidate_to_judge` fait
    # `from nokido_agent.app import forge_mutation_judge as juge` — cette forme
    # lit l'ATTRIBUT du paquet AVANT `sys.modules`. Des qu'un autre test du meme
    # processus a importe le vrai juge, l'attribut passe devant le double : le
    # VRAI juge tourne, et la docstring de ce fichier — « hermetique, aucune
    # mutation, aucun git, aucun test reellement joue » — devient fausse.
    # Mesure 2026-09-10, CI de reference sur f8d71d2d5 : 7 tests rouges ici.
    paquet = sys.modules.get("nokido_agent.app")
    if paquet is not None and hasattr(paquet, "forge_mutation_judge"):
        monkeypatch.setattr(paquet, "forge_mutation_judge", double)
    monkeypatch.setattr(AL, "_EVOLUTION_CANDIDATES", tmp_path / "cands")
    monkeypatch.setattr(AL, "record_evolution_experience", lambda rec: "exp_test")
    r = AL.submit_candidate_to_judge("ref", "app/forge_x.py", "x = 1\n", tests)
    return double, r


def test_la_boucle_emprunte_le_chemin_FERME(monkeypatch, tmp_path):
    d, r = _soumettre(monkeypatch, tmp_path, {"verdict": "AMELIORE"}, tests=["tests/t.py"])
    assert d.appels_fermes, "la boucle doit appeler juger_module_avec_gain"
    assert not d.appels_ouverts, "elle ne doit PLUS appeler juger_module (sans gain)"


def test_sans_tests_fournis_elle_COMPLETE_par_le_perimetre(monkeypatch, tmp_path):
    """Le juge ne peut pas inventer ce qu'est une amelioration : il faut lui donner
    quoi jouer. Sans ce complement, tout finirait en GAIN_INDECIDABLE."""
    d, r = _soumettre(monkeypatch, tmp_path, {"verdict": "AMELIORE"},
                      tests=None, perimetre=["tests/nr/test_forge_x_nr.py"])
    assert d.appels_fermes[0][1] == ["tests/nr/test_forge_x_nr.py"]


def test_des_tests_EXPLICITES_priment_sur_le_perimetre(monkeypatch, tmp_path):
    d, r = _soumettre(monkeypatch, tmp_path, {"verdict": "AMELIORE"},
                      tests=["tests/choisi.py"], perimetre=["tests/nr/test_forge_x_nr.py"])
    assert d.appels_fermes[0][1] == ["tests/choisi.py"]


def test_AMELIORE_attend_la_decision_owner(monkeypatch, tmp_path):
    _, r = _soumettre(monkeypatch, tmp_path, {"verdict": "AMELIORE"}, tests=["tests/t.py"])
    assert r["status"] == "AWAITING_OWNER_COMMIT"


def test_GAIN_INDECIDABLE_est_TERMINAL_et_nomme_le_manque(monkeypatch, tmp_path):
    """Ni SURVIT ni echec : un etat qui DESIGNE l'instrument a construire."""
    _, r = _soumettre(monkeypatch, tmp_path, {"verdict": "GAIN_INDECIDABLE"}, tests=[])
    assert r["status"] == "PERIMETRE_MANQUANT"
    assert r["status"] != "AWAITING_OWNER_COMMIT"


def test_SURVIT_SANS_GAIN_est_un_REFUS(monkeypatch, tmp_path):
    """Mesure faite, aucun gain : on ne conserve pas, tests verts ou non."""
    _, r = _soumettre(monkeypatch, tmp_path, {"verdict": "SURVIT_SANS_GAIN"}, tests=["tests/t.py"])
    assert r["status"] == "REJECTED"


def test_MEURT_reste_un_REFUS(monkeypatch, tmp_path):
    _, r = _soumettre(monkeypatch, tmp_path, {"verdict": "MEURT"}, tests=["tests/t.py"])
    assert r["status"] == "REJECTED"


def test_un_verdict_INCONNU_ne_tombe_pas_du_cote_sain(monkeypatch, tmp_path):
    """Liste BLANCHE : n'est promu que ce qui est PROUVE meilleur."""
    _, r = _soumettre(monkeypatch, tmp_path, {"verdict": "UN_TRUC_NEUF"}, tests=["tests/t.py"])
    assert r["status"] != "AWAITING_OWNER_COMMIT"
