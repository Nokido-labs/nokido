# -*- coding: utf-8 -*-
"""NR (owner 3/11 « routage par capacite » + « ne faudrait-il pas que les delegations soient effectuees par Nokido ? »).

Faits payes le 3/11 : une tache TDD (shell requis) partait chez ANTIGRAVITY puis MISTRAL, qui refusent tout shell
(`denied_actions: unsandboxed RunCommand`, `tool_denied`) -> deux echecs certains avant une surface capable ; une tache
touchant forge_lane_admission.py (ring 0) partait chez un delegue dont le bac console l'a refusee (`requiert ring=0`).

Contrat :
- la consigne declare ses exigences en tete (`exigences: shell, ring0`) ;
- une surface au MANQUE PROUVE n'est jamais choisie pour cette exigence (repli comme choix initial) ;
- `ring0` n'est jamais delegue : la tache revient a CLAUDE ;
- agent=AUTO : Nokido choisit la surface (pre-vol + capacites + ordre), une seule fois (pas de double routage).
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as T  # noqa: E402


def test_exigences_lues_en_tete_de_consigne():
    assert T.exigences_consigne("exigences: shell, ring0\ntaille: S\nfais X") == {"shell", "ring0"}
    assert T.exigences_consigne("Exigences : SHELL\nfais X") == {"shell"}
    assert T.exigences_consigne("fais X sans exigence") == set()
    assert T.exigences_consigne(None) == set()


def test_manques_prouves_seulement():
    assert not T.surface_capable("MISTRAL", {"shell"})
    assert not T.surface_capable("ANTIGRAVITY", {"shell"})
    assert T.surface_capable("CODEX", {"shell"})
    assert T.surface_capable("OPENCODE_DEFAUT2", {"shell"})
    assert T.surface_capable("MISTRAL", set())
    # ring 0 : aucune surface deleguee ne le porte
    assert not T.surface_capable("CODEX", {"ring0"})


@pytest.fixture
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "tasks.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, "
              "reaffectations TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(chemin))
    monkeypatch.setattr(T, "_candidat_eligible", lambda a: True)
    monkeypatch.setattr(T, "autoriser_essai_half_open", lambda a: (True, ""))
    monkeypatch.setattr(T, "_repli_gratuit_seul", lambda: False)
    monkeypatch.setattr(T, "_noter_indisponibilite", lambda *a, **k: False)
    monkeypatch.setattr(T, "_choisir_parmi", lambda vivants, classe, conn: vivants[0] if vivants else None)

    def poser(tid, agent, desc):
        c = sqlite3.connect(chemin)
        c.execute("INSERT INTO tasks (id, agent, status, description) VALUES (?, ?, 'pending', ?)", (tid, agent, desc))
        c.commit()
        c.close()

    def lire(tid):
        c = sqlite3.connect(chemin)
        r = c.execute("SELECT agent, status, reaffectations FROM tasks WHERE id=?", (tid,)).fetchone()
        c.close()
        return r

    return poser, lire


def test_le_repli_saute_les_surfaces_sans_shell(base):
    poser, lire = base
    poser("t1", "OPENCODE_GLM", "exigences: shell\nNR rouge puis code")
    vers = T._reaffecter({"id": "t1", "agent": "OPENCODE_GLM", "description": "exigences: shell\nNR rouge puis code"},
                         "echec", ordre=("ANTIGRAVITY", "MISTRAL", "CODEX"))
    assert vers == "CODEX"
    assert lire("t1")[0] == "CODEX"


def test_ring0_n_est_jamais_reaffecte(base):
    poser, lire = base
    poser("t2", "OPENCODE_GLM", "exigences: ring0\nedite forge_lane_admission.py")
    vers = T._reaffecter({"id": "t2", "agent": "OPENCODE_GLM", "description": "exigences: ring0\nedite X"},
                         "echec", ordre=("CODEX",))
    assert vers is None
    assert lire("t2")[0] == "OPENCODE_GLM"


def test_nokido_choisit_la_surface_d_une_tache_auto(base):
    poser, lire = base
    poser("a1", "AUTO", "exigences: shell\nNR rouge puis code")
    poser("a2", "AUTO", "avis sans exigence")
    poser("a3", "AUTO", "exigences: ring0, shell\nedite forge_lane_admission.py")
    poser("a4", "CODEX", "deja assignee")
    routees = dict(T.router_taches_auto(ordre=("ANTIGRAVITY", "MISTRAL", "CODEX")))
    assert routees == {"a1": "CODEX", "a2": "ANTIGRAVITY", "a3": T.AGENT_RING0}
    assert lire("a1")[0] == "CODEX" and lire("a1")[1] == "pending"
    trace = json.loads(lire("a1")[2])
    assert trace[-1]["de"] == "AUTO" and trace[-1]["vers"] == "CODEX"
    assert lire("a4")[0] == "CODEX"
    # second passage (autre executeur) : plus rien a router, rien ne bouge
    assert T.router_taches_auto(ordre=("ANTIGRAVITY", "MISTRAL", "CODEX")) == []


def test_auto_sans_surface_capable_reste_auto(base):
    poser, lire = base
    poser("a5", "AUTO", "exigences: shell\nNR")
    assert T.router_taches_auto(ordre=("ANTIGRAVITY", "MISTRAL")) == []
    assert lire("a5")[0] == "AUTO"
