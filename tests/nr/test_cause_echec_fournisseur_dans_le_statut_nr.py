"""NR -- la CAUSE d'un echec fournisseur atteint la trace (2026-10-13).

Mesure : mistral 11/11, deepseek 5/5, groq 2/2 traces `ERR` sans cause alors que la cause reelle etait
« credit epuise » (402) et « modele hors palier » (403). Le motif vit dans la charge du journal d'audit,
tronquee avant le statut ; le statut survit et le capteur de traces lit deja `ERR:<code>`.
Chemin reel : statut de `log_cloud_in` -> ligne d'audit -> `forge_trace_sidecar._STATUS_RE`.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NL = pytest.importorskip("forge_network_logger")


@pytest.mark.parametrize("motif,attendu", [
    ("ERR: Provider deepseek failed: Error code: 402 - {'error': {'message': 'Insufficient Balance'}}", "ERR:402"),
    ("ERR: Error code: 403 - {'message': 'This model is not available in your subscription tier'}", "ERR:403"),
    ("ERR: HTTP 429 Too Many Requests", "ERR:429"),
    ("ERR: TimeoutError: timed out", "ERR:timeout"),
    ("ERR: Insufficient Balance", "ERR:402"),
    ("ERR: ConnectionRefused http://127.0.0.1:8091", "ERR:connexion"),
    ("ERR: quelque chose d'illisible", "ERR"),
])
def test_la_classe_de_cause_entre_dans_le_statut(motif, attendu):
    assert NL.statut_erreur_cloud(motif) == attendu


def test_log_cloud_in_ecrit_le_statut_classe_et_ok_reste_ok(monkeypatch):
    vus = []
    monkeypatch.setattr(NL, "net_log", lambda *a, **k: vus.append(k.get("status")))
    NL.log_cloud_in("deepseek", "deepseek-chat", "HUB", "ERR: Error code: 402 - Insufficient Balance", 12.0)
    NL.log_cloud_in("groq", "gpt-oss-120b", "HUB", "PONG", 5.0)
    assert vus == ["ERR:402", "OK"], vus


def test_le_sidecar_lit_le_statut_classe_en_fin_de_ligne():
    sc = pytest.importorskip("forge_trace_sidecar")
    ligne = ('2026-10-13T18:23:34 | NetworkChannel.CLOUD:deepseek | {"direction": "Direction.IN", '
             '"agent": "HUB", "provider": "deepseek", "mo | ERR:402')
    m = sc._STATUS_RE.search(ligne)
    assert m and m.group(1) == "ERR:402"
    assert sc.succes_de("ERR:402") is False
