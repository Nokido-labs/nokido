"""NR 18/10 -- cause de l'arret RSI du 15/10 (frein evolution.halt, porte HALTED depuis 15:26:40).

`appliquer_et_mesurer` n'arretait que sur une mesure d'AVANT *illisible* (err). Le 15/10 la mesure a rendu une
reference VIDE (`{}`) sans erreur : l'acte `embed.batch_size -> 30` a ete applique sans rien a quoi comparer
l'apres, `mesurer_apres` a rendu INDECIDABLE (« reference vide ») et a pose le frein que seul l'owner retire.
Une reference sans dimension jugeable vaut une reference illisible : on n'agit pas, on s'ABSTIENT (sans frein,
sans inscription d'acte) -- s'abstenir n'est pas echouer.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_mutation_controller as m  # noqa: E402


def _armer(monkeypatch):
    monkeypatch.setattr(m, "_porte", lambda: {"autorisee": True, "etat": "ARMEE"})
    monkeypatch.setattr(m, "garde_plafonds", lambda *a, **k: None)
    inscrits, freins, vetos = [], [], []
    monkeypatch.setattr(m, "_inscrire", lambda rec: inscrits.append(rec) or "app_test")
    monkeypatch.setattr(m, "_poser_frein", lambda motif: freins.append(motif))
    monkeypatch.setattr(m, "_poser_veto_acte", lambda cible, app_id: vetos.append(cible))
    monkeypatch.setattr(m, "_lever_veto_acte", lambda svc: None)
    return inscrits, freins, vetos


def test_une_reference_vide_n_applique_rien_et_ne_freine_pas(monkeypatch):
    inscrits, freins, vetos = _armer(monkeypatch)
    actes = []
    r = m.appliquer_et_mesurer(
        "L1", "param:embed.batch_size", "exp_nr",
        appliquer=lambda: actes.append(1) or {"ok": True},
        reverter=lambda: {"ok": True},
        mesurer=lambda: {},
        empreinte=lambda: "empreinte",
        bruit={},
    )
    assert actes == [], "un acte a ete applique sur une reference VIDE (cause de l'arret du 15/10)"
    assert r["applique"] is False and r["verdict"] == "INDECIDABLE", r
    assert "reference" in r.get("pourquoi", ""), "l'abstention doit DIRE que la reference est vide"
    assert freins == [], "s'abstenir avant l'acte ne pose pas le frein evolution.halt"
    assert inscrits == [] and vetos == [], "aucune experience d'application ne s'inscrit sans acte"
