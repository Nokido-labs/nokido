# -*- coding: utf-8 -*-
"""La sante du worker de veille n'est pas la capacite de la veille.

Mesure 2026-08-30 : `forge_watch_agent_worker` ecrivait `health: ok` des lors que
`execute_pending` n'avait pas leve -- moteur de recherche a terre ou non. Et
`_check_deps` n'etait appele QU'UNE FOIS, au demarrage de la boucle : une
dependance tombee apres le boot n'etait jamais revue, si bien que le daemon
pouvait tourner des jours en se declarant sain.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _neuf(monkeypatch, deps: dict):
    """Module remis a zero + `_check_deps` remplace ; rend le compteur d'appels."""
    import forge_watch_agent_worker as w

    appels = {"n": 0}

    def _faux():
        appels["n"] += 1
        return dict(deps)

    monkeypatch.setattr(w, "_check_deps", _faux)
    monkeypatch.setattr(w, "_cap_dernier_ts", 0.0, raising=False)
    monkeypatch.setattr(w, "_cap_etat", {"capacite": "inconnue", "deps": {}}, raising=False)
    return w, appels


def test_toutes_deps_joignables_donne_une_capacite_complete(monkeypatch):
    w, _ = _neuf(monkeypatch, {"searxng": "ok", "ollama": "ok"})
    assert w._capacite_veille(force=True)["capacite"] == "complete"


def test_une_dep_a_terre_reduit_la_capacite_sans_la_declarer_nulle(monkeypatch):
    """`reduite`, pas `aveugle` : l'academique ne depend pas de SearXNG."""
    w, _ = _neuf(monkeypatch, {"searxng": "DOWN (URLError)", "ollama": "ok"})
    etat = w._capacite_veille(force=True)
    assert etat["capacite"] == "reduite"
    assert etat["deps"]["searxng"].startswith("DOWN")


def test_la_capacite_est_remesuree_et_non_figee_au_demarrage(monkeypatch):
    """Le defaut d'origine : une dep tombee APRES le boot n'etait jamais revue."""
    w, appels = _neuf(monkeypatch, {"searxng": "ok", "ollama": "ok"})
    w._capacite_veille(force=True)
    assert appels["n"] == 1
    # L'intervalle est ecoule -> nouvelle mesure, sans avoir a forcer.
    monkeypatch.setattr(w, "_cap_dernier_ts", 0.0, raising=False)
    w._capacite_veille()
    assert appels["n"] == 2, "la capacite doit se re-mesurer, pas rester figee au boot"


def test_l_intervalle_borne_le_cout_reseau(monkeypatch):
    """Re-mesurer a CHAQUE tick sonderait deux services toutes les 30 s pour rien."""
    w, appels = _neuf(monkeypatch, {"searxng": "ok", "ollama": "ok"})
    w._capacite_veille(force=True)
    for _ in range(5):
        w._capacite_veille()
    assert appels["n"] == 1
    assert w._capacite_veille()["capacite_mesuree_il_y_a_s"] is not None


def test_capacite_inconnue_tant_que_rien_n_a_ete_mesure(monkeypatch):
    """Une capacite jamais mesuree n'est pas une capacite intacte."""
    w, _ = _neuf(monkeypatch, {"searxng": "ok", "ollama": "ok"})
    assert w._cap_etat["capacite"] == "inconnue"
