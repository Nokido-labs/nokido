# -*- coding: utf-8 -*-
"""NR -- le synchroniseur de skills lit le ring des CLI au REGISTRE VIVANT des identites (15/10).

MESURE QUI L'A DECLENCHE. `CLI_RING` etait une copie a la main de la table des rings : GEMINI y valait
3 quand `config/agent_identities.json` (la source que le hub recharge a chaud) le dit ring 1. forge-core,
client-only gemini, n'etait deployee chez AUCUN CLI. Decision owner : « aligner + rafraichir ».

Contrat :
  1. un ring porte au registre pour l'identite d'un CLI gagne sur la table recopiee ;
  2. registre illisible : la table d'avant, et le synchroniseur le dit sur stderr (jamais en silence) ;
  3. un ring non entier (chaine, booleen) est ignore ;
  4. sur le vrai depot, gemini suit le registre et forge-core a de nouveau une cible gemini ;
  5. claude suit le registre lui aussi (decision owner du 15/10 : « aligner sur le registre »).
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sync = importlib.import_module("forge_skill_sync")


def _registre(tmp_path: Path, agents) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agent_identities.json").write_text(json.dumps({"agents": agents}), encoding="utf-8")
    return tmp_path


def test_le_registre_gagne_sur_la_table(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "ROOT", _registre(tmp_path, {"GEMINI": {"ring": 1}, "CODEX": {"ring": 2},
                                                           "COPILOT": {"ring": 3}, "CLAUDE": {"ring": 1}}))
    assert sync._rings_du_registre() == {"gemini": 1, "codex": 2, "agents_depot": 2, "copilot": 3, "claude": 1}


def test_ring_non_entier_ignore(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "ROOT", _registre(tmp_path, {"GEMINI": {"ring": "1"}, "CODEX": {"ring": True}}))
    assert sync._rings_du_registre() == {}


def test_registre_illisible_le_dit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sync, "ROOT", tmp_path)            # pas de config/agent_identities.json
    assert sync._rings_du_registre() is None
    assert "ILLISIBLE" in capsys.readouterr().err


def test_depot_reel_gemini_suit_le_registre_et_forge_core_a_une_cible():
    agents = json.loads((ROOT / "config" / "agent_identities.json").read_text(encoding="utf-8"))["agents"]
    assert sync.CLI_RING["gemini"] == agents["GEMINI"]["ring"]
    if isinstance((agents.get("CLAUDE") or {}).get("ring"), int):
        assert sync.CLI_RING["claude"] == agents["CLAUDE"]["ring"]
    fm = {}
    if (ROOT / "docs" / "skills" / "forge-core" / "SKILL.md").exists():
        cibles = sync._targets_for("forge-core", fm)
        if agents["GEMINI"]["ring"] <= sync._min_ring_for("forge-core", fm):
            assert "gemini" in cibles, cibles
