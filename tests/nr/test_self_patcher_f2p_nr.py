"""NR : contrat Fail-to-Pass du self-patcher sur une proposition REL.

26/10 (roadmap_p1_self_patcher_f2p_et_raffinement_20261026) : `_submit_to_judge` ne passait au thymus
que `tests/test_<module>.py`, jamais le test ROUGE du REL -- un correctif pouvait « survivre » sans
rien reparer. Desormais : (1) le test du REL est rejoue AVANT la generation (deja vert -> rien a
reparer, consomme sans appel modele ; illisible -> en attente, UNKNOWN != NO) ; (2) il est ajoute aux
tests du juge : un correctif qui ne le fait pas passer MEURT.
"""
import json
import sys
import types
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools"), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_self_patcher as sp  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _file_repos_isolee(monkeypatch, tmp_path):
    """3/11 23 h : depuis le RSI « ecrit au repos » (17bf6b2d0), une soumission hors repos va dans sp.FILE_REPOS. Ce
    module ne l'isolait pas : la VRAIE file du RSI a recu « tools/forge_x.py : def f(): return 2 » (proposition de
    test), qu'une consolidation nocturne aurait tente d'appliquer. Chaque test ecrit desormais dans tmp_path."""
    monkeypatch.setattr(sp, "FILE_REPOS", tmp_path / "file_repos_test.jsonl")


def test_error_id_junit_devient_un_nodeid(monkeypatch, tmp_path):
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_x_nr.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(sp, "ROOT", tmp_path)
    assert sp._test_du_rel({"error_id": "tests.nr.test_x_nr::test_y"}) == "tests/nr/test_x_nr.py::test_y"
    assert sp._test_du_rel({"error_id": "tests.nr.test_x_nr.TestA::test_y[1]"}) == \
        "tests/nr/test_x_nr.py::TestA::test_y[1]"
    assert sp._test_du_rel({"error_id": "tests.nr.absent::test_y"}) is None
    assert sp._test_du_rel({"error_id": "sans_separateur"}) is None


def test_le_test_du_rel_est_passe_au_juge_avec_le_perimetre(monkeypatch):
    """Des tests EXPLICITES font sauter `perimetre_mesure` cote juge : le seul test F2P perdrait la
    non-regression (P2P) des autres tests du module. Le patcher joint donc le perimetre lui-meme."""
    vus = {}

    def faux_juge(ref, rel, new_text, tests):
        vus["tests"] = tests
        return {"verdict": "MEURT", "status": "REJECTED"}

    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_autonomous_loops",
                        types.SimpleNamespace(submit_candidate_to_judge=faux_juge))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_mutation_judge",
                        types.SimpleNamespace(perimetre_mesure=lambda rel: ["tests/nr/test_forge_inexistant_xyz_nr.py",
                                                                            "tests/nr/test_x_nr.py::test_y"]))
    sp._submit_to_judge("proposal:p", "tools/forge_inexistant_xyz.py", "x = 1\n", "d",
                        test_f2p="tests/nr/test_x_nr.py::test_y")
    assert vus["tests"] == ["tests/nr/test_x_nr.py::test_y", "tests/nr/test_forge_inexistant_xyz_nr.py"]


def _deux_passes(monkeypatch, tmp_path, verdicts):
    faits, _ = _proposition(tmp_path, monkeypatch)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forge_x.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(sp, "ROOT", tmp_path)
    monkeypatch.setattr(sp, "_rel_deja_vert", lambda nodeid: False)
    monkeypatch.setattr(sp, "_safe_check", lambda target: None)
    monkeypatch.setattr(sp, "_pertinence", lambda: {"statut": "MESURE", "taux": 1.0, "n": 9})
    # 3/11 (owner, RSI au repos) : le juge n'est appele qu'au sommeil ou en transe ; ce test porte sur les DEUX PASSES
    # du juge, pas sur la phase -> on simule une mutation autorisee (la phase a son NR : test_rsi_ecrit_au_repos_nr).
    monkeypatch.setattr(sp, "_mutation_autorisee", lambda: (True, "test : mutation autorisee"))
    contextes = []

    def generer(patterns, rag_ctx, rel_ctx=""):
        contextes.append(rel_ctx)
        return {"target_file": "tools/forge_x.py", "patch_search": "return 1", "patch_replace": "return 2",
                "description": "corrige f"}

    file_verdicts = list(verdicts)
    monkeypatch.setattr(sp, "_llm_generate_patch", generer)
    monkeypatch.setattr(sp, "_submit_to_judge", lambda *a, **k: file_verdicts.pop(0))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_self_correction",
                        types.SimpleNamespace(anchor_solution=lambda **k: None))
    return sp.run_once(dry_run=False), contextes


def test_un_rejet_du_juge_nourrit_une_seconde_passe(monkeypatch, tmp_path):
    stats, contextes = _deux_passes(monkeypatch, tmp_path, [
        {"verdict": "MEURT", "pourquoi": "tests/nr/test_x_nr.py::test_y : assert 2 == 3"},
        {"verdict": "AMELIORE", "status": "AWAITING_OWNER_COMMIT"}])
    assert len(contextes) == 2
    assert "REJETEE" in contextes[1] and "assert 2 == 3" in contextes[1]
    assert "REJETEE" not in contextes[0]
    assert stats["patches_applied"] == 1


def test_jamais_plus_de_deux_passes(monkeypatch, tmp_path):
    stats, contextes = _deux_passes(monkeypatch, tmp_path, [
        {"verdict": "MEURT", "pourquoi": "a"}, {"verdict": "MEURT", "pourquoi": "b"},
        {"verdict": "AMELIORE"}])
    assert len(contextes) == sp.PASSES_MAX == 2
    assert stats["patches_applied"] == 0


