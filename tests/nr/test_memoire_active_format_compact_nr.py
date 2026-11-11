import sys
from unittest.mock import MagicMock
import pytest

from app.forge_memoire_active import _longue


def _module_factice(monkeypatch, find_rend):
    module = MagicMock()
    module.find = MagicMock(return_value=find_rend)
    module.find_fiches = MagicMock(return_value=[])
    module.requete_fts_legere = lambda q: " OR ".join(w for w in q.split() if len(w) > 3)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_keeper_base", module)
    return module


def test_un_mot_court_seul_n_annule_pas_le_rappel(monkeypatch):
    module = _module_factice(monkeypatch, [{"source": "docs/a.md", "preview": "x"}])
    entrees, _ = _longue("hub")
    assert entrees and module.find.call_args.args[0] == '"hub"'
    assert module.find_fiches.call_args.args[0] == "hub"


def test_un_canal_en_panne_ne_perd_pas_l_autre(monkeypatch):
    module = _module_factice(monkeypatch, [{"source": "docs/a.md", "preview": "x"}])
    module.find_fiches.return_value = [{"error": "OperationalError: panne"}]
    entrees, _ = _longue("relancer service")
    assert len(entrees) == 1


def test_deux_canaux_en_panne_disent_l_echec(monkeypatch):
    module = _module_factice(monkeypatch, [{"error": "OperationalError: panne"}])
    module.find_fiches.return_value = [{"error": "OperationalError: panne"}]
    entrees, note = _longue("relancer service")
    assert entrees == [] and "echec" in note and "pas panne" not in note


def test_rag_fts_ne_recoit_jamais_de_or_et_le_rappel_est_plafonne(monkeypatch):
    """Mesure 5/11 sur la vraie base : `rag_fts` en OR 1,5 s a plus de 15 s, fiches 34-192 ms ; hook a chaque message."""
    module = _module_factice(monkeypatch, [])
    _longue("comment relancer le service ?")
    assert module.find.call_args.args[0] == '"comment" "relancer" "le" "service"'
    assert module.find.call_args.kwargs["plafond_s"] is not None
    assert module.find_fiches.call_args.kwargs["plafond_s"] is not None
    assert " OR " in module.find_fiches.call_args.args[0]


def test_requete_legere_identique_a_celle_du_moteur():
    """La source est celle du moteur, jugee par banc_rappel_lexical : la copie du hook ne doit pas deriver."""
    pytest.importorskip("numpy")
    from nokido_agent.app.forge_keeper_base import requete_fts_legere
    from nokido_agent.app.forge_rag_engine import requete_fts

    for q in ("alors tu apprends des choses ?", "fais la modif du settings.json", "hub", "", "quel est pour dans with " * 4):
        assert requete_fts_legere(q) == requete_fts(q)


def test_memoire_active_format_compact_and_pointer(monkeypatch):
    mock_module = _module_factice(monkeypatch, [])
    mock_find = mock_module.find
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_keeper_base", mock_module)

    # 1. Cas: memory:abc_2026-01-01 rendu [[abc_2026-01-01]] ...
    # 2. Cas: fiche memory:* classee avant source tierce
    # 3. Cas: prefixe [episodic_memory:memory:...] retire
    # 4. Cas: entree sans preview toujours ignoree
    mock_find.return_value = [
        {"source": "autre_source", "preview": "Apercu autre"},
        {"source": "memory:abc_2026-01-01", "preview": "[episodic_memory:memory:abc_2026-01-01] Apercu memoire"},
        {"source": "memory:sans_preview", "preview": ""},
        {"source": "memory:autre_fiche", "preview": "Autre fiche sans prefixe"},
    ]

    entrees, err = _longue("test intention")
    assert err is None
    assert len(entrees) == 3

    # Fiches memory en premier, ordre stable
    assert entrees[0]["texte"] == "[[abc_2026-01-01]] Apercu memoire"
    assert entrees[1]["texte"] == "[[autre_fiche]] Autre fiche sans prefixe"
    assert entrees[2]["texte"] == "[autre_source] Apercu autre"


def test_memoire_active_aucun_resultat(monkeypatch):
    mock_find = MagicMock()
    mock_module = MagicMock()
    mock_module.find = mock_find
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_keeper_base", mock_module)

    # Cas: aucun resultat = toujours « aucun rappel sur ces termes (corpus, pas panne) »
    mock_find.return_value = []
    entrees, err = _longue("vide")
    assert entrees == []
    assert err == "aucun rappel sur ces termes (corpus, pas panne)"

    mock_find.return_value = [{"source": "memory:vide", "preview": ""}]
    entrees2, err2 = _longue("sans contenu")
    assert entrees2 == []
    assert err2 == "aucun rappel sur ces termes (corpus, pas panne)"
