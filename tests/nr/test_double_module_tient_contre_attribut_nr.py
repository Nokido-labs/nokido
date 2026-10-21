"""NR 20/10 -- un double pose par monkeypatch.setitem(sys.modules, "a.b.c", d) TIENT aussi contre `from a.b import c`.

Mesure : 3 rouges de la CI de reference 0c9c4e4d0 (test_pack_rag_non_filtre_refuse_nr, verts seuls). `from paquet
import sous_module` lit d'abord l'ATTRIBUT du paquet ; si un voisin de worker xdist a deja importe le vrai module, le
double de sys.modules est contourne. Tri statique du 20/10 : 57 modules doubles dans 72 fichiers de tests, dont 32
importes quelque part sous cette forme. Remede GENERIQUE dans le conftest : setitem sur sys.modules pose aussi
l'attribut du paquet parent, et le defait avec lui.
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest

NOM = "nokido_agent.tools.forge_knowledge_pack_export"


def test_le_double_tient_meme_si_le_vrai_module_est_deja_importe(monkeypatch):
    vrai = importlib.import_module(NOM)
    double = types.ModuleType("double_temoin")
    monkeypatch.setitem(sys.modules, NOM, double)
    from nokido_agent.tools import forge_knowledge_pack_export as vu
    assert vu is double, "le double de sys.modules est contourne par l'attribut du paquet"
    assert vrai is not double


def test_l_attribut_du_paquet_est_rendu_apres_le_test():
    vrai = importlib.import_module(NOM)
    paquet = sys.modules["nokido_agent.tools"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, NOM, types.ModuleType("double_temoin"))
    assert sys.modules[NOM] is vrai
    assert getattr(paquet, "forge_knowledge_pack_export") is vrai
