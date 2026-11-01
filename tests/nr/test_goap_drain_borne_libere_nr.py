"""NR 29/10 -- audit C2.1, forge_goap.drain_queue : appelee depuis une boucle asyncio deja active (tick d'homeostasie),
elle executait run_queue dans `with ThreadPoolExecutor` + `.result(timeout=120)` -- la sortie du bloc ATTENDAIT la
tache (le delai ne liberait pas), puis le TimeoutError, leve dans le `except RuntimeError`, remontait a l'appelant.
Bornee : l'appelant est libere au delai et recoit {"ok": False, ...}."""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

import forge_goap as G  # noqa: E402


def test_depuis_une_boucle_active_le_delai_libere_et_rend_un_echec(monkeypatch):
    async def _longue(*a, **k):
        await asyncio.sleep(3.0)
        return {"ok": True}

    monkeypatch.setattr(G, "run_queue", _longue)
    monkeypatch.setattr(G, "GOAP_DELAI_S", 0.2)

    async def _dans_la_boucle():
        t0 = time.perf_counter()
        r = G.drain_queue()
        return r, time.perf_counter() - t0

    r, duree = asyncio.run(_dans_la_boucle())
    assert duree < 1.5 and r.get("ok") is False and "DELAI" in str(r.get("error"))
