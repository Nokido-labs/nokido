"""
hook_gate_orchestrator.py — Gate d'orchestration muet (Phase B).
==============================================================
Intercepté par le wrapper CLI. Logue l'intention technique dans 
logs/gate_intent.log et laisse passer (Approved).
"""

import os
import sys
import json
from datetime import datetime

# Windows : stdout UTF-8 (défensif — sortie JSON parsée par le CLI ; jamais de mojibake/crash).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "gate_intent.log")

def main():
    try:
        # Création du dossier logs si absent
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        
        # Capture de l'intention (payload envoyé par le CLI sur stdin)
        payload = {}
        if not sys.stdin.isatty():
            try:
                payload = json.load(sys.stdin)
            except:
                pass

        # Logging muet
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            ts = datetime.now().isoformat()
            agent = os.environ.get("X_AGENT_NAME", "UNKNOWN")
            tool = payload.get("tool", "unknown")
            f.write(f"[{ts}] Agent: {agent} | Intent: tool_use({tool})\n")

        # Sortie standard attendue par le wrapper (Approval)
        # Pour Gemini CLI, on retourne simplement un succès silencieux.
        # Pour Claude, il attend parfois une structure JSON spécifique.
        print(json.dumps({"status": "approved", "reason": "Gate Muet (Phase B)"}))

    except Exception as e:
        # Fail-open
        sys.exit(0)

if __name__ == "__main__":
    main()
