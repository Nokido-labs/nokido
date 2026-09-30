# -*- coding: utf-8 -*-
"""One-shot : fabrique C:/tmp/kaggle_cfg/kaggle.json depuis la cle regeneree
de Nokido.env (KAGGLE_API_TOKEN, 2026-07-06). Appels de fonctions uniquement
(forge_secrets._dotenv), AUCUNE valeur affichee. Le paquet kaggle lira ce
fichier via KAGGLE_CONFIG_DIR (pull output detache).

Run : run action=trusted_script path=tools/forge_kaggle_cfg_from_env.py
"""
import json
import sys
from pathlib import Path

# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from nokido_agent.app.forge_secrets import _dotenv

key = _dotenv("KAGGLE_API_TOKEN")
if not key:
    print("ABORT: KAGGLE_API_TOKEN absent/commente dans Nokido.env")
    sys.exit(2)
# L'identifiant Kaggle portait le nom civil EN DUR (decision owner 2026-09-30 :
# pseudonyme dans tout le code publie) -- il se lit comme la cle.
username = __import__("os").environ.get("KAGGLE_USERNAME") or _dotenv("KAGGLE_USERNAME")
if not username:
    print("ABORT: KAGGLE_USERNAME absent (environnement ou Nokido.env)")
    sys.exit(2)

cfg = Path(r"C:\tmp\kaggle_cfg")
cfg.mkdir(parents=True, exist_ok=True)
(cfg / "kaggle.json").write_text(
    json.dumps({"username": username, "key": key}), encoding="utf-8")
# Nouveau format token (KGAT, len!=32) : s'utilise via env KAGGLE_API_TOKEN.
# On depose les DEUX formats ; le puller essaie token d'abord, json en repli.
(cfg / "token.txt").write_text(key, encoding="utf-8")
print(f"OK: kaggle.json + token.txt ecrits (len_key={len(key)}, valeur non affichee)")
