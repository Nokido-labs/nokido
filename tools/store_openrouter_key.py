"""
tools/store_openrouter_key.py
==============================
Stocke la clé OpenRouter dans Windows Credential Manager.
Usage : python tools/store_openrouter_key.py sk-or-v1-XXXXXXXX
"""

import sys

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


def store_key(key: str) -> None:
    import win32cred

    credential = {
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": "OPENROUTER_API_KEY",
        "CredentialBlob": key,  # str directement, pas bytes
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "UserName": "Nokido",
    }
    win32cred.CredWrite(credential, 0)
    print(f"OK — clé stockée: {key[:12]}...{key[-4:]}")

    # Vérification immédiate
    cred = win32cred.CredRead("OPENROUTER_API_KEY", win32cred.CRED_TYPE_GENERIC)
    val = cred["CredentialBlob"].decode("utf-16")
    assert val == key, "Vérification échouée !"
    print("Vérification OK")

    # Test rapide API
    import os

    sys.path.insert(0, "app")
    os.environ["OPENROUTER_API_KEY"] = key
    from nokido_agent.app.forge_openrouter import is_available, list_free_models

    if is_available():
        print("API OpenRouter: CONNECTÉE")
        models = list_free_models()
        print(f"Modèles gratuits disponibles: {len(models)}")
        for m in models[:10]:
            print(f"  {m}")
    else:
        print("API OpenRouter: non joignable (vérifier la clé)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/store_openrouter_key.py sk-or-v1-XXXXXXXX")
        sys.exit(1)
    store_key(sys.argv[1])
