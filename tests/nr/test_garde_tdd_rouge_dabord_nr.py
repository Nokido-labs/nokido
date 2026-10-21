"""NR -- garde TDD « rouge d'abord » (owner 2026-10-16 : « ancre la methode TDD dans le dev, arrete de contourner »,
derogation owner sur tools/forge_governed_edit.py « en attendant mieux »).

Recidive mesuree le 16/10 : 12 commits ecrits code-avant-test ; les cliquets exigeaient qu'un NR EXISTE, aucun qu'il ait
ete ROUGE. La garde : un registre des tests vus en ECHEC (plugin de tests/conftest.py) et un avertissement de
governed_edit quand on ecrit du code de app/ ou tools/ sans test rouge recent sur ce module. Non bloquante d'abord
(mesurer son bruit avant d'enforcer).

Ecrit en TDD : chaque test est vu ROUGE avant le code qui le satisfait.
"""
from __future__ import annotations

import importlib.util
import json
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ge():
    spec = importlib.util.spec_from_file_location("governed_edit_tdd_nr", ROOT / "tools" / "forge_governed_edit.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ecrire_du_code_sans_test_rouge_recent_est_signale(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_TDD_ROUGES", str(tmp_path / "rouges.jsonl"))
    assert _ge().avertissement_tdd("tools/forge_exemple.py")


def test_un_test_rouge_recent_qui_vise_le_module_leve_l_avertissement(tmp_path, monkeypatch):
    test = tmp_path / "test_exemple_nr.py"
    test.write_text("import forge_exemple\n", encoding="utf-8")
    registre = tmp_path / "rouges.jsonl"
    registre.write_text(json.dumps({"ts": time.time(), "nodeid": "test_exemple_nr.py::t", "fichier": str(test)})
                        + "\n", encoding="utf-8")
    monkeypatch.setenv("LAFORGE_TDD_ROUGES", str(registre))
    assert _ge().avertissement_tdd("tools/forge_exemple.py") is None


def test_ecrire_un_test_ou_une_doc_n_est_pas_signale(tmp_path, monkeypatch):
    """Ecrire le TEST est l'etape RED elle-meme : la garde ne vise que le code de production de app/ et tools/."""
    monkeypatch.setenv("LAFORGE_TDD_ROUGES", str(tmp_path / "rouges.jsonl"))
    m = _ge()
    assert [m.avertissement_tdd(p) for p in ("tests/nr/test_exemple_nr.py", "docs/guide.md",
                                            ".github/workflows/x.yml")] == [None, None, None]


def test_le_verdict_de_governed_write_porte_l_avertissement(tmp_path, monkeypatch):
    """Le signal doit arriver a l'agent QUI ECRIT, dans la reponse de l'ecriture -- un journal que personne ne lit ne
    l'arreterait pas. Ecriture reelle dans tmp_path ; seul le verrou d'arbre (qui parle au hub) est neutralise."""
    monkeypatch.setenv("LAFORGE_TDD_ROUGES", str(tmp_path / "rouges.jsonl"))
    m = _ge()
    monkeypatch.setattr(m, "_tree_lock_check_and_claim", lambda rel, agent: [])
    cible = tmp_path / "tools" / "forge_exemple.py"
    verdict = m.governed_write(str(cible), "x = 1\n", agent="NR")
    assert verdict.get("ok") and "avertissement_tdd" in verdict, verdict


def test_un_test_en_echec_est_note_dans_le_registre_des_rouges(tmp_path, monkeypatch):
    """Le registre est ALIMENTE par le plugin de tests/conftest.py : un test qui echoue (phase call) y est note avec
    son fichier -- c'est ce qui rend la garde verifiable, au lieu d'une declaration de l'agent."""
    registre = tmp_path / "rouges.jsonl"
    monkeypatch.setenv("LAFORGE_TDD_ROUGES", str(registre))
    spec = importlib.util.spec_from_file_location("conftest_tdd_nr", ROOT / "tests" / "conftest.py")
    c = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(c)
    rapport = types.SimpleNamespace(when="call", failed=True, nodeid="tests/nr/test_x_nr.py::t",
                                    fspath=str(tmp_path / "test_x_nr.py"))
    c.pytest_runtest_logreport(rapport)
    assert json.loads(registre.read_text(encoding="utf-8").splitlines()[-1])["nodeid"] == "tests/nr/test_x_nr.py::t"
