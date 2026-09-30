# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = cognition/subjective-time
TEMPORALITE SUBJECTIVE — le temps RESSENTI, distinct du temps horloge.

GAP adresse (doc cognitif, dernier "partiel") : « la temporalite phenomenologique —
l'experience vecue du temps, le temps subjectif » n'a pas d'equivalent. Nokido
mesurait l'objectif mais pas le FELT.

POURQUOI un module dedie (anti-dup, CLAUDE.md §3) :
  - forge_timecode = temps OBJECTIF (event sourcing, horloge murale).
  - forge_circadian = rythme OBJECTIF + dette de sommeil (phases).
  - forge_system_mood.recommended_timeout = proxy GROSSIER (stress -> +timeout).
  AUCUN ne modelise le TEMPO RESSENTI (dilatation/contraction de la duree percue).
  Psychologie (Wittmann, Droit-Volet) : l'arousal DILATE le temps (vigilance ->
  "slow motion"), l'engagement/flow le CONTRACTE ("le temps file"), la fatigue le
  traine. Ce module rend ce vecu explicite -> couche phenomenologique du temps.

0 LLM, 0 cloud.
  LAFORGE_PYTHON app/forge_subjective_time.py    # selftest : 3 regimes (flow/vigilance/idle)
"""
from __future__ import annotations
import os, sys, math, time

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def compute_tempo(arousal: float, engagement: float, fatigue: float) -> float:
    """Tempo subjectif (pur, deterministe). >1 = le temps FILE (flow), <1 = il se
    TRAINE / se DILATE (vigilance, ennui, fatigue).
      arousal    [0,1] : vigilance/stress -> dilate (ralentit le tempo).
      engagement [0,1] : flow/charge interessante -> accelere (le temps file).
      fatigue    [0,1] : traine (ralentit)."""
    a, e, f = _clamp(arousal, 0, 1), _clamp(engagement, 0, 1), _clamp(fatigue, 0, 1)
    tempo = (1.0 + 0.8 * e) / (1.0 + 1.1 * a + 0.5 * f)
    return round(_clamp(tempo, 0.2, 3.0), 3)


def felt_duration(objective_s: float, tempo: float) -> float:
    """Duree RESSENTIE d'un intervalle objectif. tempo bas (dilate) -> ressentie plus
    LONGUE ; tempo haut (file) -> plus COURTE. felt = objectif / tempo."""
    return round(objective_s / max(1e-6, tempo), 2)


def _live_inputs() -> dict:
    """Arousal/engagement/fatigue depuis le corps vivant (mood/endocrine/circadian)."""
    arousal = engagement = fatigue = 0.0
    reasons = []
    try:
        from nokido_agent.app import forge_endocrine as fe
        lv = 0.0
        for r in fe.scan():
            if any(k in r.name.lower() for k in ("cortisol", "adrenaline", "threat", "stress")):
                lv = max(lv, float(r.level))
        arousal = max(arousal, lv)
        if lv:
            reasons.append(f"hormone_stress={lv:.2f}")
    except Exception:
        pass
    try:
        from nokido_agent.app import forge_system_mood as fsm
        mood = fsm.get_mood()
        if hasattr(mood, "is_stressed") and mood.is_stressed():
            arousal = max(arousal, 0.7); reasons.append("mood_stressed")
        cur = getattr(mood, "curiosity", 0.5) or 0.5
        engagement = _clamp(float(cur) + (0.0 if getattr(mood, "is_idle", lambda: False)() else 0.3), 0, 1)
        fatigue = _clamp(float(getattr(mood, "fatigue_hours", 0.0) or 0.0) / 8.0, 0, 1)
        if getattr(mood, "is_idle", lambda: False)():
            reasons.append("idle")
    except Exception:
        engagement = 0.4
    circ = 1.0
    try:
        from nokido_agent.app import forge_circadian as fc
        ph = fc.current_phase(None) if "now" in fc.current_phase.__code__.co_varnames else fc.current_phase()
        if "sleep" in str(ph).lower() or "night" in str(ph).lower():
            circ = 0.9; reasons.append("circadian_night")
    except Exception:
        pass
    return {"arousal": round(arousal, 3), "engagement": round(engagement, 3),
            "fatigue": round(fatigue, 3), "circadian_mult": circ, "reasons": reasons}


def tempo_now() -> dict:
    """Tempo subjectif courant depuis l'etat vivant."""
    inp = _live_inputs()
    t = compute_tempo(inp["arousal"], inp["engagement"], inp["fatigue"]) * inp["circadian_mult"]
    t = round(_clamp(t, 0.2, 3.0), 3)
    return {"tempo": t, "label": describe(t), **inp}


def describe(tempo: float) -> str:
    if tempo >= 1.25:
        return "le temps file (flow)"
    if tempo >= 0.9:
        return "temps ~normal"
    if tempo >= 0.65:
        return "le temps se traine"
    return "temps dilate (slow-motion / vigilance)"


def _selftest():
    print("=== SUBJECTIVE TIME selftest ===")
    regimes = {
        "flow (engage, peu stresse)":      dict(arousal=0.25, engagement=0.9, fatigue=0.1),
        "vigilance (alerte, menace)":      dict(arousal=0.9, engagement=0.3, fatigue=0.1),
        "ennui/idle (rien a faire)":       dict(arousal=0.1, engagement=0.05, fatigue=0.2),
        "epuisement (fatigue haute)":      dict(arousal=0.3, engagement=0.3, fatigue=0.9),
    }
    rows = {}
    for name, p in regimes.items():
        t = compute_tempo(**p)
        felt = felt_duration(60, t)  # une minute objective ressentie comment ?
        rows[name] = (t, felt)
        print(f"  tempo={t:<5} | 60s objectives -> {felt:>6}s ressenties | {describe(t):<34} | {name}")
    flow_t = rows["flow (engage, peu stresse)"][0]
    vig_t = rows["vigilance (alerte, menace)"][0]
    ok = flow_t > 1.0 > vig_t and rows["flow (engage, peu stresse)"][1] < 60 < rows["vigilance (alerte, menace)"][1]
    print(f"-> discrimination temporelle {'OK' if ok else 'KO'} : flow file ({flow_t}), vigilance dilate ({vig_t})")
    try:
        print("live:", tempo_now())
    except Exception as e:  # noqa: BLE001
        print("live indispo:", e)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
