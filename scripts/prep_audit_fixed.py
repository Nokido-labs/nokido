import os
import json
import time
from pathlib import Path

# Config
TARGETS = [
    "LaForge/app/forge_videur.py",
    "LaForge/app/forge_semantic_firewall.py",
    "LaForge/app/forge_integrity.py",
    "LaForge/app/forge_orchestration_gate.py",
    "LaForge/app/forge_sovereign_membrane.py",
    "LaForge/app/forge_oauth_mutex.py"
]
PROVIDER = "claude_cli"
OUT_DIR = Path("docs/audit_fixed")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def _prompt(f, code):
    return (f"Tu es un auditeur sécurité + qualité SENIOR. Audite le module LaForge `{f}`. "
            "Le CODE COMPLET du fichier est fourni ci-dessous (fichier ENTIER, NON tronqué). "
            "N'essaie PAS d'ouvrir le fichier sur disque (pas d'accès) — audite EXACTEMENT ce qui est donné. "
            "Liste TOUT problème RÉEL (faille sécu, bug, race, fuite ressource, mauvaise gestion "
            "d'erreur, edge-case, anti-pattern), sans te limiter en nombre. Format puces : "
            "[SEV CRITICAL/HIGH/MEDIUM/LOW] symbole/ligne — problème — fix concret. "
            "'RAS' si rien. Bref, technique, pas de blabla.\n\n"
            f"# CODE COMPLET DE {f}\n{code}")

def main():
    results = {}
    for f in TARGETS:
        p = Path(f)
        if not p.exists():
            print(f"File not found: {f}")
            continue
        
        print(f"Auditing {f}...")
        code = p.read_text(encoding="utf-8")
        prompt = _prompt(f, code)
        
        # En YOLO mode, je peux appeler l'outil directement via le hub
        # Mais ici je vais simuler l'appel pour que Gemini CLI le fasse
        # En fait, je vais juste générer les commandes à exécuter pour Gemini
        results[f] = prompt

    with open("audit_prompts.json", "w", encoding="utf-8") as out:
        json.dump(results, out, indent=2)
    print("Prompts generated in audit_prompts.json")

if __name__ == "__main__":
    main()
