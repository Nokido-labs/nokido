"""NR -- regulation RAM GRADUEE face a une intention (owner 24/10, bareme a 4 paliers).

Owner : « l'intention est plus forte que la regulation » puis « il y a des nuances : critique, detresse, gene, gene
legere, ralentissement ». Avant : un seul geste (sommeil superviseur = MORT du processus) des 78 %, et l'executeur ne
lisait aucun signal de pression. Contrat :
- `palier_pression_ram(plancher_pct, libre_gb)` : CALME < 78 % ; RALENTISSEMENT >= 78 % ; GENE >= 88 % ;
  DETRESSE libre < 1,5 Go ; CRITIQUE libre < 0,5 Go ; mesure absente = INCONNU (jamais CALME).
- Hamilton publie le palier en hormone NORADRENALINE_PRESSION_RAM, l'executeur en est RECEPTEUR declare.
- Executeur : RALENTISSEMENT = boucle deux fois plus lente ; GENE = plus de nouvelle reclamation (la tache en vol
  continue) ; DETRESSE = delegation en vol GELEE, reprise des que le palier redescend ; INCONNU = comportement d'avant.
- Hamilton : le veto (intention) tient jusqu'a la DETRESSE comprise ; seul le CRITIQUE passe outre, et le DIT.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402
import nokido_agent.app.forge_endocrine as EN  # noqa: E402
import nokido_agent.app.forge_resource_manager as RM  # noqa: E402

HORMONE = "NORADRENALINE_PRESSION_RAM"


def test_paliers_de_pression():
    assert RM.palier_pression_ram(70.0, 8.0) == "CALME"
    assert RM.palier_pression_ram(80.0, 5.0) == "RALENTISSEMENT"
    assert RM.palier_pression_ram(90.0, 3.0) == "GENE"
    assert RM.palier_pression_ram(95.0, 1.2) == "DETRESSE"
    assert RM.palier_pression_ram(99.0, 0.3) == "CRITIQUE"
    assert RM.palier_pression_ram(80.0, 1.0) == "DETRESSE"   # la memoire libre prime sur le pourcentage
    assert RM.palier_pression_ram(None, None) == "INCONNU"
    assert RM.palier_pression_ram(None, 4.0) == "INCONNU"


def test_hamilton_publie_le_palier_en_hormone(monkeypatch):
    vu = []
    monkeypatch.setattr(EN, "release", lambda h, level, **k: vu.append((h, level, k)) or {"ok": True})
    RM.publier_palier_pression("GENE")
    assert vu and vu[0][0] == HORMONE and vu[0][1] == 0.5, vu
    assert "GENE" in vu[0][2].get("reason", "")


def test_le_calme_reste_un_signal_et_n_eteint_pas_l_hormone(monkeypatch):
    """Mesure 24/10 22:12 apres redemarrage : RAM 72,7 %, palier CALME publie a 0.0 -- or `release(h, 0.0)` ETEINT
    l'hormone ; les 13 executeurs lisaient INCONNU. Calme != silence : CALME s'emet a un niveau > 0, lu CALME."""
    vu = []
    monkeypatch.setattr(EN, "release", lambda h, level, **k: vu.append(level) or {"ok": True})
    RM.publier_palier_pression("CALME")
    assert vu and vu[0] > 0.0, vu
    monkeypatch.setattr(EN, "read_full", lambda h: _lecture(vu[0]))
    assert T._palier_pression() == "CALME"


def test_l_executeur_est_recepteur_declare():
    assert "tools/forge_task_executor.py" in EN.receptors(HORMONE)


def _lecture(level, age_s=10, expired=False):
    return SimpleNamespace(fresh_level=level, level=level, age_s=age_s, expired=expired, reason="")


def test_l_executeur_lit_le_palier(monkeypatch):
    monkeypatch.setattr(EN, "read_full", lambda h: _lecture(0.5))
    assert T._palier_pression() == "GENE"
    monkeypatch.setattr(EN, "read_full", lambda h: _lecture(0.75))
    assert T._palier_pression() == "DETRESSE"
    monkeypatch.setattr(EN, "read_full", lambda h: None)
    assert T._palier_pression() == "INCONNU"
    monkeypatch.setattr(EN, "read_full", lambda h: _lecture(0.5, age_s=3600))
    assert T._palier_pression() == "INCONNU"   # signal perime : STALE n'est pas CALME
    monkeypatch.setattr(EN, "read_full", lambda h: (_ for _ in ()).throw(OSError("base verrouillee")))
    assert T._palier_pression() == "INCONNU"


def test_reclamation_et_rythme_selon_le_palier():
    for p in ("CALME", "RALENTISSEMENT", "INCONNU"):
        assert T._reclamation_permise(p) is True, p
    for p in ("GENE", "DETRESSE", "CRITIQUE"):
        assert T._reclamation_permise(p) is False, p
    assert T._intervalle_boucle(60, "CALME") == 60
    assert T._intervalle_boucle(60, "INCONNU") == 60
    assert T._intervalle_boucle(60, "RALENTISSEMENT") == 120


def test_geste_sur_la_delegation_en_vol():
    assert T._geste_delegation("DETRESSE", gelee=False) == "GELER"
    assert T._geste_delegation("DETRESSE", gelee=True) is None
    assert T._geste_delegation("CRITIQUE", gelee=True) is None       # Hamilton tranchera ; on ne degele pas
    assert T._geste_delegation("GENE", gelee=True) == "DEGELER"
    assert T._geste_delegation("INCONNU", gelee=True) == "DEGELER"   # jamais gele sur un signal illisible
    assert T._geste_delegation("CALME", gelee=False) is None


def test_hamilton_respecte_l_intention_jusqu_a_la_detresse_et_passe_outre_au_critique():
    plan = {"verdict": "SOI", "motif": "pression SOI", "delester": [
        {"service": "NokidoTaskExecutorOpencodeGlm", "classe": "UTILE", "rss_mb": 300.0}]}
    vetos = {"NokidoTaskExecutorOpencodeGlm": "tache t en vol"}
    r = RM.regulation_hamilton_ram(plan, 96.0, 16.0, {}, time.time(), vetos=vetos)
    assert r["choisis"] == [], r
    r = RM.regulation_hamilton_ram(plan, 99.0, 16.0, {}, time.time(), vetos=vetos, critique=True)
    assert r["choisis"] == ["NokidoTaskExecutorOpencodeGlm"], r
    assert "CRITIQUE" in r["motif"], r