def test_un_verdict_hors_rejet_ne_relance_pas(monkeypatch, tmp_path):
    """HALTED (porte de l'evolution fermee), REJETE_HELD_OUT (sur-ajustement) : une 2e passe n'y changerait rien."""
    stats, contextes = _deux_passes(monkeypatch, tmp_path, [{"verdict": "HALTED"}, {"verdict": "AMELIORE"}])
    assert len(contextes) == 1


def test_un_candidat_ameliore_compte_comme_applique(monkeypatch, tmp_path):
    """Le juge a gain ne rend JAMAIS « SURVIT » en verdict final (AMELIORE, SURVIT_SANS_GAIN, MEURT...) :
    la branche succes du patcher etait morte -- un candidat AMELIORE laisse dans l'arbre n'etait ni compte
    ni ancre."""
    faits, appels = _proposition(tmp_path, monkeypatch)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forge_x.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(sp, "ROOT", tmp_path)
    monkeypatch.setattr(sp, "_rel_deja_vert", lambda nodeid: False)
    monkeypatch.setattr(sp, "_safe_check", lambda target: None)
    monkeypatch.setattr(sp, "_pertinence", lambda: {"statut": "MESURE", "taux": 1.0, "n": 9})  # pas d'OBSERVATION
    monkeypatch.setattr(sp, "_llm_generate_patch", lambda *a, **k: {
        "target_file": "tools/forge_x.py", "patch_search": "return 1", "patch_replace": "return 2",
        "description": "corrige f"})
    monkeypatch.setattr(sp, "_submit_to_judge", lambda *a, **k: {"verdict": "AMELIORE",
                                                                 "status": "AWAITING_OWNER_COMMIT"})
    monkeypatch.setattr(sp, "_mutation_autorisee", lambda: (True, "test : mutation autorisee"))  # 3/11 RSI au repos
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_self_correction",
                        types.SimpleNamespace(anchor_solution=lambda **k: None))
    stats = sp.run_once(dry_run=False)
    assert stats["patches_applied"] == 1


def _proposition(tmp_path, monkeypatch):
    props = tmp_path / "props"
    faits = props / "patch_applied"
    props.mkdir()
    rel = {"error_id": "tests.nr.test_x_nr::test_y", "pointer_ref": {"file": "tools/forge_x.py", "function": "f"}}
    (props / "evolution_proposal_rel_1.md").write_text(
        "- **rel** : test rouge\n\n```json\n%s\n```\n" % json.dumps(rel), encoding="utf-8")
    monkeypatch.setattr(sp, "PROPOSALS_DIR", props)
    monkeypatch.setattr(sp, "APPLIED_DIR", faits)
    monkeypatch.setattr(sp, "_rag_lookup", lambda pattern: "")
    monkeypatch.setattr(sp, "_test_du_rel", lambda rel: "tests/nr/test_x_nr.py::test_y")
    appels = []
    monkeypatch.setattr(sp, "_llm_generate_patch", lambda *a, **k: appels.append(a) or None)
    return faits, appels


def test_un_test_du_rel_deja_vert_consomme_sans_appel_modele(monkeypatch, tmp_path):
    faits, appels = _proposition(tmp_path, monkeypatch)
    monkeypatch.setattr(sp, "_rel_deja_vert", lambda nodeid: True)
    sp.run_once(dry_run=False)
    assert appels == []
    assert [f.name for f in faits.glob("*.md")] == ["evolution_proposal_rel_1.md"]


def test_un_test_du_rel_illisible_laisse_la_proposition_en_attente(monkeypatch, tmp_path):
    faits, appels = _proposition(tmp_path, monkeypatch)
    monkeypatch.setattr(sp, "_rel_deja_vert", lambda nodeid: None)
    sp.run_once(dry_run=False)
    assert appels == []
    assert list(faits.glob("*.md")) == []


def test_un_test_du_rel_rouge_ouvre_la_generation(monkeypatch, tmp_path):
    faits, appels = _proposition(tmp_path, monkeypatch)
    monkeypatch.setattr(sp, "_rel_deja_vert", lambda nodeid: False)
    sp.run_once(dry_run=False)
    assert len(appels) == 1


# 26/10 : 5 REL du soir JAMAIS consommes -- pointer_ref null ecarte AVANT le controle « deja vert »,
# donc relus a chaque cycle sans fin. Un REL sans localisation dont le test est vert est consomme ;
# rouge ou illisible, il reste en attente (rien a viser : le modele ne ferait que deviner).

def _sans_localisation(tmp_path, monkeypatch):
    faits, appels = _proposition(tmp_path, monkeypatch)
    rel = {"error_id": "tests.nr.test_x_nr::test_y", "pointer_ref": None}
    (tmp_path / "props" / "evolution_proposal_rel_1.md").write_text(
        "- **rel** : test rouge\n\n```json\n%s\n```\n" % json.dumps(rel), encoding="utf-8")
    return faits, appels


def test_rel_sans_localisation_et_test_vert_est_consomme(monkeypatch, tmp_path):
    faits, appels = _sans_localisation(tmp_path, monkeypatch)
    monkeypatch.setattr(sp, "_rel_deja_vert", lambda nodeid: True)
    sp.run_once(dry_run=False)
    assert appels == []
    assert [f.name for f in faits.glob("*.md")] == ["evolution_proposal_rel_1.md"]


def test_rel_sans_localisation_et_test_rouge_reste_en_attente(monkeypatch, tmp_path):
    faits, appels = _sans_localisation(tmp_path, monkeypatch)
    monkeypatch.setattr(sp, "_rel_deja_vert", lambda nodeid: False)
    sp.run_once(dry_run=False)
    assert appels == [] and list(faits.glob("*.md")) == []
