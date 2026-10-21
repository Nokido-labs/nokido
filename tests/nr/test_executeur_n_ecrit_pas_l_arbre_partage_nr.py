# -*- coding: utf-8 -*-
"""NR -- un executeur AUTONOME n'ecrit jamais dans l'arbre partage par governed_edit (19/10, vague 0 du plan owner).

Mesure du 19/10 : OPENCODE_GLM (job_c0eab523) a ECRASE dans le depot principal app/forge_token_monitor.py
(681 -> 71 lignes) et app/forge_llm_usage_adapters.py (215 -> 22) ; OPENCODE_NEMOTRON y a laisse un lot et une
moitie de correctif de forge_mcp_registry. Vecteur : governed_edit vise l'arbre PRINCIPAL ; les executeurs doivent
ecrire en NATIF dans leur worktree. Restaurer a demande le mode DEV owner.
Contrat (tools/forge_governed_edit.governed_write, garde EN TETE, avant tout effet de bord) :
  1. un executeur du perimetre owner (19/10 : OPENCODE_* et WORKER_CODE) dont l'identite
     (config/agent_identities.json) porte surface == "autonomous" est REFUSE (blocked = "arbre_partage") et la
     raison lui dit d'ecrire dans son worktree ; rien n'est ecrit ;
  2. les alias et la casse sont reconnus (« opencode_glm ») ;
  3. un agent interactif (CLAUDE) n'est pas concerne ; un autonome HORS perimetre (AGY_DAEMON) non plus, tant
     que son usage n'est pas verifie (decision owner 19/10) ;
  4. identites ILLISIBLES : pas de refus (on ne peut pas prouver que c'est un executeur) -- dit au journal.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_governed_edit as ge  # noqa: E402

pytestmark = pytest.mark.timeout(60)

IDENTITES = {"agents": {
    "OPENCODE_GLM": {"surface": "autonomous", "kind": "daemon", "aliases": ["opencode_glm", "agt_glm"]},
    "WORKER_CODE": {"surface": "autonomous", "kind": "relay", "aliases": ["worker_code"]},
    "CLAUDE": {"surface": "interactive", "kind": "cli"},
    "AGY_DAEMON": {"surface": "autonomous", "kind": "daemon"},
}}


@pytest.fixture()
def identites(monkeypatch):
    monkeypatch.setattr(ge, "_identites_agents", lambda: IDENTITES)


@pytest.mark.parametrize("agent", ["OPENCODE_GLM", "opencode_glm", "agt_glm", "WORKER_CODE"])
def test_un_executeur_autonome_est_refuse_sans_rien_ecrire(agent, identites, tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "ROOT", tmp_path)
    r = ge.governed_write("app/forge_token_monitor.py", "x = 1\n", agent=agent)
    assert r["ok"] is False and r["blocked"] == "arbre_partage"
    assert "worktree" in r["reason"]
    assert not (tmp_path / "app" / "forge_token_monitor.py").exists()


def test_un_agent_interactif_n_est_pas_concerne(identites):
    assert ge._executeur_autonome("CLAUDE") is False
    assert ge._executeur_autonome("OPENCODE_GLM") is True


def test_un_autonome_hors_perimetre_owner_n_est_pas_concerne(identites):
    assert ge._executeur_autonome("AGY_DAEMON") is False


def test_identites_illisibles_ne_bloquent_pas(monkeypatch):
    monkeypatch.setattr(ge, "_identites_agents", lambda: None)
    assert ge._executeur_autonome("OPENCODE_GLM") is False
