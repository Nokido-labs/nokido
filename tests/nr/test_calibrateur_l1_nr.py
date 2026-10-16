"""NR — declaration L1 `embed.batch_size` et calibrateur qui la propose (debat RSI 15/10).

AGY, tour 1 : « en regime nominal, aucun module ne propose de variation » -> producteur L1.
Il PROPOSE seulement (action set_param, exp_id unique pour la reprise apres crash) ; appliquer
reste a l'applicateur (porte, plafonds, mesure). Registre et ecriture des propositions simules.
"""
import pytest

from nokido_agent.app import forge_autonomous_loops as L
from nokido_agent.app import forge_mutation_controller as ctl
from nokido_agent.app import forge_proposal_applier as pa


def test_la_declaration_est_conforme_et_sa_mesure_existe():
    d = pa.PARAMS_L1["embed.batch_size"]
    assert d["type"] == "int" and d["min"] == 8 and d["max"] == 128 and d["defaut"] == 32
    assert set(d["bruit"]) == {"textes_par_seconde", "taux_succes"}
    assert callable(pa._mesure_declaree("embed.batch_size"))
    assert pa._valeur_conforme("embed.batch_size", 40) is None
    assert pa._valeur_conforme("embed.batch_size", 200) is not None


@pytest.fixture
def calib(monkeypatch):
    propositions = []

    def proposer(**kw):
        propositions.append(kw)
        kw["issues"].append("WRITTEN")
        return True

    monkeypatch.setattr(L, "_proposer", proposer)
    monkeypatch.setattr(pa, "PARAMS_L1", {"embed.batch_size": dict(pa.PARAMS_L1["embed.batch_size"])})
    return propositions


def _actes(n):
    return [{"kind": "application", "cible": "param:embed.batch_size"} for _ in range(n)]


def test_premier_pas_vers_le_haut(monkeypatch, calib):
    monkeypatch.setattr(ctl, "_lire_registre", lambda: [])
    monkeypatch.setattr(pa, "valeur_l1", lambda nom, defaut=None: 32)
    out = L.pat_l1_calibration()
    a = calib[0]["evidence"]["action"]
    assert a["type"] == "set_param" and a["valeur"] == 40 and a["exp_id"].startswith("l1cal-embed.batch_size-")
    assert calib[0]["confidence"] >= pa.CONF_REFLEXE and out["issue"] == "WRITTEN:1"


def test_le_sens_alterne(monkeypatch, calib):
    monkeypatch.setattr(ctl, "_lire_registre", lambda: _actes(1))
    monkeypatch.setattr(pa, "valeur_l1", lambda nom, defaut=None: 32)
    L.pat_l1_calibration()
    assert calib[0]["evidence"]["action"]["valeur"] == 24


def test_une_borne_retourne_le_sens(monkeypatch, calib):
    monkeypatch.setattr(ctl, "_lire_registre", lambda: [])
    monkeypatch.setattr(pa, "valeur_l1", lambda nom, defaut=None: 128)
    L.pat_l1_calibration()
    assert calib[0]["evidence"]["action"]["valeur"] == 96


def test_sans_mesure_rien_n_est_propose(monkeypatch, calib):
    monkeypatch.setattr(pa, "PARAMS_L1", {"x": {"type": "int", "min": 1, "max": 9, "defaut": 4}})
    monkeypatch.setattr(ctl, "_lire_registre", lambda: [])
    out = L.pat_l1_calibration()
    assert calib == [] and out["issue"] == "NO_SIGNAL"


def test_le_calibrateur_ne_mute_rien(monkeypatch, calib):
    monkeypatch.setattr(ctl, "_lire_registre", lambda: [])
    monkeypatch.setattr(pa, "valeur_l1", lambda nom, defaut=None: 32)
    monkeypatch.setattr(pa, "_set_param", lambda action: pytest.fail("le calibrateur a pose une valeur"))
    L.pat_l1_calibration()
