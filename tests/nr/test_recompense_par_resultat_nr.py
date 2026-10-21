# -*- coding: utf-8 -*-
"""NR -- utilitarisme hedoniste du corps : RECOMPENSE PAR RESULTAT, force mesuree de chaque repondeur (owner 18/10).

Owner, 18/10 ~23 h 10 : « exploite intelligemment le free tier des que c'est possible, avec mesure de la force de chaque
modele ; le temps est precieux ; assigne ce qui est pertinent au repondeur, pas utile s'il faut tout refaire derriere ;
mets en place un utilitarisme hedoniste pour le corps : la notion de recompense par resultat ».
Existant etendu (anti-dup) : app/forge_motivation.py (reward -> DOPAMINE_SUCCESS, punish -> CORTISOL_FRUSTRATION)
n'avait qu'un compteur de frustration par methode : aucune valeur cumulee par repondeur, aucun cout, aucun lecteur
qui choisisse. Mesure du soir : 1edb516b8 (code confie a AGY, tests jamais lances) REJETE -- tout a refaire.

Contrats (registre redirige dans tmp_path, hormones remplacees par des doublures) :
  1. plaisir - douleur : INTEGREE > PARTIELLE > VIDE > REJETEE (un rejet coute le refait) ;
  2. a resultat egal, un repondeur GRATUIT vaut plus qu'un payant ; un agent dont la gratuite n'est pas prouvee
     est compte payant (liste blanche) ;
  3. un verdict INCONNU n'est jamais compte comme 0 ; un verdict hors vocabulaire leve ValueError ;
  4. force par (repondeur, classe) : fort en lecture ne dit rien de l'ecriture ;
  5. ordre : un repondeur prouve bon passe devant un jamais essaye, qui passe devant un prouve mauvais ;
  6. recompenser_resultat ecrit une ligne et passe par le corps : reward sur un succes, punish sur un rejet.
"""
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_motivation as M  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def _r(rep, verdict, classe="M:ecrit", minutes=None):
    return {"repondeur": rep, "classe": classe, "verdict": verdict, "minutes": minutes}


def test_plaisir_moins_douleur_ordonne_les_verdicts():
    v = {x: M.valeur_resultat(x, "OPENCODE_GLM") for x in ("INTEGREE", "PARTIELLE", "VIDE", "REJETEE")}
    assert v["INTEGREE"] > v["PARTIELLE"] > v["VIDE"] > v["REJETEE"]
    assert v["REJETEE"] < 0


def test_le_gratuit_vaut_plus_que_le_payant_et_l_inconnu_est_payant():
    assert M.valeur_resultat("INTEGREE", "OPENCODE_GLM") > M.valeur_resultat("INTEGREE", "CLAUDE")
    assert M.valeur_resultat("INTEGREE", "AGENT_JAMAIS_VU") == M.valeur_resultat("INTEGREE", "CLAUDE")


def test_le_temps_coute():
    assert M.valeur_resultat("INTEGREE", "WORKER_CODE", minutes=60) < M.valeur_resultat("INTEGREE", "WORKER_CODE", 5)


def test_verdict_inconnu_ignore_et_hors_vocabulaire_refuse():
    assert M.valeur_resultat("INCONNU", "OPENCODE_GLM") is None
    f = M.force_repondeurs([_r("A", "INCONNU"), _r("A", "INCONNU")], "M:ecrit")
    assert f.get("A", {}).get("n", 0) == 0 and f.get("A", {}).get("utilite") is None
    with pytest.raises(ValueError):
        M.valeur_resultat("GENIAL", "A")


def test_la_force_se_mesure_par_classe():
    res = [_r("AG", "INTEGREE", "M:lit"), _r("AG", "INTEGREE", "M:lit"), _r("AG", "REJETEE", "M:ecrit")]
    assert M.force_repondeurs(res, "M:lit")["AG"]["utilite"] > 0
    assert M.force_repondeurs(res, "M:ecrit")["AG"]["utilite"] < 0


def test_ordre_prouve_bon_puis_inconnu_puis_prouve_mauvais():
    res = [_r("BON", "INTEGREE"), _r("BON", "INTEGREE"), _r("MAUVAIS", "REJETEE"), _r("MAUVAIS", "VIDE")]
    assert M.ordre_hedoniste(["MAUVAIS", "NEUF", "BON"], "M:ecrit", res) == ["BON", "NEUF", "MAUVAIS"]


def test_recompenser_ecrit_et_passe_par_le_corps(monkeypatch, tmp_path):
    reg = tmp_path / "motivation_resultats.jsonl"
    appels = []
    monkeypatch.setattr(M, "RESULTATS", reg)
    monkeypatch.setattr(M, "reward", lambda method, time_s, n_steps=1, success=True, target="":
                        appels.append(("reward", method, target)) or {"ok": True})
    monkeypatch.setattr(M, "punish", lambda method, error="", target="":
                        appels.append(("punish", method, target)) or {"ok": True})
    M.recompenser_resultat("OPENCODE_NEMOTRON", "M:ecrit", "INTEGREE", minutes=20, preuve="c7e1f498e")
    M.recompenser_resultat("ANTIGRAVITY", "M:ecrit", "REJETEE", minutes=16, preuve="1edb516b8")
    lignes = [json.loads(x) for x in reg.read_text(encoding="utf-8").splitlines()]
    assert [(x["repondeur"], x["verdict"], x["preuve"]) for x in lignes] == [
        ("OPENCODE_NEMOTRON", "INTEGREE", "c7e1f498e"), ("ANTIGRAVITY", "REJETEE", "1edb516b8")]
    assert all("ts" in x and "valeur" in x for x in lignes)
    assert [a[0] for a in appels] == ["reward", "punish"]
    assert appels[0][1] == "executeur:OPENCODE_NEMOTRON:M:ecrit"
