#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gel de la BASELINE de ranking de `RAGEngine.search` — temoin experimental.

REGLE FONDATRICE (mandat owner 2026-09-01) :

    La baseline mesure le systeme existant. Elle ne modifie RIEN pour pouvoir le
    mesurer. Toute donnee non observable aujourd'hui est marquee NOT_OBSERVABLE,
    jamais estimee, jamais mise a zero, jamais laissee a `null` ambigu.

Aucune ligne du moteur de retrieval n'est touchee. Les signaux bruts par candidat
(`raw_lexical_score`, `raw_vector_score`) ne sont PAS exposes par `search()` : ils
viendront de la phase d'instrumentation suivante, qui elle aura le droit d'y toucher.
Les recalculer ici depuis un script ferait une SECONDE VERITE : le jour ou le moteur
changerait sa normalisation BM25, son repli FAISS ou son top-200, ce script continuerait
a produire des chiffres coherents entre eux et FAUX par rapport au moteur reel.

DEUX CAPTURES SEPAREES, en deux fichiers distincts et non un champ :
    baseline_rerank_off.json   lexical + vector -> RRF -> score -> top-k
    baseline_rerank_on.json    idem + reranker
Sans cette separation, un gain du futur routeur serait indiscernable d'un gain apporte
par le seul reranker.

