import json
import os
import subprocess

import requests

# ==========================================
# CONFIGURATION CLOUD OLLAMA
# ==========================================
# Remplace par l'URL publique de ton Ollama Cloud (VPS, RunPod, etc.)
OLLAMA_CLOUD_URL = os.getenv("OLLAMA_CLOUD_URL", "http://ton-vps-cloud:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_CLOUD_MODEL", "llama3.1")  # Ou qwen2.5, mistral, etc.
OLLAMA_API_KEY = os.getenv(
    "OLLAMA_API_KEY", ""
)  # Optionnel: Token Bearer si l'API Cloud est protégée

# Chemin de l'exécutable Python Nokido pour appeler les outils
PYTHON_EXE = __import__("os").path.expanduser("~/miniforge3/python.exe")
LAFORGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parents[1])
# SECURITY 2026-05-02 : hardcoded token removed (was Token Maître Local).
FORGE_MCP_TOKEN = os.environ.get("FORGE_MCP_TOKEN", "")
if not FORGE_MCP_TOKEN:
    import sys as _sys

    print("[ollama_cloud_proxy_agent] WARN: FORGE_MCP_TOKEN env not set.", file=_sys.stderr)


# ==========================================
# 1. DÉFINITION DES OUTILS LOCAUX (Le Muscle)
# ==========================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_local_shell",
            "description": "Execute une commande shell (PowerShell/CMD) sur la machine locale sécurisée de l'utilisateur. Retourne la sortie standard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "La commande à exécuter (ex: dir, ping, docker ps).",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nokido_hub_call",
            "description": "Appelle une action native du Hub Nokido local (ex: get_mode, poll, whoami, python).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Le nom de l'action Nokido (ex: whoami, python, poll).",
                    },
                    "kwargs": {
                        "type": "string",
                        "description": 'Les arguments additionnels sous forme de chaine JSON (ex: {"code": "print(\'hello\')"}).',
                    },
                },
                "required": ["action"],
            },
        },
    },
]


# ==========================================
# 2. EXÉCUTION LOCALE (Pare-feu Naturel)
# ==========================================
def execute_local_tool(name, arguments):
    print(f"\n[🛡️ PARE-FEU LOCAL] Demande d'exécution reçue du Cloud : {name}")
    print(f"[🛡️ PARE-FEU LOCAL] Arguments : {arguments}")

    # Ici on pourrait rajouter une confirmation manuelle (Human-in-the-loop)
    # user_ok = input("Autoriser l'exécution ? (o/n) : ")
    # if user_ok.lower() != 'o': return "Exécution refusée par l'utilisateur local."

    try:
        if name == "run_local_shell":
            cmd = arguments.get("command", "")
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, cwd=LAFORGE_DIR
            , errors="replace")
            return result.stdout if result.stdout else result.stderr

        elif name == "nokido_hub_call":
            action = arguments.get("action")
            kwargs_str = arguments.get("kwargs", "{}")
            try:
                kwargs = json.loads(kwargs_str)
            except:
                kwargs = {}

            cmd = [PYTHON_EXE, "tools/hub_call.py", action]
            for k, v in kwargs.items():
                cmd.append(f"{k}={v}")

            # Ajout du token de sécurité pour Nokido
            env = os.environ.copy()
            env["FORGE_MCP_TOKEN"] = FORGE_MCP_TOKEN

            result = subprocess.run(cmd, cwd=LAFORGE_DIR, capture_output=True, text=True, env=env, errors="replace")
            return result.stdout

        else:
            return f"Erreur : Outil local inconnu '{name}'."

    except Exception as e:
        return f"Erreur d'exécution locale : {str(e)}"


# ==========================================
# 3. BOUCLE AGENT (Le Cerveau Local)
# ==========================================
def poll_cloud_and_execute(user_prompt):
    print(f"\n[☁️ CLOUD] Envoi de la requête au modèle {OLLAMA_MODEL} sur {OLLAMA_CLOUD_URL}...")

    messages = [
        {
            "role": "system",
            "content": "Tu es un assistant IA hébergé dans le cloud. Tu as accès à la machine locale de l'utilisateur grâce aux outils fournis. Utilise ces outils si l'utilisateur te demande d'interagir avec son système, ses fichiers ou Nokido.",
        },
        {"role": "user", "content": user_prompt},
    ]

    payload = {"model": OLLAMA_MODEL, "messages": messages, "tools": TOOLS, "stream": False}

    try:
        # Configuration des headers pour l'authentification Cloud si un token est fourni
        headers = {"Content-Type": "application/json"}
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

        # Étape A: Envoyer le prompt + les outils
        response = requests.post(OLLAMA_CLOUD_URL, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()

        msg = data.get("message", {})
        tool_calls = msg.get("tool_calls", [])

        if not tool_calls:
            # Pas d'outil appelé, réponse texte classique
            print(f"\n[🤖 IA CLOUD] {msg.get('content', '')}")
            return

        # Étape B: L'IA Cloud veut utiliser un outil local
        messages.append(msg)  # Historique de la conversation

        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name")
            args = func.get("arguments", {})

            # Exécution stricte en local
            result = execute_local_tool(name, args)

            # Étape C: Renvoyer le résultat de l'exécution locale au Cloud
            print("[☁️ CLOUD] Renvoi du résultat local vers le cloud...")
            messages.append({"role": "tool", "content": str(result), "name": name})

        # Deuxième appel pour que le cloud génère la réponse finale
        payload["messages"] = messages
        # On peut retirer les "tools" du payload pour la conclusion
        del payload["tools"]

        res2 = requests.post(OLLAMA_CLOUD_URL, json=payload, headers=headers, timeout=60)
        final_msg = res2.json().get("message", {}).get("content", "")
        print(f"\n[🤖 IA CLOUD] {final_msg}")

    except requests.exceptions.ConnectionError:
        print(
            f"\n[❌ ERREUR] Impossible de joindre l'API Cloud ({OLLAMA_CLOUD_URL}). Le serveur est-il allumé ?"
        )
    except Exception as e:
        print(f"\n[❌ ERREUR] {e}")


if __name__ == "__main__":
    print("==============================================")
    print("🚀 NOKIDO CLOUD-PROXY AGENT (Zero-Trust) 🚀")
    print("==============================================")
    print("Ce script tourne EN LOCAL.")
    print("Il interroge l'IA Cloud et exécute SES requêtes ICI, de manière sécurisée.")
    print("Taper 'exit' pour quitter.\n")

    while True:
        try:
            prompt = input("👤 [Toi] > ")
            if prompt.lower() in ["exit", "quit", "q"]:
                break
            if not prompt.strip():
                continue
            poll_cloud_and_execute(prompt)
        except KeyboardInterrupt:
            break
