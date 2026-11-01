"""NR -- un solde epuise chez le fournisseur declenche le repli comme un quota (mesure 26/10, OPENCODE_GLM).

z.ai a repondu deux fois `Insufficient balance or no resource package. Please recharge.` : classe PANNE FOURNISSEUR,
sans repli, la tache quittait la famille OpenCode (CLAUDE_HEADLESS) alors que `repli_ollama_cloud` (palier FREE)
etait configure. Un solde a zero est un quota a zero.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402

MESURE = ("erreur ACP OpenCode (RuntimeError): session/prompt -> {'code': -32603, 'message': "
          "'Internal error: Insufficient balance or no resource package. Please recharge.'}")


def test_le_solde_epuise_est_un_quota():
    assert te._RE_QUOTA.search(MESURE)


def test_les_quotas_deja_reconnus_le_restent():
    for m in ("Rate limit exceeded", "free-models-per-day", "HTTP 429 Too Many Requests", "quota exceeded"):
        assert te._RE_QUOTA.search(m), m
    assert not te._RE_QUOTA.search("HTTP 404 route retiree")
