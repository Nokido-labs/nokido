# -*- coding: utf-8 -*-
"""NR -- plan d'economie de contexte (owner 1/11, etape 3) : chaque `governed_edit` reussi rendait les memes champs
constants (`note` ~100 car., `avertissement_reflexe` ~250 car.), relus a chaque tour suivant. Un champ deja dit a cet
agent dans l'heure est retire et nomme dans `deja_dit` (le client sait qu'il est OMIS, pas absent) ; un autre agent,
ou le meme apres le delai, le recoit en entier ; `ok`, `verified`, `path` ne sont jamais retires."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app.forge_mcp_registry as M  # noqa: E402
from app.forge_mcp_registry import ToolRegistry  # noqa: E402

NOTE = "AST+secret OK ; tree_lock claim ; contenu RELU verifie ; le git-gate re-scanne au commit"


def _v():
    return {"ok": True, "path": "a.py", "verified": "relecture disque identique", "note": NOTE,
            "avertissement_reflexe": "aucune consultation `introspect` sur cette session avant cette ecriture."}


def test_second_appel_retire_les_champs_deja_dits(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "_CHAMPS_DEJA_DITS", {})
    reg = ToolRegistry(root_dir=tmp_path)
    v1 = reg._dedoublonner_champs(_v(), "CLAUDE", maintenant=1000.0)
    assert v1["note"] == NOTE and "deja_dit" not in v1
    v2 = reg._dedoublonner_champs(_v(), "CLAUDE", maintenant=1010.0)
    assert "note" not in v2 and "avertissement_reflexe" not in v2
    assert v2["deja_dit"] == "avertissement_reflexe,note"
    assert v2["ok"] is True and v2["verified"] and v2["path"] == "a.py"


def test_autre_agent_ou_delai_ecoule_recoit_tout(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "_CHAMPS_DEJA_DITS", {})
    reg = ToolRegistry(root_dir=tmp_path)
    reg._dedoublonner_champs(_v(), "CLAUDE", maintenant=1000.0)
    assert reg._dedoublonner_champs(_v(), "ANTIGRAVITY", maintenant=1001.0)["note"] == NOTE
    assert reg._dedoublonner_champs(_v(), "CLAUDE", maintenant=1000.0 + 3601)["note"] == NOTE


def test_le_retour_de_governed_edit_passe_par_le_dedoublonnage():
    src = inspect.getsource(ToolRegistry.handle_governed_edit)
    assert "ToolRegistry._dedoublonner_champs(verdict, agent)" in src
