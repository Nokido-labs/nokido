"""NR -- pack natif (owner 15/10 : « mesure bien que rien d'essentiel n'est absent du knowledge pack »).

Mesure qui l'impose (pack v0.20.11) : 509 des 604 .md publies sans aucun fragment, README/CHANGELOG/wiki absents --
le pack etait une selection du RAG prive. Le mode natif decoupe l'arbre publie lui-meme ; sans dist ni reseau ici."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_spec = importlib.util.spec_from_file_location("kpe_natif", ROOT / "tools" / "forge_knowledge_pack_export.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

TEXTE = "Nokido est un runtime d'organisme local-first. " * 6


class FauxDist:
    def __init__(self, fichiers: dict):
        self.fichiers, self.publies, self.commit = fichiers, set(fichiers), "abc123"

    def _git(self, *args):
        return (0, self.fichiers[args[1].split(":", 1)[1]])


def _unitaires(textes):
    out = []
    for i, _t in enumerate(textes):
        v = np.zeros(m.DIM, dtype=np.float32)
        v[i % m.DIM] = 1.0
        out.append(v.tolist())
    return out


def test_classes_et_exclusions_declarees():
    assert m.classe_natif("README.md") == "doc"
    assert m.classe_natif("docs/wiki/20-Modules-Reference.md") == "wiki"
    assert m.classe_natif("docs/skills/forge-core/SKILL.md") == "skill"
    assert m.classe_natif("app/forge_x.py") == "code" and m.classe_natif("config/a.toml") == "config"
    assert m.classe_natif("tests/nr/test_x.py") is None and m.classe_natif(".agents/skills/a/SKILL.md") is None
    assert m.classe_natif("image.png") is None


def test_un_essentiel_absent_du_dist_refuse_le_pack(monkeypatch):
    # Revue AGY 15/10 : `e in dist.publies` laissait passer un README SUPPRIME du dist.
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md", "SECURITY.md"))
    retenus, cr = m.selectionner_natif(FauxDist({"README.md": TEXTE}), lambda c, t: False, _unitaires)
    assert cr["essentiels_absents"] == ["SECURITY.md (ABSENT DU DIST)"]


def test_l_arbre_publie_entre_et_ce_qui_sort_est_dit(monkeypatch):
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md",))
    d = FauxDist({"README.md": TEXTE, "docs/wiki/Home.md": TEXTE, "app/forge_a.py": '"""' + TEXTE + '"""',
                  "docs/gros.md": "x" * (m.TAILLE_MAX_NATIF + 1), "tests/nr/test_a.py": TEXTE,
                  "docs/secret.md": TEXTE + "\nGITHUB_TOKEN=ghp_" + "a" * 36})
    retenus, cr = m.selectionner_natif(d, lambda chemin, texte: False, _unitaires)
    chemins = {r[2] for r in retenus}
    assert {"README.md", "docs/wiki/Home.md", "app/forge_a.py"} <= chemins
    assert "tests/nr/test_a.py" not in chemins
    assert cr["trop_gros"] == [("docs/gros.md", m.TAILLE_MAX_NATIF + 1)]           # liste, jamais tronque
    if "docs/secret.md" not in chemins:
        assert cr["fichiers_incomplets"]["docs/secret.md"].get("secret")
    assert cr["essentiels_absents"] == []


def test_un_lot_non_vectorise_est_compte_jamais_complete_par_un_autre_modele(monkeypatch):
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md",))
    d = FauxDist({"README.md": TEXTE})
    retenus, cr = m.selectionner_natif(d, lambda c, t: False, lambda textes: [None] * len(textes), **MUET)
    assert retenus == [] and cr["par_classe"]["doc"]["non_vectorise"] >= 1
    defaut = __import__("inspect").signature(m.selectionner_natif).parameters["reprises"].default
    assert cr["essentiels_absents"] == ["README.md"] and cr["reprises"]["tentatives"] == defaut  # repris, puis dit
    faux_espace = lambda textes: [[0.5] * 512 for _ in textes]                     # dimension etrangere
    retenus, cr = m.selectionner_natif(d, lambda c, t: False, faux_espace, **MUET)
    assert retenus == [] and cr["par_classe"]["doc"]["non_vectorise"] >= 1


MUET = {"pouls": lambda _m: None, "dormir": lambda _s: None}


def test_un_premier_bloc_en_echec_est_repris_et_l_ordre_garde(monkeypatch):
    """15/10, pack v0.20.11 REFUSE : les essentiels de la racine (en TETE du tri) tombaient tous dans les premiers
    lots, en echec cote :8099, et un lot en echec n'etait jamais retente."""
    monkeypatch.setattr(m, "ESSENTIELS", ("CHANGELOG.md", "README.md"))
    d = FauxDist({"CHANGELOG.md": TEXTE, "README.md": TEXTE, "docs/a.md": TEXTE})
    appels, pauses = {"n": 0}, []

    def embed_capricieux(textes):
        appels["n"] += 1
        return [None] * len(textes) if appels["n"] <= 2 else _unitaires(textes)

    retenus, cr = m.selectionner_natif(d, lambda c, t: False, embed_capricieux, lot=1, pause_s=7.0,
                                       pouls=lambda _m: None, dormir=pauses.append)
    assert cr["essentiels_absents"] == [], cr
    assert cr["reprises"] == {"premiere_passe_en_echec": 2, "tentatives": 1, "recuperes": 2}
    assert pauses == [7.0]
    assert [r[2] for r in retenus] == ["CHANGELOG.md", "README.md", "docs/a.md"]     # ordre des candidats


