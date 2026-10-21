"""Consolidation epistemique : extraction d'assertions, reevaluation, supersession, porte.

HISTORIQUE. Ecrit comme « Step 2 » d'une couche epistemique (extraction via Cerebras),
ce module n'a JAMAIS eu d'appelant. Mesure 2026-08-26 : `chunk_claims` = 0 ligne,
`claim_reevaluations` = 0 ligne, six modules lisent ces tables vides. C'etait la
troisieme occurrence du meme motif ce jour-la — l'organe existe, personne ne l'alimente.

CE QUI CHANGE (2026-08-26) :
  * le LLM est LOCAL par defaut (ollama, modele `LAFORGE_EPISTEMIC_MODEL`). Cerebras
    reste disponible en opt-in (`backend="cerebras"`). Regle owner : pas de cloud pour
    un travail deportable ;
  * le module devient l'EMETTEUR de deux primitives qui dormaient depuis leur ecriture :
      - `reevaluer()` juge chaque assertion neuve contre les assertions anterieures
        qui partagent ses predicats, ecrit `claim_reevaluations`, et appelle
        `forge_rag_truth.superseder()` sur une contradiction REELLE — autorite
        respectee : un brouillon ne ferme jamais un fait verifie ;
      - la meme reevaluation est la PORTE de promotion : un brouillon corrobore par une
        source independante deja verifiee passe par
        `forge_memory_archival.promouvoir_brouillon()`, ou le triple check tranche ;
  * `consolider()` enchaine les deux et rend UN compte-rendu a trois etats : ce qui a
    ete extrait, ce qui n'a rien donne, ce que le LLM n'a PAS PU lire (muet / JSON
    casse). Un LLM muet compte comme muet, jamais comme « aucune assertion » — et un
    chunk marque `muet` est re-soumis apres RETRY_MUET_H, pas exclu a vie.

Cadence : `forge_autonomous_loops.pat_epistemic_consolidation` (toutes les heures,
LLM local requis, garde RAM). Sans cadence, ce module retourne dormir.

Usage :
    LAFORGE_PYTHON tools/forge_epistemic_extract_claims.py --limit 20             # extraire
    LAFORGE_PYTHON tools/forge_epistemic_extract_claims.py --consolider --limit 20
    LAFORGE_PYTHON tools/forge_epistemic_extract_claims.py --dry-run
    LAFORGE_PYTHON tools/forge_epistemic_extract_claims.py --backend cerebras --limit 50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

__FORGE_COLOR__ = "cognition/memoire-epistemique"  # hippocampe : consolidation des assertions

logger = logging.getLogger("epistemic_extract")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------- backends LLM
CEREBRAS_MODEL = "gpt-oss-120b"
CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
OLLAMA_URL = os.environ.get("LAFORGE_OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
# MESURE 2026-08-26 : sur cette machine (box CPU), gemma4:e4b-it-q4_K_M PUIS
# qwen2.5:latest (7B q4) ont chacun laisse un runner llama-server de 4,8 a 9,7 Go qui ne
# FINIT JAMAIS de charger (/api/ps vide a 6 min, timeouts 55-180 s, unload sans effet,
# kill owner necessaire) — regle du 2026-06-30 confirmee : <= 4B ici. Seul
# qwen2.5-coder:1.5b a repondu (JSON strict OK, 4 s). Qualite d'extraction moindre,
# comptee a trois etats ; surchargeable par LAFORGE_EPISTEMIC_MODEL sur une machine
# qui porte un 7B.
MODELE_LOCAL = os.environ.get("LAFORGE_EPISTEMIC_MODEL", "qwen2.5-coder:1.5b")
TIMEOUT_LOCAL_S = int(os.environ.get("LAFORGE_EPISTEMIC_TIMEOUT_S", "120"))

# ------------------------------------------------------------ perimetre, seuils
DOMAINES = ("watch_veille", "laforge-memory", "conv_archive")
FENETRE_J = float(os.environ.get("LAFORGE_EPISTEMIC_FENETRE_J", "30"))
SEUIL_PREDICATS = 0.34  # Jaccard minimal sur les predicats pour juger une paire
SEUIL_CONTRADICTION = 0.75  # confiance du juge pour FERMER une assertion
SEUIL_CORROBORATION = 0.70  # confiance du juge pour ouvrir la porte de promotion
MAX_CANDIDATS = 5
RETRY_MUET_H = 24.0
RELATIONS = {"supports", "contradicts", "supersedes", "qualifies", "extends", "unrelated"}

PROMPT_TEMPLATE = """Extract atomic technical claims from the text below.
A claim = 1 factual assertion testable empirically (NOT opinion/recommendation).
For each claim, list 2-5 predicate keywords (lowercase, single words or short bigrams).

Examples:
  Text: "LSB steganography in JPEG is undetectable by SVM."
  -> {{"claims":[{{"text":"LSB steganography in JPEG is undetectable by SVM","predicates":["lsb","steganography","jpeg","undetectable","svm"],"confidence":0.9,"is_technical":1}}]}}

Text to analyze:
\"\"\"{text}\"\"\"

