# -*- coding: utf-8 -*-
"""NR -- Visibilité des processus : volet IDENTITÉ DÉCLARÉE & orphelins prouvés.

Owner 9/11 : « Nokido doit avoir une visibilité parfaite sur ses processus, sinon il ne pourra jamais s'autoréguler ».
(1) Le battement de chaque exécuteur porte agent et enfants (pids des processus enfants vivants).
(2) forge_process_inventory :
    - un pid présent dans enfants d'un battement est attribué à cet exécuteur (preuve « battement_enfant ») ;
    - nouveau champ du rapport collect() « orphelins_prouves » = processus déclarés enfants par le DERNIER
      battement d'un exécuteur dont le pid est MORT (ou dont le parent est mort), avec :
      {pid, nom, rss_mo, executeur, battement_ts}.
    Sans cette preuve : jamais « orphelin » (INCERTAIN) — constitution UNKNOWN ≠ NO.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_process_inventory as inv

T0 = 1_792_000_000.0


def _faux_vivants():
    return {
        1: {"nom": "nssm.exe", "ppid": 0, "rss_mo": 10.0, "cree": T0 - 1000},
        1000: {"nom": "python.exe", "ppid": 1, "rss_mo": 50.0, "cree": T0 - 500},
        2000: {"nom": "opencode.exe", "ppid": 1000, "rss_mo": 322.0, "cree": T0 - 400},
        3000: {"nom": "opencode.exe", "ppid": 9999, "rss_mo": 150.0, "cree": T0 - 300},
    }


def test_processus_enfant_attribue_par_battement_enfant():
    vivants = _faux_vivants()
    battements = {
        1000: {
            "identite": "task_executor_opencode_glm.heartbeat",
            "ts": T0,
            "enfants": [2000],
            "agent": "OPENCODE_GLM",
        }
    }
    ids, non = inv.identifier_processus(vivants, {}, {}, battements, maintenant=T0)
    assert 2000 in ids
    assert ids[2000]["preuve"] == "battement_enfant"
    assert ids[2000]["identite"] == "task_executor_opencode_glm.heartbeat"


def test_orphelin_prouve_dans_rapport_collect_quand_executeur_mort(monkeypatch):
    # Executor pid 1000 est MORT (absent de vivants)
    vivants = {
        1: {"nom": "nssm.exe", "ppid": 0, "rss_mo": 10.0, "cree": T0 - 1000},
        2000: {"nom": "opencode.exe", "ppid": 1000, "rss_mo": 322.0, "cree": T0 - 400},
    }
    battements = {
        1000: {
            "identite": "task_executor_opencode_glm.heartbeat",
            "ts": T0,
            "enfants": [2000],
            "agent": "OPENCODE_GLM",
        }
    }
    monkeypatch.setattr(inv, "_vivants", lambda: (vivants, 0))
    monkeypatch.setattr(inv, "_ports", lambda: {})
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: battements)

    rapport = inv.collect(registre={})
    assert "orphelins_prouves" in rapport
    orphelins = rapport["orphelins_prouves"]
    assert len(orphelins) == 1
    o = orphelins[0]
    assert o["pid"] == 2000
    assert o["nom"] == "opencode.exe"
    assert o["rss_mo"] == 322.0
    assert o["executeur"] == "task_executor_opencode_glm.heartbeat"
    assert o["battement_ts"] == T0


def test_processus_sans_preuve_de_battement_jamais_orphelin(monkeypatch):
    # Pid 3000 a un parent mort (9999 pas dans vivants), mais AUCUN battement ne le declare
    vivants = {
        1: {"nom": "nssm.exe", "ppid": 0, "rss_mo": 10.0, "cree": T0 - 1000},
        3000: {"nom": "opencode.exe", "ppid": 9999, "rss_mo": 150.0, "cree": T0 - 300},
    }
    monkeypatch.setattr(inv, "_vivants", lambda: (vivants, 0))
    monkeypatch.setattr(inv, "_ports", lambda: {})
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: {})

    rapport = inv.collect(registre={})
    assert "orphelins_prouves" in rapport
    assert rapport["orphelins_prouves"] == []


def test_executeur_vivant_et_parent_vivant_ne_rend_pas_enfant_orphelin(monkeypatch):
    # Pid 1000 vivant (parent 1 vivant), pid 2000 vivant declare enfant
    vivants = {
        1: {"nom": "nssm.exe", "ppid": 0, "rss_mo": 10.0, "cree": T0 - 1000},
        1000: {"nom": "python.exe", "ppid": 1, "rss_mo": 50.0, "cree": T0 - 500},
        2000: {"nom": "opencode.exe", "ppid": 1000, "rss_mo": 322.0, "cree": T0 - 400},
    }
    battements = {
        1000: {
            "identite": "task_executor_opencode_glm.heartbeat",
            "ts": T0,
            "enfants": [2000],
            "agent": "OPENCODE_GLM",
        }
    }
    monkeypatch.setattr(inv, "_vivants", lambda: (vivants, 0))
    monkeypatch.setattr(inv, "_ports", lambda: {})
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: battements)

    rapport = inv.collect(registre={})
    assert "orphelins_prouves" in rapport
    assert rapport["orphelins_prouves"] == []
    # Mais le process 2000 est bien identifie
    assert "2000" in rapport.get("identites", {})
    assert rapport["identites"]["2000"]["preuve"] == "battement_enfant"


def test_executeur_vivant_mais_parent_mort_ne_rend_pas_enfant_orphelin(monkeypatch):
    # Relecture Claude 9/11 : pid 1000 (executeur) est VIVANT, seul son lanceur 9999 est mort -> l'enfant a toujours
    # un parent ; le dire orphelin serait une sur-deduction (version AGY inversee).
    vivants = {
        1000: {"nom": "python.exe", "ppid": 9999, "rss_mo": 50.0, "cree": T0 - 500},
        2000: {"nom": "opencode.exe", "ppid": 1000, "rss_mo": 322.0, "cree": T0 - 400},
    }
    battements = {
        1000: {
            "identite": "task_executor_opencode_glm.heartbeat",
            "ts": T0,
            "enfants": [2000],
            "agent": "OPENCODE_GLM",
        }
    }
    monkeypatch.setattr(inv, "_vivants", lambda: (vivants, 0))
    monkeypatch.setattr(inv, "_ports", lambda: {})
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: battements)

    rapport = inv.collect(registre={})
    assert rapport.get("orphelins_prouves", []) == []


def test_pid_recycle_apres_le_battement_jamais_orphelin():
    # Relecture Claude 9/11 : l'executeur 1000 est mort ; le pid 2000 qu'il declarait a ete RECYCLE par un processus
    # ne APRES son dernier battement -> ce n'est pas son enfant.
    vivants = {2000: {"nom": "notepad.exe", "ppid": 4, "rss_mo": 10.0, "cree": T0 + 3600}}
    battements = {1000: {"identite": "task_executor_opencode_glm.heartbeat", "ts": T0, "enfants": [2000]}}
    assert inv._orphelins_prouves(vivants, battements) == []


def test_date_de_creation_illisible_jamais_orphelin():
    vivants = {2000: {"nom": "opencode.exe", "ppid": 1000, "rss_mo": 322.0, "cree": None}}
    battements = {1000: {"identite": "task_executor_opencode_glm.heartbeat", "ts": T0, "enfants": [2000]}}
    assert inv._orphelins_prouves(vivants, battements) == []


def test_dernier_battement_seul_pris_en_compte(monkeypatch):
    # Même exécuteur avec 2 battements : ancien (mort) à T0, nouveau (vivant) à T0 + 100
    vivants = {
        1: {"nom": "nssm.exe", "ppid": 0, "rss_mo": 10.0, "cree": T0 - 1000},
        1050: {"nom": "python.exe", "ppid": 1, "rss_mo": 50.0, "cree": T0 + 90},
        2000: {"nom": "opencode.exe", "ppid": 1000, "rss_mo": 322.0, "cree": T0 - 400},
    }
    battements = {
        1000: {
            "identite": "task_executor_opencode_glm.heartbeat",
            "ts": T0,
            "enfants": [2000],
            "agent": "OPENCODE_GLM",
        },
        1050: {
            "identite": "task_executor_opencode_glm.heartbeat",
            "ts": T0 + 100,
            "enfants": [],
            "agent": "OPENCODE_GLM",
        },
    }
    monkeypatch.setattr(inv, "_vivants", lambda: (vivants, 0))
    monkeypatch.setattr(inv, "_ports", lambda: {})
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: battements)

    rapport = inv.collect(registre={})
    # Le DERNIER battement est pid 1050 (vivant, enfants=[]). Donc pas d'orphelin prouvé par le dernier battement.
    assert rapport.get("orphelins_prouves") == []


def test_pids_enfants_executeur():
    import forge_task_executor as te

    assert hasattr(te, "_pids_enfants")
    enfants = te._pids_enfants()
    assert isinstance(enfants, list)


def test_lecture_battement_charge_enfants_et_agent(tmp_path, monkeypatch):
    import json
    sb = tmp_path / "sandbox"
    sb.mkdir()
    hb = sb / "task_executor_opencode_glm.heartbeat"
    hb.write_text(json.dumps({
        "pid": 5555,
        "ts": "2026-11-09T19:00:00",
        "agent": "OPENCODE_GLM",
        "enfants": [5556, 5557],
    }), encoding="utf-8")

    monkeypatch.setattr(inv, "_donnees", lambda: tmp_path)
    b_map = inv._battements_par_pid()
    assert 5555 in b_map
    assert b_map[5555]["agent"] == "OPENCODE_GLM"
    assert b_map[5555]["enfants"] == [5556, 5557]

