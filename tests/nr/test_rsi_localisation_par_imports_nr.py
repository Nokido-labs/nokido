# -*- coding: utf-8 -*-
"""NR (owner 3/11 23 h, choix « par les imports du test ») : les 5 propositions du RSI restaient « NON consommee (REL
pointer_ref null : aucune frame app/tools) » -- leur test rouge echoue DANS le test, aucune trace ne designe le module.
Localisation : le module forge_* IMPORTE par le test, s'il est UNIQUE et existe dans app/ ou tools/. Plusieurs
candidats, aucun, test illisible : pas de localisation (la proposition reste en attente, le journal le dit)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_self_patcher as sp  # noqa: E402


def _arbre(tmp_path, source_test, modules=("forge_x",)):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "tools").mkdir(exist_ok=True)
    for m in modules:
        (tmp_path / "app" / ("%s.py" % m)).write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "nr").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "nr" / "test_a_nr.py").write_text(source_test, encoding="utf-8")
    return "tests/nr/test_a_nr.py::test_y"


def test_un_seul_module_importe_est_la_cible(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "ROOT", tmp_path)
    nid = _arbre(tmp_path, "import sys\nimport forge_x as X  # noqa\n\ndef test_y():\n    assert X.f() == 2\n")
    assert sp._localiser_par_imports(nid) == {"file": "app/forge_x.py", "par": "imports du test"}


def test_import_par_l_espace_de_noms(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "ROOT", tmp_path)
    nid = _arbre(tmp_path, "from nokido_agent.app.forge_x import f\n\ndef test_y():\n    assert f() == 2\n")
    assert sp._localiser_par_imports(nid)["file"] == "app/forge_x.py"


def test_plusieurs_modules_pas_de_localisation(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "ROOT", tmp_path)
    nid = _arbre(tmp_path, "import forge_x\nimport forge_z\n\ndef test_y():\n    pass\n", modules=("forge_x", "forge_z"))
    assert sp._localiser_par_imports(nid) is None


def test_test_absent_ou_module_inexistant(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "ROOT", tmp_path)
    assert sp._localiser_par_imports("tests/nr/absent_nr.py::t") is None
    nid = _arbre(tmp_path, "import forge_fantome\n\ndef test_y():\n    pass\n", modules=())
    assert sp._localiser_par_imports(nid) is None


def test_le_cycle_genere_pour_un_rel_localise_par_imports(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "ROOT", tmp_path)
    nid = _arbre(tmp_path, "import forge_x\n\ndef test_y():\n    assert forge_x.f() == 2\n")
    props, faits = tmp_path / "props", tmp_path / "faits"
    props.mkdir()
    (props / "evolution_proposal_rel_1.md").write_text(
        "- **corrige f**\n```json\n{\"error_id\": \"e1\", \"pointer_ref\": null, \"evidence\": {}}\n```\n",
        encoding="utf-8")
    monkeypatch.setattr(sp, "PROPOSALS_DIR", props)
    monkeypatch.setattr(sp, "APPLIED_DIR", faits)
    monkeypatch.setattr(sp, "FILE_REPOS", tmp_path / "file_repos.jsonl")
    monkeypatch.setattr(sp, "_rag_lookup", lambda pattern: "")
    monkeypatch.setattr(sp, "_test_du_rel", lambda rel: nid)
    monkeypatch.setattr(sp, "_rel_deja_vert", lambda nodeid: False)
    monkeypatch.setattr(sp, "_pertinence", lambda: {"statut": "MESURE", "taux": 1.0, "n": 9})
    contextes = []
    monkeypatch.setattr(sp, "_llm_generate_patch", lambda pats, rag, ctx: contextes.append(ctx) or None)
    sp.run_once(dry_run=True)
    assert contextes and "app/forge_x.py" in contextes[0]
