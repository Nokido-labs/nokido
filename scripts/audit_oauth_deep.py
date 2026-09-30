import json
import httpx
import asyncio
from pathlib import Path

DAEMON_URL = "http://127.0.0.1:8770/v1/ask"
PROMPTS_FILE = "audit_prompts.json"
OUT_DIR = Path("docs/audit_fixed")
OUT_DIR.mkdir(parents=True, exist_ok=True)

async def audit_file(file_path, prompt):
    print(f"Deep auditing {file_path} via Daemon V14 (Claude)...")
    payload = {
        "provider": "claude_cli",
        "prompt": prompt
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(DAEMON_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            
            # Sauvegarde du résultat
            safe_name = file_path.replace("/", "_").replace("\\", "_") + ".audit.md"
            out_path = OUT_DIR / safe_name
            out_path.write_text(data["response"], encoding="utf-8")
            print(f"Result saved to {out_path}")
            return True
        except Exception as e:
            print(f"Error auditing {file_path}: {e}")
            return False

async def main():
    if not Path(PROMPTS_FILE).exists():
        print(f"{PROMPTS_FILE} not found. Run prep_audit_fixed.py first.")
        return

    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    tasks = []
    for file_path, prompt in prompts.items():
        tasks.append(audit_file(file_path, prompt))
    
    # Exécution séquentielle pour éviter de surcharger le CLI (Mutex=1)
    for task in tasks:
        await task

if __name__ == "__main__":
    asyncio.run(main())
