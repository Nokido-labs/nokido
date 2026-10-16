# -*- coding: utf-8 -*-
"""NR -- la remediation mesure les orphelins par l'inventaire ACTUEL du faucheur (15/10).

`forge_remediation.check_orphans` importait `_managed_scripts`, retire du faucheur par c2705bb03 : l'import
levait a chaque passage, la dette glymphatique n'etait plus mesuree, et la branche armee passait `--arm`,
que le faucheur ignore (il attend `--kill`), tout en ecrivant `auto_reaped: True`.

Contrat :
  1. l'import nomme des symboles qui EXISTENT dans tools/forge_orphan_reaper.py (chemin reel) ;
  2. inventaire refuse ou faucheur illisible -> INCONNU, jamais « 0 candidat » ;
  3. non arme : les candidats sont SIGNALES, rien n'est lance ;
  4. arme : le faucheur est lance avec `--kill` (son option reelle), et le nombre moissonne vient de sa sortie.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_remediation as rem  # noqa: E402


def _faux_faucheur(monkeypatch, res):
    mod = types.ModuleType("nokido_agent.tools.forge_orphan_reaper")
    mod.survey = lambda: res
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_orphan_reaper", mod)
    paquet = sys.modules.get("nokido_agent.tools")
    if paquet is not None:
        monkeypatch.setattr(paquet, "forge_orphan_reaper", mod, raising=False)


def test_les_symboles_importes_existent_dans_le_faucheur():
    src = (RACINE / "app" / "forge_remediation.py").read_text(encoding="utf-8")
    noms = {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)
            and (n.module or "").endswith("forge_orphan_reaper") for a in n.names}
    faucheur = ast.parse((RACINE / "tools" / "forge_orphan_reaper.py").read_text(encoding="utf-8"))
    definis = {n.name for n in faucheur.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert noms and noms <= definis, (noms, sorted(definis))
    assert '"--kill"' in src and '"--arm"' not in src


def test_inventaire_refuse_vaut_inconnu(monkeypatch):
    _faux_faucheur(monkeypatch, {"ok": False, "reason": "superviseur muet (:8765)", "candidates": []})
    r = rem.check_orphans(False)
    assert r["etat"] == "INCONNU" and "superviseur" in r["raison"] and "candidates" not in r


def test_non_arme_signale_sans_rien_lancer(monkeypatch):
    _faux_faucheur(monkeypatch, {"ok": True, "candidates": [{"pid": 1}, {"pid": 2}], "spared": [{"pid": 3}]})
    signaux = []
    monkeypatch.setattr(rem, "_signal", lambda kind, sev, payload: signaux.append((kind, payload)) or 1)
    monkeypatch.setattr(rem.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("lance")))
    r = rem.check_orphans(False)
    assert r["candidates"] == 2 and r["epargnes"] == 1 and signaux[0][0] == "orphan_debris"


def test_arme_lance_le_faucheur_avec_kill(monkeypatch):
    _faux_faucheur(monkeypatch, {"ok": True, "candidates": [{"pid": 1}], "spared": []})
    vus = []

    def faux_run(cmd, **k):
        vus.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="REAPED pid=1 rss=2.0GB\n", stderr="")

    monkeypatch.setattr(rem.subprocess, "run", faux_run)
    r = rem.check_orphans(True)
    assert vus and vus[0][-1] == "--kill" and r["rc"] == 0 and r["moissonnes"] == 1
    assert "auto_reaped" not in r
