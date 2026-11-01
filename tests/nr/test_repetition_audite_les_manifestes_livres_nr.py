# -*- coding: utf-8 -*-
"""NR — la RÉPÉTITION audite les manifestes livrés avec la MÊME règle que le tag, avant l'essai et la promotion.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de l'audit des dependances a la repetition"

CE QUI A ÉTÉ PAYÉ (21/10). 0.20.13 a été promue PUIS bloquée par la seule porte d'audit bloquante, au tag
(release.yml « Audit des dependances livrees ») : 19 failles corrigeables, découvertes après ~5 h de chaîne. La CI de
référence est hors ligne (pip-audit ne joint pas la base) et la porte locale, en avertissement, auditait les
ENVIRONNEMENTS du poste, pas les manifestes LIVRÉS. Décision owner : l'audit avant. Contrat (tools/dist_promotion.py) :
  MANIFESTES_LIVRES = les 4 fichiers audités par release.yml ;
  verdict_audit({manifeste: rapport pip-audit json | None}) -> {"ok", "bloquants", "avertis", "illisibles"} :
    faille AVEC version corrigée = bloquante ; SANS correctif = dite ; rapport absent = bloquant (comme release.yml) ;
  auditer_snapshot(snapshot, executer=subprocess.run) : pip-audit --no-deps --disable-pip sur chaque manifeste du
    snapshot ; un manifeste absent ou un audit qui n'écrit rien = illisible ;
  repetition(...) rend 3 (GARDE) quand l'audit du snapshot n'est pas ok.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _dp(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("dist_promotion_audit_nr", ROOT / "tools" / "dist_promotion.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "dist_promotion_audit_nr", mod)
    spec.loader.exec_module(mod)
    return mod


def _rapport(*vulns):
    return {"dependencies": [{"name": n, "version": v, "vulns": [{"id": i, "fix_versions": f}]} for n, v, i, f in vulns]}


def test_les_manifestes_sont_ceux_du_tag(monkeypatch):
    dp = _dp(monkeypatch)
    texte = WORKFLOW.read_text(encoding="utf-8")
    for f in dp.MANIFESTES_LIVRES:
        assert f in texte, "%s audite a la repetition mais pas au tag" % f
    assert len(dp.MANIFESTES_LIVRES) == 4


def test_regle_du_verdict(monkeypatch):
    dp = _dp(monkeypatch)
    propres = {f: {"dependencies": []} for f in dp.MANIFESTES_LIVRES}
    assert dp.verdict_audit(propres)["ok"] is True
    sans_correctif = dict(propres, **{"requirements.txt": _rapport(("diskcache", "5.6.3", "PYSEC-2026-2447", []))})
    v = dp.verdict_audit(sans_correctif)
    assert v["ok"] is True and len(v["avertis"]) == 1, v
    corrigeable = dict(propres, **{"requirements-ci.lock": _rapport(("aiohttp", "3.13.0", "GHSA-x", ["3.14.4"]))})
    v = dp.verdict_audit(corrigeable)
    assert v["ok"] is False and "aiohttp" in v["bloquants"][0], v
    non_audite = dict(propres, **{"requirements.nokido_py314.lock": None})
    v = dp.verdict_audit(non_audite)
    assert v["ok"] is False and v["illisibles"] == ["requirements.nokido_py314.lock"], v


def test_auditer_snapshot_lance_pip_audit_sur_chaque_manifeste(monkeypatch, tmp_path):
    dp = _dp(monkeypatch)
    for f in dp.MANIFESTES_LIVRES[:3]:
        (tmp_path / f).write_text("x==1\n", encoding="utf-8")  # le 4e manifeste manque au snapshot
    appels = []

    def faux_executer(cmd, **k):
        appels.append(cmd)
        sortie = Path(cmd[cmd.index("-o") + 1])
        sortie.write_text(json.dumps({"dependencies": []}), encoding="utf-8")

        class R:
            returncode = 0
        return R()

    v = dp.auditer_snapshot(tmp_path, executer=faux_executer)
    assert len(appels) == 3 and all("--no-deps" in c and "--disable-pip" in c for c in appels), appels
    assert v["ok"] is False and v["illisibles"] == [dp.MANIFESTES_LIVRES[3]], v