def test_moins_de_vecteurs_que_de_textes_met_le_lot_en_echec_sans_tronquer(monkeypatch):
    monkeypatch.setattr(m, "ESSENTIELS", ())
    d = FauxDist({"README.md": TEXTE, "docs/a.md": TEXTE})
    retenus, cr = m.selectionner_natif(d, lambda c, t: False, lambda textes: _unitaires(textes)[:1], reprises=0,
                                       **MUET)
    assert retenus == [] and cr["par_classe"]["doc"]["non_vectorise"] == 2, cr


def test_lire_lot_rend_les_contenus_d_un_vrai_depot_en_un_processus(tmp_path):
    """Chemin reel : `git cat-file --batch` sur un depot git, nom avec espace, accents, chemin absent."""
    import subprocess

    d = tmp_path / "dist"
    (d / "docs").mkdir(parents=True)
    (d / "README.md").write_bytes("bonjour\nmonde\n".encode("utf-8"))
    (d / "docs" / "a b.md").write_bytes(("é" * 10).encode("utf-8"))
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-c", "safe.directory=*", "-c", "core.autocrlf=false", "-C", str(d)] + cmd,
                       check=True, capture_output=True)
    lus = m.Dist(d).lire_lot(["README.md", "docs/a b.md", "absent.md"])
    assert lus == {"README.md": "bonjour\nmonde\n", "docs/a b.md": "é" * 10}


def test_la_decoupe_lit_le_dist_par_lot_sans_git_show(monkeypatch):
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md",))

    class DistLot(FauxDist):
        lots = 0

        def lire_lot(self, chemins):
            DistLot.lots += 1
            return {c: self.fichiers[c] for c in chemins}

        def _git(self, *args):
            raise AssertionError("git show par fichier alors que la lecture par lot a reussi")

    retenus, cr = m.selectionner_natif(DistLot({"README.md": TEXTE, "docs/a.md": TEXTE}), lambda c, t: False,
                                       _unitaires, **MUET)
    assert DistLot.lots == 1 and cr["essentiels_absents"] == [] and len(retenus) == 2


def test_un_lot_illisible_retombe_sur_git_show_et_le_dit(monkeypatch):
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md",))

    class DistMuette(FauxDist):
        def lire_lot(self, chemins):
            return {}

    dits = []
    retenus, cr = m.selectionner_natif(DistMuette({"README.md": TEXTE}), lambda c, t: False, _unitaires,
                                       pouls=dits.append, dormir=lambda _s: None)
    assert cr["essentiels_absents"] == [] and any("repli" in d for d in dits), dits


