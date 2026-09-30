#!/usr/bin/env python3
"""tools/forge_swebench_detach.py — lance forge_swebench_bg.py DÉTACHÉ.

forge_swebench_bg.py exécute le runner SWE-bench en synchrone (~3 h pour 15
instances). Lancé en `trusted_script` (compte LaForgeTrusted : réseau +
accès au coffre machine), ce wrapper le `Popen` en process INDÉPENDANT
(DETACHED_PROCESS + nouveau groupe) puis rend la main immédiatement — le
runner survit à la fin de l'appelant et au restart du hub.

Log du run : C:/tmp/swebench_bg.log
Prédictions : cf forge_swebench_bg.py (SWEBENCH_DIR = C:/tmp/swebench_work).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = __import__("os").path.expanduser(r"~\miniforge3\python.exe")
BG = ROOT / "tools" / "forge_swebench_bg.py"
LOG = Path(r"C:\tmp\swebench_bg.log")

if not BG.is_file():
    print(f"ERR: {BG} introuvable")
    sys.exit(1)

flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
# lf laissé ouvert volontairement : le process exit le ferme, l'enfant garde
# son propre handle dupliqué (pas de with -> pas de close prématuré).
lf = open(LOG, "w", encoding="utf-8")
p = subprocess.Popen(
    [PY, str(BG)],
    stdout=lf,
    stderr=subprocess.STDOUT,
    cwd=str(ROOT),
    creationflags=flags,
    close_fds=True,
)
print(f"DETACHED forge_swebench_bg pid={p.pid} log={LOG}")
sys.exit(0)
