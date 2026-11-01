"""NR -- `gemma_up` ne juge PAS l'organe de llama_keeper (owner 24/10 « nokido ne peut pas se charger du reveil ? »).

Mesure du 24/10 : le bilan proprioceptif criait « CELLULE VIVANTE, ORGANE MORT -- llama_keeper gemma_up=false ».
Or `gemma_up` (tools/forge_llama_keeper.py:299) teste le routeur gemma du CLI GEMINI (:9379) -- un tiers, et un CLI
RETIRE (remplace par AGY) : son absence est l'etat NORMAL. `_verdict_fonctionnel` prenait toute cle booleenne *_up
pour l'organe servi. Une cle hors organe est ignoree ; sans autre signal, le verdict est None (inconnu), jamais False.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_health_diagnostic as H  # noqa: E402


def test_gemma_up_faux_n_est_pas_un_organe_mort():
    verdict, _motif = H._verdict_fonctionnel({"health": "idle", "gemma_up": False, "llama_n": 2})
    assert verdict is None


def test_une_vraie_cle_d_organe_reste_jugee():
    verdict, motif = H._verdict_fonctionnel({"stats": {"daemon_up": False, "error": "pipe ferme"}})
    assert verdict is False and "daemon_up" in motif
