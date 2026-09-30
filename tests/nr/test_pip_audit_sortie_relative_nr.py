"""NR -- un `--sortie` RELATIF de forge_pip_audit_mesure se resout contre le DEPOT, pas contre le cwd.

Mesure du 2026-09-26 : le circadien lance la mesure NREM1 avec
`--sortie sandbox/pip_audit_history/pip_audit_<jour>.json` (relatif). pip-audit tourne avec
`cwd=ROOT` et ecrit donc le `.partiel` DANS le depot ; mais `main` verifiait
`provisoire.exists()` contre le cwd de l'APPELANT. Resultat : « NON MESURE : pip-audit n'a
produit aucun fichier », rc 2, et un `pip_audit_2026-09-26.partiel` parasite laisse sur le
disque -- une mesure REUSSIE lue comme un echec, et le temoin versionne jamais rafraichi.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "tools" / "forge_pip_audit_mesure.py"


def _module():
    spec = importlib.util.spec_from_file_location("forge_pip_audit_mesure_nr", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_une_sortie_relative_se_resout_contre_le_depot(tmp_path, monkeypatch):
    m = _module()
    depot = tmp_path / "depot"
    (depot / "sandbox").mkdir(parents=True)
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    monkeypatch.setattr(m, "ROOT", depot)
    monkeypatch.setattr(m, "SANDBOX", depot / "sandbox")
    monkeypatch.setattr(m, "CACHE", depot / "sandbox" / "pip_audit_cache")

    def faux_pip_audit(cible):
        # Le vrai `_sortie` lance pip-audit avec cwd=ROOT : un chemin relatif s'y resout.
        p = Path(cible) if Path(cible).is_absolute() else m.ROOT / cible
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"dependencies": [{"name": "x", "version": "1", "vulns": []}]}),
                     encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(m, "_sortie", faux_pip_audit)
    monkeypatch.chdir(ailleurs)  # le circadien n'a aucune raison de tourner a la racine du depot

    rc = m.main(["--sortie", "sandbox/pip_audit_history/pip_audit_2026-09-26.json"])

    assert rc == 0, "une mesure REUSSIE a ete lue comme un echec (rc=%s)" % rc
    assert (depot / "sandbox" / "pip_audit_history" / "pip_audit_2026-09-26.json").exists()
    assert not list(depot.rglob("*.partiel")), "un .partiel parasite est reste dans le depot"
    assert not (ailleurs / "sandbox").exists(), "le rapport a ete ecrit dans le cwd de l'appelant"