Output STRICT JSON only (no markdown, no explanation):
{{"claims":[{{"text":"...","predicates":["..."],"confidence":0.0-1.0,"is_technical":0|1}}]}}
Max 3 claims per text. If text is opinion/normative, set is_technical=0."""

PROMPT_JUGE = """Compare two technical claims extracted from two different documents.
OLDER claim: \"\"\"{ancienne}\"\"\"
NEWER claim: \"\"\"{nouvelle}\"\"\"

Relation (pick exactly ONE):
  supports    = same fact, the newer one confirms the older one
  contradicts = both cannot be true at the same time
  supersedes  = the newer one replaces the older one (updated value, version, status)
  qualifies   = the newer one restricts or nuances the older one
  extends     = the newer one adds to the older one without conflict
  unrelated   = different facts

Output STRICT JSON only (no markdown):
{{"relation":"supports|contradicts|supersedes|qualifies|extends|unrelated","confidence":0.0-1.0,"rationale":"<= 25 words"}}"""


# ---------------------------------------------------------------- appels LLM
MODELE_LOCAL_7B = "qwen2.5:latest"


def _appel_local_7b(prompt: str, timeout: int = TIMEOUT_LOCAL_S) -> str:
    """Second avis LOCAL plus grand (7B instruct) : cerebras muet 10/10 le 18/10, le local par defaut est le 1,5B
    degenere (42/42 supersedes). Meme contrat que `_appel_local` ('' = muet)."""
    return _appel_local(prompt, timeout=timeout, modele=MODELE_LOCAL_7B)


def _appel_local(prompt: str, timeout: int = TIMEOUT_LOCAL_S, modele: str = "") -> str:
    """Rend le texte du modele local, ou '' quand il ne repond pas.

    L'appelant distingue '' (muet) d'un JSON sans assertion : ce n'est pas la meme
    information, et les confondre fabrique des « aucune assertion » par centaines
    le jour ou le backend est couche.
    """
    body = json.dumps(
        {
            "model": modele or MODELE_LOCAL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"num_predict": 500, "temperature": 0},
            "keep_alive": "5m",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")).get("response", "") or ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        logger.warning("LLM local muet (%s: %s)", type(e).__name__, str(e)[:80])
        return ""


def _appel_cerebras(prompt: str, timeout: int = 25) -> str:
    """Backend cloud, OPT-IN seulement. Cle lue au coffre, jamais en ligne de commande."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        key = get_secret("CEREBRAS_API_KEY")
    except Exception as e:  # noqa: BLE001 — coffre indisponible : on le dit
        logger.error("coffre indisponible (%s)", type(e).__name__)
        return ""
    if not key:
        logger.error("CEREBRAS_API_KEY absent (coffre DPAPI)")
        return ""
    body = json.dumps(
        {
            "model": CEREBRAS_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
    ).encode()
    req = urllib.request.Request(
        CEREBRAS_URL,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"] or ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as e:
        logger.warning("cerebras muet (%s: %s)", type(e).__name__, str(e)[:80])
        return ""


def _parser_claims(raw: str) -> Optional[list]:
    """None = illisible (muet ou JSON casse) ; [] = lu, aucune assertion."""
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    claims = parsed.get("claims", []) if isinstance(parsed, dict) else []
    if not isinstance(claims, list):
        return None
    out = []
    for c in claims[:3]:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or "").strip()
        if len(text) < 10:
            continue
        preds = c.get("predicates", [])
        if not isinstance(preds, list):
            continue
        try:
            conf = float(c.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        technique = 0 if str(c.get("is_technical", 1)).strip().lower() in ("0", "false") else 1
        out.append(
            {
                "text": text,
                "predicates": [str(p).lower().strip() for p in preds if p][:5],
                "confidence": max(0.0, min(1.0, conf)),
                "is_technical": technique,
            }
        )
    return out


def _parser_verdict(raw: str) -> Optional[dict]:
    """None = juge muet ou verdict hors vocabulaire ; sinon {relation, confidence, rationale}."""
    if not raw or not raw.strip():
        return None
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    rel = str(d.get("relation") or "").strip().lower()
    if rel not in RELATIONS:
        return None
    try:
        conf = float(d.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "relation": rel,
        "confidence": max(0.0, min(1.0, conf)),
        "rationale": str(d.get("rationale") or "")[:200],
    }


def nom_backend(backend: str = "local") -> str:
    if backend == "routeur":
        return "routeur_debate"
    return f"cerebras_{CEREBRAS_MODEL}" if backend == "cerebras" else f"ollama_{MODELE_LOCAL}"


def _appel_routeur(prompt: str) -> str:
    """Juge FORT par le routeur, use_case debate (decision owner 16/10 : modele fort pour les paires d'assertions ;
    le routeur porte SemanticFirewall). Routeur injoignable ou KO -> "" (juge muet), jamais un verdict invente."""
    try:
        from nokido_agent.app.forge_llm_router import router_call
        from nokido_agent.app.forge_share_policy import contexte_legacy

        out = router_call(prompt, use_case="debate", max_tokens=500,
                          context=contexte_legacy(provenance="forge_epistemic_extract_claims.juge_routeur"))
    except Exception as e:  # noqa: BLE001 -- routeur indisponible : on le dit, le juge est muet
        logger.warning("routeur injoignable (%s)", type(e).__name__)
        return ""
    if not isinstance(out, dict) or out.get("ok") is False:
        logger.warning("routeur muet (%s)", str(out.get("error") if isinstance(out, dict) else out)[:80])
        return ""
    return out.get("text") or out.get("content") or ""


def extracteur_backend(backend: str = "local") -> Callable[[str], Optional[list]]:
    appel = _appel_cerebras if backend == "cerebras" else _appel_local

    def _extraire(texte: str) -> Optional[list]:
        return _parser_claims(appel(PROMPT_TEMPLATE.format(text=texte[:2000])))

    return _extraire


def juge_backend(backend: str = "local") -> Callable[[str, str], Optional[dict]]:
    # 16/10 : un backend inconnu retombait EN SILENCE sur le local -- c'est ainsi qu'un juge 1,5B degenere
    # (100 % supersedes) passait pour celui qu'on avait demande.
    appels = {"local": _appel_local, "local7b": _appel_local_7b, "cerebras": _appel_cerebras,
              "routeur": _appel_routeur}
    if backend not in appels:
        raise ValueError("backend de juge inconnu : %r (attendus : %s)" % (backend, ", ".join(sorted(appels))))
    appel = appels[backend]

    def _juger(ancienne: str, nouvelle: str) -> Optional[dict]:
        return _parser_verdict(appel(PROMPT_JUGE.format(ancienne=ancienne[:800], nouvelle=nouvelle[:800])))

    return _juger


# ------------------------------------------------------------------- base
def _ecrivain(db_path=None) -> sqlite3.Connection:
    """Ecrivain autocommit + WAL + busy_timeout. En production : `forge_db_path.open_writer`
    (le pattern prouve sans contention). Avec `db_path` : base de test."""
    if db_path:
        conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # muet-ok : base en memoire, pas de WAL -- ce n'est pas une erreur
        return conn
    from nokido_agent.app.forge_db_path import open_writer

    return open_writer()


def _preparer_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS epistemic_extraction_vue ("
        "chunk_id TEXT PRIMARY KEY, statut TEXT NOT NULL, extracteur TEXT, vu_at TEXT NOT NULL)"
    )
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_claims_chunk ON chunk_claims(chunk_id)")
    except sqlite3.OperationalError as e:
        logger.warning("chunk_claims absente ou verrouillee (%s) : l'index attendra", str(e)[:60])


def _claim_id(chunk_id: str, text: str) -> str:
    return hashlib.sha256(f"{chunk_id}|{text}".encode()).hexdigest()[:16]


def _marquer(conn: sqlite3.Connection, chunk_id: str, statut: str, nom: str, quand: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO epistemic_extraction_vue (chunk_id, statut, extracteur, vu_at) "
        "VALUES (?, ?, ?, ?)",
        (chunk_id, statut, nom, quand),
    )


def _chunks_a_traiter(conn: sqlite3.Connection, limit: int, fenetre_j: float) -> list:
    """Chunks du perimetre jamais soumis, ou soumis a un LLM muet il y a plus de
    RETRY_MUET_H. Fenetre glissante sur `ingested_at`, qui existe en texte ISO ET en
    epoch selon l'ecrivain : on accepte les deux formes, sinon une moitie du corpus
    serait ecartee en silence par une comparaison texte/nombre."""
    now = datetime.now(tz=UTC)
    depuis_dt = now - timedelta(days=fenetre_j)
    retry = (now - timedelta(hours=RETRY_MUET_H)).isoformat()
    return conn.execute(
        """
        SELECT c.id, c.text
        FROM rag_chunks c
        LEFT JOIN epistemic_extraction_vue v ON v.chunk_id = c.id
        WHERE (v.chunk_id IS NULL OR (v.statut = 'muet' AND v.vu_at < ?))
          AND (c.active IS NULL OR c.active = 1)
          AND c.domain IN (?, ?, ?)
          AND (
                (typeof(c.ingested_at) = 'text' AND c.ingested_at >= ?)
             OR (typeof(c.ingested_at) IN ('real', 'integer') AND c.ingested_at >= ?)
          )
          AND c.text IS NOT NULL AND length(c.text) > 200
        ORDER BY c.ingested_at DESC
        LIMIT ?
        """,
        (retry, *DOMAINES, depuis_dt.isoformat(), depuis_dt.timestamp(), limit),
    ).fetchall()


# --------------------------------------------------------------- extraction
def process_batch(
    limit: int = 100,
    dry_run: bool = False,
    backend: str = "local",
    extracteur: Optional[Callable[[str], Optional[list]]] = None,
    db_path=None,
    fenetre_j: float = FENETRE_J,
    nom_extracteur: Optional[str] = None,
) -> dict:
    """Extrait les assertions des chunks recents. Compte-rendu a TROIS etats :
    `avec_claims` / `sans_claim` / `muets` — et la liste des claims inseres, que
    `reevaluer` consomme."""
    extracteur = extracteur or extracteur_backend(backend)
    nom = nom_extracteur or nom_backend(backend)
    conn = _ecrivain(db_path)
    try:
        _preparer_schema(conn)
        rows = _chunks_a_traiter(conn, limit, fenetre_j)
        bilan = {
            "backend": nom,
            "candidats": len(rows),
            "traites": 0,
            "avec_claims": 0,
            "sans_claim": 0,
            "muets": 0,
            "claims_inseres": 0,
            "claim_ids": [],
            "dry_run": dry_run,
        }
        if dry_run or not rows:
            return bilan
        t0 = time.time()
        for chunk_id, text in rows:
            claims = extracteur(text)
            bilan["traites"] += 1
            quand = datetime.now(tz=UTC).isoformat()
            if claims is None:
                bilan["muets"] += 1
                _marquer(conn, chunk_id, "muet", nom, quand)
                continue
            if not claims:
                bilan["sans_claim"] += 1
                _marquer(conn, chunk_id, "aucune", nom, quand)
                continue
            bilan["avec_claims"] += 1
            for c in claims:
                cid = _claim_id(chunk_id, c["text"])
                cur = conn.execute(
                    "INSERT OR IGNORE INTO chunk_claims "
                    "(id, chunk_id, text, predicates, confidence_authored, is_technical, "
                    "extracted_by, extracted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        cid,
                        chunk_id,
                        c["text"][:1000],
                        json.dumps(c["predicates"]),
                        c["confidence"],
                        c["is_technical"],
                        nom,
                        quand,
                    ),
                )
                if cur.rowcount > 0:
                    bilan["claims_inseres"] += 1
                    bilan["claim_ids"].append(cid)
            _marquer(conn, chunk_id, "claims", nom, quand)
            if bilan["traites"] % 10 == 0:
                logger.info(
                    "  progression %d/%d, claims=%d, muets=%d",
                    bilan["traites"], len(rows), bilan["claims_inseres"], bilan["muets"],
                )
        bilan["elapsed_s"] = round(time.time() - t0, 1)
        logger.info(
            "[OK] %d chunks : %d avec claims (%d inseres), %d sans, %d muets, %.1fs",
            bilan["traites"], bilan["avec_claims"], bilan["claims_inseres"],
            bilan["sans_claim"], bilan["muets"], bilan["elapsed_s"],
        )
        return bilan
    finally:
        conn.close()


# ------------------------------------------------------------- reevaluation
def _jaccard(a, b) -> float:
    sa, sb = set(a or ()), set(b or ())
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def _autorite(chunk: dict) -> int:
    """2 = fait verifie ou source externe primaire ; 1 = brouillon / non qualifie.
    Un brouillon ne ferme jamais un fait d'autorite superieure — la contradiction est
    ENREGISTREE (claim_reevaluations) mais pas ACTEE (superseder)."""
    meta = chunk.get("meta") or {}
    if meta.get("consensus_level") in ("verified", "gold"):
        return 2
    if chunk.get("domain") == "watch_veille":
        return 2
    return 1


def _instant(chunk: dict) -> str:
    """Date d'OBSERVATION si le meta la porte (`valid_from`), sinon d'ingestion."""
    meta = chunk.get("meta") or {}
    return str(meta.get("valid_from") or chunk.get("ingested_at") or "")


def _charger_chunks(conn: sqlite3.Connection, ids: list) -> dict:
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    out = {}
    for r in conn.execute(
        f"SELECT id, domain, source, ingested_at, meta FROM rag_chunks WHERE id IN ({ph})", list(ids)
    ):
        try:
            meta = json.loads(r[4] or "{}") or {}
        except (TypeError, ValueError):
            meta = {}
        out[r[0]] = {
            "id": r[0], "domain": r[1], "source": r[2] or "",
            "ingested_at": str(r[3] or ""), "meta": meta,
        }
    return out


def _cote_brouillon(c1: dict, c2: dict):
    """(brouillon, corroborant) si exactement l'un est un draft et l'autre une source
    d'autorite INDEPENDANTE ; sinon (None, None)."""
    d1 = (c1.get("meta") or {}).get("consensus_level") == "draft"
    d2 = (c2.get("meta") or {}).get("consensus_level") == "draft"
    if d1 == d2:
        return None, None
    brouillon, corroborant = (c1, c2) if d1 else (c2, c1)
    if _autorite(corroborant) < 2 or brouillon.get("source") == corroborant.get("source"):
        return None, None
    return brouillon, corroborant


def _superseder(ancien_id: str, nouveau_id: str, a_partir_de: str, raison: str) -> dict:
    from nokido_agent.app import forge_rag_truth as verite

    return verite.superseder(ancien_id, nouveau_id, a_partir_de=a_partir_de, raison=raison)


def _promouvoir(chunk_id: str, corroborant_id: str, db_path) -> dict:
    from nokido_agent.app import forge_memory_archival as archival

    return archival.promouvoir_brouillon(chunk_id, corroborant_id, db_path=db_path)


def reevaluer(
    claim_ids,
    juge: Optional[Callable[[str, str], Optional[dict]]] = None,
    backend: str = "local",
    db_path=None,
    max_candidats: int = MAX_CANDIDATS,
    nom_juge: Optional[str] = None,
    rejugement_db=None,
    mesure_seule: bool = False,
) -> dict:
    """Juge chaque assertion neuve contre les anterieures qui partagent ses predicats.

    `mesure_seule` (decision owner 16/10, 18/10) : les verdicts sont ENREGISTRES et COMPTES
    (`fermetures_mesurees`, `promotions_mesurees`) mais AUCUNE fermeture ni promotion n'est executee --
    « mesurer les verdicts du juge qualifie AVANT toute ouverture de promouvoir_brouillon ».

    Effets, dans l'ordre, chacun compte :
      1. `claim_reevaluations` recoit toute relation autre que `unrelated` ;
      2. contradiction / remplacement au-dela de SEUIL_CONTRADICTION -> `superseder`
         (si l'autorite du nouveau >= celle de l'ancien, sinon `refusees_autorite`) ;
      3. corroboration au-dela de SEUIL_CORROBORATION entre un brouillon et une
         source verifiee independante -> `promouvoir_brouillon` (le triple check
         tranche ; un refus est compte, pas cache).

    `rejugement_db` (decision owner 17/10, option A) : base SEPAREE qui recoit les
    re-jugements d'un juge qualifie. Le controle « deja jugee » et l'INSERT lisent et
    ecrivent CETTE base quand elle est fournie : une paire deja jugee par le juge local
    peut donc etre re-jugee, une paire deja re-jugee ne l'est pas deux fois, et la
    grosse base n'est JAMAIS modifiee par ce chemin. Defaut None : comportement inchange.
    """
    juge = juge or juge_backend(backend)
    nom = nom_juge or nom_backend(backend)
    bilan = {
        "claims_evalues": 0, "paires_jugees": 0, "juge_muet": 0, "reevaluations": 0,
        "fermees": 0, "fermetures_refusees": 0, "refusees_autorite": 0, "fermetures_suspendues": 0,
        "promus": 0, "promotions_refusees": 0, "par_relation": {}, "raisons_refus": [],
        "fermetures_mesurees": 0, "promotions_mesurees": 0, "paires_meme_source": 0,
    }
    claim_ids = list(claim_ids or [])
    if not claim_ids:
        return bilan
    cles = ("id", "chunk_id", "text", "predicates")
    conn = _ecrivain(db_path)
    conn_rejug: Optional[sqlite3.Connection] = None
    if rejugement_db:
        # Base SEPAREE : ouverture + creation du fichier et de la table si besoin,
        # MEMES colonnes que la grosse base, UNIQUE(older_claim_id, newer_claim_id).
        conn_rejug = sqlite3.connect(str(rejugement_db), timeout=30, isolation_level=None)
        conn_rejug.execute("PRAGMA busy_timeout=30000")
        try:
            conn_rejug.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # muet-ok : base en memoire, pas de WAL -- ce n'est pas une erreur
        conn_rejug.execute(
            "CREATE TABLE IF NOT EXISTS claim_reevaluations ("
            "older_claim_id TEXT NOT NULL, newer_claim_id TEXT NOT NULL, "
            "reevaluation_type TEXT NOT NULL, confidence REAL, rationale TEXT, "
            "detected_by TEXT, detected_at TEXT NOT NULL, "
            "UNIQUE(older_claim_id, newer_claim_id))"
        )
    cible = conn_rejug if conn_rejug is not None else conn
    try:
        ph = ",".join("?" * len(claim_ids))
        neufs = [dict(zip(cles, r)) for r in conn.execute(
            f"SELECT id, chunk_id, text, predicates FROM chunk_claims WHERE id IN ({ph})", claim_ids)]
        anciens = [dict(zip(cles, r)) for r in conn.execute(
            "SELECT id, chunk_id, text, predicates FROM chunk_claims ORDER BY extracted_at DESC LIMIT 5000")]
        for c in neufs + anciens:
            try:
                c["preds"] = set(json.loads(c.get("predicates") or "[]"))
            except (TypeError, ValueError):
                c["preds"] = set()
        chunks = _charger_chunks(conn, sorted({c["chunk_id"] for c in neufs + anciens}))
        # Une paire se presente deux fois quand ses deux assertions sont neuves (chacune
        # trouve l'autre en candidate). La table ne dedoublonne que ce qui a ete ECRIT :
        # un juge muet ou un verdict `unrelated` n'ecrit rien, donc sans ce jeu de
        # paires vues, la meme question lui serait posee deux fois par passage.
        vus: set = set()

        for n in neufs:
            bilan["claims_evalues"] += 1
            scores = sorted(
                ((_jaccard(n["preds"], a["preds"]), a) for a in anciens
                 if a["chunk_id"] != n["chunk_id"] and a["id"] != n["id"]),
                key=lambda t: -t[0],
            )
            cands = [a for s, a in scores if s >= SEUIL_PREDICATS][:max_candidats]
            for a in cands:
                cn, ca = chunks.get(n["chunk_id"]), chunks.get(a["chunk_id"])
                if not cn or not ca:
                    continue
                if cn["source"] and cn["source"] == ca["source"]:
                    # 18/10 : une copie de la meme source n'est pas un temoin (61/61 supports mesures etaient
                    # des re-ingestions). Source vide = inconnue, jamais « la meme ».
                    bilan["paires_meme_source"] += 1
                    continue
                if _instant(cn) >= _instant(ca):
                    ancien, nouveau, c_anc, c_nou = a, n, ca, cn
                else:
                    ancien, nouveau, c_anc, c_nou = n, a, cn, ca
                paire = (ancien["id"], nouveau["id"])
                if paire in vus:
                    continue
                vus.add(paire)
                deja = cible.execute(
                    "SELECT 1 FROM claim_reevaluations WHERE older_claim_id = ? AND newer_claim_id = ?",
                    (ancien["id"], nouveau["id"]),
                ).fetchone()
                if deja:
                    continue
                verdict = juge(ancien["text"], nouveau["text"])
                bilan["paires_jugees"] += 1
                if verdict is None:
                    bilan["juge_muet"] += 1
                    continue
                rel = verdict["relation"]
                bilan["par_relation"][rel] = bilan["par_relation"].get(rel, 0) + 1
                if rel == "unrelated":
                    continue
                cible.execute(
                    "INSERT OR IGNORE INTO claim_reevaluations "
                    "(older_claim_id, newer_claim_id, reevaluation_type, confidence, "
                    "rationale, detected_by, detected_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ancien["id"], nouveau["id"], rel, verdict["confidence"],
                     verdict["rationale"], nom, datetime.now(tz=UTC).isoformat()),
                )
                bilan["reevaluations"] += 1

                if mesure_seule:
                    if rel in ("contradicts", "supersedes") and verdict["confidence"] >= SEUIL_CONTRADICTION:
                        bilan["fermetures_mesurees"] += 1
                    elif rel == "supports" and verdict["confidence"] >= SEUIL_CORROBORATION:
                        bilan["promotions_mesurees"] += 1
                    continue
                if rel in ("contradicts", "supersedes") and verdict["confidence"] >= SEUIL_CONTRADICTION:
                    if _autorite(c_nou) < _autorite(c_anc):
                        bilan["refusees_autorite"] += 1
                    elif os.environ.get("LAFORGE_EPISTEMIC_FERMER", "") != "1":
                        # 16/10 : le juge local rendait 100 % `supersedes` (28/28, confiance 0,9-1,0) ; ses
                        # verdicts fermaient des textes differents et des paires dans les deux sens. Le verdict
                        # reste ENREGISTRE (rejouable par un juge qualifie) ; la fermeture attend LAFORGE_EPISTEMIC_FERMER=1.
                        bilan["fermetures_suspendues"] += 1
                    else:
                        r = _superseder(c_anc["id"], c_nou["id"], _instant(c_nou), verdict["rationale"])
                        if r.get("ok"):
                            bilan["fermees"] += 1
                        else:
                            bilan["fermetures_refusees"] += 1
                            bilan["raisons_refus"].append(str(r.get("raison"))[:80])
                elif rel == "supports" and verdict["confidence"] >= SEUIL_CORROBORATION:
                    brouillon, corroborant = _cote_brouillon(c_anc, c_nou)
                    if brouillon is not None:
                        r = _promouvoir(brouillon["id"], corroborant["id"], db_path)
                        if r.get("promu"):
                            bilan["promus"] += 1
                        else:
                            bilan["promotions_refusees"] += 1
                            bilan["raisons_refus"].append(str(r.get("raison"))[:80])
        bilan["raisons_refus"] = bilan["raisons_refus"][:10]
        return bilan
    finally:
        if conn_rejug is not None:
            conn_rejug.close()
        conn.close()


