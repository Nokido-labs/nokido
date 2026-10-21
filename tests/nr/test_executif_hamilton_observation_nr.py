# -*- coding: utf-8 -*-
"""NR -- executif Hamilton en OBSERVATION, greffe sur le delestage doux existant (owner 2026-10-18, audit RAM).

Le delestage doux (`_supervisor_sleep_non_essential`, RAM >= 78 %) endort une liste figee SANS regarder qui
porte la pression : sous la fuite NON-SOI du pilote mtkbtsvc il endort le corps pour rien, puis le reveil
(< 65 %) le relance -- le va-et-vient que l'owner voit. Regle « observer avant d'enforcer » : Hamilton ne
change RIEN ici, il journalise ce qu'il AURAIT fait a cote de ce que la liste a fait.

Contrats (TOML, registre, memoire, capacites et superviseur remplaces par des doublures) :
  1. `plan_hamilton` classe les services VIVANTS du registre, mesure leur memoire privee, ordonne selon le
     verdict d'attribution ; mode OBSERVATION ;
  2. un verdict NON_SOI ne deleste rien ;
  3. une capacite critique illisible range le service VITAL (liste blanche), jamais delestable ;
  4. TOML illisible -> verdict ILLISIBLE, rien a delester, et dit ;
  5. le delestage doux journalise `hamilton_observe` (aurait_deleste + endormis_par_la_liste) et endort
     EXACTEMENT la meme liste qu'avant.
"""
import sys
import urllib.request
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402
from nokido_agent.app import forge_service_capabilities as caps  # noqa: E402

pytestmark = pytest.mark.timeout(60)

TOML = {
    "Fond": {"essential": False, "wave": 5, "heartbeat_tier": "slow"},
    "Hub": {"essential": True, "wave": 1},
    "Cerveau": {"essential": False, "wave": 4, "heartbeat_tier": "fast"},
    "Eteint": {"essential": False, "wave": 5, "disabled": True},
}
REGISTRE = {"Fond": 11, "Hub": 22, "Cerveau": 33, "Inconnu": 44}
MEMOIRE = {11: 900.0, 22: 4000.0, 33: 100.0, 44: 50.0}


@pytest.fixture()
def corps(monkeypatch):
    journal = []
    monkeypatch.setattr(rm, "_services_du_toml", lambda: dict(TOML))
    monkeypatch.setattr(rm, "_registre_corps", lambda: dict(REGISTRE))
    monkeypatch.setattr(rm, "_memoire_privee_mb", lambda pid: MEMOIRE.get(pid))
    monkeypatch.setattr(caps, "is_critical", lambda nom: False)
    monkeypatch.setattr(rm, "_audit_lifecycle", lambda action, domain, reason="", **kw:
                        journal.append({"action": action, "reason": reason, **kw}))
    return journal


def test_le_plan_classe_les_vivants_et_ne_deleste_que_le_differable(corps):
    p = rm.plan_hamilton(attrib={"verdict": "SOI"})
    assert p["mode"] == "OBSERVATION"
    assert [d["service"] for d in p["delester"]] == ["Fond"]
    assert p["delester"][0]["rss_mb"] == 900.0
    # hors TOML (Inconnu) et eteint ne sont jamais candidats
    assert {e["service"] for e in p["epargnes"]} == {"Hub", "Cerveau"}


def test_pression_non_soi_rien_a_delester(corps):
    p = rm.plan_hamilton(attrib={"verdict": "NON_SOI"})
    assert p["delester"] == [] and "NON_SOI" in p["motif"]


def test_capacite_illisible_vaut_vital(corps, monkeypatch):
    def _ko(nom):
        raise RuntimeError("source des capacites muette")
    monkeypatch.setattr(caps, "is_critical", _ko)
    p = rm.plan_hamilton(attrib={"verdict": "SOI"}, detresse=True)
    assert p["delester"] == []
    assert {e["classe"] for e in p["epargnes"]} == {"VITAL"}


def test_toml_illisible_le_dit(corps, monkeypatch):
    monkeypatch.setattr(rm, "_services_du_toml", lambda: None)
    p = rm.plan_hamilton(attrib={"verdict": "SOI"})
    assert p["verdict"] == "ILLISIBLE" and p["delester"] == [] and p["motif"]


def test_le_delestage_doux_journalise_hamilton_sans_changer_ce_qu_il_endort(corps, monkeypatch):
    endormis = []

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None):
        endormis.append(req.full_url.rsplit("/", 1)[-1])
        return _R()

    monkeypatch.setattr(rm, "_non_essential_sains", lambda: ["Cerveau", "Fond"])
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda: {})
    monkeypatch.setattr(rm, "attribuer_pression", lambda force=False: {"verdict": "NON_SOI", "mesure_ts": 1.0})
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    rm._supervisor_sleep_non_essential()
    assert endormis == ["Cerveau", "Fond"]
    obs = [j for j in corps if j["action"] == "hamilton_observe"]
    assert len(obs) == 1
    assert obs[0]["aurait_deleste"] == [] and obs[0]["endormis_par_la_liste"] == ["Cerveau", "Fond"]
    assert obs[0]["verdict"] == "NON_SOI"
