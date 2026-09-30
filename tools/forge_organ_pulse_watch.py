#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_organ_pulse_watch.py — lanceur de la boucle anti-embolie (déport run_job).

run_job ne passe pas d'arguments -> ce wrapper appelle watch() directement. Tourne
DÉTACHÉ (survit au restart du hub) et INDÉPENDANT du hub : il sonde /health par HTTP,
donc il DÉTECTE un wedge au lieu d'en être victime. Intervalle 600s (10 min)."""

__FORGE_COLOR__ = "vegetatif/heartbeat : lanceur deporte de la boucle anti-embolie"  # organe declare le 2026-09-06 (audit de raccordement)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_organ_pulse import watch  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(watch(interval=600))
