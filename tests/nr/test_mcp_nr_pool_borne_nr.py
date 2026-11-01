"""NR C2.1 — audit pool_borne dans app/mcp_nr.py : `with ThreadPoolExecutor`
+ `.result(timeout=T)` ne libère PAS l'appelant au bout de T (`__exit__` attend la tâche).
Le pool_borne rend la main au délai, la tâche bloquée est abandonnée (shutdown sans attente)."""
import sys
import time
from concurrent.futures import TimeoutError as DelaiDepasse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

import mcp_nr  # noqa: E402


def _bloque():
    time.sleep(3.0)
    return "done"


def test_delai_depasse_libere_l_appelant_au_delai():
    t0 = time.perf_counter()
    with pytest.raises(DelaiDepasse):
        mcp_nr.pool_borne(_bloque, timeout=0.2)
    assert time.perf_counter() - t0 < 1.0


def test_reponse_dans_le_delai_rendue():
    assert mcp_nr.pool_borne(lambda: "ok", timeout=2.0) == "ok"