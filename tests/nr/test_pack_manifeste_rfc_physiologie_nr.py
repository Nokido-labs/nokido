"""NR -- le manifeste reel declare les packs RFC et physiologie, licences prouvees (20/10).

- RFC : IETF TLP 5.0 section 3.c.iii (audit AGY 536584cee) ; la legende de CHAQUE RFC part dans la NOTICE
  (test_pack_rfc_notice_par_rfc_nr). Le composant manquait au manifeste : rien ne se construisait.
- Physiologie : OpenStax Anatomy and Physiology 2e, ingeree le 20/10 dans le domaine `physiologie` et vectorisee.
  Licence LUE a la source le 20/10 au commit epingle b0058a743b : LICENSE = « Attribution 4.0 International », README
  « available under the Creative Commons Attribution License ». CC BY exige l'attribution et la mention des
  modifications (decoupage en fragments).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
PHYSIO = "github:openstax/osbooks-anatomy-physiology"


def _composants():
    spec = importlib.util.spec_from_file_location("release_rfc_physio_nr", RACINE / "tools" / "forge_release_assets.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    v = m.valider_manifeste()
    assert v["ok"], v["erreurs"]
    return {c["famille"]: c for c in v["packs"]["knowledge"]["composants"] if c.get("construit") == "rag_pack_source"}


def test_le_pack_rfc_est_declare_sous_la_tlp():
    c = _composants().get("rfc")
    assert c, "composant rfc absent du manifeste"
    assert c["licence"] == "IETF-TLP-5.0" and c["preuve"] == "https://trustee.ietf.org/license-info/", c
    assert c["obligatoire"] is True, "owner 20/10 : tout est telecharge par defaut"


def test_le_pack_physiologie_est_declare_sous_cc_by_avec_son_domaine():
    c = _composants().get(PHYSIO)
    assert c, "composant physiologie absent du manifeste"
    assert c["licence"] == "CC-BY-4.0" and c.get("domaine") == "physiologie", c
    assert "b0058a743b" in c["preuve"] and c["preuve"].startswith("https://"), c
    assert "OpenStax" in c["conditions"] and "modifi" in c["conditions"], "attribution ET modifications dites"
    assert c["obligatoire"] is True
