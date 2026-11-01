"""MESURE (pas une regression) : temps de app.forge_introspect.introspect.

Lancer :  python -m pytest -s -m mesure tests/nr/test_introspect_bench_mesure.py
Hors `-m mesure`, le test est saute : aucun run ordinaire ne le paie.
"""
from __future__ import annotations

import cProfile
import io
import pstats
import statistics
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

QUESTIONS = [
    "service superviseur runAs=interactive dans services.toml (exemple tray), et comment un outil MCP du registre forge_mcp_registry délègue à un service HTTP local ; routeur ACP tools/forge_acp_router.py",
    "coffre réservé : noms réservés dans app/forge_secrets.py (liste des secrets du coffre réservé lisible par le hub et le compte owner mais pas les comptes bac à sable), et provisionnement par tools/forge_coffre_reserve_provision.py",
    "forge_delivery_integrity _scan_false_attestations pointeur de spec",
    "harness worker file d'attente sandbox/harness_jobs",
    "regulation hamilton tick plancher 60 s",
]
PASSES = 5


def _skip_si_pas_mesure(config):
    if "mesure" not in (config.getoption("-m") or ""):
        pytest.skip("mesure : lancer avec -m mesure")


@pytest.mark.mesure
def test_mesure_introspect(request):
    _skip_si_pas_mesure(request.config)
    from app import forge_introspect as fi

    fi.introspect(QUESTIONS[2])  # echauffement hors mesure (imports)
    print("\n=== MESURE introspect : mediane de %d passes (s) ===" % PASSES)
    total = []
    for i, q in enumerate(QUESTIONS, 1):
        t = []
        for _ in range(PASSES):
            d = time.perf_counter()
            fi.introspect(q)
            t.append(time.perf_counter() - d)
        m = statistics.median(t)
        total.append(m)
        print("Q%d mediane=%.3f min=%.3f max=%.3f" % (i, m, min(t), max(t)))
    print("SOMME des medianes = %.3f s" % sum(total))

    pr = cProfile.Profile()
    pr.enable()
    for q in QUESTIONS:
        fi.introspect(q)
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(25)
    print(s.getvalue())
