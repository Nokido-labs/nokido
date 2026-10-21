"""NR -- le gate de capacites rappelle qu'un run_job ne prend PAS de liste en `script_args`.

Mesure 19/10 (job_b5e587877d83) : run_job{script: tools/ci_local.py, script_args: ["--impacte"]} -> le script a recu
le LITTERAL « [--impacte] » (rc=2 « unrecognized arguments ») ; trusted_script, lui, accepte la liste. Une liste
etait INVISIBLE au gate (_texte_commande ne lisait que les chaines).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import hook_capability_gate as G  # noqa: E402


def _rappels(entree):
    txt = G._texte_commande(entree)
    return [msg for rx, msg in G._regles_du_shell(entree) if rx.search(txt)]


def test_run_job_avec_une_liste_est_rappele():
    e = {"action": "run_job", "script": "tools/ci_local.py", "script_args": ["--impacte"], "lane": "ci"}
    assert any("LISTE" in m for m in _rappels(e))


def test_run_job_avec_une_chaine_ne_l_est_pas():
    e = {"action": "run_job", "script": "tools/ci_local.py", "script_args": "--impacte", "lane": "ci"}
    assert not any("LISTE" in m for m in _rappels(e))


def test_trusted_script_avec_une_liste_ne_l_est_pas():
    e = {"action": "trusted_script", "path": "tools/forge_governed_commit.py", "script_args": ["--message", "x"]}
    assert not any("LISTE" in m for m in _rappels(e))
