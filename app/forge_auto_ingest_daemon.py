"""
app/forge_auto_ingest_daemon.py — Periodic Auto-Ingest
======================================================
Démon qui surveille data/rag_files/ et ingère les nouveaux fichiers toutes les 5 minutes.
Utilise forge_hot_ingest.py.
"""

from __future__ import annotations

import time
import sys
from pathlib import Path

# Setup path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_hot_ingest import get_watcher

# 2/11 (choix owner : service supervise dedie NokidoHotFolder) : pouls a chaque cycle -- un demon arrete ne doit plus
# se confondre avec un depot vide -- et messages d'ingestion sur stdout (capte par le superviseur).
# Pouls par le CANON forge_heartbeat.beat_daemon (sandbox/hot_folder.heartbeat, pid inscrit, ecriture atomique) :
# la version maison remontait les cliquets pouls_canon (26 > 25) et racine_donnees (245 > 244).
# NR : tests/nr/test_service_depot_surveille_nr.py


def _pouls(watcher, statut: str, ocr: "bool | None" = None) -> None:
    from nokido_agent.app.forge_heartbeat import beat_daemon

    if not beat_daemon("hot_folder", service="NokidoHotFolder", statut=statut,
                       vus=len(getattr(watcher, "_seen", ())), ocr=ocr):
        print("[DAEMON] pouls NON ecrit : l'arret deviendrait indiscernable", flush=True)


def run_daemon(intervalle: float = 300, cycles: "int | None" = None):
    print("[DAEMON] Auto-ingest started.", flush=True)
    from nokido_agent.app import forge_hot_ingest as _H

    ocr_ok, ocr_motif = _H.ocr_disponible()
    print("[DAEMON] OCR %s : %s" % ("disponible" if ocr_ok else "INDISPONIBLE", ocr_motif), flush=True)
    watcher = get_watcher(log_fn=lambda m: print(m, flush=True))
    n = 0
    while cycles is None or n < cycles:
        n += 1
        try:
            print(f"[DAEMON] Scan cycle at {time.strftime('%H:%M:%S')}...", flush=True)
            watcher._scan()
            _pouls(watcher, "ok", ocr_ok)
            if cycles is None or n < cycles:
                time.sleep(intervalle)
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001 - dit, le demon continue
            print(f"[DAEMON] Error: {e}", flush=True)
            _pouls(watcher, "erreur %s" % type(e).__name__, ocr_ok)
            time.sleep(min(60, intervalle))


if __name__ == "__main__":
    run_daemon()
