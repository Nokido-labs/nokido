"""NR canal M2M `roadmap_item` (decision owner 24/10) : contrat, keeper, apply_fact en observation."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_roadmap_keeper as K  # noqa: E402
from app import forge_m2m_protocol as M  # noqa: E402

ITEM = {"intent": "ROADMAP_ITEM", "etat": "OUVERT", "prio": "P1", "titre": "t",
        "reste": ["a"], "preuve": "abc1234"}


def test_contrat_declare_le_canal():
    cat = json.loads((ROOT / "config" / "m2m_intents.json").read_text(encoding="utf-8"))
    req = cat["schema_rules"]["required_fields_by_channel"]["roadmap_item"]
    assert set(req) == {"intent", "etat", "prio", "titre", "reste", "preuve"}
    assert "ROADMAP_ITEM" in cat["intents"]


def test_validate_roadmap_item_ok_et_champ_manquant():
    assert M.validate("roadmap_item", dict(ITEM))["code"] == "M2M_OK"
    bad = {k: v for k, v in ITEM.items() if k != "preuve"}
    assert M.validate("roadmap_item", bad)["code"] == "M2M_ERR_MISSING_FIELD"


@pytest.mark.parametrize("texte", [
    "[OUVERT] x RESTE = brancher le truc]",
    "[OUVERT] x RESTE : brancher le truc",
    "[OUVERT] x (5) RESTE : brancher le truc",
    "[OUVERT] x EN COURS : brancher le truc",
    "[OUVERT] x Ensuite : brancher le truc",
])
def test_reste_cinq_variantes(texte):
    assert K.extraire_reste(texte) == ["brancher le truc"]
    assert K._reste_arbre(texte) == "brancher le truc"


def test_reste_illisible():
    assert K.extraire_reste("[OUVERT] rien de structure") == ["ILLISIBLE"]


def test_lecture_structuree_prioritaire():
    val = json.dumps(dict(ITEM, etat="CLOS", reste=["x", "y"]))
    s = K.lire_structure(val)
    assert s["etat"] == "CLOS" and s["reste"] == ["x", "y"]
    assert K.lire_structure("[OUVERT] prose") is None
    assert K.lire_structure('{"intent": "AUTRE"}') is None


def test_structurer_texte_conserve_etat_inchange():
    txt = "P1: [PARTIEL] titre RESTE = faire ceci]"
    s = K.structurer(txt)
    assert s["intent"] == "ROADMAP_ITEM" and s["etat"] == "PARTIEL" and s["prio"] == "P1"
    assert s["texte"] == txt and s["reste"] == ["faire ceci"]
    assert K.structurer("[OUVERT] vide")["reste"] == ["ILLISIBLE"]


def test_migration_dry_run_par_defaut():
    faits = [{"key": "P1_a", "value": "[OUVERT] x RESTE : y"}]
    rep = K.migrer_structurer(faits)
    assert rep["dry_run"] is True and rep["a_migrer"] == 1 and rep["ecrits"] == 0


def test_apply_fact_observation_puis_enforce(monkeypatch):
    from app import forge_swarm_blackboard as B
    ecrits = []
    monkeypatch.setattr(B, "_write_fact", lambda *a, **k: ecrits.append(a))
    monkeypatch.setattr(B, "_garde_clos", lambda *a, **k: None)
    bad = json.dumps({"intent": "ROADMAP_ITEM", "etat": "OUVERT"})
    monkeypatch.delenv("NOKIDO_ROADMAP_SCHEMA", raising=False)
    r = asyncio.run(B.apply_fact("architecture_rules", bad, category="roadmap", key="k1", ring=1))
    assert r.get("ok") and len(ecrits) == 1
    monkeypatch.setenv("NOKIDO_ROADMAP_SCHEMA", "enforce")
    r = asyncio.run(B.apply_fact("architecture_rules", bad, category="roadmap", key="k2", ring=1))
    assert "error" in r and len(ecrits) == 1
    r = asyncio.run(B.apply_fact("architecture_rules", "[OUVERT] prose", category="roadmap", key="k3", ring=1))
    assert r.get("ok")
