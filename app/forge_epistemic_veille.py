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
    """Couverture SEMANTIQUE, QUALIFIEE : l'instrument brut, puis son aveuglement (lot B).

    Rend la mesure de `_coverage_dense_brut`, signee de l'INSTRUMENT qui l'a produite
    (`instrument`), et dont un verdict non couvert devient `aveugle_partiel` quand une part
    du corpus n'a pas de vecteur -- cf. `qualifier_aveuglement`.
    """
    return appliquer_aveuglement(_coverage_dense_brut(query))


def _coverage_dense_brut(query: str) -> dict:
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
        lex_err = None
        if terms:
            mq = " OR ".join(f'"{w}"' for w in terms[:24])
            # CLASSE PAR PERTINENCE (2026-10-01). `MATCH ? LIMIT 30` sans `ORDER BY rank` rendait
            # les 30 PREMIERS dans l'ordre physique de l'index, pas les meilleurs. Banc reel
            # (C:/tmp/corrections/banc_lexical_rank_2026-10-01.json, 9 questions : 4 intentions,
            # 4 query_log, 1 temoin) : recouvrement brut/classe = 0/30 sur LES NEUF -- le
            # reranker n'a jamais vu un seul des meilleurs candidats lexicaux, d'ou des faux gaps.
            # Sous-requete : memes 30 ids que `JOIN ... ORDER BY rank`, 0,08-3,8 s au lieu de
            # 0,09-6,9 s (le rang se calcule sur l'index seul, la jointure ne porte que sur 30).
            # Meme regle que forge_rag_engine (ORDER BY rank) : une seule verite du retrieval.
            try:
                bm_ids = [r[0] for r in con.execute(
                    "SELECT c.id FROM (SELECT rowid FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ? "
                    "ORDER BY rank LIMIT 30) f JOIN rag_chunks c ON c.rowid=f.rowid", (mq,)).fetchall()]
            except Exception as e:  # noqa: BLE001 - dit plus bas : un oeil ferme n'est pas un vide
                lex_err = f"{type(e).__name__}: {e}"[:160]
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
        if gap is True and lex_err:
            gap, verdict = None, "aveugle_lexical_abstention"
        return {
            "ok": True,
            "gap": gap,
            "score": None,
            "n_candidates": 0,
            "verdict": verdict,
            "off_manifold": off_manifold,
            "manifold_err": manifold_err,
            "lexical_err": lex_err,
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

    # AVEUGLE n'est pas GAP (2026-10-01). Branche lexicale en echec = la moitie des yeux
    # fermee : le reranker n'a juge que les candidats denses. « Rien de bon trouve » ne
    # prouve alors pas l'absence -> abstention dite, jamais un gap certain. Le cas
    # inverse (couvert malgre l'oeil ferme) reste une preuve de couverture.
    if gap is True and lex_err:
        gap, verdict = None, "aveugle_lexical_abstention"

    return {
        "ok": True,
        "gap": gap,
        "score": round(top, 3),
        "n_candidates": len(docs),
        "verdict": verdict,
        "off_manifold": off_manifold,
        "manifold_err": manifold_err,
        "lexical_err": lex_err,
    }


def coverage_score(query: str, context: str = "") -> dict:
    """Sonde la couverture RAG d'un domaine via le pipeline preflight existant.

    RAG indisponible -> gap=None (INCONNU), jamais gap=True. Jusqu'au 2026-10-01 la panne
    rendait gap=True « par prudence » : une source MUETTE devenait une LACUNE, et
    `feel_gap` emettait alors un evenement critique `knowledge_gap` et du cortisol sur une
    panne technique (UNKNOWN != NO, constitution). Releve par la revue claude.ai du 01/10
    (mission_rsi_soif), verifie dans le code avant correction."""
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose

        v = preflight_check_verbose(query, context)
    except Exception as e:  # noqa: BLE001 - la panne se DIT, elle ne se lit pas comme une lacune
        return {"ok": False, "error": repr(e), "gap": None, "score": None, "n_results": None, "tier": None,
                "verdict": "rag_indisponible", "dependance": "preflight RAG (forge_self_correction)",
                "instrument": "coverage_score"}
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


def feel_gap(domain: str, query: Optional[str] = None, context: str = "",
             cov: Optional[dict] = None) -> dict:
    """ÉPROUVE le gap : sonde la couverture, et si lacune → émet le ressenti (critical_event
    'knowledge_gap' + hormone CORTISOL_EPISTEMIC à TTL) et propose un objectif de veille.
    `domain` = libellé court du domaine de travail (ex : 'codex model_providers config').

    `cov` : mesure DEJA faite (2026-10-01). Le demon jugeait le gap avec `coverage_dense`
    puis appelait feel_gap, qui le REJUGEAIT avec un autre instrument (`coverage_score`,
    preflight) : deux verdicts pour une question, et celui qui emettait la douleur n'etait
    pas celui qui avait mesure. Quand `cov` est fourni, UN seul instrument juge.
    Seul `gap is True` emet : None (inconnu, abstention, panne) n'est jamais une lacune."""
    q = query or domain
    if cov is None:
        cov = coverage_score(q, context)
    out = {"domain": domain, **cov, "felt": False, "veille_objective": None}
    if cov.get("gap") is True:
        # n_results (preflight) ou n_candidates (coverage_dense) : zero candidat = high.
        n = cov.get("n_results", cov.get("n_candidates"))
        sev = "high" if n == 0 else "medium"
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


# ══ LOT B (2026-10-02) : aveuglement, cycle de vie des lacunes, etalonnage gele ══════════
# Note soif du 01/10, §2-§3. Trois questions que le lot A laissait ouvertes :
#   1. l'instrument VOYAIT-il ce qu'il cherchait ? (sinon : ni gap, ni couvert)
#   2. une lacune ouverte se FERME-t-elle un jour, et sur quelle preuve ?
#   3. sur quel jeu FIXE juge-t-on l'instrument lui-meme ?
# Aucune ecriture dans rag_chunks ni rag_fts : l'etat vit sous sandbox/.

import json as _json
import time as _time
from pathlib import Path as _Path

_RACINE = _Path(__file__).resolve().parent.parent

# L'IDENTITE de l'instrument porte ses seuils : remesurer avec un plancher deplace, c'est
# fermer une lacune en bougeant le but. Deux mesures ne sont comparables que si elle est egale.
INSTRUMENT_DENSE = "coverage_dense|floor=%s|ceil=%s" % (_COVERAGE_GAP_FLOOR, _COVERAGE_OK_CEIL)

# Part du corpus sans vecteur au-dela de laquelle la mesure dense est PARTIELLE. Pas zero :
# un corps vivant a toujours quelques chunks frais en attente. Toujours DITE, quel que soit le seuil.
SEUIL_AVEUGLE = float(os.environ.get("LAFORGE_SOIF_SEUIL_AVEUGLE", "0.01"))
# Verdicts que l'aveuglement peut invalider. `couvert` n'en est pas : un document trouve au-dessus
# du plafond PROUVE la couverture, et des vecteurs manquants ne peuvent que cacher d'AUTRES documents.
# `off_manifold_abstention` non plus : il parle de la QUESTION (hors domaine), pas de l'instrument.
_VERDICTS_SENSIBLES = ("gap_certain", "gap_zero_candidat", "indetermine_abstention")


def qualifier_aveuglement(snap: Optional[dict] = None) -> dict:
    """L'instrument dense voit-il le corpus ? VOIT · AVEUGLE_PARTIEL · INCONNU, fraction DITE.

    Lit `forge_memory_availability.snapshot()` (ne calcule jamais). Snapshot perime, absent ou
    sans total -> INCONNU : on ne sait pas ce que l'instrument ne voit pas, donc on ne conclut
    pas a une lacune.
    """
    if snap is None:
        try:
            from nokido_agent.app.forge_memory_availability import snapshot
            snap = snapshot()
        except Exception as e:  # noqa: BLE001 - instrument de l'instrument illisible : INCONNU, dit
            return {"etat": "INCONNU", "fraction": None,
                    "raison": "snapshot illisible (%s)" % type(e).__name__}
    pending, total = snap.get("vector_pending"), snap.get("total")
    if not snap.get("frais") or pending is None or not total:
        return {"etat": "INCONNU", "fraction": None,
                "raison": snap.get("raison") or "snapshot sans vector_pending ni total"}
    fraction = round(float(pending) / float(total), 4)
    etat = "AVEUGLE_PARTIEL" if fraction > SEUIL_AVEUGLE else "VOIT"
    return {"etat": etat, "fraction": fraction, "vector_pending": pending, "total": total,
            "seuil": SEUIL_AVEUGLE, "raison": ""}


def appliquer_aveuglement(cov: dict, aveug: Optional[dict] = None) -> dict:
    """Signe la mesure de son instrument et la DECLASSE si l'instrument ne voyait pas.

    Un verdict sensible (gap, zone grise) mesure par un instrument partiellement aveugle devient
    `aveugle_partiel` (ou `aveuglement_inconnu_abstention`) : gap=None, ni lacune ni couverture,
    avec la fraction sans vecteur. Le verdict d'origine est garde dans `verdict_instrument`.
    """
    cov = dict(cov)
    cov.setdefault("instrument", INSTRUMENT_DENSE)
    if not cov.get("ok") or cov.get("verdict") not in _VERDICTS_SENSIBLES:
        return cov
    a = aveug if aveug is not None else qualifier_aveuglement()
    cov["aveuglement"] = a
    cov["fraction_sans_vecteur"] = a.get("fraction")
    if a.get("etat") == "VOIT":
        return cov
    cov["verdict_instrument"] = cov.get("verdict")
    cov["gap"] = None
    cov["verdict"] = ("aveugle_partiel" if a.get("etat") == "AVEUGLE_PARTIEL"
                      else "aveuglement_inconnu_abstention")
    return cov


# ── Cycle de vie d'une LACUNE ──────────────────────────────────────────────────────────
# OUVERTE -> EN_ENQUETE -> FERMEE_PAR_REMESURE | IRRESOLUE
#   * on ne FERME que par une REMESURE du MEME instrument qui rend `couvert` ;
#   * IRRESOLUE est une decision OWNER (`declarer_irresolue(..., par=OWNER)`), JAMAIS
#     automatique : le daemon peut seulement la PROPOSER apres N remesures sans effet ;
#   * une lacune fermee qui revient est ROUVERTE, son historique garde (rien n'est supprime).
LACUNES = _RACINE / "sandbox" / "soif_lacunes.json"
OUVERTE, EN_ENQUETE = "OUVERTE", "EN_ENQUETE"
FERMEE_PAR_REMESURE, IRRESOLUE = "FERMEE_PAR_REMESURE", "IRRESOLUE"
ACTIVES = (OUVERTE, EN_ENQUETE)
# Verdicts qui ne disent RIEN de la question : l'instrument ne voyait pas. Ni ouverture, ni
# fermeture, ni « remesure sans effet ».
AVEUGLES = ("aveugle_partiel", "aveuglement_inconnu_abstention")
OWNER = "OWNER"
REMESURES_AVANT_PROPOSITION = int(os.environ.get("LAFORGE_SOIF_REMESURES_PROPOSITION", "3"))
_HISTORIQUE_MAX = 20


def cle_lacune(question: str) -> str:
    """Cle stable d'une question (espaces et casse normalises)."""
    return hashlib.sha256(" ".join((question or "").lower().split())[:200].encode()).hexdigest()[:16]


def lire_lacunes() -> dict:
    """Registre des lacunes. Absent = {} ; ILLISIBLE leve : reecrire par-dessus effacerait
    des lacunes ouvertes qu'on n'a pas su lire."""
    try:
        d = _json.loads(LACUNES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(d, dict):
        raise ValueError("registre des lacunes non conforme")
    return d


def _ecrire_lacunes(d: dict) -> None:
    LACUNES.parent.mkdir(parents=True, exist_ok=True)
    tmp = LACUNES.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(d, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(tmp, LACUNES)


def _noter(lac: dict, evenement: str, **detail) -> None:
    h = lac.setdefault("historique", [])
    h.append(dict(detail, evenement=evenement, ts=_time.strftime("%Y-%m-%dT%H:%M:%S")))
    del h[:-_HISTORIQUE_MAX]


def ouvrir_lacune(question: str, cov: dict, motif: str = "gap_certain") -> dict:
    """Ouvre (ou rouvre) la lacune d'un manque MESURE.

    `motif="gap_certain"` exige `gap is True`. `motif="rang_intention"` (le moins couvert de
    ce que le corps VISE, decide par rang) accepte la zone grise -- mais jamais `couvert`, et
    jamais une mesure AVEUGLE : on n'ouvre pas de lacune sur ce qu'on n'a pas pu voir."""
    if not cov.get("ok"):
        return {"ok": False, "refus": "mesure impossible (%s) : rien a ouvrir" % cov.get("error")}
    if cov.get("verdict") in AVEUGLES:
        return {"ok": False, "refus": "instrument aveugle (%s, fraction sans vecteur %s) : ni "
                "gap ni couvert" % (cov.get("verdict"), cov.get("fraction_sans_vecteur"))}
    if cov.get("gap") is False:
        return {"ok": False, "refus": "couvert : rien a ouvrir"}
    if motif == "gap_certain" and cov.get("gap") is not True:
        return {"ok": False, "refus": "pas un gap mesure (verdict %r) : rien a ouvrir"
                % cov.get("verdict")}
    if motif not in ("gap_certain", "rang_intention"):
        return {"ok": False, "refus": "motif d'ouverture hors liste blanche : %r" % motif}
    if not cov.get("instrument"):
        return {"ok": False, "refus": "mesure sans instrument : elle ne pourra jamais etre "
                                      "remesuree par le meme, donc jamais fermee"}
    d = lire_lacunes()
    k = cle_lacune(question)
    lac = d.get(k)
    if lac and lac.get("etat") in ACTIVES:
        return {"ok": True, "cle": k, "etat": lac["etat"], "deja": True}
    lac = lac or {"question": question[:300]}
    lac.update(etat=OUVERTE, instrument=cov["instrument"], score_ouverture=cov.get("score"),
               verdict_ouverture=cov.get("verdict"), motif_ouverture=motif, remesures_sans_effet=0,
               irresolution_proposee=False)
    _noter(lac, "ouverte", score=cov.get("score"), verdict=cov.get("verdict"))
    d[k] = lac
    _ecrire_lacunes(d)
    return {"ok": True, "cle": k, "etat": OUVERTE}


def debuter_enquete(cle: str, traitement: str) -> dict:
    """OUVERTE -> EN_ENQUETE quand un traitement est REELLEMENT lance (veille, enquete)."""
    d = lire_lacunes()
    lac = d.get(cle)
    if not lac or lac.get("etat") not in ACTIVES:
        return {"ok": False, "refus": "aucune lacune active sous %s" % cle}
    lac["etat"] = EN_ENQUETE
    lac["traitement"] = traitement
    _noter(lac, "enquete", traitement=traitement)
    _ecrire_lacunes(d)
    return {"ok": True, "cle": cle, "etat": EN_ENQUETE}


def remesurer_lacune(cle: str, cov: dict) -> dict:
    """La SEULE porte de fermeture : une remesure du MEME instrument qui rend `couvert`.

    Instrument different -> refus (la mesure est notee, rien ne change). Gap, zone grise ou
    aveugle -> la lacune reste active, et apres N remesures sans effet l'irresolution est
    PROPOSEE a l'owner -- jamais prononcee ici.
    """
    d = lire_lacunes()
    lac = d.get(cle)
    if not lac or lac.get("etat") not in ACTIVES:
        return {"ok": False, "refus": "aucune lacune active sous %s" % cle}
    if not cov.get("ok"):
        # Un pilier muet n'a rien remesure : ni fermeture, ni « sans effet ».
        _noter(lac, "remesure_impossible", dependance=cov.get("dependance"))
        _ecrire_lacunes(d)
        return {"ok": False, "etat": lac["etat"], "refus": "remesure impossible : %s"
                % (cov.get("dependance") or cov.get("error"))}
    if cov.get("instrument") != lac.get("instrument"):
        _noter(lac, "remesure_refusee", instrument=cov.get("instrument"))
        _ecrire_lacunes(d)
        return {"ok": False, "etat": lac["etat"],
                "refus": "instrument different (%r != %r) : une fermeture se prouve par le "
                         "MEME instrument" % (cov.get("instrument"), lac.get("instrument"))}
    if cov.get("gap") is False:
        lac["etat"] = FERMEE_PAR_REMESURE
        lac["score_fermeture"] = cov.get("score")
        _noter(lac, "fermee", score=cov.get("score"), verdict=cov.get("verdict"))
        _ecrire_lacunes(d)
        return {"ok": True, "cle": cle, "etat": FERMEE_PAR_REMESURE,
                "avant": lac.get("score_ouverture"), "apres": cov.get("score")}
    if cov.get("verdict") in AVEUGLES:
        _noter(lac, "remesure_aveugle", fraction=cov.get("fraction_sans_vecteur"))
        _ecrire_lacunes(d)
        return {"ok": True, "cle": cle, "etat": lac["etat"], "aveugle": True,
                "irresolution_proposee": bool(lac.get("irresolution_proposee"))}
    lac["remesures_sans_effet"] = int(lac.get("remesures_sans_effet") or 0) + 1
    if lac["remesures_sans_effet"] >= REMESURES_AVANT_PROPOSITION:
        lac["irresolution_proposee"] = True
    _noter(lac, "remesure", score=cov.get("score"), verdict=cov.get("verdict"))
    _ecrire_lacunes(d)
    return {"ok": True, "cle": cle, "etat": lac["etat"],
            "irresolution_proposee": lac["irresolution_proposee"]}


def declarer_irresolue(cle: str, par: str, motif: str) -> dict:
    """IRRESOLUE : decision OWNER, motivee. Tout autre declarant est refuse."""
    if par != OWNER:
        return {"ok": False, "refus": "IRRESOLUE se decide par l'owner, pas par %r" % par}
    if not (motif or "").strip():
        return {"ok": False, "refus": "une irresolution se motive"}
    d = lire_lacunes()
    lac = d.get(cle)
    if not lac or lac.get("etat") not in ACTIVES:
        return {"ok": False, "refus": "aucune lacune active sous %s" % cle}
    lac["etat"] = IRRESOLUE
    lac["motif_irresolution"] = motif[:300]
    _noter(lac, "irresolue", par=par, motif=motif[:300])
    _ecrire_lacunes(d)
    return {"ok": True, "cle": cle, "etat": IRRESOLUE}


# ── Etalonnage GELE et HACHE ───────────────────────────────────────────────────────────
# Modele : tests/baselines/retrieval_heldout_v1.json (alpha, a298f7583). L'empreinte porte sur
# le texte normalise LF : un meme jeu ouvert sous Windows (CRLF) reste le meme jeu ; une seule
# question changee le rend AUTRE, et il est refuse. Toute evolution = un NOUVEAU fichier (v2).
ETALONNAGE = _RACINE / "tests" / "baselines" / "soif_etalonnage_v1.json"
ETALONNAGE_SHA256 = "2eaff7123de72ae104b16b9a0bac47b6c1dbed67a94343b59e851dbfd12063c1"


def empreinte_lf(chemin) -> str:
    """sha256 du texte normalise LF (CRLF et CR -> LF)."""
    t = _Path(chemin).read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def charger_etalonnage(chemin=None, sha_attendu: Optional[str] = None) -> dict:
    """Le jeu d'etalonnage, SEULEMENT s'il est intact. Altere, absent ou illisible -> refus."""
    chemin = _Path(chemin) if chemin is not None else ETALONNAGE
    attendu = sha_attendu or ETALONNAGE_SHA256
    try:
        sha = empreinte_lf(chemin)
    except OSError as e:
        return {"ok": False, "verdict": "ETALONNAGE_ABSENT", "raison": "%s" % e}
    if sha != attendu:
        return {"ok": False, "verdict": "ETALONNAGE_ALTERE", "sha": sha, "attendu": attendu,
                "raison": "le jeu gele a change : une evolution se fait par un NOUVEAU fichier"}
    try:
        jeu = _json.loads(_Path(chemin).read_text(encoding="utf-8"))
    except ValueError as e:
        return {"ok": False, "verdict": "ETALONNAGE_ILLISIBLE", "raison": str(e)[:160]}
    return {"ok": True, "sha": sha, "jeu": jeu}


def etalonner(instrument=None, chemin=None, sha_attendu: Optional[str] = None) -> dict:
    """Passe le jeu GELE a l'instrument : taux de FAUX GAPS sur ce qu'on sait couvert ou hors sujet.

    Aucune question de ce jeu ne doit rendre `gap=True` : les unes sont du vocabulaire REEL de
    Nokido (le corpus les couvre), les autres hors sujet (l'instrument doit s'abstenir). Chaque
    gap rendu ici est donc un faux gap, et leur taux est la cecite MESUREE de l'instrument.
    """
    ch = charger_etalonnage(chemin, sha_attendu)
    if not ch["ok"]:
        return ch
    mesure = instrument or coverage_dense
    par_attendu: dict = {}
    faux_gaps, mesurees, illisibles = [], 0, 0
    for it in ch["jeu"].get("questions") or []:
        cov = mesure(it["q"])
        if not cov.get("ok"):
            illisibles += 1
            continue
        mesurees += 1
        v = cov.get("verdict")
        par_attendu.setdefault(it["attendu"], {}).setdefault(v, 0)
        par_attendu[it["attendu"]][v] += 1
        if cov.get("gap") is True:
            faux_gaps.append(it["id"])
    return {"ok": True, "sha": ch["sha"], "mesurees": mesurees, "illisibles": illisibles,
            "faux_gaps": faux_gaps,
            "taux_faux_gap": round(len(faux_gaps) / mesurees, 4) if mesurees else None,
            "par_attendu": par_attendu}
