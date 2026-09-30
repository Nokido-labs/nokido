#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_veille_gap_run.py — rattrapage de veille deporte, sans argument.

`run_job` lance un .py DETACHE mais n'accepte aucun argument. Ce wrapper appelle
`forge_veille_gap_recover` en mode crawl avec un plafond raisonnable par passe,
pour rattraper le contenu des URLs connues absentes du RAG (le crawl du hub a un
fallback natif : il fonctionne meme Docker eteint). Relancable : le scan repart
des URLs encore sans contenu, donc chaque passe avance.
"""

__FORGE_COLOR__ = "digestif/veille : rattrapage de veille deporte sans argument"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MAX = int(os.environ.get("NOKIDO_GAP_MAX", "120"))
PASSES = int(os.environ.get("NOKIDO_GAP_PASSES", "10"))
# Repos entre deux passes. Enchainer sans respirer ne servait a rien : 96 % du
# retard est sur un domaine qui coupe a ~26 requetes, et les passes 2 et 3
# repartaient dans un 429 encore chaud. Le cooldown par domaine (gap_recover)
# n'a d'effet que si le temps passe reellement entre les passes.
PAUSE_PASSE_S = float(os.environ.get("NOKIDO_GAP_PAUSE_PASSE_S", "90"))

from nokido_agent.tools import forge_veille_gap_recover as G  # noqa: E402

# Une passe ne rattrape que MAX URLs sur ~1400 : le job etant detache et
# relancable, il enchaine ses propres passes plutot que d'exiger un
# reordonnancement manuel a chaque lot. `main()` rescanne la base a chaque tour,
# donc l'avancement est reel ; tout rc non nul (refus de gate, zero indexation)
# arrete la boucle au lieu de la faire tourner a vide.
rc = 0
for n in range(1, PASSES + 1):
    if n > 1:
        # Attendre la duree REELLE du repos, pas une pause fixe : avec 90 s pour
        # un cooldown de 300 s, deux passes tournaient a vide apres chaque passe
        # productive, chacune payant un scan complet de la base pour rien.
        attente = max(PAUSE_PASSE_S, G.prochain_creneau())
        print("[gap] repos %s s avant la passe suivante" % int(attente), flush=True)
        time.sleep(attente)
    print("\n===== [gap] passe %s/%s =====" % (n, PASSES), flush=True)
    sys.argv = ["gap_recover", "--crawl", "--max", str(MAX)]
    rc = G.main()
    if rc != 0:
        print("[gap] arret a la passe %s (rc=%s)" % (n, rc), flush=True)
        break
raise SystemExit(rc)
