# -*- coding: utf-8 -*-
"""NR (p2_turbo_worker_mort_sans_trace, decision owner 19/10 : traceur a la prochaine CI) : nommer le test qui charge
un module.

Mesure 19/10 : 80 plantages arrow.dll viennent des workers pytest de la CI ; pyarrow n'est PAS charge a la collecte
(18 680 tests) mais pendant l'execution d'un test. `forge_trace_import.armer([...])` pose un MetaPathFinder qui ne
bloque JAMAIS l'import et journalise, au PREMIER chargement d'un module surveille (ou d'un de ses sous-modules), le
test en cours, le worker xdist et la pile. Desarme par defaut : le conftest ne l'arme que si NOKIDO_TRACE_IMPORT est pose.
"""
import importlib
import json
import sys

from nokido_agent.tools import forge_trace_import as T


def test_premier_chargement_journalise_le_test_courant(tmp_path, monkeypatch):
    pkg = tmp_path / "faux_mod_trace_19"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sortie = tmp_path / "trace.jsonl"
    finder = T.armer(["faux_mod_trace_19"], sortie=sortie)
    try:
        monkeypatch.setitem(T.COURANT, "test", "tests/nr/test_x.py::test_y")
        importlib.import_module("faux_mod_trace_19")
        sys.modules.pop("faux_mod_trace_19", None)
        importlib.import_module("faux_mod_trace_19")  # second chargement : pas de seconde ligne
        lignes = [json.loads(l) for l in sortie.read_text(encoding="utf-8").splitlines()]
        assert len(lignes) == 1
        assert lignes[0]["module"] == "faux_mod_trace_19" and lignes[0]["test"] == "tests/nr/test_x.py::test_y"
        assert "worker" in lignes[0] and isinstance(lignes[0]["pile"], list)
        # 19/10 : pas de purge (rien ne se supprime, fichier en ajout seul) -- chaque ligne porte sa SESSION de
        # tracage, et la lecture ne garde que la derniere : pas de faux positif d'un run precedent.
        assert lignes[0]["session"] == finder.session
        (sortie).write_text(sortie.read_text(encoding="utf-8")
                            + json.dumps({"module": "x", "session": "ancienne"}) + "\n", encoding="utf-8")
        assert [l["module"] for l in T.lire_derniere_session(sortie, finder.session)] == ["faux_mod_trace_19"]
    finally:
        T.desarmer(finder)
        sys.modules.pop("faux_mod_trace_19", None)


def test_le_drapeau_ci_local_pose_la_variable_apres_parse_args():
    """Reflexe du corps : un drapeau CLI a un test qui le traverse. Lancer ci_local entier coute une CI : on verifie
    sur l'AST que --trace-import est declare et qu'il pose NOKIDO_TRACE_IMPORT apres parse_args, avant les gates."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert '"--trace-import"' in src
    i_parse = src.index("a = ap.parse_args()")
    i_env = src.index('os.environ["NOKIDO_TRACE_IMPORT"] = a.trace_import')
    assert i_parse < i_env < src.index("ON FIGE ICI, AVANT TOUTE MESURE")
    ast.parse(src)


def test_un_module_non_surveille_ne_laisse_rien(tmp_path):
    sortie = tmp_path / "trace.jsonl"
    finder = T.armer(["faux_absent_19"], sortie=sortie)
    try:
        importlib.import_module("json")
        assert not sortie.exists()
    finally:
        T.desarmer(finder)
    assert finder not in sys.meta_path
