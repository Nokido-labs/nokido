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

# Homologue biologique (owner 3/11, lu par le census -> la soif en mesure la couverture au corpus de physiologie).
__FORGE_HOMOLOGUE__ = {
    "mecanisme": "comportement de maladie : cytokines et inhibition de l'exploration",
    "termes": "sickness behavior cytokines lethargy",
    "sources": ["openstax:m46058", "doi:10.1186/1742-2094-5-15"],
    "invariant": "sous cytokine ou satiete RAM, une piste est differee sans consommer budget ni refractaire",
    "nr": "tests/nr/test_soif_garde_metabolique_nr.py",
}

# Seuils (env-overridable). score = meilleur match RRF/BM25 ; proxy de profondeur de savoir.
GAP_SCORE_FLOOR = float(os.environ.get("LAFORGE_EPISTEMIC_SCORE_FLOOR", "8.0"))
GAP_MIN_RESULTS = int(os.environ.get("LAFORGE_EPISTEMIC_MIN_RESULTS", "3"))
VEILLE_TTL_S = int(os.environ.get("LAFORGE_EPISTEMIC_TTL_S", str(6 * 3600)))  # anti-spam domaine

_HORMONE = "CORTISOL_EPISTEMIC"


# Friction observee -> primitive d'ingenierie : chercher ce qui existe plutot que resoudre a l'aveugle (owner 6/11).
# Table et non LLM : stable, gratuite, sans nom interne. Une friction inconnue se compte, elle ne se devine pas.
# Termes techniques de 2-3 mots : banc du 6/11 (job_b0d3bcb4758a), `github` 0/0 en phrase de 10 mots, 41/56 ainsi, et des
# depots du sujet (qwed-verification, flaky-test). Tronquer une phrase ne vaut pas (job_c4a6c6d4225e) : c'est le terme qui compte.
_TRADUCTIONS_FRICTION = {
    "fausse_livraison": (("attestation_commit_anterieur", "attestation_contredite", "pointeur_spec_recopie"),
                         ("agent output verification", "llm hallucination detection")),
    "ci_rouge": (("ci_en_echec",), ("flaky test detection", "test failure triage")),
    "tempete_redemarrages": (("flap", "uptime_recule"), ("crash loop backoff", "process supervisor")),
    "debit_fournisseur": (("quota", "rate_limit"), ("rate limit handling", "retry after backoff")),
}
# Un choix de l'owner n'est pas une faiblesse a corriger par la veille.
_FRICTIONS_DECISION_OWNER = {"commits_non_pousses", "submodule_non_bumpe"}


def frictions_vers_requetes(evenements) -> dict:
    """Mode OMBRE : liste des requetes generales tirees des frictions. N'ouvre aucune lacune, ne lance aucune veille."""
    if not isinstance(evenements, (list, tuple)):
        return {"etat": "ILLISIBLE", "mode": "OMBRE", "requetes": [], "non_traduites": {}, "ecartees_decision_owner": 0}
    par_kind = {k: f for f, (kinds, _r) in _TRADUCTIONS_FRICTION.items() for k in kinds}
    comptes: dict = {}
    non_traduites: dict = {}
    ecartees = 0
    for ev in evenements:
        kind = str((ev or {}).get("kind") or "") if isinstance(ev, dict) else ""
        if kind in _FRICTIONS_DECISION_OWNER:
            ecartees += 1
        elif kind in par_kind:
            comptes[par_kind[kind]] = comptes.get(par_kind[kind], 0) + 1
        else:
            non_traduites[kind or "?"] = non_traduites.get(kind or "?", 0) + 1
    requetes = [{"famille": f, "n": n, "requete": _TRADUCTIONS_FRICTION[f][1][0],
                 "variantes": list(_TRADUCTIONS_FRICTION[f][1][1:])}
                for f, n in sorted(comptes.items(), key=lambda x: -x[1])]
    return {"etat": "OK", "mode": "OMBRE", "requetes": requetes, "non_traduites": non_traduites,
            "ecartees_decision_owner": ecartees}


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
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_epistemic_veille.py', 85, exc_info=True)

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
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_epistemic_veille.py', 112, exc_info=True)

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
        # 19/10 (voie longue) : la requete passe par la borne du routeur, sur le MEME embedder (:8099, espace Qdrant).
        try:
            from nokido_agent.app.forge_embed_router import _llama8099_call
        except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
            from forge_embed_router import _llama8099_call
        _vecs = _llama8099_call([query], timeout=20)
        if not _vecs:
            raise RuntimeError("embedder :8099 indisponible ou requete refusee")
        qv = _vecs[0]
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
    if v.get("tier") == "illisible":
        # 19/10 : le preflight DIT desormais la panne de ses niveaux SQLite ; avant, elle sortait `none` + 0 resultat,
        # lue ici comme une LACUNE (knowledge_gap + cortisol sur une panne technique).
        return {"ok": False, "error": "pannes: %s" % ", ".join(v.get("pannes") or []), "gap": None, "score": None,
                "n_results": None, "tier": "illisible", "verdict": "rag_indisponible",
                "dependance": "preflight RAG (forge_self_correction)", "instrument": "coverage_score"}
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
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_epistemic_veille.py', 373, exc_info=True)
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
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_epistemic_veille.py', 386, exc_info=True)
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


