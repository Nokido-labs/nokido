"""NR 29/10 soir -- audit C2.1, derniers sites (hors glob du cliquet) : app/collab_modes/legacy.py, ollama_ask_sync et
gemini_ask_sync faisaient `with ThreadPoolExecutor` + `.result(timeout=60)` : la sortie du bloc attendait la tache, le
delai ne liberait pas l'appelant. Borne : l'appelant revient au delai (TimeoutError), la tache est abandonnee."""
import asyncio
import sys
import time
from concurrent.futures import TimeoutError as DelaiDepasse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

from nokido_agent.app.collab_modes import legacy as L  # noqa: E402


async def _lent(*a, **k):
    await asyncio.sleep(3.0)
    return "trop tard"


@pytest.mark.parametrize("fonction, cible", [("ollama_ask_sync", "_ollama_ask"), ("gemini_ask_sync", "_gemini_ask")])
def test_le_delai_libere_l_appelant(monkeypatch, fonction, cible):
    monkeypatch.setattr(L, cible, _lent)
    monkeypatch.setattr(L, "_DELAI_S", 0.2)
    t0 = time.perf_counter()
    with pytest.raises(DelaiDepasse):
        getattr(L, fonction)("tache")
    assert time.perf_counter() - t0 < 1.5
