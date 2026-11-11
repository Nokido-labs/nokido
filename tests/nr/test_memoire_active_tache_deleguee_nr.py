# -*- coding: utf-8 -*-
"""NR -- geste 2a de la cognition centralisee (owner 8/11, Gate G2) : la tache deleguee recoit la MEME memoire de
travail que Claude a chaque tour. Le bloc est ajoute APRES le contexte allege, dans les TROIS fichiers (GEMINI.md,
AGENTS.md, CLAUDE.md), borne a 1200 caracteres. Un projeter qui leve est DIT (« ILLISIBLE ») et les fichiers sont
quand meme ecrits : une memoire muette ne casse pas la tache, mais ne se fait pas passer pour un succes.

Hermetique : projeter/rendre sont des faux modules injectes dans sys.modules, worktree factice dans tmp_path.
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as fte  # noqa: E402

FICHIERS = ("GEMINI.md", "AGENTS.md", "CLAUDE.md")


def _git(d, *a):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(d), *a],
                          capture_output=True, text=True, errors="replace")


def _depot(tmp_path):
    d = tmp_path / "wt"
    d.mkdir()
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    for nom in FICHIERS:
        (d / nom).write_text("contexte long\n" * 500, encoding="utf-8")
    _git(d, "add", *FICHIERS)
    _git(d, "commit", "-q", "-m", "init")
    return d


def _faux_module(monkeypatch, projeter, rendre):
    """Injecte le faux module sous les DEUX clefs que le code peut adresser (pont nokido_agent + repli plat)."""
    m = types.ModuleType("forge_memoire_active")
    m.projeter = projeter
    m.rendre = rendre
    monkeypatch.setitem(sys.modules, "forge_memoire_active", m)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_memoire_active", m)
    return m


def test_bloc_present_dans_les_trois_fichiers(tmp_path, monkeypatch):
    vus = []

    def projeter(intention, budget_chars=1200):
        vus.append((intention, budget_chars))
        return {"strates": {}, "non_vu": {}, "ecarte": 0}

    _faux_module(monkeypatch, projeter, lambda proj: "MARQUEUR_MEMOIRE_XYZ")
    d = _depot(tmp_path)
    fte._alleger_contexte_tache(d, "tache de test : ajouter la memoire")
    for nom in FICHIERS:
        t = (d / nom).read_text(encoding="utf-8")
        assert "# Memoire de travail (Nokido)" in t
        assert "MARQUEUR_MEMOIRE_XYZ" in t
        # le bloc vient APRES le contexte allege
        assert t.index("Regles permanentes") < t.index("# Memoire de travail (Nokido)")
    # la description de la tache est bien l'intention ; budget serre
    assert vus and vus[0][0] == "tache de test : ajouter la memoire"
    assert all(b == 1200 for _, b in vus)
    # meme rendu pour les trois fichiers
    rendus = {(d / n).read_text(encoding="utf-8") for n in FICHIERS}
    assert len(rendus) == 1


def test_budget_borne_a_1200(tmp_path, monkeypatch):
    _faux_module(monkeypatch, lambda intention, budget_chars=1200: {"strates": {}, "non_vu": {}, "ecarte": 0},
                 lambda proj: "A" * 5000)
    d = _depot(tmp_path)
    fte._alleger_contexte_tache(d, "x")
    t = (d / "GEMINI.md").read_text(encoding="utf-8")
    corps = t.split("# Memoire de travail (Nokido)", 1)[1]
    assert len(corps.strip()) <= 1200


def test_projeter_qui_leve_dit_illisible_et_ecrit_quand_meme(tmp_path, monkeypatch):
    def projeter(intention, budget_chars=1200):
        raise TypeError("panne de la memoire")

    _faux_module(monkeypatch, projeter, lambda proj: "jamais atteint")
    d = _depot(tmp_path)
    fte._alleger_contexte_tache(d, "tache")
    for nom in FICHIERS:
        t = (d / nom).read_text(encoding="utf-8")
        assert "Memoire de travail (Nokido)" in t
        assert "ILLISIBLE (TypeError)" in t
        # les fichiers sont quand meme ecrits avec le contexte allege
        assert "Regles permanentes" in t
