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
    """Doubles des exporteurs : on compte qui est appele, rien n'est exporte.

    2026-10-15 (decision owner) : la release construit le pack NATIF ; le pack selection (`export_pack`, troue en
    v0.20.11) ne doit plus etre appele par la release -- compte a part, `selection`."""
    appels = {"non_filtre": [], "essentiel": [], "selection": []}
    nf = type(sys)("forge_knowledge_pack")
    nf.export_pack = lambda **kw: appels["non_filtre"].append(kw)
    es = type(sys)("forge_knowledge_pack_export")

    def _essentiel(**kw):
        appels["essentiel"].append(kw)
        Path(kw["output"]).write_bytes(b"pack")
        return {"retenus": 1, "sha256": "0" * 64}

    es.export_pack_natif = _essentiel
    es.export_pack = lambda **kw: appels["selection"].append(kw)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_knowledge_pack", nf)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_knowledge_pack_export", es)
    # 20/10 : `from nokido_agent.tools import X` lit d'abord l'ATTRIBUT du paquet -- deja pose si un voisin de worker
    # a importe le vrai module. Le double se pose donc aussi la, sinon il depend de l'ordre des tests.
    import nokido_agent.tools as _paquet
    monkeypatch.setattr(_paquet, "forge_knowledge_pack", nf, raising=False)
    monkeypatch.setattr(_paquet, "forge_knowledge_pack_export", es, raising=False)
    return appels


def test_les_doubles_tiennent_meme_si_le_vrai_module_est_deja_importe(tmp_path, monkeypatch):
    """20/10 (CI de reference 0c9c4e4d0, 3 rouges ici, verts seuls) : `from nokido_agent.tools import X` lit d'abord
    l'ATTRIBUT du paquet ; un test voisin du meme worker xdist avait deja importe le vrai module, le double pose dans
    sys.modules etait contourne et le vrai export tournait (dist ILLISIBLE, rc=128). Dependait de l'ORDRE des tests."""
    import nokido_agent.tools.forge_knowledge_pack_export  # noqa: F401 -- comme un voisin de worker l'aurait fait
    m = _assets()
    appels = _pieges(monkeypatch)
    m.build_rag_pack(tmp_path, "9.9.9", _dist_avec_importeur(tmp_path, "    return {'texts': ['x']}\n"))
    assert len(appels["essentiel"]) == 1, "le VRAI export a tourne : le double ne tient pas"


def test_sans_clone_du_dist_refus_avant_tout_export(tmp_path, monkeypatch):
    m = _assets()
    appels = _pieges(monkeypatch)
    with pytest.raises(SystemExit) as e:
        m.build_rag_pack(tmp_path, "9.9.9")
    assert "--repo" in str(e.value) and "--skip-pack" in str(e.value)
    assert appels == {"non_filtre": [], "essentiel": [], "selection": []}
    assert list(tmp_path.iterdir()) == []


def _dist_avec_importeur(tmp_path, corps_lire_pack: str | None) -> Path:
    """Faux clone du dist portant SON importeur : c'est lui que l'utilisateur executera."""
    dist = tmp_path / "dist"
    (dist / "tools").mkdir(parents=True)
    if corps_lire_pack is not None:
        (dist / "tools" / "forge_knowledge_pack_import.py").write_text(
            "def lire_pack(p):\n" + corps_lire_pack, encoding="utf-8")
    return dist


def test_avec_le_clone_seul_l_export_essentiel_est_appele(tmp_path, monkeypatch):
    m = _assets()
    appels = _pieges(monkeypatch)
    dest = m.build_rag_pack(tmp_path, "9.9.9", _dist_avec_importeur(tmp_path, "    return {'texts': ['x']}\n"))
    assert appels["non_filtre"] == [], "l'export NON FILTRE a ete appele : la base partirait dans la release"
    assert appels["selection"] == [], "le pack SELECTION (troue en v0.20.11) a ete appele au lieu du natif"
    assert len(appels["essentiel"]) == 1 and appels["essentiel"][0]["dist"] == tmp_path / "dist"
    assert dest.name == "nokido_knowledge_pack_v9.9.9.npz"


def test_un_pack_que_l_importeur_du_dist_ne_lit_pas_est_refuse_et_mis_de_cote(tmp_path, monkeypatch):
    """Mesure 0.20.12 (16/10) : le pack natif publie etait refuse par l'importeur livre dans la meme version
    (« format inconnu ») -- RAG vide chez l'utilisateur. La release construit le pack sans jamais le relire par
    le code que l'utilisateur executera. Desormais : l'importeur DU DIST relit, sinon refus ; le pack refuse est
    mis de cote (`.refuse`) pour qu'aucun upload du dossier d'assets ne l'emporte."""
    m = _assets()
    _pieges(monkeypatch)
    dist = _dist_avec_importeur(tmp_path, "    raise ValueError('format inconnu : x')\n")
    with pytest.raises(SystemExit) as e:
        m.build_rag_pack(tmp_path, "9.9.9", dist)
    assert "format inconnu" in str(e.value) and "importeur" in str(e.value)
    assert not (tmp_path / "nokido_knowledge_pack_v9.9.9.npz").exists()
    assert (tmp_path / "nokido_knowledge_pack_v9.9.9.npz.refuse").exists()


def test_un_dist_sans_importeur_refuse_le_pack(tmp_path, monkeypatch):
    m = _assets()
    _pieges(monkeypatch)
    with pytest.raises(SystemExit) as e:
        m.build_rag_pack(tmp_path, "9.9.9", _dist_avec_importeur(tmp_path, None))
    assert "importeur absent" in str(e.value)


def test_pack_seul_construit_le_CANDIDAT_et_rien_d_autre(tmp_path, monkeypatch, capsys):
    """2026-10-16 : le pack n'etait construit qu'a la promotion, jamais essaye (0.20.12). `--pack-seul --repo <snapshot>`
    construit le pack candidat par build_rag_pack (relu par l'importeur du dist), donne son sha et la commande de
    depot sur la release BROUILLON ; ni tarball ni vendor.lock ; sans --repo, refus."""
    m = _assets()
    vus = []

    def _pack(out_dir, version, depot=None):
        vus.append((version, depot))
        p = out_dir / ("nokido_knowledge_pack_v%s.npz" % version)
        p.write_bytes(b"pack")
        return p

    monkeypatch.setattr(m, "build_rag_pack", _pack)
    monkeypatch.setattr(m, "build_code_tarball", lambda *a, **k: pytest.fail("tarball construit en --pack-seul"))
    monkeypatch.setattr(m, "write_vendor_lock", lambda *a, **k: pytest.fail("vendor.lock ecrit en --pack-seul"))
    monkeypatch.setattr(sys, "argv", ["forge_release_assets.py", "--version", "9.9.9", "--pack-seul",
                                      "--repo", str(tmp_path / "snap"), "--out", str(tmp_path / "out")])
    assert m.main() == 0
    assert vus == [("9.9.9", str(tmp_path / "snap"))]
    sortie = capsys.readouterr().out
    assert "gh release create v9.9.9 --draft" in sortie and "sha256" in sortie
    monkeypatch.setattr(sys, "argv", ["forge_release_assets.py", "--version", "9.9.9", "--pack-seul",
                                      "--out", str(tmp_path / "out")])
    assert m.main() == 1 and len(vus) == 1, "sans clone du snapshot : refus, rien construit"


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
    assert appels == {"non_filtre": [], "essentiel": [], "selection": []}
