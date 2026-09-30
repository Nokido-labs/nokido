# -*- coding: utf-8 -*-
"""
PR-1 AXE 8 — persona canonique « nokido » + build_system_prompt étendu.
RED-first. Voir docs/specs/axe8_persona_unifiee_plan.md.
"""
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from nokido_agent.app.forge_persona_engine import PersonaEngine, nokido_system, get_persona_engine  # noqa: E402

# Le persona canonique s'appelle "nokido" (config/personas/nokido.yaml, name: nokido)
# depuis le rename LaForge->Nokido. Le test l'assérait encore "laforge" (half-rename,
# audit ZCode 2026-07-23) -> aligné sur le nom réel. L'alias laforge/nokido dans
# PersonaEngine.load_all garde la rétro-compat des appels code encore en "laforge".
PERSONA = "nokido"
MARKER = "[LAFORGE_PERSONA]"  # marqueur d'idempotence, string figée (≠ nom persona)


def test_nokido_persona_loads():
    eng = PersonaEngine()
    p = eng.get_persona(PERSONA)
    assert p is not None
    assert p["name"] == PERSONA
    assert p.get("canonical") is True


def test_build_contains_voice_and_marker_without_rescue():
    eng = PersonaEngine()
    sp = eng.build_system_prompt(PERSONA)
    assert "laforge" in sp.lower()
    assert MARKER in sp                       # marqueur idempotence (router/proxy futurs)
    # 2026-09-26 (owner) : plus d'« INSTRUCTION DE SECOURS » qui ordonnait icacls / nssm restart
    # a tout modele, cloud compris. Ce test l'IMPOSAIT ; il l'interdit desormais.
    for interdit in ("laforge-rescue", "icacls", "nssm restart", "INSTRUCTION DE SECOURS"):
        assert interdit not in sp, interdit


def test_persona_inconnue_sans_instruction_de_secours():
    sp = PersonaEngine().build_system_prompt("persona_qui_n_existe_pas_xyz")
    for interdit in ("laforge-rescue", "icacls", "nssm restart"):
        assert interdit not in sp, interdit


def test_identity_anchor_gated_by_turn():
    eng = PersonaEngine()
    sp0 = eng.build_system_prompt(PERSONA, turn=0)
    assert "[IDENTITY_ANCHOR" not in sp0      # turn<3 → pas d'ancre
    sp3 = eng.build_system_prompt(PERSONA, turn=3, ring=1)
    assert "[IDENTITY_ANCHOR" in sp3          # turn>=3 → ancre en fin


def test_role_overlay_after_voice():
    eng = PersonaEngine()
    sp = eng.build_system_prompt(PERSONA, role_overlay="OVERLAY_ROLE_XYZ")
    assert "OVERLAY_ROLE_XYZ" in sp
    assert sp.index(MARKER) < sp.index("OVERLAY_ROLE_XYZ")   # voix AVANT overlay


def test_unknown_persona_falls_back_to_nokido():
    eng = PersonaEngine()
    sp = eng.build_system_prompt("does_not_exist_xyz")
    assert sp                                  # pas de crash, non vide
    assert MARKER in sp                        # fallback = persona canonique nokido


def test_helper_and_singleton():
    sp = nokido_system()
    assert MARKER in sp
    assert get_persona_engine() is get_persona_engine()       # singleton stable


def test_pull_lessons_toggle_no_crash():
    eng = PersonaEngine()
    # PR-1 : stub best-effort, ne doit jamais crasher quel que soit le toggle
    assert eng.build_system_prompt(PERSONA, pull_lessons=False)
    assert eng.build_system_prompt(PERSONA, pull_lessons=True)


def test_persona_carries_token_economy():
    eng = PersonaEngine()
    sp = eng.build_system_prompt(PERSONA)
    assert "token" in sp.lower()                       # gestion tokens = trait core (statique)


def test_token_budget_directive_scales_with_pressure(monkeypatch):
    from nokido_agent.app import forge_persona_engine as pe

    eng = pe.PersonaEngine()
    # Pas de pression → pas de directive d'économie stricte
    monkeypatch.setattr(pe, "_read_cost_pressure", lambda: 0.0)
    assert "SOUS PRESSION" not in eng.build_system_prompt(PERSONA)
    # Pression haute → directive injectée (volet dynamique)
    monkeypatch.setattr(pe, "_read_cost_pressure", lambda: 0.9)
    high = eng.build_system_prompt(PERSONA)
    assert "SOUS PRESSION" in high
    assert "local-first" in high


def test_cost_pressure_reader_never_crashes():
    from nokido_agent.app import forge_persona_engine as pe

    # Best-effort : retourne un float même si endocrine indispo
    assert isinstance(pe._read_cost_pressure(), float)


def test_mood_directive_conditions_voice(monkeypatch):
    from nokido_agent.app import forge_persona_engine as pe

    eng = pe.PersonaEngine()
    # Humeur neutre → pas de directive d'état
    monkeypatch.setattr(pe, "_read_mood", lambda: (0.0, 0.0))
    assert "[ÉTAT:" not in eng.build_system_prompt(PERSONA)
    # Cortisol haut (échecs récents) → FRUSTRATION (prudence)
    monkeypatch.setattr(pe, "_read_mood", lambda: (0.0, 0.8))
    assert "FRUSTRATION" in eng.build_system_prompt(PERSONA)
    # Dopamine haute (succès récents) → CONFIANCE
    monkeypatch.setattr(pe, "_read_mood", lambda: (0.8, 0.0))
    assert "CONFIANCE" in eng.build_system_prompt(PERSONA)


def test_mood_reader_never_crashes():
    from nokido_agent.app import forge_persona_engine as pe

    d, c = pe._read_mood()
    assert isinstance(d, float) and isinstance(c, float)


def test_exemplars_skipped_under_cost_pressure(monkeypatch):
    from nokido_agent.app import forge_persona_engine as pe

    eng = pe.PersonaEngine()
    # Sous pression budget → pas de few-shot (éco-tokens = trait persona)
    monkeypatch.setattr(pe, "_read_cost_pressure", lambda: 0.9)
    assert eng._pull_dialogue_exemplars() == ""


def test_exemplars_reader_never_crashes(monkeypatch):
    from nokido_agent.app import forge_persona_engine as pe

    eng = pe.PersonaEngine()
    monkeypatch.setattr(pe, "_read_cost_pressure", lambda: 0.0)
    assert isinstance(eng._pull_dialogue_exemplars(), str)
