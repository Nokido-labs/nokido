# -*- coding: utf-8 -*-
"""NR — la veille des CLI couvre la doc de CLAUDE CODE, pas seulement celle de l'API.

Constat du 2026-09-24 (question owner « es-tu a jour de tes veilles sur
code.claude.com/docs ? ») : la cible `claude` de `tools/forge_cli_version_watch.py`
pointait `platform.claude.com/llms.txt`, l'index de l'API. La doc de Claude Code
vit sur un AUTRE site (`code.claude.com/docs/llms.txt`, 208 pages le 24/09) et
n'etait surveillee par personne : des capacites livrees entre v2.1.2xx et
v2.1.281 sont restees inconnues de l'agent qui s'en sert.

Ce NR verrouille la couverture (la cible existe) et l'unicite des cles et des
domaines RAG : deux cibles sur le meme `domain` se re-ingereraient l'une sur
l'autre sans que rien ne le signale.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "forge_cli_version_watch_nr", ROOT / "tools" / "forge_cli_version_watch.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_la_doc_claude_code_est_une_cible():
    urls = {url for _cle, _exe, url, _dom in _module().CIBLES if url}
    assert "https://code.claude.com/docs/llms.txt" in urls, (
        "la doc Claude Code n'est plus surveillee : seule l'API l'est")


def test_la_doc_de_l_api_reste_une_cible():
    urls = {url for _cle, _exe, url, _dom in _module().CIBLES if url}
    assert "https://platform.claude.com/llms.txt" in urls


def test_cles_et_domaines_uniques():
    cibles = _module().CIBLES
    cles = [c for c, _e, _u, _d in cibles]
    domaines = [d for _c, _e, _u, d in cibles if d]
    assert len(cles) == len(set(cles)), cles
    assert len(domaines) == len(set(domaines)), domaines
