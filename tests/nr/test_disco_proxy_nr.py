# -*- coding: utf-8 -*-
"""NR — `@disco` avec recherche web doit resoudre son proxy sans NameError.

`handle_disco` choisissait le proxy par `get_proxy_url(...)` /
`get_best_proxy_url()`, fonctions du seul monolithe jamais liees dans
`forge_disco` : NameError des que la recherche web est active. `forge_web`
expose deja exactement ce choix (`_get_proxy_url(name)` : proxy nomme, sinon le
meilleur disponible, lus sur le monolithe). Releve par l'audit « noms non
definis » (mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import imports_introuvables, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_disco.py"


def test_le_choix_du_proxy_est_lie():
    assert not ({"get_proxy_url", "get_best_proxy_url"} & noms_globaux_non_lies(FICHIER, "handle_disco"))


def test_le_resolveur_importe_existe():
    assert imports_introuvables(FICHIER, "handle_disco") == set()
