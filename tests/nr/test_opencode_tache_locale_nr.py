# -*- coding: utf-8 -*-
"""NR — une tache marquee [local] tourne sur un modele LOCAL (Ollama) sans aucun repli cloud (owner 17/10 : « si il est
possible de preserver le quota des modeles forts, Claude et AGY, et delegues, et des LLM free tiers, fais-le »).

L'executeur lance un processus OpenCode PAR tache : la configuration peut donc suivre la tache. Contrat :
- `_modele_de_la_tache(desc, modele_instance)` : marqueur `[local]` -> modele local (defaut ollama/qwen2.5-coder:7b,
  surcharge LAFORGE_OPENCODE_MODELE_LOCAL) ; sinon le modele de l'instance ;
- `_config_opencode_instance(inst, modele)` : un modele `ollama/...` declare le fournisseur ollama en LOOPBACK, restreint
  `enabled_providers` a ollama et pose `small_model` sur le meme modele (aucun appel cloud cache, titres compris) ;
- aucune cle fournisseur n'est passee pour un modele local ; le detail de cloture DIT que la tache est locale.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _instances_de_reference(monkeypatch):
    """La logique se teste sur la table de reference, pas sur la configuration vivante (17/10)."""
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCES_FILE", str(ROOT / "tests" / "nr" / "opencode_instances_reference_nr.json"))


def test_le_marqueur_local_choisit_le_modele_local(monkeypatch):
    monkeypatch.delenv("LAFORGE_OPENCODE_MODELE_LOCAL", raising=False)
    assert T._modele_de_la_tache("[local] extraire les symboles de app/x.py", "groq/openai/gpt-oss-120b") \
        == "ollama/qwen2.5-coder:7b"
    assert T._modele_de_la_tache("tache ordinaire", "groq/openai/gpt-oss-120b") == "groq/openai/gpt-oss-120b"
    monkeypatch.setenv("LAFORGE_OPENCODE_MODELE_LOCAL", "ollama/qwen3:8b")
    assert T._modele_de_la_tache("[LOCAL] tri", "zai/glm-4.7-flash") == "ollama/qwen3:8b"


def test_un_modele_local_ferme_tout_repli_cloud():
    cfg = T._config_opencode_instance("OPENCODE_GPTOSS", "ollama/qwen2.5-coder:7b")
    assert cfg["model"] == "ollama/qwen2.5-coder:7b"
    assert cfg["small_model"] == "ollama/qwen2.5-coder:7b"
    assert cfg["enabled_providers"] == ["ollama"]
    base = cfg["provider"]["ollama"]["options"]["baseURL"]
    assert base.startswith("http://127.0.0.1:") and base.endswith("/v1"), base
    assert "qwen2.5-coder:7b" in cfg["provider"]["ollama"]["models"]
    assert cfg["mcp"]["nokido"]["enabled"] is True          # les outils du hub restent la


def test_un_modele_cloud_garde_sa_config_et_l_instance_par_defaut():
    cfg = T._config_opencode_instance("OPENCODE_GPTOSS")
    assert cfg["model"] == T._instances_opencode()["OPENCODE_GPTOSS"]["modele"]
    assert "enabled_providers" not in cfg and "provider" not in cfg
    assert T._env_cle_fournisseur("ollama/qwen2.5-coder:7b") is None
