"""NR -- la release ne publie jamais le pack RAG NON FILTRE (2026-10-07).

`forge_release_assets.build_rag_pack` appelait `forge_knowledge_pack.export_pack`, qui exporte TOUS les fragments
vectorises de la base : sessions, memoire de l'owner, veilles sous droits d'auteur. Refuse le jour meme
(ff0f31bd6), puis remplace par le pack ESSENTIEL (`forge_knowledge_pack_export`), qui se prouve contre le clone du
dist. Ce NR garde trois choses : l'export non filtre n'est JAMAIS appele ; sans clone du dist, refus avant tout
export ; et `main()` sans `--skip-pack` ni `--repo` (le chemin reel) refuse aussi.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _assets():
    spec = importlib.util.spec_from_file_location("release_assets_nr", RACINE / "tools" / "forge_release_assets.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _pieges(monkeypatch):
    """Doubles des deux exporteurs : on compte qui est appele, rien n'est exporte."""
    appels = {"non_filtre": [], "essentiel": []}
    nf = type(sys)("forge_knowledge_pack")
    nf.export_pack = lambda **kw: appels["non_filtre"].append(kw)
    es = type(sys)("forge_knowledge_pack_export")

    def _essentiel(**kw):
        appels["essentiel"].append(kw)
        Path(kw["output"]).write_bytes(b"pack")
        return {"retenus": 1, "sha256": "0" * 64}

    es.export_pack = _essentiel
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_knowledge_pack", nf)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_knowledge_pack_export", es)
    return appels


def test_sans_clone_du_dist_refus_avant_tout_export(tmp_path, monkeypatch):
    m = _assets()
    appels = _pieges(monkeypatch)
    with pytest.raises(SystemExit) as e:
        m.build_rag_pack(tmp_path, "9.9.9")
    assert "--repo" in str(e.value) and "--skip-pack" in str(e.value)
    assert appels == {"non_filtre": [], "essentiel": []}
    assert list(tmp_path.iterdir()) == []


def test_avec_le_clone_seul_l_export_essentiel_est_appele(tmp_path, monkeypatch):
    m = _assets()
    appels = _pieges(monkeypatch)
    dest = m.build_rag_pack(tmp_path, "9.9.9", tmp_path / "dist")
    assert appels["non_filtre"] == [], "l'export NON FILTRE a ete appele : la base partirait dans la release"
    assert len(appels["essentiel"]) == 1 and appels["essentiel"][0]["dist"] == tmp_path / "dist"
    assert dest.name == "nokido_knowledge_pack_v9.9.9.npz"


def test_le_point_d_entree_sans_repo_ni_skip_pack_refuse(tmp_path, monkeypatch):
    m = _assets()
    appels = _pieges(monkeypatch)

    def _fichier(nom):
        def _f(*a, **k):
            p = tmp_path / "out" / nom
            p.write_bytes(b"x")
            return p
        return _f

    # le code et le vendor.lock sont doubles : on ne teste que la decision sur le pack
    monkeypatch.setattr(m, "build_code_tarball", _fichier("nokido-9.9.9-src.tar.gz"))
    monkeypatch.setattr(m, "write_vendor_lock", _fichier("vendor.lock"))
    monkeypatch.setattr(sys, "argv", ["forge_release_assets.py", "--version", "9.9.9",
                                      "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as e:
        m.main()
    assert "--repo" in str(e.value)
    assert appels == {"non_filtre": [], "essentiel": []}