def ouvrir_lacune(question: str, cov: dict, motif: str = "gap_certain", critere: dict | None = None,
                  pistes: list | None = None) -> dict:
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
    if critere:
        lac["critere"] = dict(critere)  # l'instrument de remesure le relit (mesurer_selon_instrument)
    if pistes:
        lac["pistes"] = [str(p) for p in pistes if p]   # 3/11 : themes EXPLICITES (lacune externe de physiologie)
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


# INSTRUMENTS PAR NOM (27/10, decision owner). `remesurer_lacune` refuse
# tout instrument different de celui qui a OUVERT la lacune ; le demon remesurait pourtant TOUT par
# coverage_dense -> une lacune ouverte par un autre instrument ne pouvait jamais fermer.
# Instruments prives (config/sujets_prives.txt) : absents de la distribution publique.
try:
    from nokido_agent.app import forge_soif_instruments_prives as _prives
except ImportError:  # muet-ok : distribution publique, ces instruments et leur liste noire n'y ont pas d'objet
    _prives = None


# Les autres instruments vivent dans le module prive ci-dessus.


_BANCS = _Path(__file__).resolve().parent.parent / "sandbox" / "workspace" / "bancs"


def _instrument_banc_amelioration(lac: dict) -> dict:
    """BANC D'AMELIORATION (29/10) : instrument `banc_amelioration:<cible>`. Meilleur prouve du registre CHAINE de la
    cible (maillons REFERENCE/AMELIORE, mesures par le juge deterministe) vs `critere.seuil` (+ `sens`). Une lacune
    « metrique sous la cible » ne se ferme que par un maillon AMELIORE atteignant le seuil, ou par une impossibilite
    MESUREE : `critere.n_impossible` essais consecutifs sans gain, dits (score IMPOSSIBLE_MESURE)."""
    # 2/11 : le NOM COMPLET (famille:cible) -- « banc_amelioration » seul faisait refuser toute remesure (instrument
    # different de celui de la lacune) : une lacune de banc n'aurait jamais pu se fermer.
    nom = str(lac.get("instrument") or "banc_amelioration")
    cible = str(lac.get("instrument", "")).split(":", 1)[1]
    crit = lac.get("critere") or {}
    seuil, sens = float(crit["seuil"]), crit.get("sens", "max")
    reg = _BANCS / cible / "registre.jsonl"
    if not reg.is_file():
        return {"ok": False, "instrument": nom, "error": "registre de la cible %r absent" % cible}
    lignes = [_json.loads(l) for l in reg.read_text(encoding="utf-8").splitlines() if l.strip()]
    best, preuve = None, None
    for d in lignes:
        m = d.get("metrique")
        if d.get("statut") in ("REFERENCE", "AMELIORE") and isinstance(m, (int, float)):
            if best is None or (m > best if sens == "max" else m < best):
                best, preuve = m, d.get("empreinte")
    if best is None:
        return {"ok": False, "instrument": nom, "error": "aucune mesure au registre de %r" % cible}
    atteint = best >= seuil if sens == "max" else best <= seuil
    if atteint:
        return {"ok": True, "instrument": nom, "score": best, "gap": False, "verdict": "couvert", "preuve": preuve}
    essais = [d["statut"] for d in lignes if d.get("statut") in
              ("AMELIORE", "EGAL", "REGRESSION", "GARDE_ROUGE", "NON_APPLICABLE", "HORS_PERIMETRE")]
    sans_gain = 0
    for s in reversed(essais):
        if s == "AMELIORE":
            break
        sans_gain += 1
    n_imp = int(crit.get("n_impossible") or 0)
    if n_imp and sans_gain >= n_imp:
        return {"ok": True, "instrument": nom, "score": "IMPOSSIBLE_MESURE", "gap": False, "verdict": "couvert",
                "preuve": preuve, "essais_sans_gain": sans_gain, "meilleur": best}
    return {"ok": True, "instrument": nom, "score": best, "gap": True, "verdict": "gap", "preuve": preuve,
            "essais_sans_gain": sans_gain}


