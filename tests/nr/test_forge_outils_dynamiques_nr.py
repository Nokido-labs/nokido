# -*- coding: utf-8 -*-
"""Non-regression — les deux outils dynamiques offerts en MCP sont EPROUVES.

Mesure 2026-08-29 (registre d'atteignabilite) : `forge_call_dynamic` et
`forge_list_dynamic_tools` ressortaient OFFERT_NON_PROUVE — exposes a la surface
MCP, sans qu'aucun test joue ne les touche. Or un selftest complet EXISTE
(`tools/forge_mcp_dynamic_selftest.py`, catalogue A1/A2, ring 2 vs ring 4,
dispatch generique et nomme, deny a ring 3) : il n'est simplement joue par
personne, parce qu'il vit dans `tools/` et qu'il ECRIT dans le registre reel
(`_registry_add` / `_registry_save`), ce qui l'exclut d'une suite pure.

Un test qui existe mais que rien n'execute protege autant qu'un test absent.

Ce fichier ne remplace pas ce selftest : il prouve, SANS RIEN FORGER ni ecrire,
que les deux fonctions repondent et que leur chemin d'erreur tient. Le selftest
reste la reference pour le bout-en-bout, a lancer en contexte trusted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TF = pytest.importorskip("forge_tool_forger")


def test_lister_les_outils_forges_rend_une_structure_exploitable():
    """Lecture pure. Le nombre d'outils n'est PAS asserte : un depot vierge en a
    zero, et un test qui exigerait un chiffre echouerait sur une copie propre."""
    out = TF.forge_list_dynamic_tools()
    assert isinstance(out, dict) and "tools" in out, out
    assert isinstance(out["tools"], list)
    for t in out["tools"]:
        assert {"name", "description"} <= set(t), t
        assert isinstance(t["name"], str) and t["name"], t


def test_le_compte_annonce_correspond_a_la_liste():
    """Un compte qui diverge de la liste ferait croire a des outils invisibles."""
    out = TF.forge_list_dynamic_tools()
    if "count" in out:
        assert out["count"] == len(out["tools"]), out


def test_appeler_un_outil_INEXISTANT_refuse_proprement():
    """LE test du chemin d'erreur : un nom inconnu doit rendre un refus lisible,
    pas une exception qui remonte au client MCP."""
    try:
        r = TF.forge_call_dynamic("outil_qui_nexiste_pas_2026")
    except Exception as ex:  # noqa: BLE001
        pytest.fail("un nom inconnu a leve %s au lieu de rendre un refus"
                    % type(ex).__name__)
    assert isinstance(r, dict), r
    assert r.get("ok") is False or "error" in r or "erreur" in r, r


def test_le_selftest_de_bout_en_bout_existe_toujours():
    """Ce fichier ne couvre que la surface. Si le selftest complet disparait, la
    couverture reelle chute sans que rien ne baisse ici — on le dit."""
    p = ROOT / "tools" / "forge_mcp_dynamic_selftest.py"
    assert p.exists(), "selftest e2e des outils dynamiques disparu"
    src = p.read_text(encoding="utf-8", errors="replace")
    for attendu in ("forge_call_dynamic", "forge_list_dynamic_tools", "ring4"):
        assert attendu in src, "le selftest ne couvre plus %s" % attendu
