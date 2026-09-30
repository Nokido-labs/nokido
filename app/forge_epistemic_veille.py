"""
__FORGE_COLOR__ : cognition / metacognition (organe)

ORGANE : GAP ÉPISTÉMIQUE → VEILLE — « éprouver le besoin de savoir ».

Quand un agent travaille sur un domaine où la couverture RAG est BASSE, l'organisme doit
l'ÉPROUVER (signal + hormone) puis combler par une veille bornée. Aucun module existant ne
fait ce pont (vérifié par skeleton) :
  - forge_metacognition_gate : confiance/énergie PAR APPEL (spiking), pas couverture de DOMAINE.
  - forge_critical_events / forge_endocrine : le canal du ressenti, mais aucun émetteur 'gap savoir'.
  - forge_research_agent : la veille (SearXNG+Groq→RAG), mais déclenchée à la main.
  - forge_active_inference : surprise de routage, pas lacune de connaissance.

Cet organe COMPOSE l'existant (zéro duplication) :
  couverture = forge_self_correction.preflight_check_verbose (tier + scores RRF/BM25)
  ressenti   = forge_critical_events.persist('knowledge_gap') + endocrine CORTISOL_EPISTEMIC
  remède     = forge_research_agent.research_agent (déporté via run_job par l'appelant)

Plug : appelé par metacognition_gate (par requête) ou auto_evolution_loop (balayage périodique
des domaines de travail récents). La veille longue se DÉPORTE (run_now=False → spec à lancer en
run_job) ; run_now=True réservé au code déjà dans un job détaché.
Renforce les lacunes TECHNIQUES (config/API) ET ARCHITECTURALES (un domaine Nokido mal couvert
en RAG = carte mentale trop petite, cf census 985 modules).
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

# Seuils (env-overridable). score = meilleur match RRF/BM25 ; proxy de profondeur de savoir.
GAP_SCORE_FLOOR = float(os.environ.get("LAFORGE_EPISTEMIC_SCORE_FLOOR", "8.0"))
GAP_MIN_RESULTS = int(os.environ.get("LAFORGE_EPISTEMIC_MIN_RESULTS", "3"))
VEILLE_TTL_S = int(os.environ.get("LAFORGE_EPISTEMIC_TTL_S", str(6 * 3600)))  # anti-spam domaine

_HORMONE = "CORTISOL_EPISTEMIC"


def _is_gap(n_results: int, score: float) -> bool:
    """Logique pure (testable sans RAG) : lacune si peu de matches OU score trop bas."""
    return (n_results < GAP_MIN_RESULTS) or (score < GAP_SCORE_FLOOR)


def _domain_key(domain: str) -> str:
    return "epistemic:" + hashlib.sha256(domain.lower().strip().encode()).hexdigest()[:16]


# Seuils CALIBRES le 25-07 sur 11 requetes (6 couvertes, 5 gaps connus). Le score
# de pertinence (rerank cross-encoder) CHEVAUCHE dans la zone [-5, 0] : un seuil
# unique ferait des faux positifs (veille sur du bruit). D'ou DEUX seuils + une
# zone d'ABSTENTION, conforme a la doctrine « doute -> s'abstenir » et a l'asymetrie
# des couts (rater un gap = soif muette, coute moins qu'une veille inutile).
# Mesure : gaps certains tous < -5 (blanquette -5.7, alpagas -6.7, ADN -5.2),
# aucun sujet couvert n'y descend. Conservateurs et surchargeables.
_COVERAGE_GAP_FLOOR = float(os.environ.get("LAFORGE_GAP_RERANK_FLOOR", "-5.0"))
_COVERAGE_OK_CEIL = float(os.environ.get("LAFORGE_GAP_RERANK_CEIL", "1.0"))


_PCA_DATA = None

def _load_or_compute_pca():
    global _PCA_DATA
    if _PCA_DATA is not None:
        return _PCA_DATA

    import numpy as np
    from pathlib import Path
    import sqlite3
    from datetime import datetime
    from nokido_agent.app.forge_db_path import db_path

    # Save to config/pca_64.npz
    pca_path = Path(__file__).resolve().parent.parent / "config" / "pca_64.npz"
    if pca_path.exists():
        try:
            data = np.load(pca_path, allow_pickle=True)
            if "components" in data and "mean" in data:
                _PCA_DATA = {
                    "components": data["components"],
                    "mean": data["mean"],
                    "date": str(data.get("date", "")),
                    "sample_size": int(data.get("sample_size", 0))
                }
                return _PCA_DATA
        except Exception:
            pass

    try:
        conn = sqlite3.connect(db_path())
        try:
            # Deterministic sample of 2000 embeddings
            rows = conn.execute(
                "SELECT embedding FROM rag_chunks WHERE embedding IS NOT NULL ORDER BY id LIMIT 2000"
            ).fetchall()
        finally:
            conn.close()

        vecs = []
        for (e,) in rows:
            try:
                if isinstance(e, (bytes, bytearray)):
                    if e.startswith(b'['):
                        import json as _j
                        v = np.asarray(_j.loads(e.decode('utf-8')), dtype=np.float32)
                    else:
                        v = np.frombuffer(e, dtype=np.float32)
                else:
                    import json as _j
                    v = np.asarray(_j.loads(e), dtype=np.float32)
                if v.size == 1024:
                    vecs.append(v)
            except Exception:
                pass

        if len(vecs) < 100:
            return None

        X = np.stack(vecs)
        mean = np.mean(X, axis=0)
        X_centered = X - mean

        # Fast covariance eigh method
        C = np.dot(X_centered.T, X_centered)
        eigenvalues, eigenvectors = np.linalg.eigh(C)
        idx = np.argsort(eigenvalues)[::-1]
        components = eigenvectors[:, idx[:64]] # shape (1024, 64)

        np.savez(
            pca_path,
            components=components,
            mean=mean,
            date=datetime.now().strftime("%Y-%m-%d"),
            sample_size=len(vecs)
        )

        _PCA_DATA = {
            "components": components,
            "mean": mean,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "sample_size": len(vecs)
        }
        return _PCA_DATA
    except Exception:
        return None

def manifold_error(vec) -> float | None:
    pca = _load_or_compute_pca()
    if pca is None:
        return None
    import numpy as np
    v = np.asarray(vec, dtype=np.float32)
    x = v - pca["mean"]
    y = np.dot(x, pca["components"])
    x_rec = np.dot(y, pca["components"].T)
    err = np.linalg.norm(x - x_rec)
    return float(err)


def coverage_dense(query: str) -> dict:
    """Couverture SEMANTIQUE reelle : dense (Qdrant) + BM25, rerank cross-encoder.

    Rend gap = True (gap CERTAIN, rerank < floor) / False (couvert, > ceil) / None
    (INDETERMINE, zone grise -> on s'abstient, jamais de veille auto sur un doute).
    Fail-safe : un service muet -> gap=None (abstention), PAS gap=True : pour l'auto
    on ne declenche pas une veille sur une panne technique passagere.
    """
    import json as _j
    import sqlite3 as _sq
    import urllib.request as _u

    def _post(url, payload, timeout=20):
        req = _u.Request(url, data=_j.dumps(payload).encode(),
                         headers={"Content-Type": "application/json"}, method="POST")
        with _u.urlopen(req, timeout=timeout) as r:
            return _j.loads(r.read())

    try:
        qv = _post("http://127.0.0.1:8099/v1/embeddings", {"input": [query]})["data"][0]["embedding"]
        hits = _post("http://127.0.0.1:6333/collections/nokido_sovereign_rag/points/search",
                     {"vector": {"name": "dense", "vector": qv}, "limit": 30, "with_payload": True}, 15)["result"]
        dense_ids = [h["payload"].get("chunk_id") for h in hits]
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"dense KO: {e!r}", "gap": None, "score": None, "off_manifold": None,
                "manifold_err": None, "dependance": "dense (embedder :8099 / qdrant :6333)"}

    import re as _re
    stop = {"comment", "dans", "des", "une", "les", "que", "qui", "pour", "sur", "avec", "est", "le", "la", "du"}
    terms = [w for w in _re.findall(r"\w+", query.lower()) if len(w) > 2 and w not in stop]
    try:
        from nokido_agent.app.forge_db_path import db_path
        con = _sq.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30)
        bm_ids = []
        if terms:
            mq = " OR ".join(f'"{w}"' for w in terms[:24])
            try:
                bm_ids = [r[0] for r in con.execute(
                    "SELECT c.id FROM rag_chunks_fts JOIN rag_chunks c ON c.rowid=rag_chunks_fts.rowid "
                    "WHERE rag_chunks_fts MATCH ? LIMIT 30", (mq,)).fetchall()]
            except Exception:  # noqa: BLE001
                pass
        ids = list(dict.fromkeys(dense_ids + bm_ids))[:40]
        docs = []
        for cid in ids:
            row = con.execute("SELECT text FROM rag_chunks WHERE id=?", (cid,)).fetchone()
            docs.append((row[0] or "")[:512] if row else "")
        con.close()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"sqlite KO: {e!r}", "gap": None, "score": None, "off_manifold": None,
                "manifold_err": None, "dependance": "base RAG (sqlite)"}

    if not docs:
        manifold_err = manifold_error(qv)
        if manifold_err is not None:
            off_manifold = manifold_err > 0.76
        else:
            off_manifold = None
        gap = True
        verdict = "gap_zero_candidat"
        if off_manifold is True or off_manifold is None:
            gap = None
            verdict = "off_manifold_abstention" if off_manifold is True else "no_manifold_info_abstention"
        return {
            "ok": True,
            "gap": gap,
            "score": None,
            "n_candidates": 0,
            "verdict": verdict,
            "off_manifold": off_manifold,
            "manifold_err": manifold_err
        }

    try:
        res = _post("http://127.0.0.1:8100/v1/rerank", {"model": "x", "query": query, "documents": docs}, 25).get("results", [])
    except Exception as e:  # noqa: BLE001
        # DECLARER LE BESOIN (2026-09-25). Appele en direct par urllib, le reranker ne
        # recevait JAMAIS l'intention `rerank.wanted` que lit son rallumeur
        # (forge_llama_keeper._piliers_on_demand) : la soif s'abstenait a chaque cycle,
        # sans que le corps sache qu'un organe reclamait ce pilier. Le poseur canonique
        # passe par l'arbitre des piliers (qui peut REFUSER sous pression RAM, et le dit).
        try:
            from nokido_agent.app.forge_embed_router import declare_wanted

            posee = bool(declare_wanted("rerank.wanted", motif="soif epistemique : couverture exteroceptive"))
        except Exception:  # noqa: BLE001 - l'intention non posee se DIT dans le resultat
            posee = False
        return {"ok": False, "error": f"rerank KO: {e!r}", "gap": None, "score": None, "off_manifold": None,
                "manifold_err": None, "dependance": "reranker :8100", "intention_posee": posee}

    top = max((x.get("relevance_score", -99) for x in res), default=-99)
    if top >= _COVERAGE_OK_CEIL:
        gap, verdict = False, "couvert"
    elif top < _COVERAGE_GAP_FLOOR:
        gap, verdict = True, "gap_certain"
    else:
        gap, verdict = None, "indetermine_abstention"

    # Compute manifold error
    manifold_err = manifold_error(qv)
    if manifold_err is not None:
        off_manifold = manifold_err > 0.76
    else:
        off_manifold = None

    if off_manifold is True or off_manifold is None:
        gap = None
        verdict = "off_manifold_abstention" if off_manifold is True else "no_manifold_info_abstention"

    return {
        "ok": True,
        "gap": gap,
        "score": round(top, 3),
        "n_candidates": len(docs),
        "verdict": verdict,
        "off_manifold": off_manifold,
        "manifold_err": manifold_err
    }


def coverage_score(query: str, context: str = "") -> dict:
    """Sonde la couverture RAG d'un domaine via le pipeline preflight existant.
    Fail-safe : si le RAG est indisponible → gap=True (prudence : on suppose la lacune)."""
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose

        v = preflight_check_verbose(query, context)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": repr(e), "gap": True, "score": 0.0, "n_results": 0, "tier": None}
    results = v.get("results") or []
    n = len(results)
    top = max((float(r.get("score", 0) or 0) for r in results), default=0.0)
    return {
        "ok": True,
        "tier": v.get("tier"),
        "n_results": n,
        "score": round(top, 2),
        "gap": _is_gap(n, top),
        "sources": [r.get("source") for r in results[:5]],
    }


def feel_gap(domain: str, query: Optional[str] = None, context: str = "") -> dict:
    """ÉPROUVE le gap : sonde la couverture, et si lacune → émet le ressenti (critical_event
    'knowledge_gap' + hormone CORTISOL_EPISTEMIC à TTL) et propose un objectif de veille.
    `domain` = libellé court du domaine de travail (ex : 'codex model_providers config')."""
    q = query or domain
    cov = coverage_score(q, context)
    out = {"domain": domain, **cov, "felt": False, "veille_objective": None}
    if cov.get("gap"):
        sev = "high" if cov.get("n_results", 0) == 0 else "medium"
        try:
            from nokido_agent.app.forge_critical_events import persist

            persist("knowledge_gap", sev, {
                "domain": domain,
                "score": cov.get("score"),
                "n_results": cov.get("n_results"),
            })
        except Exception:  # noqa: BLE001
            pass
        try:
            from nokido_agent.app.forge_endocrine import release

            release(
                _HORMONE,
                0.7 if sev == "high" else 0.45,
                ttl_s=VEILLE_TTL_S,
                source="epistemic_veille",
                reason=f"couverture RAG basse: {domain}",
                meta={"domain": domain, "score": cov.get("score")},
            )
        except Exception:  # noqa: BLE001
            pass
        out["felt"] = True
        out["veille_objective"] = (
            f"Documentation et fonctionnement de: {domain}. Donne définitions précises, "
            f"schémas/config concrets et URLs des sources officielles."
        )
    return out


def veille_on_gap(objective: str, domain: str = "reference", run_now: bool = False,
                  max_rounds: int = 2, max_urls: int = 10, provider: str = "auto") -> dict:
    """Comble le gap par une veille. run_now=False (défaut) → retourne le SPEC à déporter
    (run_job) : la veille longue ne bloque jamais l'appelant. run_now=True → synchrone, réservé
    au code déjà détaché (dans un job)."""
    spec = {
        "deport": True,
        "engine": "forge_research_agent.research_agent",
        "objective": objective,
        "domain": domain,
        "provider": provider,
        "max_rounds": max_rounds,
        "max_urls": max_urls,
    }
    if not run_now:
        return spec
    try:
        from nokido_agent.app.forge_research_agent import research_agent

        res = research_agent(objective, max_rounds=max_rounds, max_urls=max_urls,
                             domain=domain, provider=provider)
        return {"deport": False, "ok": True, "result": res}
    except Exception as e:  # noqa: BLE001
        return {"deport": False, "ok": False, "error": repr(e)}


def sense_and_propose(domain: str, query: Optional[str] = None) -> dict:
    """Boucle organe complète (sans exécuter la veille longue) : éprouve le gap, et si ressenti,
    attache le spec de veille déportable. Point d'entrée pour metacognition_gate / evolution_loop."""
    felt = feel_gap(domain, query)
    if felt.get("felt") and felt.get("veille_objective"):
        felt["veille"] = veille_on_gap(felt["veille_objective"], domain="reference", run_now=False)
    return felt
