# -*- coding: utf-8 -*-
"""NR : l'arene darwinienne est consultee par le merge gate en OBSERVATION (owner 19/10).

Mesure du 19/10 : son scan AST refuse 1393 modules forge_* sur 1453 ; ses tests ne visent
qu'une fonction `solve`. Le merge gate journalise donc son avis sans jamais bloquer, et
sans ecrire dans darwinian_arena.db (un candidat par merge = du bruit en base).
"""
import json

from nokido_agent.tools import forge_merge_gate as mg
from nokido_agent.app import forge_darwinian_arena as arene
from nokido_agent.app import forge_mutation_judge as juge

CONTENUS = {"wip/x:app/pur.py": "def solve(x):\n    return x\n",
            "wip/x:app/sale.py": "import os\n"}


def _faux_git(args, cwd=None):
    if args[0] == "diff":
        return 0, "app/pur.py\napp/sale.py\nREADME.md", ""
    if args[0] == "show":
        return 0, CONTENUS[args[1]], ""
    if args[:2] == ["rev-parse", "--abbrev-ref"]:
        return 0, "alpha", ""
    if args[0] == "status":
        return 0, "", ""
    if args[0] == "merge":
        return 0, "ok", ""
    return 1, "", "inattendu"


def _preparer(monkeypatch, tmp_path):
    monkeypatch.setattr(mg, "evaluer", lambda a, t=None: {"verdict": "AMELIORE", "branch": "wip/x"})
    monkeypatch.setattr(mg, "_git", _faux_git)
    monkeypatch.setattr(mg, "JOURNAL_ARENE", tmp_path / "arene.jsonl")

    def interdit(*a, **k):
        raise AssertionError("observation : aucune ecriture dans darwinian_arena.db")
    monkeypatch.setattr(arene, "submit_candidate", interdit)


def test_merger_observe_l_arene_par_fichier(monkeypatch, tmp_path):
    _preparer(monkeypatch, tmp_path)
    ev = mg.merger("x")
    obs = {f["fichier"]: f for f in ev["arene"]["fichiers"]}
    assert ev["arene"]["mode"] == "observation"
    assert set(obs) == {"app/pur.py", "app/sale.py"}
    assert obs["app/sale.py"]["verdict"] == "REFUS_AST"
    assert obs["app/pur.py"]["verdict"] == "NON_PROMOUVABLE"
    ligne = json.loads((tmp_path / "arene.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["branch"] == "wip/x" and len(ligne["fichiers"]) == 2


def test_merger_n_est_jamais_bloque_par_l_arene(monkeypatch, tmp_path):
    _preparer(monkeypatch, tmp_path)
    monkeypatch.setattr(juge, "evolution_autorisee", lambda: {"autorisee": True})
    ev = mg.merger("x", apply=True)
    assert ev["applique"] is True
    assert ev["arene"]["fichiers"][0]["verdict"] in ("REFUS_AST", "NON_PROMOUVABLE")


def test_arene_illisible_ne_casse_pas_le_merge(monkeypatch, tmp_path):
    _preparer(monkeypatch, tmp_path)
    monkeypatch.setattr(arene, "_ast_safety_scan", lambda c: 1 / 0)
    ev = mg.merger("x")
    assert all(f["verdict"] == "INCONNU" for f in ev["arene"]["fichiers"])
    assert ev["decision"].startswith("AMELIORE")
