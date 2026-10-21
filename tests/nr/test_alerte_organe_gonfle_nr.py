# -*- coding: utf-8 -*-
"""NR (audit pair F, suite de 19921e13c) -- un hub qui gonfle par rapport a sa propre baseline est DIT au pilote.

Mesure 19/10 : hub 0,45 -> 8,5 Go en 10 min, RAM 95,5 %, aucun organe ne l'a signale (Hamilton : verdict NON_SOI ;
fuyards_hors_corps : le corps exclu). gonflement_organe (19921e13c) le detecte ; il manquait l'EFFERENT. Contrat de
`forge_resource_manager._alerter_organe_gonfle(maintenant=None, chemin=None)` :
  1. lit la queue de sandbox/hub_blackbox.jsonl (pid courant du hub), juge avec gonflement_organe ;
  2. GONFLE -> une entree `organe_gonfle` dans l'audit de cycle de vie (la voix que le pilote relit), remede propose
     = relance du hub ; JAMAIS d'action automatique sur un VITAL ;
  3. au plus une fois par 6 h pour le meme pid ;
  4. NORMAL ou INCONNU (fichier absent, serie courte) -> rien, aucune exception ;
  5. la boucle d'echantillonnage l'appelle (chemin reel).
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app import forge_resource_manager as rm  # noqa: E402

T0 = 1_000_000.0
SOIR_19_10 = [0.535, 0.581, 1.367, 0.728, 0.471, 0.46, 0.472, 0.388, 0.402, 0.372, 0.432, 0.352, 3.307, 8.511]


def _boite(tmp_path, valeurs, pid=5988):
    f = tmp_path / "hub_blackbox.jsonl"
    f.write_text("".join(json.dumps({"ts": T0 + i * 300.0, "ram_pct": 80.0, "hub": {"pid": pid, "rss_gb": v}}) + "\n"
                         for i, v in enumerate(valeurs)), encoding="utf-8")
    return f, T0 + (len(valeurs) - 1) * 300.0


@pytest.fixture()
def audits(monkeypatch):
    vus = []
    monkeypatch.setattr(rm, "_audit_lifecycle", lambda *a, **k: vus.append((a, k)))
    monkeypatch.setattr(rm, "_GONFLE_NOTIFIES", {}, raising=False)
    return vus


def test_le_gonflement_est_dit_une_seule_fois_par_6h(tmp_path, audits):
    f, fin = _boite(tmp_path, SOIR_19_10)
    v = rm._alerter_organe_gonfle(maintenant=fin, chemin=f)
    assert v["etat"] == "GONFLE"
    assert len(audits) == 1 and audits[0][0][0] == "organe_gonfle", audits
    rm._alerter_organe_gonfle(maintenant=fin + 60, chemin=f)
    assert len(audits) == 1, "redit en moins de 6 h"


def test_normal_ou_inconnu_ne_dit_rien(tmp_path, audits):
    f, fin = _boite(tmp_path, [0.4] * 14)
    assert rm._alerter_organe_gonfle(maintenant=fin, chemin=f)["etat"] == "NORMAL"
    assert rm._alerter_organe_gonfle(chemin=tmp_path / "absent.jsonl")["etat"] == "INCONNU"
    assert audits == []


def test_la_boucle_d_echantillonnage_l_appelle():
    assert "_alerter_organe_gonfle(" in inspect.getsource(rm._sampler_loop)
