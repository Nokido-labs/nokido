# -*- coding: utf-8 -*-
"""NR -- etape 2 de bb:architecture_rules/P1_worktree_par_provenance_et_reconciliation_20261018 (decision owner 22/10).

Mesure du 22/10 : a CHAQUE livraison, l'executeur `claude -p` a ecrit une copie de ses tests dans l'arbre PARTAGE par
governed_edit (comparer puis retirer a la main). Contrat de `ToolRegistry.handle_governed_edit` :
  1. une provenance EXECUTEUR (identite CLAUDE_HEADLESS / OPENCODE_* / ANTIGRAVITY / MISTRAL, ou en-tete
     LaForge-Provenance TASK_EXECUTOR) ecrit dans nokido_worktrees/<agent> et JAMAIS dans l'arbre partage ;
  2. une provenance owner / inconnue garde le comportement actuel (arbre partage) ;
  3. worktree introuvable -> REFUS explicite (jamais de repli silencieux sur l'arbre partage) ;
  4. un en-tete executeur sans identite qui nomme un worktree -> REFUS (on ne devine pas le worktree).
Tout se passe en repertoires temporaires : depot = tmp/depot, worktrees = tmp/nokido_worktrees (meme parente que
forge_worktree.WT_ROOT = ROOT.parent / "nokido_worktrees").
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(_RACINE / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_mcp_registry import ToolRegistry  # noqa: E402

pytestmark = pytest.mark.timeout(30)


class _Etat:
    def add_notification(self, *a, **k):
        return None


class _Registre:
    def __init__(self, root):
        self.root = root
        self.state_mgr = _Etat()


@pytest.fixture()
def monde(tmp_path):
    depot = tmp_path / "depot"
    depot.mkdir()
    return depot, tmp_path / "nokido_worktrees"


def _wt(wt_root, nom):
    d = wt_root / nom
    d.mkdir(parents=True)
    (d / ".git").write_text("gitdir: ailleurs\n", encoding="utf-8")
    return d


def _appel(depot, args, agent):
    return asyncio.run(ToolRegistry.handle_governed_edit(_Registre(depot), args, agent, 2))


@pytest.mark.parametrize("agent,dossier", [
    ("CLAUDE_HEADLESS", "claude_headless"),
    ("OPENCODE_GLM", "opencode_glm"),
    ("OPENCODE_GPTOSS", "opencode_gptoss"),
    ("ANTIGRAVITY", "antigravity"),
    ("MISTRAL", "mistral"),
])
def test_un_executeur_ecrit_dans_son_worktree_jamais_dans_l_arbre_partage(monde, agent, dossier):
    depot, wt_root = monde
    wt = _wt(wt_root, dossier)
    res = _appel(depot, {"path": "notes/copie.txt", "content": "bonjour\n"}, agent)
    assert '"ok": true' in res, res
    assert (wt / "notes" / "copie.txt").read_text(encoding="utf-8") == "bonjour\n"
    assert not (depot / "notes" / "copie.txt").exists(), "ecriture dans l'ARBRE PARTAGE"


def test_une_provenance_owner_garde_l_arbre_partage(monde):
    depot, wt_root = monde
    _wt(wt_root, "claude_headless")
    for agent in ("CLAUDE", "AGENT_INCONNU_XYZ"):
        res = _appel(depot, {"path": "notes/%s.txt" % agent, "content": "x\n"}, agent)
        assert '"ok": true' in res, res
        assert (depot / "notes" / ("%s.txt" % agent)).exists()
    assert not (wt_root / "claude_headless" / "notes").exists()


def test_worktree_introuvable_refuse_sans_repli_sur_l_arbre_partage(monde):
    depot, wt_root = monde  # aucun worktree cree
    res = _appel(depot, {"path": "notes/copie.txt", "content": "x\n"}, "CLAUDE_HEADLESS")
    assert res.startswith("GOVERNED EDIT BLOCKED (worktree_introuvable)"), res
    assert "claude_headless" in res
    assert not (depot / "notes").exists(), "repli silencieux sur l'arbre partage"


def test_un_dossier_sans_marqueur_git_n_est_pas_un_worktree(monde):
    depot, wt_root = monde
    (wt_root / "mistral").mkdir(parents=True)
    res = _appel(depot, {"path": "a.txt", "content": "x\n"}, "MISTRAL")
    assert res.startswith("GOVERNED EDIT BLOCKED (worktree_introuvable)"), res
    assert not (depot / "a.txt").exists() and not (wt_root / "mistral" / "a.txt").exists()


def test_l_en_tete_task_executor_sans_worktree_nomme_refuse(monde):
    depot, wt_root = monde
    _wt(wt_root, "claude_headless")
    res = _appel(depot, {"path": "a.txt", "content": "x\n", "_provenance": "TASK_EXECUTOR"}, "CLAUDE")
    assert res.startswith("GOVERNED EDIT BLOCKED (worktree_introuvable)"), res
    assert not (depot / "a.txt").exists() and not (wt_root / "claude_headless" / "a.txt").exists()


def test_l_en_tete_task_executor_avec_identite_executeur_va_au_worktree(monde):
    depot, wt_root = monde
    wt = _wt(wt_root, "opencode_glm")
    res = _appel(depot, {"path": "a.txt", "content": "x\n", "_provenance": "TASK_EXECUTOR"}, "OPENCODE_GLM")
    assert '"ok": true' in res, res
    assert (wt / "a.txt").exists() and not (depot / "a.txt").exists()


def test_une_provenance_owner_en_en_tete_ne_change_rien(monde):
    depot, wt_root = monde
    _wt(wt_root, "claude_headless")
    res = _appel(depot, {"path": "a.txt", "content": "x\n", "_provenance": "CLAUDE_CLI"}, "CLAUDE")
    assert '"ok": true' in res, res
    assert (depot / "a.txt").exists()


def test_le_chemin_ne_sort_pas_du_worktree(monde):
    depot, wt_root = monde
    _wt(wt_root, "claude_headless")
    res = _appel(depot, {"path": "../x.txt", "content": "x\n"}, "CLAUDE_HEADLESS")
    assert res.startswith("SECURITY"), res
    assert not (wt_root / "x.txt").exists() and not (depot.parent / "x.txt").exists()
