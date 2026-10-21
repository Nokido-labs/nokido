"""NR 19/10 -- le reconciliateur (tools/forge_merge_gate.py) est ATOMIQUE et dit POURQUOI il refuse.

Mesures du 19/10 (bug_merge_gate_abandon_non_atomique_20261019) :
  * ~17 h : « ABANDON » annonce mais 9 fichiers extraits laisses dans l'arbre partage (repares a la main) ;
  * ~20 h 45 : integration du rapport AGY 0b8cc9ff4 refusee avec pour seul motif « warning: could not open directory
    '.pytest_cache/': Permission denied... » -- `err[:200]` gardait la TETE du stderr (avertissements du statut git) et
    jetait la cause, en queue.
Contrat de `reconcilier(..., apply=True)` :
  1. commit refuse -> la decision porte la QUEUE du motif, avertissements `warning:` ecartes, et la taille totale ;
  2. commit refuse, extraction refusee ou tests rouges -> l'arbre est remis a l'etat d'alpha : fichier existant dans
     HEAD = `checkout HEAD --`, fichier NEUF = `rm -f --` (un checkout HEAD d'un fichier neuf echoue et le laisse).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WARN = "".join("warning: could not open directory 'pytest_temp_%d/': Permission denied\n" % i for i in range(12))


_JOURNAL_TEST = {}


def _module():
    spec = importlib.util.spec_from_file_location("forge_merge_gate_atomique_nr", ROOT / "tools" / "forge_merge_gate.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(m)
    if "f" in _JOURNAL_TEST:
        m.JOURNAL_ARENE = _JOURNAL_TEST["f"]   # 19/10 : jamais le vrai journal de l'arene (faux constat fabrique)
    return m


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _journal_arene_isole(tmp_path):
    _JOURNAL_TEST["f"] = tmp_path / "arene.jsonl"
    yield
    _JOURNAL_TEST.clear()


def _faux_git(appels, commit_rc=0, checkout_rc=0, cause_sur_stdout=False, deja=False):
    def faux(args, cwd=None):
        appels.append(list(args))
        if args[:3] == ["diff", "--cached", "--quiet"]:
            return (0 if deja else 1), "", ""
        if "--name-only" in args:
            return 0, "app/a.py\ndocs/n.md", ""
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return 0, "alpha", ""
        if args[:2] == ["cat-file", "-e"]:
            return (0, "", "") if args[2] == "HEAD:app/a.py" else (1, "", "fatal: not in HEAD")
        if args and args[0] == "checkout" and args[1] != "HEAD":
            return checkout_rc, "", "" if checkout_rc == 0 else "error: unable to write docs/n.md"
        if args and args[0] == "commit":
            if commit_rc and cause_sur_stdout:   # mesure 19/10 : le hook pre-commit ecrit sa cause sur STDOUT
                return commit_rc, "[gate] REFUS : secret detecte dans docs/n.md\n", WARN
            return commit_rc, "", "" if commit_rc == 0 else WARN + "[gate] REFUS : secret detecte dans docs/n.md\n"
        return 0, "", ""
    return faux


def _restaurations(appels):
    return ([a for a in appels if a[:2] == ["checkout", "HEAD"]], [a for a in appels if a and a[0] == "rm"])


def test_commit_refuse_dit_la_cause_en_queue_et_sa_taille(monkeypatch):
    m = _module()
    appels = []
    monkeypatch.setattr(m, "_git", _faux_git(appels, commit_rc=1))
    r = m.reconcilier("abc1234", ["app/a.py", "docs/n.md"], apply=True)
    assert r["applique"] is False
    assert "secret detecte" in r["decision"], r["decision"]
    assert "Permission denied" not in r["decision"]
    assert "car." in r["decision"], "la borne doit dire combien"


def test_fichiers_deja_dans_alpha_le_dit_sans_committer(monkeypatch):
    """19/10 ~20 h 50 : 0b8cc9ff4 rejoue trois fois -- « nothing added to commit » lu COMMIT REFUSE, alors que le
    rapport etait deja dans alpha (71ff63262), identique."""
    m = _module()
    appels = []
    monkeypatch.setattr(m, "_git", _faux_git(appels, deja=True))
    r = m.reconcilier("abc1234", ["app/a.py", "docs/n.md"], apply=True)
    assert r["decision"].startswith("DEJA DANS ALPHA"), r["decision"]
    assert not any(a and a[0] == "commit" for a in appels), appels


def test_commit_refuse_cause_sur_stdout_est_dite(monkeypatch):
    """20 h 55 : 132 736 car. de stderr, TOUS des avertissements -- la cause du hook etait sur stdout."""
    m = _module()
    appels = []
    monkeypatch.setattr(m, "_git", _faux_git(appels, commit_rc=1, cause_sur_stdout=True))
    r = m.reconcilier("abc1234", ["app/a.py", "docs/n.md"], apply=True)
    assert "secret detecte" in r["decision"], r["decision"]
    assert "Permission denied" not in r["decision"]


def test_commit_refuse_remet_l_arbre_a_l_etat_d_alpha(monkeypatch):
    m = _module()
    appels = []
    monkeypatch.setattr(m, "_git", _faux_git(appels, commit_rc=1))
    m.reconcilier("abc1234", ["app/a.py", "docs/n.md"], apply=True)
    remis, retires = _restaurations(appels)
    assert any("app/a.py" in a and "docs/n.md" not in a for a in remis), appels
    assert any("docs/n.md" in a for a in retires), appels
    # l'INDEX d'abord (git reset ne touche pas l'arbre) : tient meme si l'ecriture du fichier est refusee (MANIFESTO.md,
    # ecrit par le compte du hub, « unable to unlink » le 19/10 ~17 h -- index neuf sur arbre ancien)
    assert any(a[:2] == ["reset", "-q"] and "app/a.py" in a for a in appels), appels


def test_extraction_refusee_remet_aussi_l_arbre(monkeypatch):
    m = _module()
    appels = []
    monkeypatch.setattr(m, "_git", _faux_git(appels, checkout_rc=1))
    r = m.reconcilier("abc1234", ["app/a.py", "docs/n.md"], apply=True)
    assert r["decision"].startswith("ABANDON")
    remis, retires = _restaurations(appels)
    assert remis and retires, "une extraction PARTIELLE ne doit rien laisser : %s" % appels
