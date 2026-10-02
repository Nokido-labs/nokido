"""NR -- la fitness a enfin une CAPACITE mesuree : retrieval dense sur un examen held-out SCELLE.

2026-10-01 (revue claude.ai mission_rsi_soif, note RSI section 1) : la fitness comptait des fichiers.
Chaine livree : examen scelle tests/baselines/retrieval_heldout_v1.json (zone de l'evaluateur, partage
deterministe, surface separee ecartee) -> forge_bench_beir.mesurer_capacite (nDCG@10, bruit =
max(A/A, 1/n), cle = empreinte examen + corpus) -> forge_generation.capacites_mesurees -> CI ->
_verdict_capacites, qui ne compare que des examens IDENTIQUES.
Hermetique : mini-corpus et base temporaires, embedder simule.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import struct
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_generation as gen  # noqa: E402

SCELLE = RACINE / "tests" / "baselines" / "retrieval_heldout_v1.json"


def _bench():
    spec = importlib.util.spec_from_file_location("bench_beir_nr", RACINE / "tools" / "forge_bench_beir.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_l_examen_scelle_est_coherent_et_rejouable():
    ex = json.loads(SCELLE.read_text(encoding="utf-8"))
    held, dev = set(ex["heldout"]), set(ex["dev"])
    assert held and dev and not (held & dev) and not (held & set(ex["ecartees"]["ids"]))
    for q in held | dev:                               # la regle ecrite se rejoue a l'identique
        pair = int(hashlib.sha256(q.encode()).hexdigest()[0], 16) % 2 == 0
        assert (q in held) == pair, q
    cibles = [c for d in ex["heldout"].values() for c in d["qrels"]]
    assert not [c for c in cibles if c.startswith("skill_ctf")], "la surface separee est hors examen"


def _vec(i):
    v = [0.0] * 1024
    v[i] = 1.0
    return v


@pytest.fixture
def mini(tmp_path, monkeypatch):
    b = _bench()
    bench = tmp_path / "rag_bench"
    bench.mkdir()
    ids = ["c0", "c1", "c2"]
    (bench / "sample.jsonl").write_text("\n".join(json.dumps({"id": i, "text": "t"}) for i in ids), encoding="utf-8")
    examen = {"heldout_id": "essai", "corpus": {"sha256_ids_tries": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()},
              "heldout": {"q1": {"texte": "un", "qrels": {"c1": 1}}, "q2": {"texte": "deux", "qrels": {"c2": 1}}}}
    scelle = tmp_path / "heldout.json"
    scelle.write_text(json.dumps(examen), encoding="utf-8")
    db = tmp_path / "rag.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, embedding BLOB)")
    for i, cid in enumerate(ids):
        c.execute("INSERT INTO rag_chunks VALUES (?, ?)", (cid, struct.pack("1024f", *_vec(i))))
    c.commit()
    c.close()
    monkeypatch.setattr(b, "BENCH", bench)
    monkeypatch.setattr(b, "HELDOUT", scelle)
    monkeypatch.setattr(b, "CAPACITES", tmp_path / "capacites")
    return b, db, scelle, tmp_path


def test_la_mesure_rend_score_bruit_et_cle_d_examen(mini):
    b, db, scelle, tmp = mini
    parfait = lambda textes: ([_vec(1 if t == "un" else 2) for t in textes], "simule")  # noqa: E731
    rec = b.mesurer_capacite(embed=parfait, base=str(db))
    assert rec["verdict"] == "MESURE" and rec["score"] == 1.0 and rec["n_exploitables"] == 2
    assert rec["bruit"] == 0.5, "plancher d'une question sur deux : un delta plus petit n'est pas un signal"
    sha8 = hashlib.sha256(scelle.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:8]
    assert rec["dimension"].startswith("retrieval_dense_ndcg10@%s." % sha8)
    # La meme copie en CRLF garde la MEME cle (git convertit les fins de ligne selon la machine).
    scelle.write_bytes(scelle.read_bytes().replace(b"\n", b"\r\n"))
    assert b.mesurer_capacite(embed=parfait, base=str(db))["dimension"] == rec["dimension"]
    assert json.loads((tmp / "capacites" / "retrieval_dense.json").read_text(encoding="utf-8"))["score"] == 1.0


def test_corpus_different_ou_fournisseur_muet_donnent_indecidable(mini):
    b, db, scelle, tmp = mini
    muet = lambda textes: (None, None)  # noqa: E731
    assert b.mesurer_capacite(embed=muet, base=str(db))["verdict"] == "INDECIDABLE"
    (b.BENCH / "sample.jsonl").write_text(json.dumps({"id": "autre", "text": "t"}), encoding="utf-8")
    rec = b.mesurer_capacite(embed=muet, base=str(db))
    assert rec["verdict"] == "INDECIDABLE" and "corpus" in rec["motif"]


def test_la_generation_ne_lit_que_des_mesures_recentes_et_valides(tmp_path):
    d = tmp_path / "capacites"
    d.mkdir()
    maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
    vieux = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 30 * 86400))
    (d / "a.json").write_text(json.dumps({"verdict": "MESURE", "dimension": "dim@x.y", "score": 0.6, "bruit": 0.02, "ts": maintenant}))
    (d / "b.json").write_text(json.dumps({"verdict": "INDECIDABLE", "dimension": "dim2", "ts": maintenant}))
    (d / "c.json").write_text(json.dumps({"verdict": "MESURE", "dimension": "dim3", "score": 0.9, "ts": vieux}))
    assert gen.capacites_mesurees(dossier=d) == {"dim@x.y": {"score": 0.6, "bruit": 0.02}}


def test_deux_examens_differents_ne_se_comparent_pas():
    meme = gen._verdict_capacites({"retrieval_dense_ndcg10@aa.bb": {"score": 0.60, "bruit": 0.02}},
                                  {"retrieval_dense_ndcg10@aa.bb": {"score": 0.50, "bruit": 0.02}})
    assert meme["verdict"] == "AMELIORE"
    autre = gen._verdict_capacites({"retrieval_dense_ndcg10@aa.cc": {"score": 0.90, "bruit": 0.02}},
                                   {"retrieval_dense_ndcg10@aa.bb": {"score": 0.50, "bruit": 0.02}})
    assert autre is None, "corpus vectorise different : aucune conclusion"
