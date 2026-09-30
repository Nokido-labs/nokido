"""forge_swarm_bus.py — bus side-channel des événements de collaboration swarm.

ADDITIF et non-intrusif : `run_swarm` (et le fan-out `/api/swarm/run`) publient
ici leurs étapes ; l'endpoint SSE `/api/swarm/stream` s'y abonne et l'UI web
affiche la collaboration EN LIVE. Le chemin du *résultat* (ce que renvoie
run_swarm à l'appelant) est INCHANGÉ → zéro perte d'efficacité.

In-process, stdlib pur, fan-out best-effort :
  - aucun abonné (pas d'UI ouverte) → publish ≈ no-op (append à un ring borné).
  - chaque abonné = une queue.Queue ; backpressure = on droppe pour cet abonné
    lent, jamais pour le producteur (run_swarm ne bloque jamais).
  - ring buffer des N derniers events → un onglet ouvert en cours de swarm
    rejoue le contexte récent (late-join), sans persistance.

Limite assumée : in-process. Un swarm exécuté dans un process détaché (job)
n'atteint pas le hub ; le cas couvert est l'exécution dans le process du hub
(orchestrate / ask fan-out / run_swarm appelé via le registre MCP).
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_SUBS: list[queue.Queue] = []
_RING: list[str] = []
_RING_MAX = 60

# Miroir JSONL persistant pour consumers cross-process (CLI/web viz du flux de
# réflexion). In-process ring = late-join UI ; ce fichier = tailable hors-hub.
_REFLEX_LOG = str(Path(__file__).resolve().parent.parent / "sandbox" / "reflexion.jsonl")
_MIRROR_MAX_BYTES = 5_000_000
_pub_count = 0


# Handle PERSISTANT du miroir. Mesure 2026-08-30 : `publish()` coutait 366 us, dont
# 630 us/evenement pour le seul open/write/close du JSONL -- 99,7 % du total. Un item
# de travail utile (parse AST) coute ~6 us : un evenement coutait donc SOIXANTE FOIS
# plus cher que le travail qu'il decrit, et le producteur payait cette I/O dans son
# propre thread. Garder le fichier ouvert rend 1,8 us/evenement, soit x354.
#
# Pourquoi PAS un thread writer + file bornee (l'autre voie mesuree) : il rend 1,3 us,
# soit x1,3 de mieux, au prix d'un thread, d'une file et d'une semantique de PERTE
# d'evenements. 99,7 % du gain s'obtient sans rien de tout cela.
#
# Verrou DEDIE : `_mirror` est appele HORS `_LOCK` (a dessein, pour ne pas tenir le
# verrou du ring pendant une I/O). Un handle partage entre threads exige donc sa
# propre exclusion -- sans elle, deux writes concurrents s'entrelacent et produisent
# une ligne JSONL corrompue.
_MIRROR_LOCK = threading.Lock()
_mirror_fh = None


def _mirror_close() -> None:
    """Ferme le handle (trim, tests). Idempotent, jamais d'exception."""
    global _mirror_fh
    if _mirror_fh is not None:
        try:
            _mirror_fh.close()
        except Exception:  # noqa: BLE001 - muet-ok : fermeture best-effort
            pass
        _mirror_fh = None


def _mirror(line: str) -> None:
    """Append best-effort au JSONL tailable. Trim périodique. Jamais d'exception."""
    global _pub_count, _mirror_fh
    try:
        with _MIRROR_LOCK:
            if _mirror_fh is None:
                _mirror_fh = open(_REFLEX_LOG, "a", encoding="utf-8")
            _mirror_fh.write(line + "\n")
            # flush a chaque ligne : le journal est TAILABLE (la GUI le suit en direct).
            # C'est ~1,8 us, pas les 630 us de l'ouverture -- on garde donc la lecture
            # temps reel sans payer le cout qui posait probleme.
            _mirror_fh.flush()
            _pub_count += 1
            if _pub_count % 200 == 0 and os.path.getsize(_REFLEX_LOG) > _MIRROR_MAX_BYTES:
                _mirror_close()          # le trim reecrit le fichier : handle relache
                tail = open(_REFLEX_LOG, encoding="utf-8",
                            errors="replace").read().splitlines()[-1500:]
                with open(_REFLEX_LOG, "w", encoding="utf-8") as f:
                    f.write("\n".join(tail) + "\n")
    except Exception:
        _mirror_close()                  # handle douteux : on repart proprement


def subscribe() -> queue.Queue:
    """Nouvel abonné. Rejoue le ring récent puis reçoit le live."""
    q: queue.Queue = queue.Queue(maxsize=500)
    with _LOCK:
        backlog = list(_RING)
        _SUBS.append(q)
    for line in backlog:
        try:
            q.put_nowait(line)
        except queue.Full:
            break
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _LOCK:
        if q in _SUBS:
            _SUBS.remove(q)


def publish(kind: str, data: dict | None = None, topic: str = "swarm") -> None:
    """Publie un event. Best-effort, n'élève jamais d'exception au producteur."""
    try:
        ev = {"ts": round(time.time(), 3), "topic": topic, "kind": kind, "data": data or {}}
        line = json.dumps(ev, ensure_ascii=False)
    except Exception:
        return
    with _LOCK:
        _RING.append(line)
        if len(_RING) > _RING_MAX:
            del _RING[0]
        dead = []
        for q in _SUBS:
            try:
                q.put_nowait(line)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _SUBS.remove(q)
    _mirror(line)


def subscriber_count() -> int:
    with _LOCK:
        return len(_SUBS)