INSTRUMENTS = {"banc_amelioration": _instrument_banc_amelioration}
if _prives is not None:
    INSTRUMENTS.update(_prives.INSTRUMENTS)


def _executer_nr(chemin: str):
    """rc de pytest sur un fichier NR du depot (0 = vert) ; None si illisible (delai, absent)."""
    import subprocess as _sp
    import sys as _sys
    if not (_RACINE / chemin).is_file():
        return None
    try:
        p = _sp.run([_sys.executable, "-m", "pytest", chemin, "-q", "-x", "--no-header", "-p", "no:cacheprovider",
                     "-o", "addopts="], cwd=str(_RACINE), capture_output=True, text=True, errors="replace", timeout=25,
                    env=dict(os.environ, PYTHONNOUSERSITE="1"))
        return p.returncode
    except Exception:  # noqa: BLE001 - delai ou lancement impossible : ILLISIBLE, jamais « vert »
        return None


def _instrument_nr(lac: dict) -> dict:
    """Instrument `nr:<tests/nr/...py>` (2/11) : la lacune d'une dette se ferme quand SON NR passe vert."""
    nom = str(lac.get("instrument"))
    chemin = nom.split(":", 1)[1]
    rc = _executer_nr(chemin)
    if rc is None:
        return {"ok": False, "instrument": nom, "error": "NR illisible (absent ou delai) : %s" % chemin}
    return {"ok": True, "instrument": nom, "score": rc, "gap": rc != 0, "verdict": "gap" if rc else "couvert"}


INSTRUMENTS["nr"] = _instrument_nr


# --- PHYSIOLOGIE (owner 3/11, debat Claude x AGY : docs/debats/SYNTHESE_DEBATS_SOIF_AUTOREGULATION_20261103.md) ----
# Le corpus de physiologie guide la conception des organes (owner 20/10). La soif mesure la couverture de chaque
# homologue DECLARE dans un module (census -> sandbox/workspace/homologues.json) ; un trou ouvre une lacune EXTERNE dont
# la piste est la veille. « Couvert » = DIVERSITE ET PROFONDEUR : mesure 3/11, 5 resumes DOI (1-2 chunks) sur les
# cytokines ne couvrent rien, et une source unique de 65 chunks non plus. Le nombre de chunks seul ne decide jamais.
import re as _re_physio  # noqa: E402 -- le module n'importe re que localement

_PHYSIO_REFERENCE = _re_physio.compile(r"openstax|pmc\.ncbi|ncbi\.nlm|pubmed|doi\.org|europepmc|biorxiv|nature\.com|"
                                       r"sciencedirect|frontiersin|springer|wiley|cell\.com", _re_physio.I)
_PHYSIO_DOCUMENT = ("github:openstax", "http://", "https://", "watch")   # le code et les resultats d'outils ne comptent pas
PHYSIO_SOURCES_MIN = 2
PHYSIO_PROFONDEUR_MIN = 5     # chunks d'une source de reference : un resume n'est pas un texte
# 3/11 (debat 1 tour 2) : arXiv est une reference pour un homologue de CONTROLE (boucle, regulateur), jamais de BIOLOGIE.
_PHYSIO_REFERENCE_CONTROLE = _re_physio.compile(r"arxiv\.org", _re_physio.I)
# Texte INTEGRAL en acces libre : mesure 3/11, la veille par theme ne ramenait que des resumes DOI (1-2 chunks).
EUROPEPMC_RECHERCHE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TEXTE_INTEGRAL_MAX = 5
PISTES_AVANT_ESCALADE = 2     # pistes lancees sans fermeture -> escalade (irresolution_proposee), pas une 3e veille


def _get_json(url: str):
    import json as _json
    import urllib.request as _ur
    req = _ur.Request(url, headers={"User-Agent": "Nokido-soif/1.0", "Accept": "application/json"})
    with _ur.urlopen(req, timeout=15) as r:
        return _json.loads(r.read().decode("utf-8", "replace"))


