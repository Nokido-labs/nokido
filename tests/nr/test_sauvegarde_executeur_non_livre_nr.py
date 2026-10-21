"""NR -- une session en echec dont TOUS les chemins sales sont « d'avant » est quand meme sauvegardee (copie).

Enquete AGY job_198d901b (docs/audit/sauvegarde_executeur_rates_20261019.md) : job_a34c8407 (GLM, 22:06:53) --
les 2 fichiers ecrits avant une relance du superviseur sont entres dans `_sales_avant` a la reprise ; le committer,
qui les exclut, rendait None et `_preserver_livraison` sortait (« if not note: return None ») SANS copie. Une copie
dans sandbox/ ne pollue aucun historique : rien ne justifie de la refuser.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def test_non_livre_sauvegarde_meme_si_chemins_dans_sales_avant(tmp_path, monkeypatch):
    wt = tmp_path / "wt"
    (wt / "app").mkdir(parents=True)
    (wt / "app" / "travail.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(T, "_SAUVEGARDES", tmp_path / "sauvegardes")
    monkeypatch.setattr(T, "_chemins_status", lambda _wt: frozenset({"app/travail.py"}))
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *_a, **_k: None)   # tout est exclu : rien a committer
    note = T._preserver_livraison(False, str(wt), "job_a34c8407_nr", "detail", "OPENCODE_GLM",
                                  exclus=frozenset({"app/travail.py"}))
    copie = tmp_path / "sauvegardes" / "OPENCODE_GLM" / "job_a34c8407_nr" / "app" / "travail.py"
    assert copie.exists(), note
    assert note and "COPIE" in note


def test_session_en_echec_sans_rien_de_sale_ne_sauvegarde_rien(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "_SAUVEGARDES", tmp_path / "sauvegardes")
    monkeypatch.setattr(T, "_chemins_status", lambda _wt: frozenset())
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *_a, **_k: None)
    assert T._preserver_livraison(False, str(tmp_path), "t", "d", "OPENCODE_GLM") is None
    assert not (tmp_path / "sauvegardes").exists()
