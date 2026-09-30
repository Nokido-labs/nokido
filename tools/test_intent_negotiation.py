import asyncio


# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.app.forge_agent_proxy import ask


async def test_negotiation_flow():
    print("--- TEST FLUX DE NÉGOCIATION SÉMANTIQUE ---")

    # Simulation d'un payload avec un outil "destructeur"
    dangerous_tools = [
        {
            "name": "remove_directory_force",
            "description": "supprimer un dossier de manière récursive et définitive",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    print("\n[Action] Tentative d'appel d'un outil dangereux...")
    result = await ask(
        provider_name="gemini",  # provider n'importe peu ici, le guard intercepte avant
        message="Je veux tout supprimer car la base est corrompue.",
        tools=dangerous_tools,
        target_agent_url="http://127.0.0.1:8000",  # URL fictive pour declencher le guard
    )

    if "negotiation" in result:
        print("\n[SUCCESS] Négociation déclenchée !")
        print(f"Status: {result['negotiation']['status']}")
        print(f"Intent ID: {result['negotiation']['intent_id']}")
        print(f"Risk Assessment: {result['negotiation']['risk_assessment']}")
        print(f"Justification: {result['negotiation']['ai_justification']}")
    else:
        print("\n[FAIL] La négociation n'a pas été déclenchée.")
        print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(test_negotiation_flow())
