"""forge_bench_beir.py — Benchmark retrieval BEIR-style sur l'echantillon Nokido.

Etape 3 du benchmark (preuve BEIR). Corpus = sample.jsonl (embeddings bge-m3
relus depuis embeddings.db), queries/qrels = forge_bench_questions. Retrieval
dense (cosine), metriques IR standard : NDCG@10, Recall@{1,5,10,100}, MAP, MRR@10.

Embedding des requetes via le llama-server bge-m3 (:8099) -- exactement le meme
embedder (Q8 GGUF, pooling CLS) que celui ayant produit les embeddings du corpus.

Run : run action=trusted_script path=tools/forge_bench_beir.py  (si server :8099 up)
      sinon sous user (demarrage llama-server depuis llama-vulkan).
"""

import json
import math
import sqlite3
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "sandbox" / "rag_bench"
DB = ROOT / "RAG" / "embeddings.db"
PORT = 8099
SERVER = __import__("os").path.expanduser(r"~\llama-vulkan\llama-server.exe")
GGUF = str(ROOT / "data" / "llm_models" / "bge-m3-Q8_0.gguf")
DIM = 1024
KS = [1, 5, 10, 100]


def _server_up() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _start_server() -> bool:
    """Demande au superviseur (:8765) de demarrer le service NokidoLlamaEmbed.
    Fallback Popen direct (ne marche que si le compte accede a llama-vulkan)."""
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:8765/supervisor/restart/NokidoLlamaEmbed", data=b"", timeout=10
        )
        print("[beir] superviseur sollicite (NokidoLlamaEmbed)", flush=True)
    except Exception:
        try:
            subprocess.Popen(
                [
                    SERVER,
                    "-m",
                    GGUF,
                    "--embedding",
                    "--pooling",
                    "cls",
                    "-ngl",
                    "99",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(PORT),
                    "-c",
                    "8192",
                    "-b",
                    "2048",
                    "--ubatch-size",
                    "2048",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[beir] fallback Popen direct llama-server", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[beir] demarrage impossible: {e}", flush=True)
            return False
    for _ in range(90):
        time.sleep(2)
        if _server_up():
            return True
    return False


def _embed(texts: list) -> list:
    body = json.dumps({"input": texts}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/embeddings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return [it["embedding"] for it in sorted(d["data"], key=lambda x: x.get("index", 0))]


def _decode(blob) -> list:
    if isinstance(blob, bytes) and len(blob) == DIM * 4:
        return list(struct.unpack(f"{DIM}f", blob))
    if isinstance(blob, (bytes, str)):
        try:
            v = json.loads(blob)
            if isinstance(v, list) and len(v) == DIM:
                return v
        except Exception:
            pass
    return None


def _norm(mat) -> np.ndarray:
    m = np.asarray(mat, dtype=np.float32)
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


# ── MESURE DE CAPACITE SUR L'EXAMEN SCELLE (2026-10-01) ──────────────────────────────────
# Revue claude.ai (mission_rsi_soif, note RSI section 1) : la fitness de l'auto-amelioration ne
# mesurait aucune capacite. Ce mode mesure le retrieval DENSE (bge-m3) sur l'examen HELD-OUT scelle
# (tests/baselines/retrieval_heldout_v1.json, zone de l'evaluateur) et ecrit une dimension que la CI
# rattache a la generation (forge_generation.capturer(capacites=...)). La CLE de la dimension porte
# l'empreinte de l'examen ET du corpus vectorise : deux generations ne se comparent que sur un examen
# identique (sinon _verdict_capacites n'a aucune dimension commune et ne conclut rien).
HELDOUT = ROOT / "tests" / "baselines" / "retrieval_heldout_v1.json"
CAPACITES = ROOT / "sandbox" / "capacites"


def _embed_compatible(texts: list):
    """(vecteurs, fournisseur) : le MEME modele que le corpus (bge-m3) -- local :8099 s'il vit, puis
    Cloudflare et Modal (texte masque). Jamais jina/voyage : autre espace vectoriel. (None, None) sinon.
    Ne DEMARRE rien : une mesure ne relance pas de service."""
    import sys as _sys

    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    essais = [("llama8099", _embed)] if _server_up() else []
    try:
        from nokido_agent.app.forge_embed_router import _cloudflare_call, _modal_call

        essais += [("cloudflare", lambda t: _cloudflare_call(t, timeout=120.0)),
                   ("modal", lambda t: _modal_call(t, timeout=180.0))]
    except Exception as e:  # noqa: BLE001 - dit, pas tu
        print("[capacite] fournisseurs cloud indisponibles (%s)" % type(e).__name__, flush=True)
    for nom, appel in essais:
        try:
            v = appel(texts)
        except Exception:  # noqa: BLE001 - fournisseur suivant ; l'echec final est dit par l'appelant
            v = None
        if v and len(v) == len(texts) and all(len(x) == DIM for x in v):
            return v, nom
    return None, None


def mesurer_capacite(embed=None, base=None, ecrire=True) -> dict:
    """nDCG@10 dense sur le held-out SCELLE ; bruit = max(ecart A/A, 1/n) ; INDECIDABLE dit sinon."""
    import hashlib
    import sys as _sys

    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    brut = HELDOUT.read_bytes()
    # Empreinte sur fins de ligne NORMALISEES : git convertit CRLF <-> LF selon la copie de travail ;
    # sur les octets bruts, le meme examen aurait deux empreintes selon la machine.
    h_sha = hashlib.sha256(brut.replace(b"\r\n", b"\n")).hexdigest()
    ex = json.loads(brut)
    rec = {"heldout_id": ex["heldout_id"], "heldout_sha256": h_sha, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    sample_ids = [json.loads(l)["id"] for l in (BENCH / "sample.jsonl").open(encoding="utf-8") if l.strip()]
    if hashlib.sha256("\n".join(sorted(sample_ids)).encode()).hexdigest() != ex["corpus"]["sha256_ids_tries"]:
        rec.update(verdict="INDECIDABLE", motif="corpus sample.jsonl different de celui que l'examen scelle")
        return _ecrire_capacite(rec) if ecrire else rec
    if base is None:
        from nokido_agent.tools.forge_tier_policy import base_rag

        base = base_rag()
    vecs = {}
    con = sqlite3.connect("file:%s?mode=ro" % base, uri=True, timeout=30)
    try:
        for i in range(0, len(sample_ids), 900):
            lot = sample_ids[i:i + 900]
            for cid, blob in con.execute("SELECT id, embedding FROM rag_chunks WHERE id IN (%s)"
                                         % ",".join("?" * len(lot)), lot):
                v = _decode(blob)
                if v is not None:
                    vecs[cid] = v
    finally:
        con.close()
    corpus_ids = sorted(vecs)
    pos = {cid: i for i, cid in enumerate(corpus_ids)}
    corpus_cle = hashlib.sha256("\n".join(corpus_ids).encode()).hexdigest()
    questions = [(q, d["texte"], d["qrels"]) for q, d in sorted(ex["heldout"].items())]
    exploitables = [(q, t, [pos[c] for c in g if c in pos]) for q, t, g in questions]
    exploitables = [x for x in exploitables if x[2]]
    rec.update(n_heldout=len(questions), n_exploitables=len(exploitables), n_corpus_vectorise=len(corpus_ids),
               corpus_cle=corpus_cle)
    if not exploitables:
        rec.update(verdict="INDECIDABLE", motif="aucune reponse attendue n'a de vecteur")
        return _ecrire_capacite(rec) if ecrire else rec
    embed = embed or _embed_compatible
    textes = [t for _q, t, _g in exploitables]
    mat = _norm([vecs[c] for c in corpus_ids])
    scores = []
    for _passe in range(2):                      # A/A : le bruit se MESURE, il ne se decrete pas
        qv, fournisseur = embed(textes)
        if not qv:
            rec.update(verdict="INDECIDABLE", motif="aucun fournisseur bge-m3 joignable pour les requetes")
            return _ecrire_capacite(rec) if ecrire else rec
        # SANS BLAS (2026-10-01) : `@` sur ces matrices a fait tomber le processus (Windows fatal
        # exception 0xc06d007f, chargement differe d'une DLL BLAS) sous le compte bac a sable. Le
        # produit element par element puis la somme ne passent pas par BLAS ; a cette taille (une
        # cinquantaine de requetes x ~10 000 chunks) c'est l'affaire de quelques secondes.
        qn = _norm(qv)
        total = 0.0
        for i, (_q, _t, gold) in enumerate(exploitables):
            ordre = np.argsort(-(mat * qn[i]).sum(axis=1))[:10]
            rang = next((r for r, idx in enumerate(ordre, start=1) if int(idx) in gold), None)
            total += 1.0 / math.log2(rang + 1) if rang else 0.0
        scores.append(total / len(exploitables))
    n = len(exploitables)
    rec.update(verdict="MESURE", fournisseur=fournisseur, score=round(scores[0], 4),
               bruit=round(max(abs(scores[0] - scores[1]), 1.0 / n), 4),
               dimension="retrieval_dense_ndcg10@%s.%s" % (h_sha[:8], corpus_cle[:8]))
    return _ecrire_capacite(rec) if ecrire else rec


def _ecrire_capacite(rec: dict) -> dict:
    CAPACITES.mkdir(parents=True, exist_ok=True)
    (CAPACITES / "retrieval_dense.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def main() -> None:
    for f in ("sample.jsonl", "queries.jsonl", "qrels.json"):
        if not (BENCH / f).exists():
            raise SystemExit(f"[beir] {f} absent")

    # 1. corpus + embeddings depuis la DB
    sample = [json.loads(l) for l in (BENCH / "sample.jsonl").open(encoding="utf-8")]
    ids = [c["id"] for c in sample]
    idpos = {cid: i for i, cid in enumerate(ids)}
    emb = [None] * len(ids)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for i in range(0, len(ids), 900):
        batch = ids[i : i + 900]
        ph = ",".join("?" * len(batch))
        for cid, blob in con.execute(
            f"SELECT id, embedding FROM rag_chunks WHERE id IN ({ph})", batch
        ):
            v = _decode(blob)
            if v is not None and cid in idpos:
                emb[idpos[cid]] = v
    con.close()
    keep = [i for i, v in enumerate(emb) if v is not None]
    corpus_ids = [ids[i] for i in keep]
    corpus_pos = {cid: i for i, cid in enumerate(corpus_ids)}
    corpus_mat = _norm([emb[i] for i in keep])
    print(f"[beir] corpus : {len(corpus_ids)}/{len(ids)} chunks embeddes", flush=True)

    # 2. queries + qrels
    queries = []
    for _l in (BENCH / "queries.jsonl").open(encoding="utf-8"):
        _l = _l.strip()
        if not _l:
            continue
        try:
            queries.append(json.loads(_l))
        except json.JSONDecodeError:
            continue
    # qrels reconstruit (mapping deterministe qid 'q{i:04d}' -> picked[i])
    gchunks = [c for c in sample if 250 <= len(c["text"]) <= 4000]
    gstep = max(1, len(gchunks) // 120)
    picked = gchunks[::gstep][:120]
    qrels = {}
    for q in queries:
        try:
            idx = int(q["_id"].lstrip("q"))
        except ValueError:
            continue
        if idx < len(picked):
            qrels[q["_id"]] = {picked[idx]["id"]: 1}
    valid = [
        q for q in queries if q["_id"] in qrels and any(c in corpus_pos for c in qrels[q["_id"]])
    ]
    print(f"[beir] requetes exploitables : {len(valid)}/{len(queries)}", flush=True)
    if not valid:
        raise SystemExit("[beir] aucune requete exploitable")

    # 3. embedding des requetes (meme bge-m3 que le corpus)
    if not _server_up():
        print("[beir] llama-server :8099 down -> demarrage...", flush=True)
        if not _start_server():
            raise SystemExit("[beir] llama-server injoignable -- relancer sous user")
    qvecs = []
    for i in range(0, len(valid), 32):
        qvecs.extend(_embed([q["text"] for q in valid[i : i + 32]]))
        print(f"[beir] requetes embeddees {min(i + 32, len(valid))}/{len(valid)}", flush=True)
    qmat = _norm(qvecs)

    # 4. retrieval dense + metriques
    sims = qmat @ corpus_mat.T
    agg = {f"recall@{k}": 0.0 for k in KS}
    agg.update({"ndcg@10": 0.0, "map": 0.0, "mrr@10": 0.0})
    for qi, q in enumerate(valid):
        gold = [corpus_pos[c] for c in qrels[q["_id"]] if c in corpus_pos]
        order = np.argsort(-sims[qi])[: max(KS)]
        rank = {int(idx): r for r, idx in enumerate(order, start=1)}
        best = min((rank.get(g, 10**9) for g in gold), default=10**9)
        for k in KS:
            if best <= k:
                agg[f"recall@{k}"] += 1.0
        if best <= 10:
            agg["ndcg@10"] += 1.0 / math.log2(best + 1)
            agg["mrr@10"] += 1.0 / best
        if best < 10**9:
            agg["map"] += 1.0 / best

    n = len(valid)
    res = {k: round(v / n, 4) for k, v in agg.items()}
    res["n_queries"] = n
    res["n_corpus"] = len(corpus_ids)
    (BENCH / "beir_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print("[beir] === RESULTATS (dense bge-m3) ===")
    for k in (
        "recall@1",
        "recall@5",
        "recall@10",
        "recall@100",
        "mrr@10",
        "ndcg@10",
        "map",
        "n_queries",
        "n_corpus",
    ):
        print(f"  {k:<12} {res[k]}")


if __name__ == "__main__":
    import sys as _sys

    if "--capacite" in _sys.argv:
        print(json.dumps(mesurer_capacite(), ensure_ascii=False, indent=1), flush=True)
    else:
        main()
