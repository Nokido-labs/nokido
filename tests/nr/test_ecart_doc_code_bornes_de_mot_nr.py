# -*- coding: utf-8 -*-
"""NR -- le detecteur d'ecarts doc/code ne prend plus un morceau de nom pour un module absent.

Instruction AGY job_ff1fee28 (15 dossiers ECART_DOC_CODE de la file owner, 18/10) : deux dossiers etaient des FAUX
POSITIFS du producteur `_modules_absents_des_docs`, pas des docs faux -- son motif `forge_\\w+\\.py` n'avait aucune
borne : `forge_public_mirror_nr.py` lu DANS `test_forge_public_mirror_nr.py`, `forge_starter.py` lu DANS
`forge_starter.pyc`. Chaque faux positif devient un dossier que l'owner doit arbitrer pour rien.

Contrat : `_RX_MODULE_DOC` (motif de module, au niveau du module) borne le nom des deux cotes.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_autonomous_loops as L  # noqa: E402


@pytest.mark.parametrize("texte, attendu", [
    ("voir tests/nr/test_forge_public_mirror_nr.py", []),
    ("binaire app/_attic/forge_starter.pyc", []),
    ("le module `app/forge_council.py` deliberera", ["app/forge_council.py"]),
    ("chemin Nokido/tools/forge_x.py, puis", ["tools/forge_x.py"]),
    ("forge_wasm_embedder.py (wasmtime)", ["forge_wasm_embedder.py"]),
    ("myforge_y.py n'est pas un module forge", []),
])
def test_le_motif_borne_le_nom_des_deux_cotes(texte, attendu):
    assert L._RX_MODULE_DOC.findall(texte) == attendu
