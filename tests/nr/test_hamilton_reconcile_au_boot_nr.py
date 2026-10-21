# -*- coding: utf-8 -*-
"""NR HAMILTON (derogation owner 19/10) : reconcile_jobs tourne au BOOT du hub.

Spec RED_4 (pair_1200324b1e5391b0) : « reconcile_jobs n'a aucun appelant au boot » (introspect 19/10 : 0 appelant).
Au demarrage, les fiches `running` d'avant le restart sont reconciliees : la morte rend sa lane, le survivant
DIFFERABLE est SIGNALE A_SUSPENDRE (jamais de kill). `reconcilier_au_boot` ne leve jamais (un boot ne casse pas pour
un bilan) ; le hub la lance dans un thread, comme ses warmups -- verifie sur l'AST de main() : importer nokido_hub
lancerait le boot.
"""
import ast
from pathlib import Path

from nokido_agent.app import forge_job_runner as J

ROOT = Path(__file__).resolve().parents[2]


def test_reconcilier_au_boot_applique_et_resume(monkeypatch):
    vus = []
    monkeypatch.setattr(J, "reconcile_jobs", lambda apply=False: vus.append(apply) or
                        {"vus": 3, "dead": 1, "a_suspendre": 1, "vivants": 2, "indetermine": 0, "details": []})
    r = J.reconcilier_au_boot()
    assert vus == [True] and r["dead"] == 1 and r["a_suspendre"] == 1


def test_reconcilier_au_boot_ne_leve_jamais(monkeypatch):
    def casse(apply=False):
        raise RuntimeError("fiches illisibles")
    monkeypatch.setattr(J, "reconcile_jobs", casse)
    r = J.reconcilier_au_boot()
    assert r["ok"] is False and "RuntimeError" in r["erreur"]


def test_le_hub_la_lance_au_boot():
    arbre = ast.parse((ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace"))
    main = next(n for n in arbre.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "main")
    src = ast.unparse(main)
    assert "reconcilier_au_boot" in src and "Thread" in src
