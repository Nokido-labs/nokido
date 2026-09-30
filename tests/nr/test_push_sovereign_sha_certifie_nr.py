# -*- coding: utf-8 -*-
"""NR — `forge_push_sovereign --sha` pousse EXACTEMENT le sha certifie.

Mesure du 2026-09-23 : la CI a certifie `fd499fa24` (CAPTURED/SUITE_COMPLETE),
mais `alpha` pointait deja sur `cd0b67a82`, commite pendant la CI et jamais
certifie. L'outil ne savait pousser que la TETE de branche : publier le sha
certifie obligeait soit a pousser du non-certifie, soit a relancer 30 min de CI.

Contrat :
  * sans --sha : refspec historique `<branche>:<branche>` (rien ne change) ;
  * --sha ANCETRE de la branche : refspec `<sha>:refs/heads/<branche>` --
    avance rapide, jamais de --force ;
  * --sha NON ancetre (etranger, ou posterieur) : REFUS nomme, rien pousse.
Exerce sur un vrai depot git temporaire, pas sur des faux.
"""
import importlib
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.29)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
P = importlib.import_module("forge_push_sovereign")


def _g(repo, *a):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo)] + list(a),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout.strip()


def _depot(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _g(repo, "init", "-q", "-b", "alpha")
    _g(repo, "config", "user.email", "t@t")
    _g(repo, "config", "user.name", "t")
    shas = []
    for i in range(3):
        (repo / "f.txt").write_text(str(i), encoding="utf-8")
        _g(repo, "add", "f.txt")
        _g(repo, "commit", "-q", "-m", "c%d" % i)
        shas.append(_g(repo, "rev-parse", "HEAD"))
    _g(repo, "checkout", "-q", "-b", "autre", shas[0])
    (repo / "g.txt").write_text("x", encoding="utf-8")
    _g(repo, "add", "g.txt")
    _g(repo, "commit", "-q", "-m", "etranger")
    etranger = _g(repo, "rev-parse", "HEAD")
    _g(repo, "checkout", "-q", "alpha")
    return repo, shas, etranger


def test_sans_sha_refspec_historique(tmp_path, monkeypatch):
    repo, _s, _e = _depot(tmp_path)
    monkeypatch.setattr(P, "_REPO", repo)
    assert P.refspec("alpha", None) == ("alpha:alpha", None)


def test_sha_ancetre_pousse_exactement_ce_sha(tmp_path, monkeypatch):
    repo, shas, _e = _depot(tmp_path)
    monkeypatch.setattr(P, "_REPO", repo)
    spec, err = P.refspec("alpha", shas[1][:9])
    assert err is None
    assert spec == "%s:refs/heads/alpha" % shas[1], spec


def test_sha_etranger_est_REFUSE(tmp_path, monkeypatch):
    repo, _s, etranger = _depot(tmp_path)
    monkeypatch.setattr(P, "_REPO", repo)
    spec, err = P.refspec("alpha", etranger)
    assert spec is None and err and "ancetre" in err


def test_sha_inconnu_est_REFUSE(tmp_path, monkeypatch):
    repo, _s, _e = _depot(tmp_path)
    monkeypatch.setattr(P, "_REPO", repo)
    spec, err = P.refspec("alpha", "deadbeef1")
    assert spec is None and err
