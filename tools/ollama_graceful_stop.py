#!/usr/bin/env python3
"""
tools/ollama_graceful_stop.py
==============================
Ferme Ollama proprement :
1. Unload tous les modèles via API (libère VRAM progressivement)
2. Attend 2s pour que le driver Vulkan se stabilise
3. Termine le process
"""

import json
import subprocess
import time
import urllib.request


def unload_models():
    try:
        # Liste les modèles chargés
        r = urllib.request.urlopen("http://localhost:11434/api/ps", timeout=3)
        data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        print(f"Modèles chargés: {models}")
        for model in models:
            # Unload via keep_alive=0
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps({"model": model, "keep_alive": 0, "prompt": ""}).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=5)
                print(f"  Unloaded: {model}")
            except Exception:
                pass
        return len(models)
    except Exception as e:
        print(f"Ollama non disponible: {e}")
        return 0


n = unload_models()
if n > 0:
    print(f"Attente stabilisation Vulkan ({n} modèles)...")
    time.sleep(3)

# Stop Ollama proprement
subprocess.run(
    ["taskkill", "/IM", "ollama.exe", "/F"], capture_output=True, stdin=subprocess.DEVNULL
)
subprocess.run(
    ["taskkill", "/IM", "ollama_llama_server.exe", "/F"],
    capture_output=True,
    stdin=subprocess.DEVNULL,
)
print("Ollama arrêté proprement.")
