"""NR 29/10 -- audit C2.1 sur le chemin du RAG (app/forge_embed_router.py, cascade d'embed) : `with ThreadPoolExecutor`
+ `.result(timeout=T)` ne libere PAS l'appelant au bout de T (`__exit__` attend la tache). L'appel borne rend la main au
delai, la tache bloquee est abandonnee (shutdown sans attente)."""
import sys
import time
from concurrent.futures import TimeoutError as DelaiDepasse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

import forge_embed_router as R  # noqa: E402


def _bloque(_texte):
    time.sleep(3.0)
    return [0.0] * 1024


def test_delai_depasse_libere_l_appelant_au_delai():
    t0 = time.perf_counter()
    with pytest.raises(DelaiDepasse):
        R._appel_borne(_bloque, "texte", 0.2)
    assert time.perf_counter() - t0 < 1.0


def test_reponse_dans_le_delai_rendue():
    assert R._appel_borne(lambda t: [1.0, 2.0], "texte", 2.0) == [1.0, 2.0]
