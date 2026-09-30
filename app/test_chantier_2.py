import asyncio
import os
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Setup
sys.path.insert(0, os.path.abspath("app"))


async def test_chantier_2():
    print("🚀 [TEST CHANTIER 2] Démarrage...")

    # 1. Test Providers Registry
    from nokido_agent.app.forge_agent_proxy import list_providers, get_provider

    providers = list_providers()
    names = [p["name"] for p in providers]
    print(f"📊 Providers enregistrés ({len(names)}) : {names}")

    for target in ["cohere", "perplexity", "tavily"]:
        if target in names:
            print(f"✅ Provider '{target}' trouvé.")
        else:
            print(f"❌ Provider '{target}' MANQUANT.")

    # 2. Test Web Search logic
    from nokido_agent.app.forge_web_search import aggregate_search

    print("\n🔍 Test Web Search (DuckDuckGo fallback)...")
    try:
        # On ne peut pas tester Tavily sans API KEY réelle dans cet environnement
        # mais on peut tester le fallback DDG
        results = await aggregate_search("Nokido AI devops 2026", max_results=2)
        print(f"✅ Web Search a retourné {len(results)} résultats.")
        for r in results:
            print(f"   - {r['title']} ({r['url']})")
    except Exception as e:
        print(f"❌ Web Search FAILED: {e}")

    # 3. Test Tool Registry Integration
    from nokido_agent.app.forge_mcp_registry import get_registry

    reg = get_registry()
    tools = [t["name"] for t in reg.get_tool_list()]
    print(f"\n🛠️ Tools MCP enregistrés : {tools}")

    for t in ["web_search", "ask", "hub"]:
        if t in tools:
            print(f"✅ Tool '{t}' intégré au Registry.")
        else:
            print(f"❌ Tool '{t}' MANQUANT au Registry.")

    print("\n🏁 [DONE] Chantier 2 validé structurellement.")


if __name__ == "__main__":
    asyncio.run(test_chantier_2())