REJUGEMENT_DB = ROOT / "sandbox" / "epistemic_rejugements.db"
# Base SEPAREE des re-jugements (decision owner 17/10, option A) : chemin PAR DEFAUT
# propose a l'appelant via `reevaluer(..., rejugement_db=REJUGEMENT_DB)` et
# `verdict_effectif(..., rejugement_db=REJUGEMENT_DB)`. Rien ne l'active tout seul --
# sans ce parametre, le comportement reste celui d'avant (tout dans la grosse base).


def verdict_effectif(
    older_claim_id: str,
    newer_claim_id: str,
    db_path=None,
    rejugement_db=None,
) -> Optional[dict]:
    """Verdict qui PRIME sur la paire : base de re-jugement d'abord, sinon grosse base.

    Le re-jugement par un juge qualifie vit dans une base SEPAREE (option A, 17/10) :
    il l'emporte sur le verdict d'origine sans jamais modifier `claim_reevaluations`
    principal. Sans ligne de re-jugement, le verdict d'origine est rendu avec
    `source` = "principale". Base de re-jugement absente ou illisible : lecture de la
    principale, jamais d'exception.
    """
    requete = (
        "SELECT reevaluation_type, confidence, rationale, detected_by, detected_at "
        "FROM claim_reevaluations WHERE older_claim_id = ? AND newer_claim_id = ?"
    )
    ligne, source = None, "principale"
    if rejugement_db and Path(str(rejugement_db)).exists():
        try:
            conn = sqlite3.connect(str(rejugement_db), timeout=30, isolation_level=None)
            try:
                ligne = conn.execute(requete, (older_claim_id, newer_claim_id)).fetchone()
            finally:
                conn.close()
            if ligne is not None:
                source = "rejugement"
        except sqlite3.Error as e:
            logger.warning("base de re-jugement illisible (%s) : lecture de la principale", str(e)[:60])
    if ligne is None:
        conn = _ecrivain(db_path)
        try:
            ligne = conn.execute(requete, (older_claim_id, newer_claim_id)).fetchone()
        finally:
            conn.close()
    if ligne is None:
        return None
    rel, conf, rationale, detecteur, quand = ligne
    return {
        "relation": rel,
        "confidence": conf,
        "rationale": rationale,
        "detected_by": detecteur,
        "detected_at": quand,
        "source": source,
    }


