"""NR -- le guetteur n'ecarte comme bruit QUE ce qui nomme l'exportateur OTLP ; une vraie panne de connexion reste lisible.

Relecture 24/10 de 3fcb3c1c9 : le filtre `_BRUIT_OTLP` ecartait aussi `Max retries exceeded`, `NewConnectionError`,
`ConnectionRefusedError` et `WinError 10061` SANS mention de l'exportateur. Un job mort parce que le hub (:8766) est
eteint perdait alors son motif : rc non nul toujours ECHEC, mais un motif masque.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_job_watch_cli as W  # noqa: E402

_HUB_ETEINT = """Traceback (most recent call last):
  File "sandbox/workspace/mon_job.py", line 12, in <module>
    r = urllib.request.urlopen("http://127.0.0.1:8766/health")
urllib.error.URLError: <urlopen error [WinError 10061] Aucune connexion n'a pu etre etablie>
ConnectionRefusedError: [WinError 10061] Aucune connexion n'a pu etre etablie
requests.exceptions.ConnectionError: HTTPConnectionPool(host='127.0.0.1', port=8766): Max retries exceeded with url: /health (Caused by NewConnectionError('Failed to establish a new connection'))"""


def test_vraie_panne_de_connexion_garde_son_motif():
    lignes = W._sans_bruit_technique(_HUB_ETEINT.splitlines())
    texte = "\n".join(lignes)
    assert "8766" in texte, texte
    assert "ConnectionRefusedError" in texte


def test_le_bruit_qui_nomme_l_exportateur_reste_ecarte():
    bruit = ("Transient error HTTPConnectionPool(host='127.0.0.1', port=4318): Max retries exceeded with url: /v1/traces "
             "(Caused by NewConnectionError(...))\nFailed to export spans batch due to timeout, max retries or shutdown.")
    assert W._sans_bruit_technique(bruit.splitlines()) == []