def urls_texte_integral(termes: str, _get=None, maximum: int = TEXTE_INTEGRAL_MAX) -> list:
    """URL PMC de textes integraux en acces libre (EuropePMC) pour ces termes. Injoignable ou illisible -> [] (la
    piste repart alors par theme) ; jamais d'exception."""
    from urllib.parse import quote
    q = "(%s) AND OPEN_ACCESS:y" % " ".join(str(termes or "").split())
    url = "%s?query=%s&format=json&pageSize=%d&resultType=lite" % (EUROPEPMC_RECHERCHE, quote(q), maximum * 2)
    try:
        res = (((_get or _get_json)(url) or {}).get("resultList") or {}).get("result") or []
    except Exception:  # noqa: BLE001 - EuropePMC injoignable (bac hors ligne, delai) : aucune URL, la piste reste
        return []
    out = []
    for r in res:
        pmc = str((r or {}).get("pmcid") or "").strip()
        if pmc.upper().startswith("PMC") and str(r.get("isOpenAccess") or "").upper() == "Y":
            u = "https://pmc.ncbi.nlm.nih.gov/articles/%s/" % pmc.upper()
            if u not in out:
                out.append(u)
    return out[:maximum]


def verdict_couverture_physio(compte: dict, nature: str | None = None) -> dict:
    """{gap, verdict, sources_distinctes, references_profondes, score} d'apres {source: nb de chunks trouves}.
    `nature` de l'homologue : `controle` admet arXiv comme reference ; `biologie` (defaut) non."""
    docs = {str(s): int(n) for s, n in (compte or {}).items() if str(s).startswith(_PHYSIO_DOCUMENT)}
    controle = str(nature or "biologie").lower() == "controle"
    profondes = [s for s, n in docs.items() if n >= PHYSIO_PROFONDEUR_MIN and (
        _PHYSIO_REFERENCE.search(s) or (controle and _PHYSIO_REFERENCE_CONTROLE.search(s)))]
    couvert = len(docs) >= PHYSIO_SOURCES_MIN and bool(profondes)
    return {"gap": not couvert, "verdict": "couvert" if couvert else "gap", "sources_distinctes": len(docs),
            "references_profondes": len(profondes), "score": len(docs)}


def _fts_de_termes(termes: str) -> str:
    mots = [m for m in _re_physio.findall(r"[A-Za-z0-9-]{3,}", termes or "")][:3]
    return " AND ".join('"%s"' % m for m in mots)


def _sources_physio(fts: str):
    """{source: nb de chunks} par FTS INDEXE (plan verifie AVANT ; jamais de balayage de rag_chunks). None = illisible."""
    import logging as _lg
    import sqlite3 as _sq
    from nokido_agent.app.forge_db_path import db_path

    sql = "SELECT source FROM rag_fts WHERE rag_fts MATCH ? LIMIT 2000"
    try:
        con = _sq.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30)
        try:
            plan = " ".join(str(r[-1]) for r in con.execute("EXPLAIN QUERY PLAN " + sql, (fts,)))
            if "VIRTUAL TABLE" not in plan:
                _lg.getLogger(__name__).warning("physiologie_fts : plan sans index (%s) -- NON execute", plan[:120])
                return None
            compte: dict = {}
            for (s,) in con.execute(sql, (fts,)):
                compte[s] = compte.get(s, 0) + 1
            return compte
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 - base illisible : mesure IMPOSSIBLE, jamais « pas couvert »
        _lg.getLogger(__name__).warning("physiologie_fts illisible : %s", type(e).__name__)
        return None


def mesurer_physiologie(termes: str, fts: str | None = None, cle: str | None = None,
                        instrument: str | None = None, nature: str | None = None) -> dict:
    """Mesure remesurable de la couverture d'un homologue. FTS illisible -> ok=False (ni gap ni couvert)."""
    nom = instrument or "physiologie_fts:" + str(cle or termes)[:60]
    compte = _sources_physio(fts or _fts_de_termes(termes))
    if compte is None:
        return {"ok": False, "instrument": nom, "error": "FTS illisible ou plan sans index"}
    return dict(verdict_couverture_physio(compte, nature=nature), ok=True, instrument=nom)


def _instrument_physiologie_fts(lac: dict) -> dict:
    crit = lac.get("critere") or {}
    return mesurer_physiologie(crit.get("termes") or lac.get("question", ""), crit.get("fts"),
                               instrument=lac.get("instrument"), nature=crit.get("nature"))


