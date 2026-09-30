import asyncio
import sys
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(r"%NOKIDO_WORKSPACE%\LaForge\app")))

from forge_symbiotic_bridge import SymbioticBridge

async def test_live_symbiose():
    bridge = SymbioticBridge()
    
    print("--- Test 1 : Compression de Log (Scout) ---")
    raw_log = """
    ERROR:root:Uncaught exception
    Traceback (most recent call last):
      File "app/core/logic.py", line 45, in execute
        result = self.database.query("SELECT * FROM users WHERE id = ?", user_id)
      File "app/db/driver.py", line 12, in query
        raise ConnectionError("Database is down")
    ConnectionError: Database is down
    """ * 10 # On simule un log un peu long
    
    compressed = await bridge.compress_context(raw_log)
    print(f"Log original : {len(raw_log)} chars")
    print(f"Log compressé : {len(compressed)} chars")
    print(f"Contenu : {compressed}")
    
    print("\n--- Test 2 : Validation JSON (Linter) ---")
    bad_tools = [{"name": "get_weather", "parameters": {"type": "object", "properties": {"loc": "string"}}}] # Manque 'type' global etc
    ok, err = await bridge.validate_mcp_payload(bad_tools)
    print(f"Validation (devrait être False ou signaler erreur) : {ok}")
    if not ok:
        print(f"Erreur détectée par Gemma : {err}")

if __name__ == "__main__":
    asyncio.run(test_live_symbiose())