def consolider(
    limit: int = 25,
    backend: str = "local",
    extracteur=None,
    juge=None,
    db_path=None,
    dry_run: bool = False,
    fenetre_j: float = FENETRE_J,
) -> dict:
    """Extraction puis reevaluation, UN compte-rendu. C'est ce que la cadence appelle."""
    ext = process_batch(limit=limit, dry_run=dry_run, backend=backend,
                        extracteur=extracteur, db_path=db_path, fenetre_j=fenetre_j)
    if dry_run:
        return {"extraction": ext, "reevaluation": None, "dry_run": True}
    ree = reevaluer(ext.get("claim_ids") or [], juge=juge, backend=backend, db_path=db_path)
    ext_sans_ids = {k: v for k, v in ext.items() if k != "claim_ids"}
    return {
        "extraction": ext_sans_ids,
        "reevaluation": ree,
        "fermees": ree["fermees"],
        "promus": ree["promus"],
        "muets": ext["muets"] + ree["juge_muet"],
    }


# ---------------------------------------------------------- consolidation de nuit (Q5)
# Debat tour 3, decision Q5 (15/10). Le motif horaire sautait ~20 fois par jour : le modele local
# n'est pas CHAUD, son chargement depasse le tick de 60 s, et un modele chaud 24/7 declencherait
# l'eviction RAM (AGY : 87,4 % mesures). La nuit, le motif lance donc CE job detache : il prend la
# lane, reveille le modele SANS contrainte de tick, consolide UN lot borne, puis DECHARGE le modele
# (keep_alive 0). Jamais de modele chaud permanent. L'issue est ecrite pour le recul du motif.
ETAT_NUIT = ROOT / "sandbox" / "consolidation_nuit.json"
LANE_NUIT = "consolidation_nuit"


