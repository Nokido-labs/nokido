"""NR - la CI de reference refuse de partir sans audit frais des manifestes livres (pre-controle, avant ~3 h de CI)."""
from __future__ import annotations

import datetime
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_ci_reference as C  # noqa: E402
import dist_promotion as DP  # noqa: E402

JOUR = datetime.date(2026, 10, 22)
TEXTE = "x==1\n"


def _contenu(_sha, _f):
    return TEXTE


def _propres():
    return dict((f, {"dependencies": []}) for f in DP.MANIFESTES_LIVRES)


def _ecrire(d, jour="2026-10-22", rapports=None, empreintes=None):
    rapports = _propres() if rapports is None else rapports
    if empreintes is None:
        empreintes = dict((f, DP._empreinte(TEXTE)) for f in DP.MANIFESTES_LIVRES)
    (d / ("audit_manifestes_%s.json" % jour)).write_text(
        json.dumps({"rapports": rapports, "empreintes": empreintes}), encoding="utf-8")


def _juge(d):
    return DP.audit_manifestes_frais("abc", d, JOUR, _contenu)


def test_absent_refuse_et_dit_la_commande(tmp_path):
    ok, m = _juge(tmp_path)
    assert not ok and "--audit-manifestes" in m and "online=true" in m


def test_frais_vert_ok(tmp_path):
    _ecrire(tmp_path)
    assert _juge(tmp_path)[0] is True


def test_perime_refuse(tmp_path):
    _ecrire(tmp_path, jour="2026-10-01")
    ok, m = _juge(tmp_path)
    assert not ok and "PERIME" in m and "--audit-manifestes" in m


def test_illisible_refuse(tmp_path):
    (tmp_path / "audit_manifestes_2026-10-22.json").write_text("{pas du json", encoding="utf-8")
    ok, m = _juge(tmp_path)
    assert not ok and "ILLISIBLE" in m


def test_manifeste_modifie_depuis_refuse(tmp_path):
    _ecrire(tmp_path, empreintes=dict((f, "0") for f in DP.MANIFESTES_LIVRES))
    assert not _juge(tmp_path)[0]


def test_manifeste_non_audite_refuse(tmp_path):
    _ecrire(tmp_path, rapports=dict((f, None) for f in DP.MANIFESTES_LIVRES))
    assert not _juge(tmp_path)[0]


def test_faille_corrigeable_refuse(tmp_path):
    r = _propres()
    vuln = dict(id="X", fix_versions=["2"])
    r["requirements.txt"] = dict(dependencies=[dict(name="a", version="1", vulns=[vuln])])
    _ecrire(tmp_path, rapports=r)
    ok, m = _juge(tmp_path)
    assert not ok and "ROUGE" in m


def test_ci_reference_refuse_sans_rien_lancer(tmp_path, capsys):
    appels = []

    def ex(cmd, **_k):
        appels.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    assert C.main(["--sha", "abc", "--dossier", str(tmp_path)], executer=ex,
                  audit=lambda s: (False, "perime -- lancer : cmd")) == 3
    assert appels == [] and "REFUS" in capsys.readouterr().out


def test_ci_reference_lecture_impossible_est_un_refus(monkeypatch):
    def boom(sha):
        raise OSError("x")

    monkeypatch.setattr(DP, "audit_manifestes_frais", boom)
    ok, m = C._audit_manifestes("abc")
    assert ok is False and "refus" in m


def test_fenetre_egale_a_celle_de_ci_local():
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert int(re.search(r"^_AUDIT_FRAICHEUR_J = (\d+)", src, re.M).group(1)) == DP.FRAICHEUR_J
