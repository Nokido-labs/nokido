# -*- coding: utf-8 -*-
"""
tools/forge_active_inference_homeostat_prototype.py
Non-intrusive prototype demonstrating adaptive homeostatic limits driven by FEP surprise.

═══════════════════════════════════════════════════════════════════════════
NE PAS CÂBLER `adaptive_ram` EN L'ÉTAT — verdict mesuré le 2026-07-29
═══════════════════════════════════════════════════════════════════════════
Ce prototype est en zone morte depuis son écriture. Il a été instruit ce jour-là
plutôt que branché, et voici pourquoi — pour que personne ne refasse le tour.

`adaptive_ram = max(65, 85 - ALPHA * surprise)` REPRODUIT la panne du jour.
Abaisser le seuil de ressources quand la surprise monte, c'est le défaut exact
du cortisol corrigé le matin même (c4f73684) : le gate refuse alors davantage de
spawns, donc moins d'organes démarrent, donc le modèle se trompe davantage, donc
la surprise monte encore. Boucle iatrogène — et ici l'amplitude est de 20 points
(85 -> 65) là où le durcissement du cortisol en fait 10.

Mesure du 29-07 qui l'établit : au boot de 08:16, une hormone à 0,001 au-dessus
de son seuil a fait refuser 471 spawns avec la RAM à 60 % ; puis 382 de plus avec
la RAM à 37,8 %. Dans les deux cas le frein a empêché la guérison au lieu de
protéger quoi que ce soit — les organes manquants étaient ceux qu'il refusait.

INVARIANT : freiner le spawn ne peut JAMAIS soigner un manque d'organes. Un
signal de détresse module la CONFIANCE, pas la CAPACITÉ D'AGIR.

CE QUI EST DÉJÀ FAIT, ET BIEN FAIT : `forge_homeostasis_orchestrator` consomme
déjà la surprise via `_prediction_error_factor()` (L173-207) — elle pondère `tau`,
un facteur de FILTRAGE. « Modèle fiable (surprise nulle) -> 1.0, on garde le
filtrage nominal. » C'est le bon usage, il est en place, ne pas le doubler.

CE QUI RESTE DÉFENDABLE ICI : `adaptive_tick`. Observer PLUS SOUVENT quand le
modèle se trompe est sain — cela acquiert de l'information au lieu d'en retirer,
et c'est le sens même de l'inférence active. À instruire séparément, avec un
plancher (déjà présent : MIN_TICK_S) et une mesure du coût CPU réel.

À LIRE AVANT DE TOUCHER : la table `active_inference_signals` (ajoutée le 29-07)
porte l'attendu CONDITIONNÉ AU CONTEXTE — c'est elle, et non la moyenne globale
des surprises d'actions utilisée ici, qui permet de juger « normal ICI, MAINTENANT ».
"""
from __future__ import annotations

import os
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"

# Parameters
DEFAULT_RAM_LIMIT = 85
MIN_RAM_LIMIT = 65
ALPHA = 5.0  # RAM reduction factor per unit of surprise

DEFAULT_TICK_S = 300
MIN_TICK_S = 60
BETA = 0.5  # Tick acceleration factor per unit of surprise

def calculate_adaptive_limits() -> tuple[float, float, float]:
    """
    Queries active_inference_surprises and computes:
    - average surprise (last 20 entries)
    - adaptive RAM limit
    - adaptive tick interval
    """
    if not DB_PATH.exists():
        return 0.0, float(DEFAULT_RAM_LIMIT), float(DEFAULT_TICK_S)

    conn = sqlite3.connect(DB_PATH)
    try:
        # Check if table exists
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='active_inference_surprises'")
        if not cursor.fetchone():
            return 0.0, float(DEFAULT_RAM_LIMIT), float(DEFAULT_TICK_S)

        # Get last 20 surprise values
        cursor.execute("SELECT surprise FROM active_inference_surprises ORDER BY ts DESC LIMIT 20")
        rows = cursor.fetchall()
        if not rows:
            return 0.0, float(DEFAULT_RAM_LIMIT), float(DEFAULT_TICK_S)

        surprises = [r[0] for r in rows]
        avg_surprise = sum(surprises) / len(surprises)
    except Exception as exc:
        print(f"Error querying surprises: {exc}", file=sys.stderr)
        avg_surprise = 0.0
    finally:
        conn.close()

    # Apply FEP adaptation formulas
    adaptive_ram = max(MIN_RAM_LIMIT, DEFAULT_RAM_LIMIT - (ALPHA * avg_surprise))
    adaptive_tick = max(MIN_TICK_S, DEFAULT_TICK_S / (1.0 + BETA * avg_surprise))

    return avg_surprise, adaptive_ram, adaptive_tick

def main():
    print("=== Nokido Homeostasis - Active Inference Adaptive Limits Prototype ===")
    print(f"Database: {DB_PATH}")
    
    avg_surprise, ram_limit, tick_interval = calculate_adaptive_limits()
    
    print("\n--- Current Metrics ---")
    print(f"Moving Average Surprise (last 20 actions): {avg_surprise:.4f}")
    
    print("\n--- Adaptive Parameters ---")
    print(f"Base RAM Limit:       {DEFAULT_RAM_LIMIT}%")
    print(f"Adaptive RAM Limit:   {ram_limit:.1f}%")
    print(f"Base Tick Interval:    {DEFAULT_TICK_S}s")
    print(f"Adaptive Tick Interval: {tick_interval:.1f}s")
    
    # Threshold interpretation
    if avg_surprise > 1.5:
        print("\n[POSTURE] CRITICAL SURPRISE: Hardened posture active (accelerated ticks, low RAM allowance).")
        print("  -> Recommendation: Trigger active learning/epistemic search and cache compaction.")
    elif avg_surprise > 0.5:
        print("\n[POSTURE] MODERATE SURPRISE: Cautionary posture active.")
    else:
        print("\n[POSTURE] STABLE: Normal relaxed parameters.")

if __name__ == "__main__":
    main()
