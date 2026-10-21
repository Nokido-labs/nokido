"""NR -- l'arbre roadmap fusionne la CARTE des dependances (docs/roadmap_dependances.json) avec les citations du SSoT.

Mesure 19/10 sur le SSoT reel : les citations explicites ne donnent que 26 dependances pour 140 items (116 pendent encore
sous une priorite). La carte relisible `{aretes: [{de, vers, raison}]}` porte les dependances que le texte n'ecrit pas
sous forme de cle ; `arbre()` les ajoute aux `cite` de l'item dependant. Une arete vers une cle inconnue est ECARTEE et
comptee (`carte_ecartees`), jamais inventee ; une carte absente ou illisible ne casse rien et se dit (`carte`).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_roadmap_keeper as K  # noqa: E402

FAITS = [
    {"key": "p1_socle", "value": "[PARTIEL 2026-10-19 : reste = socle]", "trust": 0.9, "updated_at": 1},
    {"key": "p1_suite", "value": "[PARTIEL 2026-10-19 : reste = suite]", "trust": 0.9, "updated_at": 2},
]


def _double(monkeypatch):
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda zone, *, category=None, min_trust=None, limit=200: list(FAITS)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)


def test_la_carte_ajoute_une_dependance_et_ecarte_l_inconnu(tmp_path, monkeypatch):
    _double(monkeypatch)
    carte = tmp_path / "deps.json"
    carte.write_text(json.dumps({"aretes": [
        {"de": "p1_socle", "vers": "p1_suite", "raison": "la suite se construit sur le socle"},
        {"de": "p1_fantome", "vers": "p1_suite", "raison": "cle inconnue"}]}), encoding="utf-8")
    monkeypatch.setattr(K, "CARTE_DEPENDANCES", carte)
    doc = K.arbre(out=tmp_path / "a.json")
    par = {i["cle"]: i for i in doc["items"]}
    assert par["p1_suite"]["cite"] == ["p1_socle"] and par["p1_socle"]["cite"] == []
    assert doc["carte_ecartees"] == 1 and doc["carte"] == "lue"


def test_carte_absente_ne_casse_rien_et_se_dit(tmp_path, monkeypatch):
    _double(monkeypatch)
    monkeypatch.setattr(K, "CARTE_DEPENDANCES", tmp_path / "absente.json")
    doc = K.arbre(out=tmp_path / "a.json")
    assert doc["carte"] == "absente" and doc["total"] == 2
