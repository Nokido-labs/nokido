
# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "qualite/_test : test du routeur LM Studio (mal place dans app/)"  # organe declare le 2026-09-06 (audit de raccordement)
import asyncio
import os
import sys
from pathlib import Path

# Setup
sys.path.insert(0, os.path.abspath("app"))


async def test_lms_integration():
    from nokido_agent.app.forge_llm_router import get_router

    router = get_router()

    print("🛰️ [LLM ROUTER] Audit des providers disponibles...")
    status = router.all_status()

    lms = next((p for p in status["configured"] if p["name"] == "lmstudio_native"), None)

    if lms:
        print(f"✅ LM Studio détecté : {lms['name']} (Port 1234)")
        print(f"   Status : {'Disponible' if lms['available'] else 'Indisponible (Cooldown/RPM)'}")
        print(f"   Modèles configurés : {lms['models']}")
    else:
        print("❌ LM Studio non trouvé dans la configuration du routeur.")

    # Simulation d'un choix de cascade pour le 'code'
    from nokido_agent.app.forge_llm_router import USE_CASE_CHAINS

    chain = USE_CASE_CHAINS.get("code", [])
    print(f"\n🔗 Cascade pour 'code' : {' -> '.join(chain)}")

    if "lmstudio_native" in chain:
        print("🚀 LM Studio est bien intégré dans la chaîne de priorité.")


if __name__ == "__main__":
    asyncio.run(test_lms_integration())
