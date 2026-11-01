"""NR : un echec CONFIRME par le JUnit de la CI locale emet ses REL pour le self-patcher (owner 26/10).

Le producteur tools/forge_rel_depuis_junit.py (9868bb7d7) existait sans que personne ne l'appelle : le
self-patcher restait sans propositions localisees. Branche dans ci_local la ou l'echec est confirme ;
jamais en mode preuve (le worktree juge reste le code juge), coupable par LAFORGE_CI_REL=0, jamais bloquant.
"""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="1" failures="1" errors="0">
<testcase classname="tests.nr.test_x" name="test_y">
<failure message="assert 1 == 2">tests/nr/test_x.py:10: in test_y
    f()
app/forge_x.py:42: in f
    assert 1 == 2
E   assert 1 == 2</failure></testcase></testsuite></testsuites>
"""


def _junit(tmp_path):
    p = tmp_path / "pytest_junit.xml"
    p.write_text(JUNIT, encoding="utf-8")
    return p


def test_un_echec_confirme_emet_un_rel(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_local, "_PROOF_DIR", None, raising=False)
    monkeypatch.delenv("LAFORGE_CI_REL", raising=False)
    out = tmp_path / "out"
    n = ci_local._emettre_rel(_junit(tmp_path), out_dir=out)
    props = list(out.glob("evolution_proposal_rel_*.md"))
    assert n == 1 and len(props) == 1
    assert "app/forge_x.py" in props[0].read_text(encoding="utf-8")


def test_en_mode_preuve_sans_role_baseline_rien(tmp_path, monkeypatch):
    """Owner 26/10 : en preuve, REL seulement quand la CI juge HEAD (baseline), jamais un candidat."""
    monkeypatch.setattr(ci_local, "_PROOF_DIR", str(tmp_path / "preuve"), raising=False)
    monkeypatch.delenv("LAFORGE_PREUVE_ROLE", raising=False)
    monkeypatch.setenv("LAFORGE_REL_OUTBOX", str(tmp_path / "outbox"))
    assert ci_local._emettre_rel(_junit(tmp_path)) == 0
    assert not (tmp_path / "outbox").exists()


def test_en_mode_preuve_baseline_ecrit_hors_du_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_local, "_PROOF_DIR", str(tmp_path / "preuve"), raising=False)
    monkeypatch.setenv("LAFORGE_PREUVE_ROLE", "baseline")
    monkeypatch.setenv("LAFORGE_REL_OUTBOX", str(tmp_path / "outbox"))
    monkeypatch.delenv("LAFORGE_CI_REL", raising=False)
    assert ci_local._emettre_rel(_junit(tmp_path)) == 1
    assert len(list((tmp_path / "outbox").glob("evolution_proposal_rel_*.md"))) == 1
    assert not (tmp_path / "preuve").exists()


def test_en_mode_preuve_baseline_sans_outbox_rien(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_local, "_PROOF_DIR", str(tmp_path / "preuve"), raising=False)
    monkeypatch.setenv("LAFORGE_PREUVE_ROLE", "baseline")
    monkeypatch.delenv("LAFORGE_REL_OUTBOX", raising=False)
    assert ci_local._emettre_rel(_junit(tmp_path)) == 0


def test_la_ci_de_reference_se_declare_baseline_et_donne_l_outbox(tmp_path, monkeypatch):
    import forge_ci_reference as ref

    vus = {}

    def executer(cmd, **kw):
        vus.update(kw.get("env") or {})
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    ref.jouer("complete", ["--reference", "abc"], 10, "abc", tmp_path, executer=executer)
    assert vus.get("LAFORGE_PREUVE_ROLE") == "baseline"
    assert vus.get("LAFORGE_REL_OUTBOX", "").replace("\\", "/").endswith("/sandbox")


def test_interrupteur_coupe(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_local, "_PROOF_DIR", None, raising=False)
    monkeypatch.setenv("LAFORGE_CI_REL", "0")
    out = tmp_path / "out"
    assert ci_local._emettre_rel(_junit(tmp_path), out_dir=out) == 0


def test_un_rapport_illisible_ne_casse_pas_la_ci(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_local, "_PROOF_DIR", None, raising=False)
    monkeypatch.delenv("LAFORGE_CI_REL", raising=False)
    p = tmp_path / "casse.xml"
    p.write_text("<pas du xml", encoding="utf-8")
    assert ci_local._emettre_rel(p, out_dir=tmp_path / "out") == 0


def test_la_branche_echec_confirme_appelle_l_emission():
    src = (_R / "tools" / "ci_local.py").read_text(encoding="utf-8")
    i = src.index("le rapport JUnit CONFIRME l'echec")
    assert "_emettre_rel(_xml" in src[i:i + 1500]