def lire_etat_nuit() -> dict:
    try:
        d = json.loads(ETAT_NUIT.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def ecrire_etat_nuit(maj: dict) -> None:
    d = lire_etat_nuit()
    d.update(maj)
    try:
        ETAT_NUIT.parent.mkdir(parents=True, exist_ok=True)
        tmp = ETAT_NUIT.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ETAT_NUIT)
    except OSError as e:
        logger.warning("etat de la consolidation de nuit NON ecrit (%s)", type(e).__name__)


def _decharger_modele() -> bool:
    """keep_alive 0 sans prompt : Ollama decharge le modele. Faux si la demande n'a pas abouti."""
    body = json.dumps({"model": MODELE_LOCAL, "keep_alive": 0}).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("dechargement du modele NON confirme (%s)", type(e).__name__)
        return False


def consolidation_nuit(limit: int = 20, appel=None, consolider_fn=None, decharger=None, admettre=None,
                       liberer=None) -> dict:
    """Un lot borne, modele reveille puis decharge. Issue : OK | MUET | LANE_REFUSEE | ERREUR."""
    appel = appel or _appel_local
    consolider_fn = consolider_fn or consolider
    decharger = decharger or _decharger_modele
    holder = "consolidation_nuit:%d" % os.getpid()
    if admettre is None or liberer is None:
        from nokido_agent.app.forge_lane_admission import admit, release
        admettre = admettre or (lambda: admit(LANE_NUIT, holder, heavy=True, ttl=4 * 3600))
        liberer = liberer or (lambda: release(LANE_NUIT, holder))
    debut = time.time()
    adm = admettre() or {}
    if not adm.get("admit"):
        res = {"issue": "LANE_REFUSEE", "raison": str(adm.get("reason") or adm)[:200]}
    else:
        try:
            # Reveil SANS contrainte de tick : le chargement a froid se paie ici, une fois.
            if not appel('Reply with the JSON {"ok": true}.', timeout=300):
                res = {"issue": "MUET", "raison": "le modele local n'a pas repondu au reveil (300 s)"}
            else:
                choix_juge = os.environ.get("LAFORGE_EPISTEMIC_JUGE", "routeur")
                rapport = consolider_fn(limit=limit, juge=juge_backend(choix_juge))
                res = {"issue": "OK", "rapport": rapport}
        except Exception as e:  # noqa: BLE001 - l'issue est ECRITE, le motif recule
            res = {"issue": "ERREUR", "raison": "%s: %s" % (type(e).__name__, str(e)[:160])}
        finally:
            res_dech = decharger()
            liberer()
        res["modele_decharge"] = res_dech
    prec = lire_etat_nuit()
    echecs = 0 if res["issue"] == "OK" else int(prec.get("echecs_consecutifs", 0)) + 1
    ecrire_etat_nuit({"fin_ts": time.time(), "duree_s": round(time.time() - debut, 1), "issue": res["issue"],
                      "echecs_consecutifs": echecs, "dernier": res})
    return res


