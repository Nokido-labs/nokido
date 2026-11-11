# -*- coding: utf-8 -*-
"""NR (owner 3/11, diagnostic job_32c95d214473) : forge_deep_explore rendait 0 hit en silence.

Mesure sur forge_local_explore.search : une INTENTION en phrase (sans `target`) servait de regex litterale -> 0 ;
des `globs` passes en LISTE devenaient str(list) -> motifs invalides -> 0 ; et 0 hit revenait `ok: True` sans raison
(UNKNOWN != NO). Le NR traverse le vrai gestionnaire `ToolRegistry._handle_deep_explore`.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from nokido_agent.app.forge_mcp_registry import ToolRegistry  # noqa: E402


@pytest.fixture(autouse=True)
def _sans_trace(monkeypatch):
    import nokido_agent.app.forge_introspect as fi

    monkeypatch.setattr(fi, "noter_consultation", lambda *a, **k: None)


def _appel(args):
    return asyncio.run(ToolRegistry._handle_deep_explore(None, args, "NR_TEST", 1))


def test_intention_seule_trouve_le_code():
    r = _appel({"intent": "où est définie valider_autorisation dans la route OAuth ?"})
    assert r.get("n_hits", 0) > 0, r.get("raison")
    assert any("forge_oauth_route.py" in f for f in r["files_touched"])


def test_globs_en_liste_acceptes():
    r = _appel({"intent": "x", "target": "valider_autorisation", "globs": ["app/forge_oauth*.py"]})
    assert r.get("n_hits", 0) > 0, r.get("raison")


def test_zero_hit_dit_pourquoi():
    r = _appel({"intent": "x", "target": "zzqq_introuvable_qqzz", "globs": "app/forge_oauth*.py"})
    assert r["n_hits"] == 0
    assert "raison" in r and "zzqq_introuvable_qqzz" in r["raison"]


def test_identifiant_present_ecarte_les_mots_communs():
    # Owner 3/11 apres restart : « definie|valider_autorisation|OAuth » diluait le classement (400 hits, la definition
    # hors des 20 extraits). Un identifiant fort present -> on ne cherche QUE les identifiants.
    q = ToolRegistry._requete_deep_explore("où est définie valider_autorisation dans la route OAuth ?", None)
    assert q == "valider_autorisation", q
    r = _appel({"intent": "où est définie valider_autorisation dans la route OAuth ?", "breadth": "narrow"})
    assert "forge_oauth_route.py" in r["digest"], r.get("requete")


def test_requete_derivee_echappe_les_identifiants():
    q = ToolRegistry._requete_deep_explore("Cartographier forge_dpop.py et la signature ES256", None)
    assert "forge_dpop\\.py" in q and "ES256" in q and "|" in q
    assert ToolRegistry._requete_deep_explore("peu importe", "cible|exacte") == "cible|exacte"
