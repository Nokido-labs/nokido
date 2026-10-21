# -*- coding: utf-8 -*-
"""NR (audit pair 19/10, analyse C, signale par OPENCODE_GLM 930da2add puis verifie sur piece) : la version VERBOSE du
preflight dit ses pannes comme son jumeau.

Mesure : `preflight_check` note depuis le 19/10 la panne de chaque niveau (`pannes=`) et dit ILLISIBLE quand FTS5 et
LIKE, les deux niveaux SQLite « toujours disponibles », sont en panne sans resultat. `preflight_check_verbose` -- le
chemin du CORPS (10 appelants : forge_dsl, forge_epistemic_veille, forge_grounder, forge_rescue, nokido_hub...) -- ne
transmettait pas `pannes` : « tous les niveaux en panne » et « rien trouve » sortaient tous deux `tier: none`.
Contrat :
  1. le dict porte toujours `pannes` (liste, vide si aucune) ;
  2. FTS5 ET LIKE en panne sans resultat -> `tier == "illisible"` (jamais « none » : aucune verification n'a eu lieu) ;
  3. vraie absence (aucune panne) -> `tier == "none"`, inchange.
"""
from nokido_agent.app import forge_self_correction as S


def _niveaux(monkeypatch, *, en_panne):
    def niveau(nom):
        def f(query, limit=5, pannes=None):
            if nom in en_panne and pannes is not None:
                pannes.append("%s:OperationalError" % nom)
            return []
        return f
    monkeypatch.setattr(S, "_ragengine_search", niveau("ragengine"))
    monkeypatch.setattr(S, "_fts5_search", niveau("fts5"))
    monkeypatch.setattr(S, "_like_fallback", niveau("like"))


def test_tous_les_niveaux_sqlite_en_panne_se_dit_illisible(monkeypatch):
    _niveaux(monkeypatch, en_panne={"ragengine", "fts5", "like"})
    v = S.preflight_check_verbose("governed_edit", "arbre partage")
    assert v["results"] == []
    assert v["tier"] == "illisible", v
    assert any(p.startswith("fts5") for p in v["pannes"]) and any(p.startswith("like") for p in v["pannes"])


def test_la_veille_ne_lit_pas_une_panne_comme_une_lacune(monkeypatch):
    """Aval reel : coverage_score (forge_epistemic_veille) comptait 0 resultat = LACUNE -> feel_gap emettait
    knowledge_gap + cortisol sur une panne SQLite. Panne = INCONNU (gap None), jamais gap True."""
    from nokido_agent.app import forge_epistemic_veille as V

    _niveaux(monkeypatch, en_panne={"ragengine", "fts5", "like"})
    cov = V.coverage_score("governed_edit", "arbre partage")
    assert cov["gap"] is None and cov.get("verdict") == "rag_indisponible", cov


def test_une_vraie_absence_reste_none(monkeypatch):
    _niveaux(monkeypatch, en_panne=set())
    v = S.preflight_check_verbose("governed_edit", "arbre partage")
    assert v["tier"] == "none" and v["pannes"] == []
