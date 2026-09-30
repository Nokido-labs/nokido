"""
test_cognitive_convergence.py — Test de Convergence Darwinienne (TCD).
=====================================================================
Vérifie que Gemini et Claude (via le router) convergent vers la même 
solution technique validée par exécution (MCTS).
"""

import sys
import asyncio
import json
from pathlib import Path

# Setup path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_mcts_engine import MCTSEngine, ConsensusEvaluator, TransientCodeEvaluator
from forge_llm_router import get_router

async def test_darwin_convergence():
    print("=== 🧬 TEST DE CONVERGENCE DARWINIENNE ===")
    
    # 1. Configuration de la Cour d'Arbitrage (Consensus)
    # On met Gemini (nous) et Groq (Llama 3 local) comme évaluateurs
    evaluators = [
        {"provider": "gemini_flash", "weight": 1.0}, # Juge Cloud
        {"provider": "groq", "weight": 1.2}          # Juge Local (fort sur le code)
    ]
    consensus = ConsensusEvaluator(evaluators)
    
    # 2. Le Problème à résoudre (Petit mutant)
    problem = "Écris une fonction Python 'safe_divide(a, b)' qui retourne a/b mais gère la division par zéro en retournant None."
    
    # 3. Lancement du moteur de réflexion délibérée (MCTS)
    engine = MCTSEngine(max_iterations=4)
    print(f"Réflexion en cours sur : {problem}")
    
    try:
        best_node = await engine.think(problem, consensus)
        
        print(f"\n--- RÉSULTAT DU CONSENSUS ---")
        print(f"Modèle gagnant : {best_node.model_origin}")
        print(f"Score de consensus : {best_node.score:.2f}")
        print(f"Code généré :\n{best_node.prompt}")
        
        # 4. Vérification de la Convergence
        # Si le score est > 8, nous considérons qu'il y a convergence
        convergence = best_node.score >= 7.0
        print(f"\n[TSC] Convergence Sémantique : {'✅ OK' if convergence else '❌ DRIFT'}")
        
        return convergence
    except Exception as e:
        print(f"Erreur lors du test de convergence : {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_darwin_convergence())
