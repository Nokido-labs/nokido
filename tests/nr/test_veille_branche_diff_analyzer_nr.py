"""NR 18/10 -- C_06c (decision owner) : brancher forge_diff_analyzer sur la veille RSS.

Constat du 18/10 : `forge_diff_analyzer.analyze_all_watch_alerts` (compare les releases de watch_alerts aux imports
reels du code) n'etait appele par AUCUN organe ; `run_watch` collectait des alertes breaking/securite et s'arretait la.
Contrat :
  * un cycle qui a produit au moins une alerte appelle l'analyse et met ses impacts dans le bilan (`impacts`) ;
  * un cycle sans alerte ne l'appelle pas et le DIT (`impacts` = « non calcule ... ») ;
  * une base illisible rend « ILLISIBLE ... », jamais [] -- « rien » n'est pas « illisible ».
Le module est importe sous son nom canonique `nokido_agent.app.forge_diff_analyzer` (un seul nom = une seule instance).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_rss_watcher as rw  # noqa: E402

CANON = "nokido_agent.app.forge_diff_analyzer"


def _analyseur(monkeypatch, comportement):
    faux = types.ModuleType(CANON)
    appels = []

    def analyze_all_watch_alerts():
        appels.append(1)
        return comportement()
    faux.analyze_all_watch_alerts = analyze_all_watch_alerts
    monkeypatch.setitem(sys.modules, CANON, faux)
    return appels


def _cycle(monkeypatch, role):
    monkeypatch.setattr(rw, "GITHUB_REPOS", ["org/projet"])
    for nom in ("PYPI_PACKAGES", "ARXIV_QUERIES", "WATCH_QUERIES_RYZENAI", "WATCH_URLS"):
        monkeypatch.setattr(rw, nom, [])
    monkeypatch.setattr(rw, "_load_state", lambda: {})
    monkeypatch.setattr(rw, "_save_state", lambda s: None)
    monkeypatch.setattr(rw, "_already_seen", lambda s, u: False)
    monkeypatch.setattr(rw, "_marquer_si_succes", lambda *a, **k: None)
    monkeypatch.setattr(rw, "_ingest", lambda **k: ("OK", 1))
    monkeypatch.setattr(rw, "_infer_release_role", lambda body: role)
    monkeypatch.setattr(rw, "fetch_github_release", lambda repo: {
        "version": "9.9.9", "body": "notes", "title": "v9.9.9", "url": "https://x/r", "age_days": 1})
    monkeypatch.setattr(rw.time, "sleep", lambda s: None)
    return rw.run_watch(since_days=7)


def test_un_cycle_avec_alerte_appelle_l_analyse_et_rend_les_impacts(monkeypatch):
    appels = _analyseur(monkeypatch, lambda: [{"paquet": "projet", "statut": "A_EXAMINER"}])
    s = _cycle(monkeypatch, "release:breaking")
    assert appels == [1], "le cycle a produit une alerte breaking mais n'a pas appele forge_diff_analyzer"
    assert s.get("impacts") == [{"paquet": "projet", "statut": "A_EXAMINER"}]


def test_un_cycle_sans_alerte_ne_l_appelle_pas_et_le_dit(monkeypatch):
    appels = _analyseur(monkeypatch, lambda: [])
    s = _cycle(monkeypatch, "release:feature")
    assert appels == []
    assert str(s.get("impacts", "")).startswith("non calcule"), s.get("impacts")


def test_une_base_illisible_n_est_jamais_une_liste_vide(monkeypatch):
    def leve():
        raise sqlite3_erreur()
    import sqlite3

    def sqlite3_erreur():
        return sqlite3.OperationalError("database is locked")
    _analyseur(monkeypatch, leve)
    s = _cycle(monkeypatch, "release:security")
    assert str(s.get("impacts", "")).startswith("ILLISIBLE"), s.get("impacts")