def rejuger_supports_mesure(db_path=None, rejugement_db=None, backend: str = "routeur") -> dict:
    """Re-juge, par le juge QUALIFIE et en MESURE SEULE, les assertions que le juge LOCAL a dites `supports`.

    Item decision_owner_a_prendre_rejugement_epistemique (owner 16/10, 18/10) : « faire re-juger les 36 supports par
    le juge qualifie et mesurer les verdicts AVANT toute ouverture de promouvoir_brouillon ». Verdicts vers la base
    SEPAREE (REJUGEMENT_DB par defaut), aucune fermeture, aucune promotion : le bilan rend la distribution a mesurer.
    """
    conn = _ecrivain(db_path)
    try:
        # TOUS les verdicts du juge local, quel que soit le type : mesure du 18/10, %NOKIDO_DATA%\embeddings.db porte 42
        # `supersedes` locaux et 0 `supports` -- le libelle « 36 supports » de l'item ne designait rien en base.
        lignes = conn.execute(
            "SELECT older_claim_id, newer_claim_id FROM claim_reevaluations "
            "WHERE COALESCE(detected_by, '') NOT LIKE 'qualifie%'"
        ).fetchall()
    finally:
        conn.close()
    ids = sorted({i for paire in lignes for i in paire})
    bilan = reevaluer(ids, backend=backend, db_path=db_path, nom_juge="qualifie_" + backend,
                      rejugement_db=rejugement_db or REJUGEMENT_DB, mesure_seule=True)
    bilan["paires_supports_locales"] = len(lignes)
    return bilan


