# -*- coding: utf-8 -*-
"""NR — `@evolve` doit lier le RAG, les reglages et le versionnement avant usage.

`handle_at_evolve` lisait `rag_engine`, `settings` et `version_manager` comme des
globals que seul le monolithe definit (14 lectures) : `@evolve <requete>` levait
NameError des le test `if not rag_engine`, hors de tout `try`. Seule la closure
`_bench_only` les liait correctement, par `app_ctx()`. Releve par l'audit « noms
non definis » (mesures/audits/noms_non_definis.md).

Correctif : la meme liaison que `_bench_only`, en tete du handler. Test statique :
le cycle demande Ollama, le RAG et un gestionnaire de versions.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_contexte_d_evolve_est_lie():
    manquants = noms_globaux_non_lies("app/forge_at_dispatch.py", "handle_at_evolve")
    assert not ({"rag_engine", "settings", "version_manager"} & manquants)
