"""NR -- l'arbre de la roadmap ne compte pas les ETATS GLOBAUX (CURRENT_ / NEXT_) parmi les items, et le DIT.

Decision owner 19/10 (choix multiple) : `CURRENT_reprise_...` et `NEXT_audit_...` sont des faits d'etat global du projet
(RULES_SHARED : « CURRENT: et NEXT: disent l'etat global du projet et n'appartiennent a aucune session »), pas des items :
ils gonflaient le denominateur de cloture (142). Ils sortent du compte, et le document les nomme (`etats_globaux_exclus`).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_roadmap_keeper as K  # noqa: E402

FAITS = [
    {"key": "CURRENT_reprise_20261017_nuit", "value": "CURRENT: 2026-10-18 ~01 h 30 -- etat global", "trust": 0.9,
     "updated_at": 1},
    {"key": "NEXT_audit_securite_apres_roadmaps", "value": "NEXT: une fois les roadmaps finies, refaire l'audit",
     "trust": 0.9, "updated_at": 2},
    {"key": "P1_item_reel", "value": "[PARTIEL 2026-10-19 : reste = coder le GREEN]", "trust": 0.9, "updated_at": 3},
]


def test_les_etats_globaux_sortent_du_compte_et_sont_nommes(tmp_path, monkeypatch):
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda zone, *, category=None, min_trust=None, limit=200: list(FAITS)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)
    doc = K.arbre(out=tmp_path / "arbre.json")
    assert doc["total"] == 1 and [i["cle"] for i in doc["items"]] == ["P1_item_reel"]
    assert sorted(doc["etats_globaux_exclus"]) == ["CURRENT_reprise_20261017_nuit", "NEXT_audit_securite_apres_roadmaps"]
    assert sum(doc["par_etat"].values()) == 1
