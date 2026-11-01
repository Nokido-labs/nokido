"""NR 30/10 : un pylint ABSENT ou muet n'est pas une note de 0/10.

Mesure : l'interpreteur du gate n'a pas pylint (« No module named pylint », rc=1, stdout vide) ;
`QualityGate.check` lisait l'absence de note comme 0.0, refusait le fichier ET deposait une fausse
lecon « Quality gate FAIL » au RAG. UNKNOWN != NO : sans note, la mesure est ILLISIBLE et se dit.
"""
import subprocess
import types

from nokido_agent.app import forge_quality_gate as qg


def _fichier(tmp_path):
    f = tmp_path / "module_sain.py"
    f.write_text("X = 1\n", encoding="utf-8")
    return str(f)


def _faux_run(stdout="", stderr="", rc=0, expire=False):
    def run(cmd, **kw):
        if expire:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 30))
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)
    return run


def test_pylint_absent_rend_illisible_pas_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(qg.subprocess, "run", _faux_run(stderr="python.exe: No module named pylint\n", rc=1))
    res = qg.QualityGate().check(_fichier(tmp_path))
    assert res.ok is True
    assert not any("pylint" in e for e in res.errors)
    assert any("pylint" in i and "No module named pylint" in i for i in res.illisibles)


def test_pylint_expire_rend_illisible(tmp_path, monkeypatch):
    monkeypatch.setattr(qg.subprocess, "run", _faux_run(expire=True))
    res = qg.QualityGate().check(_fichier(tmp_path))
    assert res.ok is True
    assert any("pylint" in i for i in res.illisibles)


def test_marqueur_todo_critique_seulement_en_commentaire(tmp_path, monkeypatch):
    """Le gate se refusait LUI-MEME (5 « TODO CRITICAL » : sa docstring, sa recherche, son message) : un instrument
    ne lit pas son propre vocabulaire. Le marqueur est un COMMENTAIRE ; une chaine qui le cite n'en est pas un."""
    monkeypatch.setattr(qg.subprocess, "run", _faux_run(stdout="Your code has been rated at 9.00/10\n"))
    cite = tmp_path / "cite.py"
    cite.write_text('MOTIF = "TODO CRITICAL"\n', encoding="utf-8")
    assert qg.QualityGate().check(str(cite)).ok is True
    marque = tmp_path / "marque.py"
    marque.write_text("X = 1  # TODO " + "CRITICAL: a reprendre\n", encoding="utf-8")  # compose : le gate lit ce NR
    res = qg.QualityGate().check(str(marque))
    assert res.ok is False and any("line 1" in e for e in res.errors)
    assert not any("TODO" in e for e in qg.QualityGate().check(qg.__file__).errors)


def test_note_basse_reste_un_echec(tmp_path, monkeypatch):
    monkeypatch.setattr(qg.subprocess, "run",
                        _faux_run(stdout="Your code has been rated at 5.00/10\n"))
    res = qg.QualityGate().check(_fichier(tmp_path))
    assert res.ok is False
    assert any("pylint 5.0/10" in e for e in res.errors)
    assert res.illisibles == []
