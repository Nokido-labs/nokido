# -*- coding: utf-8 -*-
"""NR (31/10) : le circadien ne relance JAMAIS un service lui-meme, et ses refus se disent.

Historique mesure le 31/10 : 11:21:49 et 11:51:49, POST /supervisor/restart SANS jeton -> REFUS 401 x4 par NREM3,
refus muet ; 0d5ade792 (passer par le hub sous l'identite CIRCADIAN) -> 12:51:49 [RBAC] DENY manage_forge_lifecycle
(ring 3 < 1). Remplace par le choix owner « demande au regulateur » (NR test_circadien_demande_au_regulateur_nr) :
ce fichier garde les invariants qui survivent -- aucun appel direct au superviseur ni au hub, identite CIRCADIAN
declaree (elle signe les demandes), une demande non posee est un echec DIT.
"""
# pylint: disable=missing-function-docstring
import inspect
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_circadian as fc  # noqa: E402


def test_plus_aucun_appel_direct_au_superviseur_ni_au_hub():
    src = inspect.getsource(fc._restart_service)
    assert "/supervisor/restart/" not in src and "manage_forge_lifecycle\"," not in src
    assert "urlopen" not in src and "HubClient" not in src


def test_l_identite_circadian_est_declaree_ring_3():
    reg = json.loads((ROOT / "config" / "agent_identities.json").read_text(encoding="utf-8"))
    agents = reg.get("agents", reg)
    assert agents["CIRCADIAN"]["ring"] == 3
    assert agents["CIRCADIAN"]["audience"].endswith(":8766/mcp")


def test_une_demande_non_posee_est_un_echec_dit(monkeypatch, caplog):
    for nom in ("nokido_agent.app.forge_opsec", "forge_opsec"):
        try:
            mod = __import__(nom, fromlist=["is_human_locked"])
            monkeypatch.setattr(mod, "is_human_locked", lambda *a, **k: False)
        except ImportError:
            pass

    def refuse(*a, **k):
        raise RuntimeError("base des demandes verrouillee")
    for nom in ("nokido_agent.app.forge_organ_demand", "forge_organ_demand"):
        try:
            mod = __import__(nom, fromlist=["acquerir"])
            monkeypatch.setattr(mod, "acquerir", refuse)
        except ImportError:
            pass
    with caplog.at_level(logging.WARNING):
        r = fc._restart_service("NokidoNightTrainer")
    assert r["ok"] is False and "NokidoNightTrainer" in caplog.text and "CIRCADIAN" in caplog.text
