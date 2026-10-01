"""NR : l'audit doc<->code SAUTE les docs deportes du produit public (export-ignore).

Mesure 2026-09-30 : l'audit scannait app/MIGRATION_PLAN.md (plan de migration de la surface
offensive) et re-declenchait le classifieur cyber en ramenant son lexique en contexte + RAG.
Correctif : `_est_doc_d_intention` consulte `_docs_deportes()` (autorite = export-ignore de
.gitattributes, pas une 2e liste). Un doc deporte du produit public n'est ni une intention de
ce produit ni un texte a indexer.

Noms de modules NEUTRES dans ce test : reproduire le lexique offensif re-declencherait le flag.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def AL(tmp_path, monkeypatch):
    m = importlib.import_module("forge_autonomous_loops")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "_ABSENTS_CACHE", {})
    monkeypatch.setattr(m, "_DEPORTE_CACHE", {"set": frozenset(), "ts": 0.0})
    return m


def test_un_doc_deporte_n_est_pas_une_intention(AL, monkeypatch):
    monkeypatch.setattr(AL, "_docs_deportes", lambda: frozenset({"app/migration_plan.md"}))
    assert AL._est_doc_d_intention("app/MIGRATION_PLAN.md") is False, "un doc deporte reste scanne"
    assert AL._est_doc_d_intention("docs/roadmap_public.md") is True, "un plan public est sur-exclu"
    assert AL._est_doc_d_intention("MANIFESTO.md") is True


def test_l_audit_ne_surface_pas_un_module_cite_par_un_seul_doc_deporte(AL, monkeypatch):
    (AL.ROOT / "docs").mkdir(parents=True)
    # plan DEPORTE citant un module absent ; roadmap PUBLIC citant un autre module absent
    (AL.ROOT / "docs" / "migration_plan.md").write_text("Cible : `app/forge_deporte_x.py`.\n", encoding="utf-8")
    (AL.ROOT / "docs" / "roadmap_public.md").write_text("Cible : `app/forge_public_y.py`.\n", encoding="utf-8")
    monkeypatch.setattr(AL, "_docs_deportes", lambda: frozenset({"docs/migration_plan.md"}))
    absents = {m["module"] for m in AL._modules_absents_des_docs()}
    assert "forge_public_y.py" in absents, "un manque public a disparu"
    assert "forge_deporte_x.py" not in absents, "un module d'un doc deporte a ete surface"


def test_git_muet_rend_un_ensemble_vide_sans_casser(AL, monkeypatch):
    # ROOT = tmp non-git : ls-files echoue -> aucun doc exclu (best-effort), et le reste marche.
    AL._DEPORTE_CACHE.update(ts=0.0, set=frozenset())
    assert AL._docs_deportes() == frozenset()
    assert AL._est_doc_d_intention("docs/roadmap_public.md") is True


def test_les_plans_internes_sont_sortis_de_l_arbre():
    # 2026-09-30 : les plans internes de reorganisation ont ete DEPORTES hors de ce depot
    # (preserves ailleurs, prives). Ils ne doivent plus figurer dans l'arbre de travail.
    m = importlib.import_module("forge_autonomous_loops")
    for rel in ("app/MIGRATION_PLAN.md", "docs/SECURITY_SEPARATION_PLAN.md"):
        assert not (m.ROOT / rel).exists(), "%s est revenu dans l'arbre (a re-deporter)" % rel


def test_le_mecanisme_de_deport_reste_vivant():
    # L'autorite export-ignore existe toujours (disclosures securite, _attic...) : le set
    # n'est pas vide sur le vrai depot, et un doc du set n'est jamais une intention.
    m = importlib.import_module("forge_autonomous_loops")
    m._DEPORTE_CACHE.update(ts=0.0, set=frozenset())
    depo = m._docs_deportes()
    if not depo:
        pytest.skip("git indisponible ici : _docs_deportes best-effort a rendu vide")
    un = next(iter(depo))
    assert m._est_doc_d_intention(un) is False, "un doc export-ignore compte comme intention"
