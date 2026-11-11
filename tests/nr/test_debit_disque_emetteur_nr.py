# -*- coding: utf-8 -*-
"""NR (3/11, preuve apres restart : io_mo_s null) : un garde branche sur un signal que PERSONNE n'emet. Le debit disque
(ior/iow, Mo/s, forge_vitals_channels) n'etait calcule qu'a l'ecriture de l'historique des vitaux, jamais publie.
_append_vitals_history publie desormais le dernier debit horodate ; dernier_debit_disque(max_age_s) le rend, ou None
s'il est perime ou jamais mesure (UNKNOWN, jamais 0)."""
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_resource_manager as RM  # noqa: E402


def test_l_historique_publie_le_dernier_debit(monkeypatch):
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_vitals_channels",
                        types.SimpleNamespace(echantillon=lambda palier: {"ior": 50.0, "iow": 7.5}))
    monkeypatch.setattr(RM, "_ecrire_jsonl", lambda *a, **k: None)
    monkeypatch.setattr(RM, "_last_vitals_write_ts", 0.0)
    monkeypatch.setattr(RM, "_DEBIT_DISQUE", {})
    RM._append_vitals_history({"ts": time.time()})
    assert RM.dernier_debit_disque() == pytest.approx(57.5)


def test_debit_perime_ou_absent_none(monkeypatch):
    monkeypatch.setattr(RM, "_DEBIT_DISQUE", {})
    assert RM.dernier_debit_disque() is None
    monkeypatch.setattr(RM, "_DEBIT_DISQUE", {"ts": time.time() - 3600, "ior": 50.0, "iow": 7.5})
    assert RM.dernier_debit_disque(max_age_s=90.0) is None
