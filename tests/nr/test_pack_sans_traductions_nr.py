# -*- coding: utf-8 -*-
"""NR -- 1/11, workflow public « Installation complete » rouge sur 3 OS depuis v0.20.15 (vert le 21/10) : rag_direct
attendait la doc d'installation pour « How do I install Nokido with pip? » ; les 7 README_complet traduits (meme
contenu que l'anglais, retraduits le 31/10 - 1/11) passaient devant. Choix owner : exclure docs/i18n du Knowledge Pack
(les traductions dupliquent l'anglais x 7 : pack plus petit, resultats non dilues). L'anglais reste dans le pack."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_knowledge_pack_export as K  # noqa: E402


def test_les_traductions_ne_vont_pas_dans_le_pack():
    for p in ("docs/i18n/README_complet.de.md", "docs/i18n/README.fr.md", "docs/i18n/MANIFESTO.en.md"):
        assert K.classe_natif(p) is None, p


def test_l_anglais_et_la_doc_d_installation_restent():
    assert K.classe_natif("docs/README_complet.md") == "doc"
    assert K.classe_natif("docs/wiki/01-Installation.md") is not None   # classe « wiki »
    assert K.classe_natif("README.md") == "doc"