def test_un_pack_troue_au_dela_du_seuil_est_refuse(monkeypatch, tmp_path):
    """15/10 : l'embedder a ete mis en sommeil pendant la mesure ; un pack a moitie vectorise ne sort pas."""
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md",))
    monkeypatch.setattr(m, "Dist", lambda chemin: FauxDist({"README.md": TEXTE, "docs/a.md": "Autre contenu. " * 20}))
    monkeypatch.setattr(m, "_juge_public", lambda: (lambda c, t: False))
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)
    moitie = lambda textes: [None if "Autre" in t else v for t, v in zip(textes, _unitaires(textes))]  # noqa: E731
    with pytest.raises(SystemExit) as e:
        m.export_pack_natif(tmp_path, tmp_path / "p.npz", "9.9.9", embed_fn=moitie)
    assert "NON vectorises" in str(e.value) and not (tmp_path / "p.npz").exists()


def test_le_pack_declare_son_besoin_de_l_embedder_avant_chaque_lot():
    """15/10 : le keeper a arrete l'embedder en plein pack (« sans intention + idle »)."""
    from types import SimpleNamespace

    vu = []
    er = SimpleNamespace(declare_wanted=lambda flag, cooldown, motif: vu.append(flag) or True,
                         _llama8099_call=lambda textes, timeout: [[0.0] * m.DIM for _ in textes])
    m._embed_bge_m3_local(["a", "b"], er=er)
    m._embed_bge_m3_local(["c"], er=er)
    assert vu == ["embed.wanted", "embed.wanted"], "chaque lot DECLARE le besoin (le cooldown est cote routeur)"


def test_un_refus_de_l_intention_ne_casse_pas_le_lot(capsys):
    from types import SimpleNamespace

    def refus(flag, cooldown, motif):
        raise OSError("sandbox illisible")

    er = SimpleNamespace(declare_wanted=refus, _llama8099_call=lambda textes, timeout: [[0.0] * m.DIM for _ in textes])
    assert len(m._embed_bge_m3_local(["a"], er=er)) == 1
    assert "NON posee" in capsys.readouterr().err


def test_le_refus_imprime_le_rapport_avant_de_sortir(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md",))
    monkeypatch.setattr(m, "Dist", lambda chemin: FauxDist({"README.md": TEXTE}))
    monkeypatch.setattr(m, "_juge_public", lambda: (lambda c, t: True))
    with pytest.raises(SystemExit):
        m.export_pack_natif(tmp_path, tmp_path / "p.npz", "9.9.9", embed_fn=_unitaires)
    err = capsys.readouterr().err
    assert '"essentiels_absents"' in err and '"fichiers_incomplets"' in err


def test_un_essentiel_absent_refuse_le_pack(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md", "CHANGELOG.md"))
    monkeypatch.setattr(m, "Dist", lambda chemin: FauxDist({"README.md": TEXTE, "CHANGELOG.md": TEXTE}))
    monkeypatch.setattr(m, "_juge_public", lambda: (lambda c, t: c == "CHANGELOG.md"))
    with pytest.raises(SystemExit) as e:
        m.export_pack_natif(tmp_path, tmp_path / "p.npz", "9.9.9", embed_fn=_unitaires)
    assert "CHANGELOG.md" in str(e.value) and not (tmp_path / "p.npz").exists()


def test_le_pack_natif_ecrit_se_relit_avec_son_manifeste(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "ESSENTIELS", ("README.md",))
    monkeypatch.setattr(m, "Dist", lambda chemin: FauxDist({"README.md": TEXTE, "docs/wiki/Home.md": TEXTE}))
    monkeypatch.setattr(m, "_juge_public", lambda: (lambda c, t: False))
    s = m.export_pack_natif(tmp_path, tmp_path / "p.npz", "9.9.9", embed_fn=_unitaires)
    z = np.load(tmp_path / "p.npz")
    meta = json.loads(bytes(z["meta"]).decode("utf-8"))
    assert meta["manifest"]["format"] == m.FORMAT_NATIF and meta["manifest"]["dist_commit"] == "abc123"
    assert set(meta["sources"]) == {"README.md", "docs/wiki/Home.md"} and s["retenus"] == len(meta["sources"])
    assert z["embeddings"].shape == (s["retenus"], m.DIM)
