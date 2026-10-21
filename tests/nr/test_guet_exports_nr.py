# -*- coding: utf-8 -*-
"""NR — forge_guet_exports : detection par le CONTENU, verdicts DITS, idempotence.

Sur un faux dossier Telechargements (tout sous `tmp_path`, aucune base reelle :
l'insertion est INJECTEE et compte les fragments) :
  - un zip Claude et un zip ChatGPT sont reconnus par le CONTENU (jamais par le nom) ;
  - un zip Takeout et un zip quelconque sont ECARTES et le DISENT (raison nommee) ;
  - un zip tronque echoue et le DIT (verdict ECHEC, raison) -- non terminal, il se rejouera ;
  - un second passage ne reindexe rien (empreinte sha256) : seuls les verdicts TRANCHES
    (INDEXE, IGNORE, MIS_DE_COTE) ne reviennent pas ; l'ECHEC, lui, se redit (le telechargement peut finir).

Import par les NOMS des modules (`forge_conv_exports`, `forge_guet_exports`), jamais
par exec/compile.
"""
from __future__ import annotations

import json
import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import forge_conv_exports as fx  # noqa: E402
import forge_guet_exports as gx  # noqa: E402

_CLAUDE = [{"uuid": "u1", "chat_messages": [{"sender": "human", "text": "question longue " * 10},
                                            {"sender": "assistant", "text": "reponse detaillee " * 10}]}]
_CHATGPT = [{"id": "g1", "current_node": "b", "mapping": {
    "a": {"parent": None, "message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["salut " * 20]}}},
    "b": {"parent": "a", "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["bonjour " * 20]}}}}}]


def _dossier(tmp_path):
    dl, sortie, etat = tmp_path / "Downloads", tmp_path / "exports", tmp_path / "etat.json"
    dl.mkdir()
    for nom, membres in (("data-abc-batch-0000.zip", {"conversations.json": _CLAUDE, "users.json": []}),
                         ("f00ba4.zip", {"conversations.json": _CHATGPT, "chat.html": "x"}),
                         ("takeout-20261014.zip", {"Takeout/My Activity/Gemini Apps/MyActivity.json": []}),
                         ("photos.zip", {"img.txt": "rien"})):
        with zipfile.ZipFile(dl / nom, "w") as z:
            for m, c in membres.items():
                z.writestr(m, c if isinstance(c, str) else json.dumps(c))
    (dl / "tronque.zip").write_bytes(b"PK\x03\x04pas fini")
    vieux = time.time() - 600
    for p in dl.iterdir():
        os.utime(p, (vieux, vieux))
    return dl, sortie, etat


def _passage(dl, sortie, etat):
    lots = []

    def inserer(lot):
        lots.append(len(lot))
        return len(lot)

    verdicts = gx.passage(dl, sortie, etat, fx.indexer_export, inserer)
    return {v["zip"]: v for v in verdicts}, lots


def test_zips_reconnus_par_le_contenu_et_indexes(tmp_path):
    dl, sortie, etat = _dossier(tmp_path)
    v, _ = _passage(dl, sortie, etat)
    assert v["data-abc-batch-0000.zip"]["type"] == "claude" and v["data-abc-batch-0000.zip"]["verdict"] == "INDEXE"
    assert v["f00ba4.zip"]["type"] == "chatgpt" and v["f00ba4.zip"]["verdict"] == "INDEXE"


def test_takeout_et_zip_quelconque_ecartes_et_dits(tmp_path):
    dl, sortie, etat = _dossier(tmp_path)
    v, _ = _passage(dl, sortie, etat)
    assert v["takeout-20261014.zip"]["verdict"] == "MIS_DE_COTE"
    assert "Takeout" in v["takeout-20261014.zip"]["raison"], "le motif d'ecartement doit etre DIT"
    assert v["photos.zip"]["verdict"] == "IGNORE"
    assert v["photos.zip"]["raison"], "un zip ecarte sans raison nommee serait un silence"


def test_zip_tronque_echoue_et_le_dit(tmp_path):
    dl, sortie, etat = _dossier(tmp_path)
    v, _ = _passage(dl, sortie, etat)
    assert v["tronque.zip"]["verdict"] == "ECHEC"
    assert v["tronque.zip"]["raison"], "un echec silencieux ne se rejouerait pas"


def test_deuxieme_passage_est_idempotent(tmp_path):
    dl, sortie, etat = _dossier(tmp_path)
    _, lots1 = _passage(dl, sortie, etat)
    v2, lots2 = _passage(dl, sortie, etat)
    assert len(lots1) == 2, "les deux exports attendus (claude, chatgpt) doivent donner chacun leur lot"
    assert not lots2, "un second passage a reindexe des zips deja INDEXES (empreinte inoperante)"
    assert set(v2) == {"tronque.zip"}, "seul l'ECHEC non tranche se redit ; un verdict tranche ne revient jamais"
    assert v2["tronque.zip"]["verdict"] == "ECHEC"


def test_le_point_d_entree_branche_la_vraie_insertion():
    """Le guet sans point d'entree n'etait lance par rien : main() doit brancher forge_conv_indexer._insert_chunks."""
    import inspect
    src = inspect.getsource(gx.main)
    assert "_insert_chunks" in src and "passage(" in src