SEUIL_ACCORD_PROMOTION = 0.8


def accord_inter_juges(n: int = 10, juge2=None, backend2: str = "cerebras", rejugement_db=None, db_path=None,
                       graine=None) -> dict:
    """Accord d'un SECOND juge sur un echantillon des `supports` du juge qualifie -- MESURE SEULE, rien n'est ecrit.

    Decision owner 18/10 (choix multiple) : avant d'ouvrir la promotion des brouillons corrobores (61 `supports`
    mesures, job_8693bbc95276), un echantillon est re-juge par un juge DIFFERENT ; on n'ouvre que si l'accord atteint
    SEUIL_ACCORD_PROMOTION. `ouvrir` est une recommandation chiffree, jamais un geste.
    """
    import random  # noqa: PLC0415

    juge2 = juge2 or juge_backend(backend2)
    rj = sqlite3.connect("file:%s?mode=ro" % (rejugement_db or REJUGEMENT_DB), uri=True, timeout=30)
    try:
        paires = rj.execute("SELECT older_claim_id, newer_claim_id FROM claim_reevaluations "
                            "WHERE reevaluation_type = 'supports' ORDER BY older_claim_id, newer_claim_id").fetchall()
    finally:
        rj.close()
    echant = random.Random(graine).sample(paires, min(n, len(paires)))
    conn = _ecrivain(db_path)
    try:
        texte = {i: t for i, t in conn.execute(
            "SELECT id, text FROM chunk_claims WHERE id IN (%s)" % ",".join("?" * (2 * len(echant)) or "''"),
            [x for p in echant for x in p]).fetchall()} if echant else {}
    finally:
        conn.close()
    accord, desaccords, muets = 0, [], 0
    for anc, nou in echant:
        v = juge2(texte.get(anc, ""), texte.get(nou, ""))
        if v is None:
            muets += 1
            continue
        if v.get("relation") == "supports":
            accord += 1
        else:
            desaccords.append({"paire": [anc, nou], "juge2": v.get("relation")})
    juges = len(echant) - muets
    taux = round(accord / juges, 3) if juges else 0.0
    return {"n": len(echant), "juges": juges, "muets": muets, "accord": accord, "taux": taux,
            "seuil": SEUIL_ACCORD_PROMOTION, "ouvrir": bool(juges) and taux >= SEUIL_ACCORD_PROMOTION,
            "desaccords": desaccords[:10], "paires_supports": len(paires)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25, help="Max chunks par passage")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backend", choices=("local", "cerebras"), default="local")
    ap.add_argument(
        "--juge",
        choices=("local", "cerebras", "routeur"),
        default=os.environ.get("LAFORGE_EPISTEMIC_JUGE", "routeur"),
        help="Backend du juge de reevaluation (defaut: LAFORGE_EPISTEMIC_JUGE sinon routeur)",
    )
    ap.add_argument("--consolider", action="store_true", help="extraction PUIS reevaluation")
    ap.add_argument("--nuit", action="store_true",
                    help="job detache de nuit : lane, reveil du modele, UN lot, dechargement (keep_alive 0)")
    ap.add_argument("--rejuger-supports", action="store_true",
                    help="re-juge les `supports` du juge local par --juge, MESURE SEULE, base de re-jugement separee")
    ap.add_argument("--accord-inter-juges", action="store_true",
                    help="echantillon de 10 `supports` re-juges par un second juge (--juge2), mesure seule")
    ap.add_argument("--juge2", choices=("local7b", "cerebras", "routeur", "local"), default="local7b",
                    help="second juge de l'accord inter-juges (defaut local7b : cerebras muet 10/10 le 18/10)")
    args = ap.parse_args()
    if args.accord_inter_juges:
        result = accord_inter_juges(n=10, backend2=args.juge2)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0
    if args.rejuger_supports:
        result = rejuger_supports_mesure(backend=args.juge)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0
    if args.nuit:
        result = consolidation_nuit(limit=args.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("issue") == "OK" else 1
    if args.consolider:
        result = consolider(
            limit=args.limit,
            backend=args.backend,
            dry_run=args.dry_run,
            juge=juge_backend(args.juge),
        )
    else:
        result = process_batch(limit=args.limit, dry_run=args.dry_run, backend=args.backend)
        result.pop("claim_ids", None)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
