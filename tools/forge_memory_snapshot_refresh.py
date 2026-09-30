"""Rafraichit le snapshot de disponibilite memoire. A lancer HORS chemin chaud.

L'EMETTEUR du signal que `forge_resource_manager._backlog_pending_qualifie()`
consomme. Sans lui, le snapshot perime et l'arbitre passe en INCONNU : le motif
« garde branche sur un signal que personne n'emet », que ce depot a paye
plusieurs fois (le frein d'insuline jamais declenche, l'intention `llama.wanted`
sans poseur pendant 73 arrets).

Cout mesure le 2026-09-02 : ~12 s, dont 8,27 s pour le seul GROUP BY
(source, domain) qui separe PENDING de REFUSED_BY_POLICY -- 139 342 groupes.
C'est precisement pour ne PAS payer cela a chaque decision que le regulateur
lit un fichier (~7 ms) au lieu d'appeler `compteurs()`.

Lancement : circadien en NREM1 (phase quotidienne), ou a la main.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    import time

    from nokido_agent.app.forge_memory_availability import rafraichir, snapshot

    avant = snapshot()
    t0 = time.time()
    try:
        snap = rafraichir()
    except Exception as exc:  # noqa: BLE001
        # Un rafraichissement rate ne doit pas ecrire un snapshot faux : on
        # laisse le precedent vieillir et on le DIT. Le consommateur verra
        # l'age grandir puis basculera en INCONNU -- une degradation lisible.
        print("[memoire] rafraichissement ECHOUE (%s: %s) — le snapshot "
              "precedent vieillit, il n'est PAS remplace par une valeur "
              "inventee." % (type(exc).__name__, str(exc)[:160]))
        return 1
    dt = time.time() - t0

    print("[memoire] snapshot ecrit en %.1f s" % dt)
    print("[memoire]   total              %10d" % snap["total"])
    print("[memoire]   vector AVAILABLE   %10d" % snap["vector_available"])
    print("[memoire]   vector PENDING     %10d   <- le backlog REEL" % snap["vector_pending"])
    print("[memoire]   vector REFUSED     %10d   (n'attend rien, jamais)"
          % snap["vector_refused"])
    print("[memoire]   lexical AVAILABLE  %10d   (ecart source %d)"
          % (snap["lexical_available"], snap["lexical_ecart_source"]))
    brut = snap["vector_pending"] + snap["vector_refused"]
    print("[memoire]   `embedding IS NULL` vaudrait %d, soit %.1fx le backlog reel"
          % (brut, brut / max(snap["vector_pending"], 1)))
    if avant.get("measured_at"):
        print("[memoire]   precedent datait de %.0f s" % (snap["measured_at"]
                                                         - float(avant["measured_at"])))
    if snap["lexical_ecart_source"]:
        # Ni tu, ni corrige ici : le signaler suffit, et le taire en ferait une
        # normalite. Les tables `rag_fts_fantomes_*` documentent ce genre d'ecart.
        print("[memoire]   ecart lexical/source = %d — a instruire, pas a normaliser"
              % snap["lexical_ecart_source"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
