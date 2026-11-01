# -*- coding: utf-8 -*-
"""NR — Passation compacte d'historique entre agents lors d'un handoff.

Chasse aux tokens (owner 30/10) :
- Sous le seuil (LAFORGE_HANDOFF_COMPACT_CHARS, defaut 24000) -> historique intact.
- Au-dessus du seuil -> compacte : message system initial preserve s'il existe,
  un message system injectant le bloc format_compressed_for_prompt, et les 2 derniers
  tours intacts.
- Utilise _fallback_truncate par defaut (deterministe, pas d'appel cloud) sauf si
  LAFORGE_HANDOFF_COMPACT_LLM=1.
- En cas d'erreur ou d'exception du compresseur -> conservation intacte sans perte
  silencieuse.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_handoff as fh
from forge_handoff import Agent, _compacter_pour_transfert


def test_sous_le_seuil_rend_identique():
    messages = [
        {"role": "system", "content": "System prompt initial."},
        {"role": "user", "content": "Question courte."},
        {"role": "assistant", "content": "Reponse courte."},
    ]
    cible = Agent(name="EXPERT", instructions="Role expert.")
    res = _compacter_pour_transfert(messages, cible)
    assert res == messages


def test_au_dessus_du_seuil_avec_system_initial(monkeypatch):
    monkeypatch.setenv("LAFORGE_HANDOFF_COMPACT_CHARS", "100")

    sys_init = {"role": "system", "content": "Instruction systeme racine."}
    # historiques REALISTES : un resume n'allege que ce qui est plus long que lui (garde du 30/10)
    m1 = {"role": "user", "content": "Texte long A " * 400}
    m2 = {"role": "assistant", "content": "Texte long B " * 400}
    m3 = {"role": "user", "content": "Texte long C " * 400}
    m4 = {"role": "assistant", "content": "Dernier message tour 1."}
    m5 = {"role": "user", "content": "Dernier message tour 2."}

    messages = [sys_init, m1, m2, m3, m4, m5]
    cible = Agent(name="EXPERT_CODE", instructions="Specialiste code.")

    res = _compacter_pour_transfert(messages, cible)

    # Doit etre plus court en nombre de caracteres
    orig_chars = sum(len(m["content"]) for m in messages)
    new_chars = sum(len(m["content"]) for m in res)
    assert new_chars < orig_chars

    # Doit preserver le system initial en premier
    assert res[0] == sys_init

    # Le deuxieme message doit etre un system contenant le TLDR formate
    assert res[1]["role"] == "system"
    assert "### Handoff TLDR (transferred to EXPERT_CODE)" in res[1]["content"]

    # Les 2 derniers tours doivent etre preserves intacts
    assert res[-2:] == [m4, m5]


def test_au_dessus_du_seuil_sans_system_initial(monkeypatch):
    monkeypatch.setenv("LAFORGE_HANDOFF_COMPACT_CHARS", "100")

    m1 = {"role": "user", "content": "Historique ancien " * 400}
    m2 = {"role": "assistant", "content": "Reponse ancienne " * 400}
    m3 = {"role": "user", "content": "Avant-dernier tour"}
    m4 = {"role": "assistant", "content": "Dernier tour"}

    messages = [m1, m2, m3, m4]
    cible = Agent(name="TEST_AGENT", instructions="")

    res = _compacter_pour_transfert(messages, cible)

    # Pas de system initial au depart : res[0] doit directement etre le system compact
    assert res[0]["role"] == "system"
    assert "### Handoff TLDR (transferred to TEST_AGENT)" in res[0]["content"]

    # Les 2 derniers tours intacts
    assert res[-2:] == [m3, m4]
    assert len(res) == 3


def test_une_compaction_qui_n_allege_pas_garde_l_original(monkeypatch):
    # garde du 30/10 : un resume plus long que l'historique resume n'est jamais transmis
    monkeypatch.setenv("LAFORGE_HANDOFF_COMPACT_CHARS", "10")
    messages = [{"role": "user", "content": "court " * 5}, {"role": "assistant", "content": "bref"},
                {"role": "user", "content": "fin"}]
    assert _compacter_pour_transfert(messages, Agent(name="X", instructions="")) == messages


def test_exception_compresseur_rend_identique_sans_perte(monkeypatch):
    monkeypatch.setenv("LAFORGE_HANDOFF_COMPACT_CHARS", "50")

    messages = [
        {"role": "user", "content": "Message qui depasse le seuil largement 1234567890"},
        {"role": "assistant", "content": "Autre message qui depasse"},
    ]
    cible = Agent(name="FAIL_AGENT", instructions="")

    with patch("forge_handoff_compress._fallback_truncate", side_effect=RuntimeError("Boom simulateur")):
        res = _compacter_pour_transfert(messages, cible)
        assert res == messages


def test_mode_llm_active_si_env_var(monkeypatch):
    monkeypatch.setenv("LAFORGE_HANDOFF_COMPACT_CHARS", "50")
    monkeypatch.setenv("LAFORGE_HANDOFF_COMPACT_LLM", "1")

    messages = [
        {"role": "user", "content": "Historique long A " * 10},
        {"role": "assistant", "content": "Historique long B " * 10},
        {"role": "user", "content": "Dernier tour 1"},
        {"role": "assistant", "content": "Dernier tour 2"},
    ]
    cible = Agent(name="AGENT_LLM", instructions="Persona cible")

    fake_result = {
        "summary": "Resume LLM simule",
        "key_facts": ["fact 1"],
        "decisions": [],
        "open_questions": [],
        "context_state": {},
        "last_messages": messages[-2:],
    }

    with patch("forge_handoff_compress.compress_for_handoff", return_value=fake_result) as mock_llm:
        res = _compacter_pour_transfert(messages, cible)
        mock_llm.assert_called_once()
        assert res[0]["role"] == "system"
        assert "Resume LLM simule" in res[0]["content"]
        assert res[-2:] == messages[-2:]
