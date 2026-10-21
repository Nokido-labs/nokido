# -*- coding: utf-8 -*-
"""NR -- planificateur AlphaGo de la roadmap : PUCT sur (item, repondeur), en OBSERVATION (decisions owner 18/10).

Owner, 18/10 ~23 h 40 : « as-tu seulement classe les evolutions demandees et donc aussi les roadmap en arene darwinienne
et arbre MCTS avec la logique AlphaGo pour developper intelligemment et collaborativement les suites demandees ? » --
non : les attributions etaient choisies a la main. Decisions owner (choix multiple) : planificateur en OBSERVATION puis
armement sur decision ; arene en DUEL pour les items P0/P1 de code (deux executeurs gratuits, l'oracle gele departage).
Existant etendu : forge_roadmap_keeper.arbre (l'etat), forge_motivation (force mesuree = valeur Q).

Contrats :
  1. classe_item : un reste qui demande du code (RED/GREEN, cabler, implementer, ecrire) -> M:ecrit ; sinon M:lit ;
  2. seuls les items OUVERTS (PARTIEL/OUVERT) sont jouables : CLOS, GELE, OWNER_PLANIFIE, SANS_MARQUEUR,
     DECISION_OWNER ecartes, et le nombre ecarte est DIT ;
  3. PUCT = Q + c.P.sqrt(N)/(1+n) : le fort en ecriture recoit le P0 de code, le fort en lecture l'enquete ;
  4. un item deja beaucoup visite cede la place a un item neuf de meme priorite (exploration) ;
  5. un P0/P1 de code part en DUEL chez les deux meilleurs ecrivains libres ; un P2 jamais ;
  6. le drapeau CLI --plan traverse le chemin reel (arbre et registre de recompense rediriges par l'environnement).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_roadmap_keeper as K  # noqa: E402

RES = [
    {"repondeur": "OPENCODE_NEMOTRON", "classe": "M:ecrit", "verdict": "INTEGREE"},
    {"repondeur": "OPENCODE_GPTOSS", "classe": "M:ecrit", "verdict": "INTEGREE"},
    {"repondeur": "ANTIGRAVITY", "classe": "M:ecrit", "verdict": "REJETEE"},
    {"repondeur": "ANTIGRAVITY", "classe": "M:lit", "verdict": "INTEGREE"},
]


def _it(cle, etat="PARTIEL", prio="P1", reste="RED puis GREEN dans app/x.py"):
    return {"cle": cle, "etat": etat, "priorite": prio, "reste": reste}


def test_classe_item():
    assert K.classe_item(_it("a", reste="ecrire le RED puis le GREEN")) == "M:ecrit"
    assert K.classe_item(_it("b", reste="cabler forge_x dans le chemin de promotion")) == "M:ecrit"
    assert K.classe_item(_it("c", reste="enqueter sur la cause et constater un reveil")) == "M:lit"


def test_seuls_les_items_ouverts_sont_jouables():
    items = [_it("ok"), _it("c", "CLOS"), _it("g", "GELE"), _it("o", "OWNER_PLANIFIE"), _it("s", "SANS_MARQUEUR"),
             _it("d", "DECISION_OWNER")]
    p = K.plan_puct(items, ["OPENCODE_NEMOTRON"], RES)
    assert [a["cle"] for a in p["attributions"]] == ["ok"]
    assert p["ecartes"] == 5


def test_le_fort_en_ecriture_prend_le_code_et_le_fort_en_lecture_l_enquete():
    items = [_it("code", prio="P0"), _it("enquete", prio="P1", reste="enqueter et constater")]
    p = K.plan_puct(items, ["ANTIGRAVITY", "OPENCODE_NEMOTRON"], RES, duel=False)
    par = {a["repondeur"]: a["cle"] for a in p["attributions"]}
    assert par == {"OPENCODE_NEMOTRON": "code", "ANTIGRAVITY": "enquete"}


def test_un_item_tres_visite_cede_a_un_neuf_de_meme_priorite():
    items = [_it("vieux", prio="P1"), _it("neuf", prio="P1")]
    p = K.plan_puct(items, ["OPENCODE_NEMOTRON"], RES, visites={"vieux": 12}, duel=False)
    assert p["attributions"][0]["cle"] == "neuf"


def test_duel_sur_p1_de_code_jamais_sur_p2():
    p = K.plan_puct([_it("fort", prio="P1")], ["OPENCODE_NEMOTRON", "OPENCODE_GPTOSS"], RES)
    assert sorted(a["repondeur"] for a in p["attributions"] if a["cle"] == "fort") == \
        ["OPENCODE_GPTOSS", "OPENCODE_NEMOTRON"]
    assert all(a["duel"] for a in p["attributions"])
    p2 = K.plan_puct([_it("faible", prio="P2")], ["OPENCODE_NEMOTRON", "OPENCODE_GPTOSS"], RES)
    assert len([a for a in p2["attributions"] if a["cle"] == "faible"]) == 1


def test_sans_arbre_fourni_le_plan_ecrit_son_arbre_dans_le_sandbox(monkeypatch, tmp_path):
    """Mesure 18/10 : `arbre()` sans `out` ecrit docs/roadmap_arbre.json -> PermissionError sous le compte bac a sable."""
    vus = {}

    def _arbre(out=None):
        vus["out"] = out
        return {"items": [_it("code", prio="P0")]}

    monkeypatch.delenv("NOKIDO_PLAN_ARBRE", raising=False)
    monkeypatch.setenv("NOKIDO_PLAN_JOURNAL", str(tmp_path / "plan.jsonl"))
    monkeypatch.setenv("NOKIDO_MOTIVATION_RESULTATS", str(tmp_path / "vide.jsonl"))
    monkeypatch.setattr(K, "arbre", _arbre)
    K._plan_cli(["OPENCODE_NEMOTRON"])
    assert vus["out"] and "sandbox" in str(vus["out"]).replace("\\", "/")


def test_le_drapeau_plan_traverse_le_chemin_reel(tmp_path):
    (tmp_path / "arbre.json").write_text(json.dumps({"items": [_it("code", prio="P0")]}), encoding="utf-8")
    (tmp_path / "r.jsonl").write_text("\n".join(json.dumps(r) for r in RES) + "\n", encoding="utf-8")
    env = {**os.environ, "NOKIDO_PLAN_ARBRE": str(tmp_path / "arbre.json"),
           "NOKIDO_MOTIVATION_RESULTATS": str(tmp_path / "r.jsonl"),
           "NOKIDO_PLAN_JOURNAL": str(tmp_path / "plan.jsonl"), "PYTHONNOUSERSITE": "1"}
    r = subprocess.run([sys.executable, str(RACINE / "tools" / "forge_roadmap_keeper.py"), "--plan",
                        "--libres", "ANTIGRAVITY,OPENCODE_NEMOTRON"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, errors="replace", env=env, timeout=60, cwd=str(RACINE))
    assert r.returncode == 0, r.stderr[-800:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["mode"] == "OBSERVATION"
    assert {a["repondeur"] for a in out["attributions"]} >= {"OPENCODE_NEMOTRON"}
    assert (tmp_path / "plan.jsonl").exists()
