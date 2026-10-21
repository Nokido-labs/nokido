# -*- coding: utf-8 -*-
"""NR — forge_conv_exports : lecture au fil de l'eau, stabilite des fragments, rien de tronque.

Trois proprietes eprouvees sur des exports SYNTHETIQUES (jamais la vraie base) :
  1. la lecture au fil de l'eau (blocs de 4 Ko) rend EXACTEMENT le meme objet que
     `json.load`, sur un tableau ET sur l'enveloppe Grok `{"conversations": [...]}` ;
  2. un export qui a GRANDI re-produit EXACTEMENT les fragments des messages deja
     vus -- c'est ce qui fait tenir la deduplication a l'insertion ;
  3. rien n'est tronque : aucun fragment ne depasse `CHUNK_MAX` (un message long est
     DECOUPE, jamais ampute), et les blocs d'outil ne sont pas indexes.

L'insertion est SIMULEE (un compteur), donc aucune base reelle n'est touchee.
Import par le NOM du module (`forge_conv_exports`), jamais par exec/compile.
"""
from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import forge_conv_exports as fx  # noqa: E402

MOTS = ["memoire", "organisme", "revocation", '"guillemet"', "accent é", "{accolade}", "[crochet]", "ligne\n"]


def _rnd():
    return random.Random(14)


def _texte(rng, n):
    return " ".join(rng.choice(MOTS) for _ in range(n))


def _claude(rng, k, n):
    return {"uuid": "c%05d" % k, "name": "fil %d" % k, "chat_messages": [
        {"sender": rng.choice(["human", "assistant"]),
         "created_at": "2026-05-0%dT10:%02d:00Z" % (1 + k % 9, j),
         "content": [{"type": "text", "text": _texte(rng, rng.choice([12, 60, 900]))},
                     {"type": "tool_use", "text": "NE PAS INDEXER"}]} for j in range(n)]}


def _chatgpt(rng, k, n):
    mapping, parent = {}, None
    for j in range(n):
        nid = "n%d_%d" % (k, j)
        mapping[nid] = {"parent": parent, "message": {"author": {"role": rng.choice(["user", "assistant"])},
                        "create_time": 1.7e9 + k * 100 + j,
                        "content": {"content_type": "text", "parts": [_texte(rng, rng.choice([12, 60, 900]))]}}}
        parent = nid
    return {"id": "g%05d" % k, "title": "t%d" % k, "mapping": mapping, "current_node": parent}


def _grok(rng, k, n):
    return {"conversation": {"id": "x%05d" % k, "title": "grok %d" % k}, "responses": [
        {"response": {"sender": rng.choice(["human", "assistant"]), "message": _texte(rng, rng.choice([12, 60, 900])),
                      "create_time": {"$date": {"$numberLong": str(int((1.7e9 + k * 100 + j) * 1000))}}}}
        for j in range(n)]}


def _jeu(tmp_path):
    """v1 (tableau claude+chatgpt, enveloppe grok), v2 = v1 dont chaque fil a grandi + des fils neufs."""
    rng = _rnd()
    v1_tab = [_claude(rng, k, 3) if k % 2 else _chatgpt(rng, k, 3) for k in range(120)]
    v1_grok = {"conversations": [_grok(rng, k, 3) for k in range(40)]}
    f1, g1 = tmp_path / "v1.json", tmp_path / "g1.json"
    f1.write_text(json.dumps(v1_tab, ensure_ascii=False, indent=1), encoding="utf-8")
    g1.write_text(json.dumps(v1_grok, ensure_ascii=False), encoding="utf-8")

    v2_tab = copy.deepcopy(v1_tab)
    for c in v2_tab:
        if "chat_messages" in c:
            c["chat_messages"] += _claude(rng, 999, 2)["chat_messages"]
        else:
            last = c["current_node"]
            for j in (7, 8):
                nid = last + "_+%d" % j
                c["mapping"][nid] = {"parent": last, "message": {"author": {"role": "user"},
                                     "create_time": 1.8e9 + j,
                                     "content": {"content_type": "text", "parts": [_texte(rng, 60)]}}}
                last = nid
            c["current_node"] = last
    v2_tab += [_claude(rng, 500 + k, 2) for k in range(10)]
    f2 = tmp_path / "v2.json"
    f2.write_text(json.dumps(v2_tab, ensure_ascii=False), encoding="utf-8")
    return v1_tab, v1_grok, f1, g1, f2


def _tous(f):
    return [fr for conv in fx.conversations(f) for fr in fx.fragments(fx.plateforme(conv), conv)]


def test_lecture_au_fil_de_l_eau_egale_json_load(tmp_path):
    v1_tab, v1_grok, f1, g1, _ = _jeu(tmp_path)
    assert list(fx.iter_tableau_json(f1, bloc=4096)) == v1_tab, "tableau : flux != json.load"
    assert list(fx.iter_tableau_json(g1, cle="conversations", bloc=4096)) == v1_grok["conversations"], \
        "enveloppe Grok : flux != json.load"


def test_un_export_qui_grandit_reproduit_les_memes_fragments(tmp_path):
    _, _, f1, _, f2 = _jeu(tmp_path)
    manquants = set(_tous(f1)) - set(_tous(f2))
    assert not manquants, (
        "%d fragment(s) de l'export v1 ont disparu dans v2 : un export plus recent ne reproduit pas "
        "les fragments deja vus (la dedup est cassee)" % len(manquants))


def test_rien_n_est_tronque_et_les_blocs_d_outil_ne_sont_pas_indexes(tmp_path):
    _, _, f1, g1, f2 = _jeu(tmp_path)
    tous = _tous(f1) + _tous(f2) + _tous(g1)
    trop_longs = [s for s, x in tous if len(x) > fx.CHUNK_MAX]
    fuite_outil = [s for s, x in tous if "NE PAS INDEXER" in x]
    assert not trop_longs, "%d fragment(s) depassent CHUNK_MAX : un message long doit etre DECOUPE" % len(trop_longs)
    assert not fuite_outil, "un bloc d'outil a ete indexe (seuls les blocs `text` doivent entrer)"


def test_indexer_export_simule_compte_les_lots(tmp_path):
    _, _, _, _, f2 = _jeu(tmp_path)
    lots = []

    def inserer(lot):
        lots.append(len(lot))
        return len(lot)

    compte = fx.indexer_export(f2, inserer)
    assert compte["inseres"] == compte["fragments"] > 0
    assert sum(lots) == compte["fragments"]
