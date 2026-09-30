"""
forge_metabolism.py — Régulateur métabolique et énergétique de Nokido.

Gère les trois flux d'énergie computationnelle :
1. Énergie Compute (ATP / Quotas et coûts API).
2. Énergie Informationnelle (Curiosité active et ingestion sélective).
3. Énergie Entropique (Oubli Ebbinghaus et nettoyage NREM3).

Régule le rythme d'activité ("cœur battant") :
- HIGH_ENERGY (Tachycardie computationnelle) : Curiosité maximum, modèles cloud prioritaires.
- LOW_ENERGY (Famine / Hibernation) : Modèles locaux, suspension de curiosité, GC agressive.
"""

from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/resource : regulateur metabolique et energetique"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import sys
import time
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent.parent
# LECTEUR de `token_usage`. Ce module n'emet QU'UNE requete et ne touche aucune
# autre table de cette base (verifie le 2026-09-22) : substituer la constante est
# donc sur ici. Tant que l'interrupteur n'est pas pose, `CheminJournal` rend la
# base HISTORIQUE -- aucun comportement ne change.
try:
    from nokido_agent.app.forge_db_path import CheminJournal as _CheminJournal
    DB_PATH = _CheminJournal("token_usage")
except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
    DB_PATH = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("Nokido.Metabolism")

# Seuils financiers quotidiens par défaut (USD)
DAILY_BUDGET_USD = float(os.environ.get("LAFORGE_DAILY_BUDGET", "1.50"))
FATAL_BUDGET_USD = float(os.environ.get("LAFORGE_FATAL_BUDGET", "2.00"))

class MetabolismState:
    HIGH = "HIGH_ENERGY"       # Pleine capacité sémantique
    HOMEOSTASIS = "HOMEOSTASIS"# Régime nominal
    FAMINE = "LOW_ENERGY"      # Hibernation / Local-only

def get_compute_energy_state() -> tuple[str, float]:
    """Analyse la consommation d'API sur les dernières 24 heures et retourne l'état énergétique."""
    if not DB_PATH.exists():
        return MetabolismState.HOMEOSTASIS, 0.0
        
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    try:
        # Somme des coûts de jetons d'API sur les dernières 24h
        cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        cost = conn.execute(
            "SELECT SUM(cost_usd) FROM token_usage WHERE ts >= ?", (cutoff,)
        ).fetchone()[0] or 0.0
        
        # Logique d'état énergétique
        if cost >= FATAL_BUDGET_USD:
            return MetabolismState.FAMINE, cost
        elif cost >= DAILY_BUDGET_USD * 0.8:
            return MetabolismState.FAMINE, cost
        elif cost <= DAILY_BUDGET_USD * 0.3:
            return MetabolismState.HIGH, cost
        return MetabolismState.HOMEOSTASIS, cost
    except Exception as e:
        logger.warning(f"Error querying token usage: {e}")
        return MetabolismState.HOMEOSTASIS, 0.0
    finally:
        conn.close()

def adjust_cognitive_rhythm(state: str, current_cost: float):
    """
    Adapte la charge cognitive et le comportement de Nokido selon l'énergie disponible.
    """
    print(f"[metabolism] Current State: {state} (24h Cost: ${current_cost:.4f})")
    
    if state == MetabolismState.FAMINE:
        print("[metabolism] [!] LOW ENERGY STATE (FAMINE): Triggering hibernation rules...")
        # 1. Forcer le routage vers Ollama/modèles locaux
        os.environ["LAFORGE_FORCE_LOCAL_LLM"] = "true"
        # 2. Réduire le budget de curiosité
        os.environ["LAFORGE_CURIOSITY_BUDGET_PER_CYCLE"] = "1"
        # 3. Sécréter de l'hormone de stress (Cortisol) pour informer les agents
        try:
            from nokido_agent.app.forge_hormones import release
            release("cortisol", level=0.8, payload={"reason": "famine_compute", "cost_24h": current_cost})
            print("[metabolism] Cortisol hormone released to signal stress/conciseness.")
        except ImportError:
            pass
        # 4. Déclencher un nettoyage Ebbinghaus immédiat pour réduire l'entropie
        try:
            from scratch.ebbinghaus_forgetting import run_ebbinghaus_and_gc
            run_ebbinghaus_and_gc()
            print("[metabolism] Garbage collection forced to clean up entropy.")
        except ImportError:
            pass
            
    elif state == MetabolismState.HIGH:
        print("[metabolism] [+] HIGH ENERGY STATE: Accelerating curiosity and cloud reasoning...")
        os.environ["LAFORGE_FORCE_LOCAL_LLM"] = "false"
        os.environ["LAFORGE_CURIOSITY_BUDGET_PER_CYCLE"] = "10" # Exploration agressive
        try:
            from nokido_agent.app.forge_hormones import release
            # Sécrétion de dopamine pour stimuler la créativité et l'autotelic goal generation
            release("dopamine", level=0.7, payload={"reason": "surplus_compute"})
        except ImportError:
            pass
            
    else:
        print("[metabolism] [=] HOMEOSTASIS: Nominal compute and curiosity parameters.")
        os.environ["LAFORGE_FORCE_LOCAL_LLM"] = "false"
        os.environ["LAFORGE_CURIOSITY_BUDGET_PER_CYCLE"] = "5"

def run_metabolic_cycle():
    """Point d'entrée du cœur battant du métabolisme."""
    state, cost = get_compute_energy_state()
    adjust_cognitive_rhythm(state, cost)
    return {"state": state, "24h_cost_usd": cost}

if __name__ == "__main__":
    run_metabolic_cycle()
