# -*- coding: utf-8 -*-
"""Non-regression — la couverture de mesure se REGENERE, elle n'est pas une photo datee.

Question owner du 2026-09-08 : « si ils s'importent par la suite, seront-ils donc
couverts dynamiquement ? ». Reponse mesuree : NON, pas en l'etat — la generation
etait un acte PONCTUEL. Un module repare demain, ou un module neuf ecrit la semaine
prochaine, resterait sans perimetre, et `juger_module_avec_gain` continuerait a rendre
GAIN_INDECIDABLE sur lui sans que personne ne le sache.

C'est le motif deja paye deux fois dans ce depot : un garde branche sur un signal que
PERSONNE n'emet. La mesure existe, aucun emetteur ne la rafraichit.

D'ou ce cablage, en phase NREM1 (sommeil leger), aux cotes de l'audit de conformite
pose le 2026-09-04 pour exactement la meme raison : « un audit qui depend d'un agent
pour s'executer n'est pas une capacite du systeme ».

DEUX EXIGENCES, chacune adossee a un piege paye :

1. **Le handler ne leve JAMAIS.** Les actions de phase sont best-effort : une action
   qui explose emporterait les suivantes. Mais elle ne se tait pas non plus — un
   `except` muet ferait passer une panne pour un cycle sain.

2. **L'ecriture refusee se DIT, avec son remede.** Le circadien tourne sous un compte
   de service, et `tests/nr/` est ACL-ferme a ces comptes (mesure repetee : le registre
   de vitalite tombe exactement dessus). Un handler qui echouerait en silence ferait
   croire a une regeneration qui n'a jamais lieu. Il MESURE toujours (lecture seule,
   qui marche partout) et NOMME le chemin de reprise privilegie.

Hermetique : handler appele directement, dependances remplacees. Aucun fichier ecrit,
aucun service, aucune phase reellement declenchee.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_circadian as C  # noqa: E402


def test_l_action_est_DECLAREE_en_NREM1():
    """Un handler qui existe mais n'est declare nulle part ne tourne jamais."""
    noms = [a.name for a in C.PHASE_PROGRAM[C.Phase.NREM1]]
    assert "regeneration_perimetre_mesure" in noms, noms


def test_l_action_porte_un_handler_et_un_pourquoi():
    act = [a for a in C.PHASE_PROGRAM[C.Phase.NREM1]
           if a.name == "regeneration_perimetre_mesure"][0]
    assert act.handler is not None
    assert act.service is None, "aucun service a redemarrer : c'est un handler pur"
    assert act.why and len(act.why) > 30, "le pourquoi doit etre lisible dans six mois"


def test_le_handler_rend_les_DEUX_metriques(monkeypatch):
    monkeypatch.setattr(C, "_mesurer_couverture_pour_phase",
                        lambda: {"denominateur": 100,
                                 "perimetre_non_vide": {"n": 20, "part": 20.0},
                                 "couverture_prouvee": {"n": 15, "part": 15.0},
                                 "sans_perimetre": ["app/forge_x.py"]})
    monkeypatch.setattr(C, "_generer_appui_pour_phase", lambda cibles: {"ecrits": [], "non_importables": {}})
    r = C._regenerer_perimetre_mesure()
    assert r["perimetre_non_vide"] == 20
    assert r["couverture_prouvee"] == 15
    assert "score" not in r, "jamais d'agregat : les deux metriques restent disjointes"


def test_le_handler_NE_LEVE_PAS_si_la_mesure_echoue(monkeypatch):
    def _boum():
        raise RuntimeError("base illisible")

    monkeypatch.setattr(C, "_mesurer_couverture_pour_phase", _boum)
    r = C._regenerer_perimetre_mesure()
    assert r["ok"] is False
    assert "RuntimeError" in r["motif"], "l'echec est NOMME, pas avale"


def test_une_ecriture_refusee_est_DITE_avec_son_remede(monkeypatch):
    monkeypatch.setattr(C, "_mesurer_couverture_pour_phase",
                        lambda: {"denominateur": 10,
                                 "perimetre_non_vide": {"n": 1, "part": 10.0},
                                 "couverture_prouvee": {"n": 1, "part": 10.0},
                                 "sans_perimetre": ["app/forge_x.py"]})

    def _refuse(cibles):
        raise PermissionError("[Errno 13] Permission denied: tests/nr")

    monkeypatch.setattr(C, "_generer_appui_pour_phase", _refuse)
    r = C._regenerer_perimetre_mesure()
    # La MESURE a eu lieu : elle est en lecture seule et marche sous tout compte.
    assert r["perimetre_non_vide"] == 1
    assert r["generation"] == "REFUSEE"
    assert "trusted_script" in r["remede"], "un refus sans remede oblige a re-chercher"


def test_le_handler_compte_ce_qu_il_a_genere(monkeypatch):
    monkeypatch.setattr(C, "_mesurer_couverture_pour_phase",
                        lambda: {"denominateur": 10,
                                 "perimetre_non_vide": {"n": 1, "part": 10.0},
                                 "couverture_prouvee": {"n": 1, "part": 10.0},
                                 "sans_perimetre": ["app/forge_a.py", "app/forge_b.py"]})
    monkeypatch.setattr(C, "_generer_appui_pour_phase",
                        lambda cibles: {"ecrits": ["tests/nr/test_appui_forge_a_nr.py"],
                                        "non_importables": {"app/forge_b.py": "NameError: X"}})
    r = C._regenerer_perimetre_mesure()
    assert r["generes"] == 1
    assert r["non_importables"] == 1
    assert r["generation"] == "OK"
