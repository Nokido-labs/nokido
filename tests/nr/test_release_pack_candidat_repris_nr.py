# -*- coding: utf-8 -*-
"""NR — la promotion REPREND le pack candidat quand son arbre publié est identique, au lieu de tout revectoriser.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la reprise du pack candidat a la promotion"

CE QUI A ÉTÉ PAYÉ (21/10). La promotion 0.20.13 reconstruisait le Knowledge Pack (42 418 fragments, ~55 min de bge-m3)
alors que le pack candidat du MÊME contenu (arbre git 7042a7e4… dans nokido-dist-essai ET dans nokido-dist) était déjà
construit, relu par l'importeur, essayé sur 3 OS et déposé sur le brouillon. En cours de route, l'embedder a été coupé
(RAM > 80 %) : 1 408 fragments en échec, refus certain du pack -- 1 h perdue. Décision owner : arrêter et reprendre le
candidat. La clé est l'ARBRE, pas le commit : la promotion crée un nouveau commit de snapshot au contenu identique.
Contrat (tools/forge_release_assets.py) :
  pack_reutilisable(pack, depot, version, depots_connus=()) -> (bool, raison)
    vrai si le pack existe, porte la bonne version, et que son `dist_commit` (résolu dans `depot` ou un des
    `depots_connus`) a le MÊME arbre que HEAD de `depot` ; sinon (faux, raison DITE) ;
  build_rag_pack(out_dir, version, depot, depots_connus=...) : pack réutilisable -> relu par l'importeur du dist et
    rendu SANS export ; sinon reconstruit comme avant.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _ra(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("forge_release_assets_nr", ROOT / "tools" / "forge_release_assets.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "forge_release_assets_nr", mod)
    spec.loader.exec_module(mod)
    return mod


def _git(d, *a):
    r = subprocess.run(["git", "-c", "user.name=nr", "-c", "user.email=nr@nr", "-c", "safe.directory=*", *a], cwd=str(d),
                       capture_output=True, text=True, errors="replace")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _depot(d: Path, contenu: str, message: str) -> str:
    d.mkdir(parents=True, exist_ok=True)
    if not (d / ".git").exists():
        _git(d, "init", "-q", "-b", "main")
    (d / "README.md").write_text(contenu, encoding="utf-8")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", message)
    return _git(d, "rev-parse", "HEAD")


def _pack(chemin: Path, dist_commit: str, version: str = "9.9.9"):
    from nokido_agent.tools import forge_knowledge_pack_export as kpe
    manifest = {"format": kpe.FORMAT, "version": version, "dist_commit": dist_commit,
                "model": "BAAI/bge-m3 (local :8099 seul)", "count": 1}
    kpe.ecrire_pack(chemin, [("id1", "texte", "README.md", "doc", np.zeros(4, dtype=np.float32))], manifest)


@pytest.fixture
def depots(tmp_path):
    essai, dist = tmp_path / "essai", tmp_path / "dist"
    c_essai = _depot(essai, "# meme contenu\n", "snapshot de repetition")
    _depot(dist, "# meme contenu\n", "snapshot de promotion")  # autre commit, MEME arbre
    return essai, dist, c_essai


def test_arbre_identique_dans_un_depot_connu_est_reutilisable(monkeypatch, tmp_path, depots):
    ra = _ra(monkeypatch)
    essai, dist, c_essai = depots
    pack = tmp_path / "lot" / "nokido_knowledge_pack_v9.9.9.npz"
    _pack(pack, c_essai)
    ok, raison = ra.pack_reutilisable(pack, dist, "9.9.9", depots_connus=[essai])
    assert ok is True and raison == "", raison


def test_arbre_different_n_est_pas_reutilisable_et_le_dit(monkeypatch, tmp_path, depots):
    ra = _ra(monkeypatch)
    essai, dist, c_essai = depots
    pack = tmp_path / "lot" / "nokido_knowledge_pack_v9.9.9.npz"
    _pack(pack, c_essai)
    _depot(dist, "# contenu CHANGE\n", "nouveau contenu")
    ok, raison = ra.pack_reutilisable(pack, dist, "9.9.9", depots_connus=[essai])
    assert ok is False and "arbre" in raison, raison


def test_version_differente_ou_commit_introuvable_refuse(monkeypatch, tmp_path, depots):
    ra = _ra(monkeypatch)
    essai, dist, c_essai = depots
    pack = tmp_path / "lot" / "p.npz"
    _pack(pack, c_essai, version="9.9.8")
    assert ra.pack_reutilisable(pack, dist, "9.9.9", depots_connus=[essai])[0] is False
    _pack(pack, c_essai)
    ok, raison = ra.pack_reutilisable(pack, dist, "9.9.9", depots_connus=[])  # commit de l'essai inconnu du dist
    assert ok is False and raison, raison
    assert ra.pack_reutilisable(tmp_path / "absent.npz", dist, "9.9.9")[0] is False


def test_build_rag_pack_reprend_sans_exporter(monkeypatch, tmp_path, depots):
    ra = _ra(monkeypatch)
    essai, dist, c_essai = depots
    out = tmp_path / "lot"
    dest = out / ra.BUILDERS["rag_pack"].format(version="9.9.9")
    _pack(dest, c_essai)
    from nokido_agent.tools import forge_knowledge_pack_export as kpe

    def _interdit(**k):
        raise AssertionError("export_pack_natif appele alors que le candidat etait reutilisable")

    monkeypatch.setattr(kpe, "export_pack_natif", _interdit)
    relus = []
    monkeypatch.setattr(ra, "_relire_par_l_importeur_du_dist", lambda p, d: relus.append(p) or 1)
    assert ra.build_rag_pack(out, "9.9.9", dist, depots_connus=[essai]) == dest
    assert relus == [dest], "le pack repris doit etre RELU par l'importeur du dist"


def test_build_rag_pack_va_chercher_le_candidat_du_dossier_pack_seul(monkeypatch, tmp_path, depots):
    """21/10, 2e run tue : la promotion ecrit dans C:/tmp/nokido-release/v<V>, le candidat --pack-seul vit dans
    C:/tmp/laforge-release/v<V> -- « pack absent », 42 k fragments revectorises. Le candidat est cherche la ou
    --pack-seul l'a pose (DOSSIERS_PACK_CANDIDAT, gabarit par version), COPIE au lot, puis relu."""
    ra = _ra(monkeypatch)
    essai, dist, c_essai = depots
    nom = ra.BUILDERS["rag_pack"].format(version="9.9.9")
    candidat_dir = tmp_path / "laforge-release" / "v9.9.9"
    _pack(candidat_dir / nom, c_essai)
    monkeypatch.setattr(ra, "DOSSIERS_PACK_CANDIDAT", (str(tmp_path / "laforge-release" / "v{version}"),))
    from nokido_agent.tools import forge_knowledge_pack_export as kpe

    def _interdit(**k):
        raise AssertionError("export_pack_natif appele alors qu'un candidat reutilisable existait")

    monkeypatch.setattr(kpe, "export_pack_natif", _interdit)
    monkeypatch.setattr(ra, "_relire_par_l_importeur_du_dist", lambda p, d: 1)
    lot = tmp_path / "nokido-release" / "v9.9.9"
    dest = ra.build_rag_pack(lot, "9.9.9", dist, depots_connus=[essai])
    assert dest == lot / nom and dest.is_file()
    assert dest.read_bytes() == (candidat_dir / nom).read_bytes(), "la copie doit etre identique au candidat"


def test_build_rag_pack_reconstruit_si_l_arbre_differe(monkeypatch, tmp_path, depots):
    ra = _ra(monkeypatch)
    essai, dist, c_essai = depots
    out = tmp_path / "lot"
    dest = out / ra.BUILDERS["rag_pack"].format(version="9.9.9")
    _pack(dest, c_essai)
    _depot(dist, "# contenu CHANGE\n", "nouveau contenu")
    from nokido_agent.tools import forge_knowledge_pack_export as kpe
    appels = []

    def _export(**k):
        appels.append(k)
        return {"retenus": 1, "sha256": "0" * 64}

    monkeypatch.setattr(kpe, "export_pack_natif", _export)
    monkeypatch.setattr(ra, "_relire_par_l_importeur_du_dist", lambda p, d: 1)
    ra.build_rag_pack(out, "9.9.9", dist, depots_connus=[essai])
    assert len(appels) == 1, "un arbre different doit etre reconstruit"
