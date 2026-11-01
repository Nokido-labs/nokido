# -*- coding: utf-8 -*-
"""NR — le pack natif ne revectorise que les fragments NEUFS : les autres reprennent le vecteur du pack précédent.

__FORGE_COLOR__ = "immunitaire/guard : non-regression du cache de vecteurs du Knowledge Pack"

CE QUI A ÉTÉ PAYÉ (21/10). Chaque construction du pack natif revectorisait les 42 418 fragments (~55 min de bge-m3
:8099) ; entre 0.20.13 et 0.20.14 seuls 4 fichiers changent (version, CHANGELOG, release.yml). Owner : « tu me fais
perdre trop de temps ». Contrat (tools/forge_knowledge_pack_export.py) :
  cache_depuis_pack(pack) -> {texte: vecteur} si le manifeste porte le MÊME modèle et le MÊME critère de découpage,
    sinon {} (un autre espace de vecteurs ne se mélange jamais) ;
  embed_avec_cache(embed_fn, cache) -> fonction : n'appelle embed_fn QUE pour les textes absents du cache, rend les
    vecteurs dans l'ordre ; un lot neuf en échec reste en échec (jamais complété par le cache) ;
  export_pack_natif(..., cache_pack=None) : avec un pack précédent, ne vectorise que les fragments neufs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _kpe(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("kpe_cache_nr", ROOT / "tools" / "forge_knowledge_pack_export.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "kpe_cache_nr", mod)
    spec.loader.exec_module(mod)
    return mod


def _pack(kpe, chemin, textes, model=None, critere=None):
    manifest = {"format": kpe.FORMAT, "version": "9.9.9", "model": model or "BAAI/bge-m3 (local :8099 seul)",
                "critere": critere or "pack natif : arbre publie du dist a ce commit, decoupe MarkdownChunker 2000/200"}
    retenus = [("id%d" % i, t, "f.md", "doc", np.full(4, i + 1, dtype=np.float32)) for i, t in enumerate(textes)]
    kpe.ecrire_pack(chemin, retenus, manifest)


def test_cache_depuis_un_pack_du_meme_espace(monkeypatch, tmp_path):
    kpe = _kpe(monkeypatch)
    p = tmp_path / "ancien.npz"
    _pack(kpe, p, ["alpha", "beta"])
    c = kpe.cache_depuis_pack(p)
    assert set(c) == {"alpha", "beta"} and float(c["beta"][0]) == 2.0, c


def test_un_autre_modele_ou_decoupage_ne_donne_aucun_cache(monkeypatch, tmp_path):
    kpe = _kpe(monkeypatch)
    p = tmp_path / "ancien.npz"
    _pack(kpe, p, ["alpha"], model="autre-modele")
    assert kpe.cache_depuis_pack(p) == {}
    _pack(kpe, p, ["alpha"], critere="decoupe 512/64")
    assert kpe.cache_depuis_pack(p) == {}
    assert kpe.cache_depuis_pack(tmp_path / "absent.npz") == {}


def test_seuls_les_textes_neufs_passent_par_l_embedder(monkeypatch):
    kpe = _kpe(monkeypatch)
    vus = []

    def embed(textes):
        vus.append(list(textes))
        return [np.full(4, 9, dtype=np.float32) for _ in textes]

    f = kpe.embed_avec_cache(embed, {"alpha": np.full(4, 1, dtype=np.float32)})
    v = f(["alpha", "neuf", "alpha"])
    assert vus == [["neuf"]], vus
    assert [float(x[0]) for x in v] == [1.0, 9.0, 1.0]
    vus.clear()
    assert len(f(["alpha"])) == 1 and vus == [], "un lot entierement en cache n'appelle pas l'embedder"


def test_un_lot_neuf_en_echec_reste_en_echec(monkeypatch):
    kpe = _kpe(monkeypatch)
    f = kpe.embed_avec_cache(lambda textes: [], {"alpha": np.full(4, 1, dtype=np.float32)})
    assert f(["alpha", "neuf"]) == [], "un echec de l'embedder ne se masque pas par le cache"


def test_export_pack_natif_utilise_le_pack_precedent(monkeypatch, tmp_path):
    kpe = _kpe(monkeypatch)
    precedent = tmp_path / "precedent.npz"
    _pack(kpe, precedent, ["fragment ancien"])
    vus = []

    def selection(dist, juge, embed_fn, **k):
        vecs = embed_fn(["fragment ancien", "fragment neuf"])
        return [("i1", "fragment ancien", "a.md", "doc", np.asarray(vecs[0])),
                ("i2", "fragment neuf", "b.md", "doc", np.asarray(vecs[1]))], {
            "essentiels_absents": [], "non_vectorise_total": 0, "candidats": 2}

    class _Dist:
        def __init__(self, chemin):
            self.commit = "c" * 40

    monkeypatch.setattr(kpe, "Dist", _Dist)
    monkeypatch.setattr(kpe, "_juge_public", lambda: None)
    monkeypatch.setattr(kpe, "selectionner_natif", selection)
    stats = kpe.export_pack_natif(tmp_path, output=tmp_path / "neuf.npz", version="9.9.9",
                                  embed_fn=lambda t: vus.append(list(t)) or [np.zeros(4, dtype=np.float32) for _ in t],
                                  cache_pack=precedent)
    assert vus == [["fragment neuf"]], vus
    assert stats["retenus"] == 2 and stats.get("depuis_cache") == 1, stats
