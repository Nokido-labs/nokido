"""NR -- decision owner 28/10 : un worktree se distingue PAR ECRIVAIN, pas par protocole.

Le routeur prenait nokido_worktrees/<cli> : pour codex, c'etait le worktree de l'EXECUTEUR Codex -- une session
/acp et une tache deleguee pouvaient ecrire dans le meme arbre (clobber). La session ACP interactive est une surface
d'ecriture a part : nokido_worktrees/acp_<cli>.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402
import forge_worktree as W  # noqa: E402


def test_le_routeur_demande_le_worktree_acp_de_l_agent(monkeypatch):
    demandes = []
    monkeypatch.setattr(W, "route", lambda agent: demandes.append(agent) or "C:/wt/" + agent)
    for cli in ("claude", "codex", "opencode"):
        assert R._route_worktree(cli) == "C:/wt/acp_" + cli
    assert demandes == ["acp_claude", "acp_codex", "acp_opencode"]


def test_jamais_le_worktree_d_un_executeur(monkeypatch):
    monkeypatch.setattr(W, "route", lambda agent: "C:/wt/" + agent)
    assert R._route_worktree("codex") != "C:/wt/codex"
