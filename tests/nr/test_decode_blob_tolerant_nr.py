"""NR -- le decodeur de vecteurs lit le binaire ET le JSON, et ne fabrique jamais un vecteur faux.

Recensement du 2026-10-01 : 359 005 vecteurs (~20 %) stockes en JSON (321 758 TEXT, 37 247 BLOB)
a cote de 1 459 808 binaires float32. `decode_blob` depaquetait un BLOB JSON comme du binaire
(~5 100 floats ABSURDES) et levait sur un TEXT. Decision owner : decodeur TOLERANT (la conversion
en base est un chantier a part). Le doublon de forge_semantic_pressure delegue a la regle unique.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(30)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_embed_router as er  # noqa: E402
from nokido_agent.app import forge_semantic_pressure as sp  # noqa: E402

VEC = [0.5, -0.25, 1.0, 0.0]


def test_le_binaire_canonique_reste_lu_a_l_identique():
    assert er.decode_blob(struct.pack("4f", *VEC)) == VEC


def test_le_json_texte_et_le_json_blob_sont_lus():
    texte = json.dumps(VEC)
    assert er.decode_blob(texte) == VEC
    assert er.decode_blob(texte.encode("utf-8")) == VEC, "un BLOB JSON n'est plus lu comme du binaire"


@pytest.mark.parametrize("illisible", [b"", None, b"[1, 2", b"\x00\x00\x00", "[]", '["a"]', "[true, false]"])
def test_l_illisible_rend_none_sans_lever(illisible):
    assert er.decode_blob(illisible) is None


def test_le_doublon_delegue_a_la_regle_unique():
    assert sp._decode_blob(json.dumps(VEC).encode("utf-8")) == VEC
    assert sp._decode_blob(struct.pack("4f", *VEC)) == VEC