INSTRUMENTS["physiologie_fts"] = _instrument_physiologie_fts

_RE_NR_CITE = __import__("re").compile(r"tests/nr/test_\w+\.py")


def collecter_bancs(bancs: dict) -> dict:
    """Bancs d'amelioration -> lacune « depasser le meilleur prouve » (instrument banc, nom complet), pistes = axes.
    Liste blanche : un banc sans mesure au registre est DIT, jamais ouvert."""
    out = {"ouvertes": [], "deja": [], "refus": []}
    for nom, b in (bancs or {}).items():
        sens = (b.get("juge") or {}).get("sens", "max")
        inst = "banc_amelioration:%s" % nom
        sonde = _instrument_banc_amelioration({"instrument": inst, "critere": {
            "seuil": float("inf") if sens == "max" else float("-inf"), "sens": sens}})
        if not sonde.get("ok") or not isinstance(sonde.get("score"), (int, float)):
            out["refus"].append("%s : %s" % (nom, sonde.get("error") or "aucune mesure exploitable"))
            continue
        best = float(sonde["score"])
        seuil = best + max(0.01, 0.02 * abs(best)) if sens == "max" else best - max(1.0, 0.005 * abs(best))
        crit = {"seuil": round(seuil, 4), "sens": sens, "n_impossible": 10}
        cov = _instrument_banc_amelioration({"instrument": inst, "critere": crit})
        q = "Banc %s : la metrique %s peut-elle depasser son meilleur prouve %s (seuil %s, sens %s) ?" % (
            nom, (b.get("juge") or {}).get("metrique", "?"), best, crit["seuil"], sens)
        r = ouvrir_lacune(q, cov, critere=crit)
        if not r.get("ok"):
            out["refus"].append("%s : %s" % (nom, r.get("refus")))
            continue
        if r.get("deja"):
            out["deja"].append(nom)
            continue
        d = lire_lacunes()
        d[r["cle"]]["pistes"] = [a.get("description") or a.get("nom") for a in b.get("axes") or () if a]
        d[r["cle"]]["source"] = "banc_amelioration"
        _ecrire_lacunes(d)
        out["ouvertes"].append(nom)
    return out


def collecter_dettes(dettes, nr_rouge=None) -> dict:
    """Dettes ouvertes -> lacune SEULEMENT si un NR cite est MESURE ROUGE (instrument nr:, ferme au vert).
    Sans NR cite, ou NR vert/illisible : DIT dans le rapport, jamais ouvert (liste blanche)."""
    if nr_rouge is None:
        def nr_rouge(p):
            rc = _executer_nr(p)
            return None if rc is None else rc != 0
    out = {"ouvertes": [], "deja": [], "refus": []}
    for dt in dettes or ():
        cle, texte = str(dt.get("cle")), str(dt.get("texte") or "")
        cites = list(dict.fromkeys(_RE_NR_CITE.findall(texte)))
        if not cites:
            out["refus"].append({"cle": cle, "motif": "sans instrument : aucun NR cite"})
            continue
        etats = {p: nr_rouge(p) for p in cites}
        rouges = [p for p, e in etats.items() if e is True]
        if not rouges:
            out["refus"].append({"cle": cle, "motif": "NR cite(s) vert(s) ou illisible(s) : %s" % etats})
            continue
        cov = {"ok": True, "instrument": "nr:%s" % rouges[0], "score": 1, "gap": True, "verdict": "gap"}
        r = ouvrir_lacune("Dette %s : %s" % (cle, texte[:200]), cov)
        if r.get("deja"):
            out["deja"].append(cle)
        elif r.get("ok"):
            d = lire_lacunes()
            d[r["cle"]]["source"] = "dette:%s" % cle
            _ecrire_lacunes(d)
            out["ouvertes"].append(cle)
        else:
            out["refus"].append({"cle": cle, "motif": r.get("refus")})
    return out


COLLECTEUR_ETAT = _RACINE / "sandbox" / "soif_collecteur.json"
COLLECTEUR_PERIODES_S = {"bancs": 6 * 3600.0, "dettes": 24 * 3600.0}


