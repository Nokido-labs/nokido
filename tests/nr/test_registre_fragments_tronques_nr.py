# -*- coding: utf-8 -*-
"""NR -- voie longue de l'embedding, etape 1 : chaque fragment TRONQUE pour le vecteur est inscrit avec son id.

Item SSoT roadmap_p1_voie_longue_embedding_20261008. Les textes au-dela du lot physique de :8099 sont tronques pour
le vecteur et ce n'etait dit qu'au journal (un compte, aucun id) : impossible de les revectoriser plus tard.
Une livraison executeur (1edb516b8, non integree) bornait les textes AVANT la cascade -- donc aussi pour les
fournisseurs cloud qui acceptent plus long -- et inscrivait des troncatures que :8099 n'avait pas faites. Ici on
inscrit la ou la troncature a LIEU (`_borner_textes_8099`), avec les ids du lot portes par `embed_batch_fast`.

Contrats (:8099, politique et sandbox remplaces par des doublures) :
  1. avec ids : une ligne {id, jetons, borne, ts} par texte tronque, alignee a travers les sous-lots ;
  2. sans ids : aucune ecriture (comportement inchange pour les autres appelants) ;
  3. /tokenize injoignable : {id, jetons: null, repli: true} -- INCONNU, jamais 0 ;
  4. le drain (tools/forge_embed_auto_trigger.py) passe ses ids.
"""
import json
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_embed_router as er  # noqa: E402

pytestmark = pytest.mark.timeout(60)


@pytest.fixture()
def embedder(monkeypatch, tmp_path):
    etat = {"tokenize_ko": False}

    def _appel(chemin, corps, timeout):
        if chemin == "/tokenize":
            if etat["tokenize_ko"]:
                raise OSError("tokenizer injoignable")
            return {"tokens": list(range(len(corps["content"])))}
        if chemin == "/detokenize":
            return {"content": "x" * len(corps["tokens"])}
        if chemin == "/v1/embeddings":
            return {"data": [{"index": i, "embedding": [0.1] * 1024} for i in range(len(corps["input"]))]}
        raise AssertionError(chemin)

    registre = tmp_path / "rag_fragments_tronques.jsonl"
    monkeypatch.setattr(er, "REGISTRE_TRONQUES", registre)
    monkeypatch.setattr(er, "_appel_8099", _appel)
    monkeypatch.setattr(er, "_limite_8099", lambda: 100 + er._JETONS_SPECIAUX_8099)
    monkeypatch.setattr(er, "_role_embed_local_autorise", lambda: True)
    monkeypatch.setattr(er, "_politique_embed", lambda: None)
    return registre, etat


def _lignes(registre):
    return [json.loads(x) for x in registre.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if registre.exists() else []


def test_les_tronques_sont_inscrits_avec_leur_id_a_travers_les_sous_lots(embedder):
    registre, _ = embedder
    vecs = er.embed_batch_fast(["court", "y" * 150, "z" * 300], batch_size=2, max_workers=1, ids=["a", "b", "c"])
    assert all(v for v in vecs)
    lignes = sorted(_lignes(registre), key=lambda x: x["id"])
    assert [(x["id"], x["jetons"], x["borne"]) for x in lignes] == [("b", 150, 100), ("c", 300, 100)]
    assert all("ts" in x for x in lignes)


def test_sans_ids_rien_n_est_ecrit(embedder):
    registre, _ = embedder
    er.embed_batch_fast(["y" * 150], batch_size=2, max_workers=1)
    assert not registre.exists()


def test_tokenizer_injoignable_jetons_inconnus(embedder):
    registre, etat = embedder
    etat["tokenize_ko"] = True
    er.embed_batch_fast(["y" * 150], batch_size=2, max_workers=1, ids=["b"])
    [ligne] = _lignes(registre)
    assert ligne["id"] == "b" and ligne["jetons"] is None and ligne["repli"] is True


def test_le_drain_passe_ses_ids():
    src = (RACINE / "tools" / "forge_embed_auto_trigger.py").read_text(encoding="utf-8", errors="replace")
    assert re.search(r"embed_batch_fast\(\s*texts\s*,[^)]*\bids\s*=", src)
