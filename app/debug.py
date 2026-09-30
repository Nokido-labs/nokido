"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_debug
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
# debug_boot.py
try:
    print("⏳ Tentative d'importation de Nokido...")
    from nokido_agent.app import Nokido

    print("✅ Importation réussie. Lancement du main...")
    import asyncio

    asyncio.run(Nokido.main())
except Exception as e:
    import traceback

    print("\n❌ ERREUR DÉTECTÉE :")
    traceback.print_exc()
