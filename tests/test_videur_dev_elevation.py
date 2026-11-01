"""Reco #1 (2026-06-14) — élévation de ring par dev-mode armé.

Câble `forge_dev_mode.arm()` au ring de requête : sans ça, armer dev ne débloque
que le sandbox-bypass, pas la visibilité/RBAC des tools (owner bloqué malgré dev).

Invariants testés :
  - owner + LOCAL + dev armé           -> ring élevé à DEV(1)
  - dev NON armé                        -> ring inchangé
  - agent DISTANT                       -> jamais élevé (dev = surface owner locale)
  - agent HORS allowlist               -> jamais élevé
  - agent déjà >= DEV                   -> jamais downgrade (pas de remontée du n°)

MISE A JOUR DU CONTRAT (2026-10-22) : ces tests étaient rouges car ils présentaient
`token="x"` SANS agent_tokens, donc via=header (identité NON prouvée). Le code a été
durci volontairement, il n'a pas régressé :
  - 8291bf257 (2026-06-15) « fix(videur): fail-closed identity + anti-spoof header » :
    via=header est plafonné à _HEADER_FLOOR_RING (4) ;
  - _maybe_elevate exige une identité prouvée (_identite_prouvee(via)), correction du
    2026-09-12 (figée par tests/test_antispoof_survit_a_l_elevation.py).
Les tests fournissent donc un VRAI jeton d'agent (agent_tokens) : l'invariant d'origine
reste testé sur le chemin authentifié. Aucun ring n'est monté pour faire passer un test.
"""
import importlib

import pytest

vid = importlib.import_module("forge_videur")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # store vide -> le ring vient du seed (déterministe), pas d'un store vivant
    monkeypatch.setattr(vid, "_load_store", lambda: {})


def _ring(agent="CLAUDE", local=True):
    # jeton valide pour CET agent -> via=token (identite prouvee, hors plancher header)
    return vid.resolve_identity(agent, token="x", local=local,
                                agent_tokens={agent.upper(): "x"}, hub_token="")["ring"]


def _armed(monkeypatch, on: bool):
    monkeypatch.setattr(vid, "_DEV_IS_ARMED_OVERRIDE",
                        (lambda: (on, 999)), raising=False)


def test_owner_local_armed_elevates_to_dev(monkeypatch):
    _armed(monkeypatch, True)
    monkeypatch.setitem(vid._SEED_RING, "CLAUDE", 3)
    assert _ring("CLAUDE") == 1


def test_not_armed_no_elevation(monkeypatch):
    _armed(monkeypatch, False)
    monkeypatch.setitem(vid._SEED_RING, "CLAUDE", 3)
    assert _ring("CLAUDE") == 3


def test_remote_never_elevated(monkeypatch):
    _armed(monkeypatch, True)
    monkeypatch.setitem(vid._SEED_RING, "CLAUDE", 3)
    assert _ring("CLAUDE", local=False) == 3


def test_non_owner_not_elevated(monkeypatch):
    _armed(monkeypatch, True)
    monkeypatch.setitem(vid._SEED_RING, "RANDO", 3)
    assert _ring("RANDO") == 3


def test_never_downgrade(monkeypatch):
    _armed(monkeypatch, True)
    monkeypatch.setitem(vid._SEED_RING, "CLAUDE", 0)
    assert _ring("CLAUDE") == 0
