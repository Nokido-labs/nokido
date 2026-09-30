"""
forge_nervous_system.py — Système Nerveux Central (SNC) de Nokido.

Orchestre la double conscience (Système 1 / Système 2) :
- Système 1 (Réflexe / Reptilien) : Si Cortisol élevé ou Famine. Route locale, concision maximale, cache agressif.
- Système 2 (Conscient / Préfrontal) : Si Dopamine élevée ou Richesse API. Raisonnement profond, cloud Sonnet, deep GraphRAG.

Modifie chimiquement les prompts via injection d'hormones virtuelles (Dopamine / Cortisol).
"""

from __future__ import annotations

__FORGE_COLOR__ = "cerveau/nervous system central : systeme 1 reflexe, systeme 2 lent"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_metabolism import get_compute_energy_state, MetabolismState

class NervousMode:
    SYSTEM_1 = "SYSTEM_1_REFLEX"
    SYSTEM_2 = "SYSTEM_2_COGNITIVE"

def get_endocrine_levels() -> tuple[float, float]:
    """Lit les niveaux courants de dopamine et cortisol dans la base sémantique."""
    if not DB_PATH.exists():
        return 0.0, 0.0
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    try:
        # Recherche des signaux hormonaux récents actifs (demi-vie gérée par decay)
        # Par défaut, on retourne 0.0 si non trouvés
        cortisol = conn.execute(
            "SELECT level FROM endocrine_signals WHERE name='cortisol' ORDER BY released_at DESC LIMIT 1"
        ).fetchone()
        dopamine = conn.execute(
            "SELECT level FROM endocrine_signals WHERE name='dopamine' ORDER BY released_at DESC LIMIT 1"
        ).fetchone()
        
        c_level = cortisol[0] if cortisol else 0.0
        d_level = dopamine[0] if dopamine else 0.0
        return c_level, d_level
    except Exception:
        return 0.0, 0.0
    finally:
        conn.close()

def get_active_nervous_mode() -> str:
    """Détermine le mode nerveux actif selon l'état métabolique et endocrinien."""
    energy_state, _ = get_compute_energy_state()
    cortisol, dopamine = get_endocrine_levels()
    
    # Priorité absolue à la survie énergétique (Cortisol / Famine -> Système 1)
    if energy_state == MetabolismState.FAMINE or cortisol > 0.6:
        return NervousMode.SYSTEM_1
    return NervousMode.SYSTEM_2

def chemical_prompt_modulation(base_system_prompt: str) -> str:
    """Modifie chimiquement le system prompt avec des directives hormonales."""
    mode = get_active_nervous_mode()
    cortisol, dopamine = get_endocrine_levels()
    
    modulated = base_system_prompt
    
    if mode == NervousMode.SYSTEM_1:
        # Modulation "Cortisol" : Restriction de ressources et d'outils
        stress_directive = (
            "\n\n[SYSTEMIC CORTISOL HIGH - CRITICAL RESOURCE MODE]\n"
            "Le système est en mode d'économie d'énergie. Sois extrêmement concis, direct et minimaliste.\n"
            "N'utilise aucun outil optionnel ou recherche web. Reste sur des faits bruts.\n"
            "Limite tes réponses à 3 paragraphes maximum."
        )
        modulated += stress_directive
    else:
        # Modulation "Dopamine" : Expansion sémantique et curiosité
        curiosity_directive = (
            "\n\n[SYSTEMIC DOPAMINE HIGH - COGNITIVE EXPANSION MODE]\n"
            "Le système dispose de ressources optimales. Tu es encouragé à mener des raisonnements approfondis,\n"
            "à utiliser la Chain of Thought détaillée, à faire du deep GraphRAG et à exploiter pleinement la Sandbox.\n"
            "N'hésite pas à proposer de nouveaux liens et explorations conceptuelles."
        )
        if dopamine > 0.5:
            modulated += curiosity_directive
            
    return modulated

if __name__ == "__main__":
    c, d = get_endocrine_levels()
    mode = get_active_nervous_mode()
    print(f"[nervous_system] Dopamine: {d:.2f} | Cortisol: {c:.2f} | Mode: {mode}")
    dummy_prompt = "Tu es l'assistant de recherche de Nokido."
    mod_prompt = chemical_prompt_modulation(dummy_prompt)
    print("\nModulated Prompt Sample:")
    print(mod_prompt)
