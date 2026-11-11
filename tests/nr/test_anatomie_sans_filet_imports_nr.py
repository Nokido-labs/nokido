"""NR 11/11 -- le gate `anatomie` ne depend pas du filet « imports », qui varie d'une machine a l'autre.

Run self-hosted 42929942758 (a9603ce55) : `gates` ROUGE sur `tools/forge_gordon.py` « non classe », alors que le
pre-vol local du meme arbre etait VERT (job_470dcd142930). Cause : `organ()` classe par carte > nom > dossier >
IMPORTS > declaration. En local, les imports classaient le module AVANT que sa declaration soit lue ; sur le
runner ils ne donnaient rien, la declaration etait lue -- et elle etait ILLISIBLE (description sur la meme ligne :
`__FORGE_COLOR__ = "metabolisme/gordon : conseiller Docker en lecture ..."`).
Un module classe SEULEMENT par ses imports est donc un vert local fragile : sa declaration doit se lire seule.
Forme lisible : `__FORGE_COLOR__ = "organe/role"` SEULE sur sa ligne (ni description, ni commentaire en fin).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_module_census as census  # noqa: E402


def test_tout_module_reste_classe_sans_le_filet_imports(monkeypatch):
    """La vue du runner : filet imports muet -> 0 module non classe."""
    monkeypatch.setattr(census, "_organ_by_imports", lambda fname: None)
    non_classes = ["%s/%s" % (d, f.name) for d, f in census._modules()  # pylint: disable=protected-access
                   if census._organe_de(d, f).startswith("?")]  # pylint: disable=protected-access
    assert not non_classes, (
        "classes SEULEMENT par leurs imports (vert local, rouge sur le runner) -- declarer "
        "`__FORGE_COLOR__ = \"organe/role\"` seule sur sa ligne : %s" % non_classes)


def test_la_forme_de_declaration_lisible_est_la_forme_courte():
    """Verrouille ce que le lecteur accepte : la forme courte passe, une description sur la ligne non."""
    def lu(ligne):
        m = census.DECL_RE.search(ligne)
        return census._organ_by_text(m.group(1), source_is_declaration=True) if m else None  # pylint: disable=protected-access

    assert lu('__FORGE_COLOR__ = "metabolisme/gordon"')
    assert lu("__FORGE_COLOR__ = 'metabolisme/gordon'")