def collecter_sources(maintenant: float, charger_bancs, charger_dettes, nr_rouge=None) -> dict:
    """Collecteur de manques (owner 2/11) : chaque source a sa periode (bancs 6 h ; dettes 24 h, ses NR coutent a
    mesurer). Etat persistant ; une source en panne est DITE, les autres passent."""
    try:
        etat = _json.loads(COLLECTEUR_ETAT.read_text(encoding="utf-8")) if COLLECTEUR_ETAT.is_file() else {}
    except (OSError, ValueError):
        etat = {}
    out = {}
    for src, periode in COLLECTEUR_PERIODES_S.items():
        dernier = etat.get(src)   # jamais collectee -> a faire (pas « collectee au temps 0 »)
        # un dernier passage DANS LE FUTUR est une trace corrompue (paye le 2/11 : 1e10 ecrit par un test) -> a refaire
        if dernier is not None and 0 <= maintenant - float(dernier) < periode:
            out[src] = "refractaire"
            continue
        try:
            out[src] = (collecter_bancs(charger_bancs()) if src == "bancs"
                        else collecter_dettes(charger_dettes(), nr_rouge=nr_rouge))
            etat[src] = maintenant
        except Exception as e:  # noqa: BLE001 - une source en panne n'arrete pas les autres, et c'est DIT
            out[src] = {"erreur": "%s: %s" % (type(e).__name__, str(e)[:160])}
    try:
        COLLECTEUR_ETAT.parent.mkdir(parents=True, exist_ok=True)
        COLLECTEUR_ETAT.write_text(_json.dumps(etat), encoding="utf-8")
    except OSError as e:   # etat non persiste : la prochaine collecte recommencera trop tot, et c'est DIT
        out["etat_non_persiste"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return out


def mesurer_selon_instrument(lac: dict) -> dict:
    """Mesure une lacune avec SON instrument ; instrument non enregistre -> coverage_dense (historique).
    Un instrument parametre s'ecrit `famille:cible` (ex. banc_amelioration:juge_ancrage_swarm)."""
    nom = lac.get("instrument")
    f = INSTRUMENTS.get(nom) or (INSTRUMENTS.get(nom.split(":", 1)[0]) if isinstance(nom, str) and ":" in nom else None)
    if f is None:
        return coverage_dense(lac.get("question", ""))
    try:
        return f(lac)
    except Exception as e:  # noqa: BLE001 -- instrument en panne : remesure IMPOSSIBLE, jamais « fermee »
        return {"ok": False, "instrument": lac.get("instrument"), "error": "%s: %s" % (type(e).__name__, e)}


# --- Pistes de METHODE sur lacune qui stagne (owner 2/11) -----------------------------------------------------------
# Constat : une lacune OUVERTE, 0 veille -- branchee « mesure seulement » le 27/10 en traduisant mal
# l'interdit owner : les SOLUTIONS PUBLIQUES du defi sont interdites, pas la litterature de methodes. La soif derive
# desormais des themes de son DIAGNOSTIC (tags mesures) et les lance par le workflow officiel ; la liste noire porte
# l'interdit exact. Stagnation = remesures_sans_effet (compteur existant), refractaire 24 h, tout est note.
_LISTE_NOIRE_SOLUTIONS = tuple(_prives.LISTE_NOIRE_SOLUTIONS) if _prives is not None else ()
THEMES_METHODES = dict(_prives.THEMES_METHODES) if _prives is not None else {}
_PISTES_GENERIQUES = dict(_prives.PISTES_GENERIQUES) if _prives is not None else {}
PISTES_SEUIL_STAGNATION = int(os.environ.get("LAFORGE_SOIF_PISTES_SEUIL", "3"))
PISTES_REFRACTAIRE_S = 86400.0
# Budget de pistes sur 24 h glissantes, toutes lacunes confondues : 19 lacunes de couverture qui stagnent ensemble ne
# doivent pas reveiller 19 veilles d'un coup (owner : reveil pilote par l'utilite, budget RAM projete).
PISTES_MAX_JOUR = int(os.environ.get("LAFORGE_SOIF_PISTES_MAX_JOUR", "4"))
# Instruments dont la piste naturelle est la QUESTION de la lacune elle-meme : une lacune de couverture dit « le RAG
# ne couvre pas ceci » ; la veille a lancer porte donc sur ce sujet (mesure 3/11 : 19 lacunes sans aucune piste).
_PISTES_PAR_QUESTION = ("coverage_dense",)
# Question INTERNE = texte de roadmap / d'artefact Nokido (mesure 3/11 : « Nokido P1 : [OUVERT 2026-10-21] ATLAS DES
# DONNEES... ») : une veille web ne peut que ramener du bruit -> pas de piste (« aucune piste », rien note).
import re as _re_q  # noqa: E402 -- le module n'importe re que localement

_QUESTION_INTERNE = _re_q.compile(
    r"^\s*Nokido\b|\[(OUVERT|PARTIEL|CLOS|MESURE|ATTEINT|OWNER|DECISION)\b|\bbb:|\b[0-9a-f]{9}\b", _re_q.I)


def theme_autorise(theme: str) -> tuple:
    """(permis ?, motif) -- interdit owner 27/10 : aucune veille sur les SOLUTIONS PUBLIQUES du defi."""
    import re as _re
    for motif in _LISTE_NOIRE_SOLUTIONS:
        if _re.search(motif, theme or "", _re.I):
            return False, "liste noire : solutions publiques du defi interdites (motif %r)" % motif
    return True, "methode permise"


def pistes_pour_lacune(lac: dict) -> list:
    """Themes de methode derives du DIAGNOSTIC mesure de la lacune (tags), sinon generiques de son instrument."""
    out = [str(p) for p in lac.get("pistes") or () if p]   # pistes explicites (ex. axes d'un banc)
    for tag in lac.get("diagnostic") or ():
        for t in THEMES_METHODES.get(tag, ()):
            if t not in out:
                out.append(t)
    # L'instrument porte ses parametres (`coverage_dense|floor=-5.0|ceil=1.0`) : chercher aussi par son NOM de base.
    base = str(lac.get("instrument") or "").split("|", 1)[0]
    if not out:
        out = list(_PISTES_GENERIQUES.get(lac.get("instrument")) or _PISTES_GENERIQUES.get(base, ()))
    if (not out and base in _PISTES_PAR_QUESTION and str(lac.get("question") or "").strip()
            and not _QUESTION_INTERNE.search(str(lac["question"]))):
        out = [" ".join(str(lac["question"]).split())[:160]]
    return out


def corps_sous_tension() -> tuple:
    """(sous_tension, raison). Arbitre de saillance de la soif (owner 3/11) : la soif lit l'etat du corps AVANT
    d'agir. UN seul predicat de satiete pour tout le corps -- celui qui retient deja les chaines de veille
    (forge_chain_executor._ram_en_satiete, seuil du superviseur) : pas de second seuil qui divergerait.
    Mesure illisible -> (False, raison) : meme repli que le predicat (fail-open), DIT dans la raison."""
    # Transe de guerison du RSI (cytokine, owner 3/11) : la soif entre en lethargie AVANT tout predicat RAM -- le corps
    # se repare, il ne chasse pas. On LIT le taux publie par l'autre organe, on ne le re-mesure pas.
    try:
        import importlib as _il

        if float(_il.import_module("nokido_agent.app.forge_endocrine").read("CYTOKINE_RSI") or 0.0) > 0.0:
            return True, "transe de guerison RSI en cours (CYTOKINE_RSI) : lethargie de la soif"
    except Exception:  # noqa: BLE001  # muet-ok : cytokine illisible -> on passe au predicat de satiete RAM ci-dessous
        pass
    try:
        from nokido_agent.app import forge_chain_executor as _ce

        if _ce._ram_en_satiete():
            return True, "RAM systeme en satiete (forge_chain_executor._ram_en_satiete)"
        return False, "RAM systeme sous le seuil de satiete"
    except Exception as e:  # noqa: BLE001 - predicat illisible : la soif n'est pas bloquee, la raison le dit
        return False, "predicat de satiete illisible (%s) : non differe" % type(e).__name__


def lancer_pistes(cle: str, creer, maintenant: float | None = None) -> dict:
    """Lance (par `creer(theme) -> chain_id`, le workflow officiel) les pistes d'une lacune ACTIVE qui STAGNE.

    Refractaire 24 h ; les themes en liste noire sont refuses et DITS ; chaque lancement est note dans l'historique
    de la lacune (lien lacune -> veilles), pour en mesurer ensuite la pertinence."""
    t = _time.time() if maintenant is None else float(maintenant)
    d = lire_lacunes()
    lac = d.get(cle)
    if not lac or lac.get("etat") not in ACTIVES:
        return {"lancees": 0, "motif": "lacune inactive ou absente"}
    if int(lac.get("remesures_sans_effet") or 0) < PISTES_SEUIL_STAGNATION:
        return {"lancees": 0, "motif": "pas de stagnation (%s remesure(s) sans effet)" % lac.get("remesures_sans_effet")}
    # Seul un lancement qui a LANCE quelque chose arme le refractaire : les 8 evenements vides du 2/11 (chaines=[])
    # bloquaient 24 h les vraies pistes (NR test_un_lancement_vide_passe_n_arme_pas_le_refractaire).
    lances = [float(h.get("t") or 0) for h in lac.get("historique") or ()
              if h.get("evenement") == "pistes_lancees" and h.get("chaines")]
    dernier = max(lances) if lances else None
    if dernier is not None and t - dernier < PISTES_REFRACTAIRE_S:
        return {"lancees": 0, "motif": "refractaire (%.0f s < %.0f s)" % (t - dernier, PISTES_REFRACTAIRE_S)}
    # 3/11 (debat 1 tour 2) : N pistes lancees et la lacune toujours ouverte -> la veille ne la fermera pas ; on
    # ESCALADE (irresolution proposee, a trancher) au lieu de relancer indefiniment une veille sterile.
    if len(lances) >= PISTES_AVANT_ESCALADE:
        if not lac.get("irresolution_proposee"):
            lac["irresolution_proposee"] = True
            _noter(lac, "escalade", t=t, motif="%d piste(s) lancee(s) sans fermeture" % len(lances))
            _ecrire_lacunes(d)
        return {"lancees": 0, "escalade": True,
                "motif": "%d piste(s) sans fermeture : irresolution proposee, plus de veille" % len(lances)}
    physio = str(lac.get("instrument") or "").startswith("physiologie_fts")
    pistes = pistes_pour_lacune(lac)
    if not pistes:
        # 3/11 : on notait `pistes_lancees` avec 0 theme -- faux signal d'action, et refractaire de 24 h arme pour rien.
        return {"lancees": 0, "motif": "aucune piste derivable (instrument %r, ni pistes ni diagnostic) : rien note, "
                                       "refractaire non arme" % lac.get("instrument")}
    deja = sum(len(h.get("chaines") or ()) for v in d.values() if isinstance(v, dict)
               for h in v.get("historique") or () if isinstance(h, dict)
               and h.get("evenement") == "pistes_lancees" and t - float(h.get("t") or 0) < 86400.0)
    if deja >= PISTES_MAX_JOUR:
        return {"lancees": 0, "motif": "budget jour atteint (%d/%d piste(s) en 24 h)" % (deja, PISTES_MAX_JOUR)}
    # 3/11 (owner, arbitre de saillance) : sous tension metabolique la piste est DIFFEREE -- ni budget du jour ni
    # refractaire consommes (la chaine aurait attendu en aval en comptant comme lancee : REQUESTED != ACHIEVED).
    # La lacune reste active : elle repart au cycle suivant. Noter une fois par episode, pas a chaque cycle.
    tendu, raison = corps_sous_tension()
    if tendu:
        hist = lac.get("historique") or []
        if not hist or not isinstance(hist[-1], dict) or hist[-1].get("evenement") != "pistes_differees":
            _noter(lac, "pistes_differees", t=t, motif="DIFFERE_METABOLIQUE", raison=raison)
            _ecrire_lacunes(d)
        return {"lancees": 0, "differe": "DIFFERE_METABOLIQUE", "motif": raison}
    permis, refusees, chaines, erreurs = [], [], [], []
    for theme in pistes[:PISTES_MAX_JOUR - deja]:
        ok, motif = theme_autorise(theme)
        if not ok:
            refusees.append({"theme": theme, "motif": motif})
            continue
        try:
            # 3/11 : une lacune physiologique cherche du TEXTE INTEGRAL (EuropePMC) ; sans URL, la piste part par theme
            chaines.append(creer(theme, urls=urls_texte_integral(theme) or None) if physio else creer(theme))
            permis.append(theme)
        except Exception as e:  # noqa: BLE001 - une piste qui ne part pas est DITE, les autres partent
            erreurs.append({"theme": theme, "erreur": "%s: %s" % (type(e).__name__, str(e)[:120])})
    _noter(lac, "pistes_lancees", t=t, themes=permis, chaines=chaines, refusees=refusees, erreurs=erreurs)
    _ecrire_lacunes(d)
    return {"lancees": len(chaines), "chaines": chaines, "refusees": refusees, "erreurs": erreurs,
            "motif": "lacune stagnante : %d piste(s) lancee(s)" % len(chaines)}


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
