# -*- coding: utf-8 -*-
"""NR — `BSL-1.0` (Boost) n'est pas `BSL-1.1` (Business Source).

__FORGE_COLOR__ = "qualite/gate : non-regression du garde de licence AGPLv3"

CE QUI A ÉTÉ PAYÉ (2026-09-07). Le gate de licence refusait `torch 2.13.0`, dont
l'expression SPDX est `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause
AND BSD-3-Clause AND BSL-1.0 AND MIT` — **que des licences de l'allowlist**. Le motif
interdit `"bsl-"` visait Business Source License et attrapait **Boost Software License**.

Deux licences s'écrivent `BSL-1.x`, une seule est interdite :

| sigle | vraie licence | statut |
|---|---|---|
| `BSL-1.0` | **Boost** Software License | permissive, **compatible** AGPLv3 |
| `BSL-1.1` / `BUSL-1.1` | **Business Source** License | source-available, **NON libre** |

Le garde était JUSTE (refuser Business Source est correct), son DIAGNOSTIC était FAUX.
La règle de la maison s'applique telle quelle : **on corrige le diagnostic, jamais on ne
contourne le garde** — et un faux positif se corrige tout de suite, sinon un garde qui
crie à faux finit désarmé.

Ce test tient les DEUX bords : le faux positif ne doit pas revenir, et la couverture de
Business Source ne doit pas avoir été sacrifiée pour l'obtenir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


def _guard():
    import forge_license_guard as g  # noqa: PLC0415

    return g


@pytest.mark.parametrize("licence", [
    "BSL-1.0",
    "Boost Software License 1.0",
    "Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause"
    " AND BSL-1.0 AND MIT",                      # l'expression EXACTE de torch 2.13.0
])
def test_boost_est_compatible(licence: str) -> None:
    g = _guard()
    bas = licence.lower()
    interdits = [d for d in g.DENY if d in bas]
    assert not interdits, (
        f"« {licence} » attrapee par {interdits} : Boost est PERMISSIVE et compatible AGPLv3")


@pytest.mark.parametrize("licence", [
    "Business Source License 1.1",
    "BUSL-1.1",
    "BSL-1.1",
    "bsl 1.1",
])
def test_business_source_reste_interdite(licence: str) -> None:
    """Le resserrement du motif ne doit pas avoir ouvert la porte a la licence visee."""
    g = _guard()
    bas = licence.lower()
    assert any(d in bas for d in g.DENY), (
        f"« {licence} » n'est plus attrapee : le garde a ete AFFAIBLI, pas corrige")


@pytest.mark.parametrize("licence", ["SSPL-1.0", "Elastic License 2.0", "Commons Clause",
                                     "CC-BY-NC-4.0", "Proprietary"])
def test_les_autres_interdites_sont_intactes(licence: str) -> None:
    g = _guard()
    assert any(d in licence.lower() for d in g.DENY), f"« {licence} » devrait rester refusee"


def test_le_motif_large_ne_revient_pas() -> None:
    """`bsl-` et `bsl ` nus sont precisement ce qui a produit le faux positif."""
    g = _guard()
    assert "bsl-" not in g.DENY, "motif trop large : il attrape Boost (BSL-1.0)"
    assert "bsl " not in g.DENY, "motif trop large : il attrape Boost (BSL-1.0)"


def test_la_raison_reste_ecrite() -> None:
    """Sans l'explication des homonymes, le prochain elargira le motif « pour bien faire »."""
    src = (ROOT / "tools" / "forge_license_guard.py").read_text(encoding="utf-8",
                                                                errors="replace")
    assert "HOMONYMES" in src
    assert "Boost" in src and "Business Source" in src
