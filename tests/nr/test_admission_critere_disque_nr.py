# -*- coding: utf-8 -*-
"""NR (owner 3/11 « des garde-fous E/S sur le disque avaient ete mis en place, pourquoi ca a ete contourne ? ») :
l'admission des jobs ne regardait que la RAM et le CPU -- quatre jobs ont parcouru plus d'un million de fichiers sur C:
(22:17-22:26) sans qu'aucun garde ne les voie. Le debit disque du sampler (ior + iow, Mo/s) entre dans le verdict :
OBSERVE d'abord (journalise, ne refuse rien), BLOQUANT sur LAFORGE_ADMISSION_DISQUE=bloquant. Debit illisible : jamais
un refus (garde neuf ; la RAM reste fail-closed)."""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_lane_admission as A  # noqa: E402


def test_decision_disque_pure():
    assert A.decision_disque({"io_mo_s": A.MAX_IO_MO_S + 40})["ok"] is False
    assert A.decision_disque({"io_mo_s": 1.0})["ok"] is True
    assert A.decision_disque({})["ok"] is None            # illisible : ni oui ni non


@pytest.fixture
def sain(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "_ram_saturee", lambda h: False)
    monkeypatch.setattr(A, "_ram_decision", lambda h: {"ok": True})
    monkeypatch.setattr(A, "_FICHIER_OBSERVATION_DISQUE", str(tmp_path / "obs_disque.jsonl"))

    def poser(io):
        h = {"cpu_pct": 10.0, "ram_pct": 50.0, "ram_dispo_gb": 10.0, "source": "sampler"}
        if io is not None:
            h["io_mo_s"] = io
        monkeypatch.setattr(A, "_get_system_health", lambda: dict(h))
    return poser, tmp_path / "obs_disque.jsonl"


def test_observer_journalise_et_admet(sain, monkeypatch):
    poser, obs = sain
    monkeypatch.setattr(A, "MODE_DISQUE", "observer")
    poser(A.MAX_IO_MO_S + 40)
    r = A._check_ressources_brut(True)
    assert r["ok"] is True and r["disque_observe"]["ok"] is False
    ligne = json.loads(obs.read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["decision_disque"] is False and ligne["mode"] == "observer"


def test_bloquant_refuse_sur_debit(sain, monkeypatch):
    poser, _ = sain
    monkeypatch.setattr(A, "MODE_DISQUE", "bloquant")
    poser(A.MAX_IO_MO_S + 40)
    r = A._check_ressources_brut(True)
    assert r["ok"] is False and "DISQUE" in r["reason"]


def test_bloquant_debit_illisible_ne_refuse_pas(sain, monkeypatch):
    poser, _ = sain
    monkeypatch.setattr(A, "MODE_DISQUE", "bloquant")
    poser(None)
    assert A._check_ressources_brut(True)["ok"] is True


def test_le_debit_vient_de_l_emetteur_reel(monkeypatch):
    # 3/11 22:47 (preuve apres restart) : le snapshot du sampler NE porte PAS ior/iow -- ils ne vivent que dans
    # l'historique des vitaux. La 1re version de ce test lisait un snapshot invente : vert sur une fiction, garde
    # aveugle en vrai (io_mo_s null). Le debit vient de dernier_debit_disque (publie a l'ecriture de l'historique).
    import time
    snap = {"ts": time.time(), "cpu_pct": 12.0}            # forme REELLE : pas de ior/iow
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager",
                        types.SimpleNamespace(get_snapshot=lambda: snap,
                                              dernier_debit_disque=lambda max_age_s=90.0: 57.5))
    h = A._get_system_health()
    assert h["source"] == "sampler" and h["io_mo_s"] == pytest.approx(57.5)


def test_debit_perime_reste_illisible(monkeypatch):
    import time
    snap = {"ts": time.time(), "cpu_pct": 12.0}
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager",
                        types.SimpleNamespace(get_snapshot=lambda: snap, dernier_debit_disque=lambda max_age_s=90.0: None))
    assert "io_mo_s" not in A._get_system_health()
