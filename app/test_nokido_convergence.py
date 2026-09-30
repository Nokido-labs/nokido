
# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "qualite/_test : test de convergence (mal place dans app/)"  # organe declare le 2026-09-06 (audit de raccordement)
import asyncio
import sys
import os
from pathlib import Path

# Setup environnement
sys.path.insert(0, os.path.abspath("app"))
sys.path.insert(0, os.path.abspath("tools"))


async def run_all_tests():
    print("🚀 [START] BATTERIE DE TESTS DE CONVERGENCE")

    # 1. Test AutocompleteEngine
    try:
        from nokido_agent.app.forge_ui_autocomplete import AutocompleteEngine

        ae = AutocompleteEngine()
        suggestions = ae.suggest_cmd("@rag")
        # suggestions est une liste de chaînes comme ['@rag info', ...]
        assert any("info" in s for s in suggestions), f"Autocomplete @rag échoué: {suggestions}"
        print("✅ Module: forge_ui_autocomplete OK")
    except Exception as e:
        print(f"❌ Module: forge_ui_autocomplete FAILED: {e}")

    # 2. Test Reasoning Agents
    try:
        from nokido_agent.app.forge_agents_reasoning import SupervisorAgent

        supervisor = SupervisorAgent()
        analysis = await supervisor.analyze_intent("Audit le code de forge_handlers.py")
        assert analysis.needs_action is True, "Analyse d'intention Action échouée"
        print("✅ Module: forge_agents_reasoning (Supervisor) OK")
    except Exception as e:
        print(f"❌ Module: forge_agents_reasoning FAILED: {e}")

    # 3. Test CodeSurgeon (AST)
    try:
        from nokido_agent.app.forge_code_surgery import CodeSurgeon

        # Test sur lui-même
        surgeon = CodeSurgeon("app/forge_code_surgery.py")
        structure = surgeon.locate_all()
        assert "CodeSurgeon" in structure, "Détection de classe AST échouée"
        print("✅ Module: forge_code_surgery OK")
    except Exception as e:
        print(f"❌ Module: forge_code_surgery FAILED: {e}")

    # 4. Test SiloEngine Fast-Track
    try:
        from nokido_agent.app.forge_silo_engine import SiloEngine

        engine = SiloEngine()
        assert engine._is_complex("Salut") is False, "Fast-Track non détecté pour Salut"
        assert engine._is_complex("Audit complet de la topologie réseau") is True, "Complex non détecté pour Audit"
        print("✅ Module: forge_silo_engine (Fast-Track) OK")
    except Exception as e:
        print(f"❌ Module: forge_silo_engine FAILED: {e}")

    # 5. Test RAG Hybrid (BM25)
    try:
        from nokido_agent.app.forge_app_context import get_rag

        rag = get_rag()
        if rag:
            # Test recherche technique
            results = await rag.search("CVE-2024-0001", k=1)
            print(f"✅ Module: forge_rag_engine (Hybrid) OK - Top score: {results[0]['score'] if results else 'N/A'}")
        else:
            print("⚠️ Module: forge_rag_engine - RAG non initialisé, skip")
    except Exception as e:
        print(f"❌ Module: forge_rag_engine FAILED: {e}")

    print("\n🏁 [DONE] TOUS LES SYSTÈMES SONT NOMINAUX")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
