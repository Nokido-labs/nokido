# -*- coding: utf-8 -*-
"""NR -- un import mort dans un fichier NON VERSIONNE n'est pas une regression du corps.

2026-10-13 : `tools/tmp_bench_rust_go.py`, brouillon non suivi, importait `forge_bm25`.
`audit_import_resolvability` balayait `app/*.py` + `tools/*.py` par glob : -6 points au score
de sante, DOULEUR critical relancee 3 fois en 6 h, puis relayee par claude.ai comme regression.
Le fichier non suivi est CLASSE a part (hors_corps), visible, jamais compte comme panne ;
git illisible -> perimetre glob, et le rapport le dit.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_health_diagnostic as H  # noqa: E402


def _depot(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "app" / "forge_suivi.py").write_text("import forge_disparu_suivi\n", encoding="utf-8")
    (tmp_path / "tools" / "tmp_brouillon.py").write_text("import forge_disparu_brouillon\n",
                                                         encoding="utf-8")
    return tmp_path


def test_un_brouillon_non_versionne_est_hors_corps_pas_une_panne(tmp_path, monkeypatch):
    depot = _depot(tmp_path)
    monkeypatch.setattr(H, "ROOT", depot)
    monkeypatch.setattr(H, "_fichiers_versionnes", lambda dossiers: {"app/forge_suivi.py"})

    r = H.audit_import_resolvability()

    assert [b["missing"] for b in r["broken"]] == ["forge_disparu_suivi"], r
    assert [b["missing"] for b in r["hors_corps"]] == ["forge_disparu_brouillon"], (
        "l'import mort du brouillon doit rester VISIBLE, classe hors du corps")
    assert r["perimetre"].startswith("fichiers versionnes")


def _git(depot, *args):
    import subprocess
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(depot), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)


def test_root_sous_dossier_d_un_autre_depot_est_illisible_pas_vide(tmp_path, monkeypatch):
    """Mesure 13/10 : le dossier temporaire du pre-controle vit DANS Nokido (sandbox/) ; `ls-files` y rendait rc=0
    et une liste vide -> aucun fichier examine, pris pour un perimetre lu (test_keeper_organe_nr rouge). Racine du
    depot : les fichiers suivis ; sous-dossier d'un autre depot : None (illisible), jamais un ensemble vide."""
    depot = tmp_path / "depot"
    (depot / "app").mkdir(parents=True)
    (depot / "app" / "forge_suivi.py").write_text("x = 1\n", encoding="utf-8")
    sous = depot / "sous"
    (sous / "app").mkdir(parents=True)
    _git(depot, "init", "-q")
    _git(depot, "add", "app/forge_suivi.py")

    monkeypatch.setattr(H, "ROOT", depot)
    assert H._fichiers_versionnes(["app", "tools"]) == {"app/forge_suivi.py"}
    monkeypatch.setattr(H, "ROOT", sous)
    assert H._fichiers_versionnes(["app", "tools"]) is None


def test_git_illisible_compte_tout_et_le_dit(tmp_path, monkeypatch):
    depot = _depot(tmp_path)
    monkeypatch.setattr(H, "ROOT", depot)
    monkeypatch.setattr(H, "_fichiers_versionnes", lambda dossiers: None)

    r = H.audit_import_resolvability()

    assert sorted(b["missing"] for b in r["broken"]) == ["forge_disparu_brouillon",
                                                        "forge_disparu_suivi"]
    assert r["hors_corps"] == []
    assert "git illisible" in r["perimetre"], "un perimetre degrade doit se nommer"
