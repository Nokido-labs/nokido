"""NR — l'organe de regulation a plusieurs rythmes, et espacer un bilan ne rend aveugle
aucun canal d'alarme.

Mesure 2026-09-06 (12 ticks consecutifs, `tools/forge_homeostasis_tick_profil.py`) :
`health` prenait 487 s des 700 s de la serie (70 %, 40,6 s par appel) et `pluripotent`
116 s (17 %) ; tous les reflexes reunis coutaient 1,6 s. Le RSS, lui, etait PLAT
(0,337 Go, aucune accumulation) — le probleme de cet organe n'a jamais ete la memoire,
c'etait de faire battre un bilan complet au rythme des reflexes.

Trois garanties :
  1. le bilan de sante tourne 1 tick sur RYTHME_HEALTH, pas a chaque tick ;
  2. un tick SANS bilan rejoue le dernier resultat en le marquant de son AGE — sinon
     `_algedonic_signals` perdrait « cellule vivante, organe mort » deux ticks sur trois ;
  3. tant qu'aucun bilan n'a eu lieu, l'absence est DITE (`ok: False`), jamais remplacee
     par un vert par defaut.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_homeostasis_orchestrator as H  # noqa: E402


def _tick_leger(monkeypatch, appels: list, resultat_health=None):
    """Neutralise tout sauf la logique de rythme : chaque phase devient un noop."""
    def _faux_safe_call(nom, fn, timeout_s=None):
        appels.append(nom)
        if nom == "health":
            return {"ok": True, "result": resultat_health or {"organes_morts": []}}
        return {"ok": True, "result": None}

    monkeypatch.setattr(H, "_safe_call", _faux_safe_call)
    monkeypatch.setattr(H, "_get_novelty", lambda: None)
    monkeypatch.setattr(H, "_ram_pct", lambda: 50.0)
    monkeypatch.setattr(H._flow_regulator, "get_dynamic_threshold", lambda: 0.05)


def test_le_bilan_de_sante_ne_tourne_pas_a_chaque_tick(monkeypatch):
    appels: list[str] = []
    _tick_leger(monkeypatch, appels)
    monkeypatch.setattr(H, "RYTHME_HEALTH", 3)
    state = {"tick_count": 0}
    faits = []
    for _ in range(6):
        appels.clear()
        H.tick(state)
        faits.append("health" in appels)
        state["tick_count"] += 1
    # ticks 0 et 3 -> bilan ; 1, 2, 4, 5 -> rejoue
    assert faits == [True, False, False, True, False, False], faits


def test_un_tick_sans_bilan_rejoue_le_dernier_avec_son_age(monkeypatch):
    appels: list[str] = []
    _tick_leger(monkeypatch, appels, resultat_health={"organes_morts": [{"organe": "x", "motif": "muet"}]})
    monkeypatch.setattr(H, "RYTHME_HEALTH", 3)
    state = {"tick_count": 0}
    H.tick(state)                      # bilan frais
    state["tick_count"] += 1
    out = H.tick(state)                # sans bilan
    ph = out["phases"]["health"]
    assert ph.get("rejoue") is True and ph.get("age_ticks") == 1, ph
    # le canal d'alarme voit toujours l'organe mort
    sigs = [s["kind"] for s in H._algedonic_signals(out)]
    assert "organe_mort" in sigs, sigs


def test_tant_qu_aucun_bilan_n_a_eu_lieu_l_absence_est_dite(monkeypatch):
    appels: list[str] = []
    _tick_leger(monkeypatch, appels)
    monkeypatch.setattr(H, "RYTHME_HEALTH", 3)
    state = {"tick_count": 1}  # demarrage hors multiple : aucun bilan encore
    out = H.tick(state)
    ph = out["phases"]["health"]
    assert ph["ok"] is False and "pas encore" in ph["err"], ph
    assert ph["age_ticks"] is None


def test_le_travail_cognitif_a_son_propre_rythme(monkeypatch):
    appels: list[str] = []
    _tick_leger(monkeypatch, appels)
    monkeypatch.setattr(H, "RYTHME_PLURIPOTENT", 2)
    state = {"tick_count": 0}
    vus = []
    for _ in range(4):
        appels.clear()
        out = H.tick(state)
        vus.append("saute" not in str(out["phases"].get("pluripotent")))
        state["tick_count"] += 1
    assert vus == [True, False, True, False], vus
