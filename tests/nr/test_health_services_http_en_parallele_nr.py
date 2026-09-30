"""NR -- `audit_services_http` sonde ses cibles EN PARALLELE, sans changer ce qu'il en conclut.

Mesure du 2026-09-24 (job_d30003a5ec90) : 8,10 s sur 44,9 s de phase health. Les 8 cibles
etaient interrogees en serie avec un delai de 2 s, et chaque service endormi (llamacpp,
graph_explorer, searxng quand docker est coupe) consommait son delai entier avant la suivante.
Meme motif que la fusion multi-capteurs (18 s de ports en serie, meme jour).

Ce qui est garde ici, par le point d'entree reel de l'audit :
  1. la duree ne croit plus avec le nombre de cibles lentes ;
  2. les trois issues gardent leur sens : reponse = up + status ; HTTPError = up +
     auth_protected (401/403 = vivant) ; autre exception = up False + TYPE de l'erreur
     (un delai reste lisible comme tel, jamais confondu avec un refus) ;
  3. toutes les cibles sont presentes, dans l'ordre declare.
"""
from __future__ import annotations

import io
import sys
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_health_diagnostic as hd  # noqa: E402

LENT = 0.4


class _Reponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_simule(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    time.sleep(LENT)
    if ":8767/" in url:
        raise urllib.error.HTTPError(url, 401, "auth", {}, io.BytesIO(b""))
    if ":8090/" in url:
        raise TimeoutError("timed out")
    return _Reponse()


def test_audit_services_http_en_parallele_et_meme_sens(monkeypatch):
    monkeypatch.setattr(hd.urllib.request, "urlopen", _urlopen_simule)
    t0 = time.perf_counter()
    out = hd.audit_services_http()
    duree = time.perf_counter() - t0
    n = len(out)
    assert n >= 8, "cibles perdues : %d" % n
    assert duree < n * LENT / 2, (
        "audit_services_http a dure %.2f s pour %d cibles a %.1f s : encore en SERIE" % (duree, n, LENT))
    assert out["hub_mcp"] == {"up": True, "status": 200}
    assert out["netcfg_mcp"] == {"up": True, "status": 401, "auth_protected": True}
    assert out["llamacpp_python"] == {"up": False, "err": "TimeoutError"}
    assert list(out)[:2] == ["hub_mcp", "web_hub"], "l'ordre declare des cibles est perdu"
