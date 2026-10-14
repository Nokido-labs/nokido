# -*- coding: utf-8 -*-
"""NR -- statistique publique en bas du README de la vitrine (decision owner 2026-10-13).

Ce que ces tests tiennent :
- l'archive est PAR JOUR et le releve le plus recent fait foi (GitHub ne garde que 14 jours) ;
- un trafic NON mesure (pas de jeton) s'affiche « n/d », jamais 0 -- un zero de remplacement
  ferait croire a une vitrine sans visiteur ;
- la taille de l'organisme est RELUE dans le tampon STATS du post-commit, jamais recalculee ;
- le point d'entree `main` ecrit archive.json et stats.svg ;
- le workflow ne tourne que sur le depot public, ne pousse que sur `stats`, et part dans le dist.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("forge_stats_publiques_nr", ROOT / "tools" / "forge_stats_publiques.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


TAMPON = "<!-- STATS:0690e3a84:2026-09-23 modules=582 rag_chunks=4899487 embeddings=1581437 -->"


def _faux_get(url, jeton=None):
    if url.endswith("/traffic/views"):
        return {"views": [{"timestamp": "2026-10-06T00:00:00Z", "count": 3, "uniques": 2}]}
    if url.endswith("/traffic/clones"):
        return {"clones": [{"timestamp": "2026-10-06T00:00:00Z", "count": 40, "uniques": 9}]}
    if "/actions/workflows/" in url:
        return {"workflow_runs": [{"created_at": "2026-10-06T10:00:00Z"}, {"created_at": "2026-10-06T12:00:00Z"}]}
    if "pypistats.org" in url:
        return {"data": {"last_month": 120}}
    return {"stargazers_count": 5}


def test_collecte_relit_le_tampon_et_compte_les_runs_ci(monkeypatch):
    m = _module()
    monkeypatch.setattr(m, "_get_json", _faux_get)
    r = m.collecter("Nokido-labs/nokido", "jeton", "jeton_actions", "fin\n" + TAMPON)
    assert r["vues"] == {"2026-10-06": [3, 2]} and r["clones"] == {"2026-10-06": [40, 9]}
    assert r["runs_ci"] == {"2026-10-06": 2}, "nos propres CI clonent le depot : a distinguer des lecteurs"
    assert r["organisme"]["modules"] == "582", "la taille de l'organisme vient du tampon du post-commit"
    assert r["pypi_30j"]["nokido-agent"] == 120 and not r["manques"]


def test_archive_par_jour_le_releve_recent_fait_foi():
    m = _module()
    a = m.fusionner({}, {"vues": {"2026-10-05": [1, 1], "2026-10-06": [2, 1]}, "manques": {}})
    a = m.fusionner(a, {"vues": {"2026-10-06": [5, 3], "2026-10-07": [4, 2]}, "manques": {}})
    assert a["jours"]["2026-10-05"]["vues"] == [1, 1], "un jour sorti de la fenetre de 14 j est GARDE"
    assert a["jours"]["2026-10-06"]["vues"] == [5, 3]
    assert len(a["jours"]) == 3


def test_trafic_non_mesure_s_affiche_nd_jamais_zero(monkeypatch):
    m = _module()
    monkeypatch.setattr(m, "_get_json", _faux_get)
    r = m.collecter("Nokido-labs/nokido", None, "jeton_actions", TAMPON)
    assert "trafic" in r["manques"]
    s = m.resume(m.fusionner({}, r))
    assert s["vues"] is None and s["clones"] is None
    svg = m.rendre_svg(s)
    assert "n/d vues" in svg and "0 vues" not in svg


def test_le_point_d_entree_ecrit_l_archive_et_la_carte(tmp_path, monkeypatch):
    m = _module()
    monkeypatch.setattr(m, "_get_json", _faux_get)
    monkeypatch.setenv("STATS_TOKEN", "jeton")
    readme = tmp_path / "README.md"
    readme.write_text(TAMPON, encoding="utf-8")
    assert m.main(["--sortie", str(tmp_path / "stats"), "--readme", str(readme)]) == 0
    archive = json.loads((tmp_path / "stats" / "archive.json").read_text(encoding="utf-8"))
    assert archive["jours"]["2026-10-06"]["clones"] == [40, 9]
    svg = (tmp_path / "stats" / "stats.svg").read_text(encoding="utf-8")
    assert "3 vues" in svg and "582 modules" in svg


def test_le_workflow_reste_sur_le_depot_public_et_la_branche_stats():
    wf = (ROOT / ".github" / "workflows" / "stats-publiques.yml").read_text(encoding="utf-8")
    assert "if: github.repository == 'Nokido-labs/nokido'" in wf
    assert "git push --quiet origin HEAD:stats" in wf and "HEAD:main" not in wf
    src = (ROOT / "tools" / "forge_dist_publish.py").read_text(encoding="utf-8")
    assert '".github/workflows/stats-publiques.yml"' in src, "le workflow doit partir dans le dist"
