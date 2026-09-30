"""Gate P1 RAM intent-aware : evincer l'IDLE plutot que refuser, jamais la cognition.

Le gate vit dans forge_sandbox_exec et spawne des process Windows : on teste la
POLITIQUE (qui a le droit d'etre evince) sur les primitives de forge_resource_manager,
sans jamais declencher d'eviction reelle.
"""
from __future__ import annotations

import os
import sys

import pytest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_resource_manager as rm  # noqa: E402


def test_request_resources_sans_evict_ne_fait_aucun_effet_de_bord(monkeypatch):
    """allow_evict=False doit rester une simple CONSTATATION."""
    monkeypatch.setattr(rm, "get_snapshot", lambda: {"ram_free_gb": 0.5, "ram_total_gb": 24.0})
    appels = []
    monkeypatch.setattr(rm, "ollama_loaded_models", lambda: appels.append("ollama") or [])
    monkeypatch.setattr(rm, "docker_pause_all", lambda: appels.append("docker") or 0)

    r = rm.request_resources(4.0, allow_evict=False)
    assert r["ok"] is False
    assert r["action"] == "noop"
    assert appels == [], "allow_evict=False ne doit RIEN evincer"


def test_request_resources_noop_si_ram_suffisante(monkeypatch):
    monkeypatch.setattr(rm, "get_snapshot", lambda: {"ram_free_gb": 9.0, "ram_total_gb": 24.0})
    r = rm.request_resources(4.0, allow_evict=True)
    assert r["ok"] is True and r["action"] == "noop"


def test_get_active_intents_contrat():
    """Le gate lit ces deux cles : elles doivent toujours exister."""
    i = rm.get_active_intents()
    assert "docker_wanted" in i and "chains_active" in i
    assert isinstance(i["chains_active"], int)
    assert isinstance(i["docker_wanted"], bool)


@pytest.mark.parametrize("intents,evictable", [
    ({"chains_active": 0, "docker_wanted": False}, True),
    ({"chains_active": 3, "docker_wanted": False}, False),
    ({"chains_active": 0, "docker_wanted": True}, False),
    ({"chains_active": 5, "docker_wanted": True}, False),
])
def test_politique_cognitive(intents, evictable):
    """Regle du gate : on n'evince QUE si aucune cognition ne tourne.

    Reproduit la condition ecrite dans forge_sandbox_exec pour la figer ici —
    une regulation capacitive (qui ne regarde que les Go) evincerait un resident
    en train de servir une veille.
    """
    cognition_active = bool(intents.get("chains_active") or intents.get("docker_wanted"))
    assert (not cognition_active) is evictable


def test_cible_eviction_repasse_sous_le_seuil():
    """18% du total laisse une marge franche sous le seuil de 85%."""
    total = 23.67
    target = round(total * 0.18, 2)
    ram_pct_apres = (total - target) / total * 100
    assert ram_pct_apres < 85.0, "la cible doit repasser sous le seuil, pas le raser"


def test_kill_switch_documente():
    """LAFORGE_P1_EVICT=0 doit desarmer l'eviction (garde owner)."""
    src_path = os.path.join(_APP, "forge_sandbox_exec.py")
    src = open(src_path, encoding="utf-8", errors="replace").read()
    assert "LAFORGE_P1_EVICT" in src
    assert "get_active_intents" in src, "le gate doit consulter les intentions vivantes"
