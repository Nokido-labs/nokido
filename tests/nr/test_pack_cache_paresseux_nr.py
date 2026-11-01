# -*- coding: utf-8 -*-
"""NR -- owner 1/11 : « l'embedder va rendre exactement pareil qu'avant en version 15, vraiment utile ? ». Mesure : la
voie normale des assets (forge_release_assets, appelee par la promotion) ne transmettait PAS --cache-pack, et
export_pack_natif exigeait :8099 AVANT de savoir s'il restait des fragments neufs : chaque release revectorisait les
44 797 fragments (~45 min) et la promotion v0.20.16 restait bloquee sur la RAM pour des vecteurs deja connus.
Desormais : cache transmis, et l'embedder n'est reveille qu'au PREMIER fragment absent du cache."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_knowledge_pack_export as K  # noqa: E402


class _Compteur:
    def __init__(self, pret=True):
        self.n, self.pret = 0, pret

    def __call__(self):
        self.n += 1
        return self.pret, "sonde factice"


def test_cache_complet_aucun_reveil_de_l_embedder():
    sonde, appels = _Compteur(), []
    fn = K.fonction_embed(lambda t: appels.append(t) or [[0.0]] * len(t), {"a": [1.0], "b": [2.0]}, preflight=sonde)
    assert fn(["a", "b"]) == [[1.0], [2.0]]
    assert sonde.n == 0 and appels == []


def test_fragment_neuf_reveille_une_seule_fois():
    sonde, appels = _Compteur(), []
    fn = K.fonction_embed(lambda t: appels.append(list(t)) or [[9.0]] * len(t), {"a": [1.0]}, preflight=sonde)
    assert fn(["a", "n1"]) == [[1.0], [9.0]] and fn(["n2"]) == [[9.0]]
    assert sonde.n == 1 and appels == [["n1"], ["n2"]]


def test_embedder_absent_refuse_au_premier_fragment_neuf_pas_avant():
    sonde = _Compteur(pret=False)
    fn = K.fonction_embed(lambda t: [[0.0]] * len(t), {"a": [1.0]}, preflight=sonde)
    assert fn(["a"]) == [[1.0]] and sonde.n == 0
    with pytest.raises(SystemExit):
        fn(["neuf"])


def test_sans_cache_la_sonde_passe_avant_tout():
    sonde = _Compteur(pret=False)
    with pytest.raises(SystemExit):
        K.fonction_embed(lambda t: [[0.0]] * len(t), {}, preflight=sonde)
    assert sonde.n == 1


def test_les_chemins_reels_passent_par_le_cache():
    src_export = (ROOT / "tools" / "forge_knowledge_pack_export.py").read_text(encoding="utf-8")
    assert "fonction_embed(embed_fn, cache, dry_run)" in src_export
    src_assets = (ROOT / "tools" / "forge_release_assets.py").read_text(encoding="utf-8")
    assert "build_rag_pack(out_dir, args.version, args.repo, cache_pack=args.cache_pack)" in src_assets
