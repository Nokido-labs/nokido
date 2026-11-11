# -*- coding: utf-8 -*-
"""NR (31/10) : Hamilton ne reprend plus en bloc ce qu'il a cede.

Mesure 31/10 (sandbox/regulation_tick.jsonl + sandbox/supervisor_ordres.jsonl, 2 observateurs) : 11:08, 11:12,
11:18 plancher 80,7 / 82,0 / 84,7 % -> 42 DIFFERABLE suspendus (RESOURCE_MANAGER) ; la RAM ne retombe qu'a
76-77 % (juste sous le seuil de 78) ; une fois le calme ecoule (double a chaque rechute : 3, 5, 9 min) les 42 sont
REPRIS d'un coup a 11:11, 11:17 et 11:27 -- a 11:17 SOUS pression (plancher 79 %, verdict NON_SOI, plan vide) -- et
le redemarrage recree la pression. Owner 31/10 : « la cognition doit nourrir le reveil utile des surfaces utiles » :
reprise par ordre de demande prouvee, dans un budget RAM projete (seuil de sommeil moins une marge), jamais un
service dont l'ABSENCE de demande est prouvee ; poids inconnu compte prudemment, RAM illisible = aucune reprise.
"""
# pylint: disable=protected-access,missing-function-docstring  # un NR de regulation exerce ses primitives privees
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_resource_manager as rm  # noqa: E402

T = 1_000_000.0
TOTAL_GB = 23.7  # RAM visible mesuree (iGPU 780M : 8 Go reserves)
MO_PAR_PT = TOTAL_GB * 1024 / 100.0


def _etat(n=42, poids=25.0):
    """n services en pause depuis 1 h, calme deja ecoule : tous eligibles a la reprise."""
    e = {"pause_ts": T - 3600, "calme_ts": T - rm._HAMILTON_CALME_MIN_S - 1, "rechutes": 0}
    if poids is not None:
        e["rss_mb"] = poids
    return {"Svc%02d" % i: dict(e) for i in range(n)}


def _reprises(r):
    return sorted(s for s, g in r["gestes"].items() if g == "REPRENDRE")


def _en_pause(r):
    return {s for s in r["etat"] if not s.startswith("_")}


def test_aucune_reprise_sous_pression():
    # 11:17:29 : plancher 79 %, verdict NON_SOI -> plan vide ; avant, les 42 etaient repris ICI
    r = rm.regulation_hamilton_ram({"verdict": "NON_SOI", "delester": []}, 79.0, TOTAL_GB, _etat(), T)
    assert _reprises(r) == []
    assert _en_pause(r) == set(_etat())  # restent en pause, eligibles quand la RAM le permettra


def test_juste_sous_le_seuil_rien_ne_repart():
    # 11:10-11:11 : 76,8 % ; plafond de reprise = 78 - marge -> rien
    r = rm.regulation_hamilton_ram({}, 76.8, TOTAL_GB, _etat(), T)
    assert _reprises(r) == []


def test_la_reprise_tient_dans_le_budget():
    r = rm.regulation_hamilton_ram({}, 70.0, TOTAL_GB, _etat(), T)
    n = len(_reprises(r))
    assert 0 < n < 42
    plafond = rm._SUPERVISOR_SLEEP_RAM_THRESHOLD - rm._HAMILTON_MARGE_REPRISE_PCT
    assert 70.0 + n * 25.0 / MO_PAR_PT <= plafond + 1e-9
    assert len(_en_pause(r)) == 42 - n  # le reste attend le tick suivant, RAM relue


def test_la_demande_prouvee_passe_en_premier():
    demandes = {"Svc41": True, "Svc00": False}
    # 71 % : 2 pts de budget (~485 Mo) -> un seul service de 300 Mo : celui dont la demande est prouvee
    r = rm.regulation_hamilton_ram({}, 71.0, TOTAL_GB, _etat(poids=300.0), T, demandes=demandes)
    assert _reprises(r) == ["Svc41"]


def test_l_absence_de_demande_prouvee_reste_endormie():
    demandes = {"Svc00": False}
    r = rm.regulation_hamilton_ram({}, 40.0, TOTAL_GB, _etat(n=5, poids=100.0), T, demandes=demandes)
    assert "Svc00" not in _reprises(r) and "Svc00" in _en_pause(r)
    # les autres (aucun signal : UNKNOWN != NO) repartent dans le budget -- 7/11 : par lot, jamais les 4 d'un coup
    assert len(_reprises(r)) == min(4, rm._HAMILTON_REPRISE_LOT)


def test_poids_inconnu_compte_prudemment():
    # 72 % : 1 pt (~243 Mo) < poids inconnu -> aucune reprise (avant : un poids inconnu valait 0, tout repartait)
    r = rm.regulation_hamilton_ram({}, 72.0, TOTAL_GB, _etat(n=10, poids=None), T)
    assert _reprises(r) == []


def test_ram_illisible_aucune_reprise():
    r = rm.regulation_hamilton_ram({}, None, TOTAL_GB, _etat(), T)
    assert _reprises(r) == []
    assert _en_pause(r) == set(_etat())


def test_la_cession_retient_le_poids():
    plan = {"verdict": "SOI", "delester": [{"service": "A", "rss_mb": 120.0}, {"service": "B", "rss_mb": None}]}
    r = rm.regulation_hamilton_ram(plan, 85.0, TOTAL_GB, {}, T)
    assert r["gestes"].get("A") == "SUSPENDRE"
    assert r["etat"]["A"]["rss_mb"] == 120.0
    assert "rss_mb" not in r["etat"]["B"] or r["etat"]["B"]["rss_mb"] is None


def test_le_tick_lit_la_demande_des_services_en_pause(monkeypatch):
    """Le chemin reel : _demande_du_service dit True/False/None ; un executeur dedie sans tache = False."""
    monkeypatch.setattr(rm, "_agent_du_service", lambda s: "OPENCODE_GLM" if s.endswith("Glm") else None)
    monkeypatch.setattr(rm, "_taches_de_l_agent", lambda agent: 0)
    assert rm._demande_du_service("NokidoTaskExecutorOpencodeGlm") is False
    monkeypatch.setattr(rm, "_taches_de_l_agent", lambda agent: 2)
    assert rm._demande_du_service("NokidoTaskExecutorOpencodeGlm") is True
    assert rm._demande_du_service("NokidoTaskExecutor") is None  # generique : pas d'agent, pas de preuve
    assert rm._demande_du_service("NokidoGraphExplorer") is None  # aucun emetteur de demande : INCONNU
    monkeypatch.setattr(rm, "_taches_de_l_agent", lambda agent: None)
    assert rm._demande_du_service("NokidoTaskExecutorOpencodeGlm") is None  # illisible