TROIS GARDES QUI REFUSENT DE GELER UN TEMOIN FAUSSE — chacune vaut un incident mesure :

 1. DENSE MUET. `search()` commence par embarquer la requete. Si aucun backend
    d'embedding ne repond (le 2026-09-01 : Modal 404 quota, Cloudflare 10 000 neurons
    epuises, pilier local ecarte par politique), alors `sims = [0.0] * len(chunks)` et
    la baseline serait LEXICALE SEULE. Un tel temoin ne represente pas le regime
    nominal, et le comparer plus tard a un routeur donnerait un verdict inventé.
 2. RAM. Instancier un RAGEngine charge le corpus entier (~2,63 Go de texte + 0,74 Go
    d'enveloppe, davantage sans `skip_emb`). Lance sur une machine deja chargee, c'est
    le geste qui a fait tomber le poste ce jour-la. On refuse sous un plancher de marge.
 3. IMMUABILITE. Une baseline deja ecrite n'est jamais ecrasee : un temoin qu'on
    remplace en silence ne temoigne plus de rien. Il faut `--force` explicite.
"""

from __future__ import annotations

__FORGE_COLOR__ = "memoire/baseline-ranking"

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JEU = ROOT / "tests" / "baselines" / "retrieval_queries_v1.json"
SORTIE = ROOT / "tests" / "baselines"
NOT_OBSERVABLE = "NOT_OBSERVABLE"
MARGE_RAM_GO = 6.0


def _git_commit() -> str:
    try:
        # `errors="replace"` n'est pas cosmetique : sans lui, une sortie non decodable
        # fait crasher le thread de lecture de subprocess (garde anti-regression du
        # git-gate, incident 47 Go). Un capteur de baseline ne doit jamais tomber sur
        # l'encodage de la sortie de git.
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                            "rev-parse", "HEAD"], capture_output=True, text=True,
                           errors="replace", timeout=20)
        return (r.stdout or "").strip() or "INCONNU"
    except Exception as exc:  # noqa: BLE001
        return f"INCONNU ({type(exc).__name__})"


def _corpus_fingerprint() -> dict:
    """Empreinte du corpus : une baseline n'est comparable qu'a corpus connu."""
    import sqlite3

    from nokido_agent.app.forge_db_path import db_path

    try:
        c = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30)
        try:
            c.execute("BEGIN")
            n = c.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
            fts = c.execute("SELECT count(*) FROM rag_chunks_fts_docsize").fetchone()[0]
            vec = c.execute(
                "SELECT count(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
            c.execute("COMMIT")
        finally:
            c.close()
        return {"chunks": n, "indexes_fts": fts, "avec_embedding": vec}
    except Exception as exc:  # noqa: BLE001
        return {"erreur": f"{type(exc).__name__}: {exc}"}


def _ram_libre_go() -> float | None:
    try:
        import psutil

        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception as exc:  # noqa: BLE001 - sans mesure on ne force pas, on le DIT
        print(f"[baseline] RAM non mesurable ({type(exc).__name__}) -- garde inoperante",
              flush=True)
        return None


def _dense_vivant() -> tuple[bool, str]:
    """Le canal dense peut-il seulement parler ? (garde n°1)"""
    try:
        from nokido_agent.app.forge_embed_router import embed

        t = time.time()
        v = embed("sonde de disponibilite du canal dense")
        if v and len(v) >= 256:
            return True, f"embedding requete OK (dim={len(v)}, {time.time() - t:.2f}s)"
        return False, ("aucun backend d'embedding ne repond : `search()` retomberait sur "
                       "sims=[0.0] et la baseline serait LEXICALE SEULE")
    except Exception as exc:  # noqa: BLE001
        return False, f"routeur d'embedding indisponible ({type(exc).__name__}: {exc})"


async def _capturer(engine, requetes, k: int, rerank: bool) -> list:
    lignes = []
    for r in requetes:
        t0 = time.time()
        try:
            docs = await engine.search(r["q"], k=k, rerank=rerank)
            erreur = None
        except Exception as exc:  # noqa: BLE001 - un echec se CONSIGNE, il ne s'efface pas
            docs, erreur = [], f"{type(exc).__name__}: {exc}"
        ms = round((time.time() - t0) * 1000, 1)
        lignes.append({
            "query_id": r["id"], "cat": r["cat"], "query": r["q"],
            "latence_ms": ms, "erreur": erreur, "n_resultats": len(docs),
            "resultats": [{
                "rank": i + 1,
                "chunk_id": d.get("id"),
                "source": d.get("source"),
                "domain": d.get("domain"),
                "final_score": d.get("score"),
                "raw_lexical_score": NOT_OBSERVABLE,
                "raw_vector_score": NOT_OBSERVABLE,
                "structure_score": NOT_OBSERVABLE,
            } for i, d in enumerate(docs)],
        })
        print(f"[baseline] {r['id']} rerank={rerank} n={len(docs)} {ms}ms", flush=True)
    return lignes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gel de la baseline de ranking RAGEngine.search")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--force", action="store_true",
                    help="ecraser une baseline existante (a n'utiliser qu'en connaissance)")
    ap.add_argument("--ignorer-dense-muet", action="store_true",
                    help="capturer MEME si le canal dense est muet : le fichier sera "
                         "marque regime=DEGRADE et ne vaut pas temoin nominal")
    args = ap.parse_args(argv)

    requetes = json.loads(JEU.read_text(encoding="utf-8"))["requetes"]

    # --- Garde 3 : immuabilite -------------------------------------------------
    cibles = {False: SORTIE / "baseline_rerank_off.json",
              True: SORTIE / "baseline_rerank_on.json"}
    deja = [str(p) for p in cibles.values() if p.exists()]
    if deja and not args.force:
        print(json.dumps({"ok": False, "refus": "baseline deja gelee", "fichiers": deja,
                          "pourquoi": "un temoin qu'on remplace en silence ne temoigne "
                                      "plus de rien ; utiliser --force sciemment"},
                         ensure_ascii=False, indent=2))
        return 2

    # --- Garde 2 : RAM ---------------------------------------------------------
    libre = _ram_libre_go()
    if libre is not None and libre < MARGE_RAM_GO:
        print(json.dumps({"ok": False, "refus": "marge RAM insuffisante",
                          "libre_go": round(libre, 2), "plancher_go": MARGE_RAM_GO,
                          "pourquoi": "charger le corpus entier sous ce plancher a deja "
                                      "fait tomber le poste"}, ensure_ascii=False, indent=2))
        return 3

    # --- Garde 1 : dense vivant ------------------------------------------------
    dense_ok, motif = _dense_vivant()
    if not dense_ok and not args.ignorer_dense_muet:
        print(json.dumps({"ok": False, "refus": "canal dense muet", "detail": motif,
                          "pourquoi": "geler un temoin en regime degrade rendrait toute "
                                      "comparaison ulterieure fausse",
                          "remede": "attendre le retour d'un backend d'embedding, ou "
                                    "assumer --ignorer-dense-muet"},
                         ensure_ascii=False, indent=2))
        return 4

    empreinte = _corpus_fingerprint()
    commit = _git_commit()
    from nokido_agent.app.forge_rag_engine import RAGEngine

    engine = RAGEngine()
    SORTIE.mkdir(parents=True, exist_ok=True)
    resume = {}
    for rerank, chemin in cibles.items():
        lignes = asyncio.run(_capturer(engine, requetes, args.k, rerank))
        doc = {
            "baseline_id": f"retrieval_v1_rerank_{'on' if rerank else 'off'}",
            "gele_le": datetime.now(timezone.utc).isoformat(),
            "git_commit": commit,
            "corpus_fingerprint": empreinte,
            "retrieval_path": "RAGEngine.search",
            "jeu_requetes": JEU.name,
            "regime": "NOMINAL" if dense_ok else "DEGRADE",
            "regime_detail": motif,
            "effective_parameters": {
                "top_k": args.k, "reranker": rerank, "rrf_k": 60,
                "bm25_weight": "1.2 si is_technical sinon 1.0",
                "is_technical_regex": r"cve-\d+|[a-z]{2,}-\d+|\d{1,3}\.\d{1,3}|\b0x[0-9a-f]+\b",
                "note": "parametres RELEVES dans forge_rag_engine.search au 2026-09-01 ; "
                        "ils ne sont pas imposes par ce script.",
            },
            "non_observable": {
                "raw_lexical_score": "expose seulement apres instrumentation (phase 2)",
                "raw_vector_score": "idem",
                "structure_score": "aucun canal structurel n'est branche dans le moteur",
            },
            "requetes": lignes,
        }
        chemin.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        resume[chemin.name] = {"requetes": len(lignes),
                               "resultats": sum(x["n_resultats"] for x in lignes),
                               "erreurs": sum(1 for x in lignes if x["erreur"])}
    print(json.dumps({"ok": True, "regime": "NOMINAL" if dense_ok else "DEGRADE",
                      "ecrit": resume}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
