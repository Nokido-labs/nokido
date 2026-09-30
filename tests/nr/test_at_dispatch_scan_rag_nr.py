# -*- coding: utf-8 -*-
"""NR — la branche `run_async` de `@scan` doit transmettre un moteur RAG lie.

Dans `handle_at_scan.do_scan`, la branche `nd.run_async(inject_rag=rag_engine)`
lisait `rag_engine`, global du monolithe absent de `forge_at_dispatch` : NameError
des qu'une implementation de `NetworkDiscovery` expose `run_async`. Chemin latent
aujourd'hui (la classe actuelle n'a pas `run_async`), mais il est ecrit pour
servir. Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Le correctif lit le moteur par `forge_app_context.get_rag()`, meme source que le
monolithe. Test statique : le chemin demande nmap et la TUI.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_moteur_rag_du_scan_est_lie():
    assert "rag_engine" not in noms_globaux_non_lies("app/forge_at_dispatch.py", "handle_at_scan")
