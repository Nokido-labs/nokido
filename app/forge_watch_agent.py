# -*- coding: utf-8 -*-
"""
forge_watch_agent.py — Veille active intelligente (Watch Agent)

PIPELINE N8N-STYLE (reprise possible à chaque étape) :

  THÈME
    → [LLM local] génère mots-clés raffinés      (step: keywords)
    → [vérification] pertinence des mots-clés    (step: verify_kw)
    → [SearXNG] recherche par mot-clé            (step: search)
    → [LLM local] post-traitement résultats      (step: refine)
    → [Nokido RAG] vectorisation + scoring      (step: ingest)
    → [biblio_raw] insertion si pertinent        (step: store)

PRINCIPES :
  - Chaque étape est une ligne dans watch_jobs (SQLite WAL)
  - Si interrompu → reprise depuis la dernière étape complétée
  - Toutes les transitions sont visibles via /api/watch/stream (SSE)
  - Les tâches longues sont détachées (thread daemon)

ANALOGIE BIOLOGIQUE :
  Yeux (SearXNG) → nerf optique (keywords) → cortex (LLM refine)
  → hippocampe (RAG ingest) → inconscient (biblio_raw queued)
"""

from __future__ import annotations
import hashlib, json, logging, os, re, sqlite3, threading, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Nokido.WatchAgent")

ROOT = Path(__file__).resolve().parent.parent
from nokido_agent.app.forge_db_path import db_path as _db_path  # realpath symlink C:->V: (writable, fix create_job readonly)

DB = _db_path()
SEARXNG_URL = os.environ.get("LAFORGE_SEARXNG_URL", "http://127.0.0.1:8080")

# ── Steps du pipeline ────────────────────────────────────────────────────────
STEPS = ["keywords", "verify_kw", "search", "refine", "ingest", "store", "done"]

# Garde anti-fabrication (2026-07-10). Un resultat de recherche sans CORPS n'est
# pas du savoir : c'est un titre et une URL. Quand SearXNG tombe (keeper crit du
# 2026-07-08 -> 2026-07-10) les etapes LLM en amont continuent de produire des
# entrees plausibles ; l'ingest les vectorisait telles quelles. Resultat observe :
# 6 chunks au corps IDENTIQUE pour 6 URLs distinctes de claudepluginhub.com,
# embeddes dans le RAG et indiscernables d'une source reelle (auto-empoisonnement).
_MIN_CONTENT_CHARS = 80

# Chrome de navigation des pages JS-rendered (GitHub/Springer/PKP) : le crawl
# rapatrie le squelette de nav et non l'article. Ca franchit _MIN_CONTENT_CHARS
# (la chrome fait des milliers de chars) ET le dedup md5 (chaque page a sa
# propre chrome) -> il faut un signal dedie.
_CHROME_MARKERS = (
    "skip to content",
    "skip to main content",
    "skip to main navigation",
    "skip to site footer",
    "open menu",
    "advertisement",
    "doubleclick.net",
    "enable javascript",
    "accept all cookies",
)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Magic bytes des payloads binaires que le crawl rapatrie tels quels quand une
# URL sert un fichier au lieu d'une page (DOI -> PDF direct). Vectoriser ca
# produit un chunk de flux compresse : zero valeur au retrieval, et il franchit
# _is_boilerplate (aucun lien, aucun marqueur de chrome).
_BINARY_MAGICS = ("%PDF-", "PK\x03\x04", "\x89PNG", "GIF8", "\xff\xd8\xff", "%!PS")


def _purger_fts(conn, cid: str, ancien) -> list:
    """Purge la ligne lexicale de `cid` par MATCH sur son ANCIEN texte.

    Jamais `DELETE FROM rag_fts WHERE chunk_id=?` : `chunk_id` est UNINDEXED, c'est un
    balayage complet de l'index lexical sous verrou d'ecriture de la base RAG (hub fige
    chaque soir a 22 h, 2026-09-27). Source unique : `forge_db_path.purger_fts`.
    Rend les ids LAISSES (ancien texte sans mot exploitable) pour que l'appelant le dise.
    """
    try:
        from nokido_agent.app.forge_db_path import purger_fts
    except ImportError:  # lance par chemin : app/ est sys.path[0]
        from forge_db_path import purger_fts
    return purger_fts(conn, [(cid, ancien)])[1]


def _is_binary_payload(content: str) -> bool:
    """True si `content` est un fichier binaire et non du texte.

    Deux signaux : magic bytes en tete, ou forte proportion d'octets de
    controle (un flux compresse en est saturé, de la prose n'en a aucun).
    """
    head = content.lstrip()[:8]
    if any(head.startswith(m) for m in _BINARY_MAGICS):
        return True
    probe = content[:2000]
    if not probe:
        return False
    ctrl = sum(1 for ch in probe if ord(ch) < 32 and ch not in "\t\n\r")
    return ctrl / len(probe) > 0.05
# Seuil calibre sur les 15 chunks vectorises le 2026-07-16 : la prose plafonne a
# 4.9 liens/1k (arxiv 2412.03801) tandis que la chrome demarre a 8.0 (menus
# GitHub/PKP/Springer, jusqu'a 21.9). 6.0 = milieu du fosse. Compter les LIENS,
# pas les chars d'ancre : une barre de nav = beaucoup de liens tres courts.
_MAX_LINKS_PER_1K = 6.0


def _is_boilerplate(content: str) -> bool:
    """True si `content` est une chrome de navigation plutot que de la prose.

    La densite de liens SEULE ne suffit pas a decider : un README GitHub ou une
    liste `awesome-*` est legitimement dense en liens -- c'est son contenu. Le
    discriminant est le marqueur de chrome, que ces pages n'ont pas. D'ou :
      1. >= 2 marqueurs distincts  -> chrome (un menu se cite plusieurs fois).
      2. 1 marqueur ET densite > _MAX_LINKS_PER_1K -> chrome (un article de
         prose peut citer un marqueur par hasard, mais pas avec 10 liens/1k).
    On rate ainsi la chrome sans marqueur ; c'est le prix a payer pour ne
    jamais jeter un vrai README. Precision > rappel : un faux negatif coute un
    chunk de bruit, un faux positif detruit une source reelle.
    """
    low = content.lower()
    n_markers = sum(1 for m in _CHROME_MARKERS if m in low)
    if n_markers >= 2:
        return True
    if not n_markers:
        return False
    n_links = len(_MD_LINK_RE.findall(content))
    return n_links / max(len(content) / 1000, 0.001) > _MAX_LINKS_PER_1K

# ── DB init ───────────────────────────────────────────────────────────────────

DDL_WATCH = """
CREATE TABLE IF NOT EXISTS watch_jobs (
    id           TEXT PRIMARY KEY,
    theme        TEXT NOT NULL,
    idea_id      TEXT NOT NULL DEFAULT 'veille_active',
    step         TEXT NOT NULL DEFAULT 'keywords',
    status       TEXT NOT NULL DEFAULT 'pending',
    keywords_json TEXT,
    search_results_json TEXT,
    refined_json TEXT,
    n_ingested   INTEGER DEFAULT 0,
    n_stored     INTEGER DEFAULT 0,
    agent        TEXT DEFAULT 'SYSTEM',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_watch_status ON watch_jobs(status, step);
"""

# SSE broadcast (shared avec nokido_hub si importé)
_SSE_CALLBACKS: list = []


def _broadcast(event: dict) -> None:
    """Broadcast un event de pipeline à tous les listeners SSE."""
    for cb in list(_SSE_CALLBACKS):
        try:
            cb(event)
        except Exception:
            pass
    print(
        f"[WATCH] {event.get('step', '?')} -> {event.get('status', '?')} | {event.get('theme', '?')[:40]}", flush=True
    )


def register_sse_callback(cb) -> None:
    _SSE_CALLBACKS.append(cb)


def _get_conn() -> sqlite3.Connection:
    """Connexion AUTOCOMMIT — `sqlite3.connect()` nu ouvre une transaction IMPLICITE
    au premier INSERT et garde le verrou d'ecriture jusqu'au commit. Sous un second
    ecrivain (une ingestion qui tourne en parallele), le voisin se prend
    `OperationalError: database is locked` MALGRE `busy_timeout` : ce dernier attend
    un verrou liberable, pas un verrou tenu par une transaction restee ouverte.

    Mesure 2026-07-25 : les 3 veilles thematiques lancees pendant une ingestion ont
    TOUTES echoue ainsi — le workflow autonome devenait inutilisable des qu'autre
    chose ecrivait. `open_writer()` est le pattern deja prouve ailleurs
    (isolation_level=None + WAL + busy_timeout, « 0 contention sous N workers »).
    """
    try:
        from nokido_agent.app.forge_db_path import open_writer

        conn = open_writer(timeout=30.0)
    except Exception:  # noqa: BLE001
        conn = sqlite3.connect(str(DB), timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(DDL_WATCH)
    return conn


# ── VERDICT METIER D'UNE CHAINE ───────────────────────────────────────────────
# MESURE 2026-08-31 sur les 45 jobs de `watch_jobs` : QUATRE portent un verdict
# plus optimiste que leurs propres etapes. Le cas net est `wj_aef42808d` —
# keywords, verify_kw, search, refine et crawl OK, `ingest` FAILED sur
# « database is locked », `store` completed — et le job se lit `completed`, avec
# n_ingested=220 pour n_stored=4. Trois autres jobs lisent `completed` en portant
# au moins un node `degraded`.
#
# CAUSE : le verdict etait deduit du SEUL compteur de retention. Une etape
# OBLIGATOIRE cassee restait donc invisible des lors que le stockage avait ecrit
# quelque chose. Un worker vivant et un compteur non nul ne prouvent pas qu'une
# veille a fait son travail : le verdict doit lire les ETAPES.
_STEPS_OBLIGATOIRES = ("search", "ingest", "store")
_NODE_CASSE = ("failed", "stalled", "retry_pending")
_NODE_EN_COURS = ("pending", "running")


def verdict_chaine(nodes, n_stored: int, dedup: bool = False) -> str:
    """Verdict METIER d'une veille, deduit des etapes ET du resultat.

    `nodes` = iterable de couples (step_name, status). Une chaine ABSENTE (chemin
    direct, aucun node en base) rend EXACTEMENT le verdict d'avant, celui de la
    retention seule : ce chemin n'a pas d'etapes a contredire, et changer son
    comportement serait une regression deguisee en correctif.

    Sorties, toutes deja connues du corps sauf `completed_partial` :
      indetermine       les etapes n'ont pas pu etre LUES — aucun verdict possible
      en_cours          une etape n'a pas de statut terminal — pas encore de verdict
      failed            une etape OBLIGATOIRE est cassee ET rien n'a ete retenu
      completed_partial une etape est cassee mais du resultat a survecu
      completed_dedup   rien de neuf, la base possedait deja (ce n'est pas un echec)
      completed_empty   rien retenu, aucune etape cassee (vide ASSUME)
      completed         retention non nulle et toutes les etapes terminees

    `en_cours` est le troisieme etat qui manquait : une chaine inachevee n'a pas
    un verdict neutre, elle n'en a pas encore. Le confondre avec un verdict est
    ce qui permet a un restart de transformer une veille incomplete en succes.
    """
    if nodes is None:
        # ILLISIBLE n'est ni ABSENT ni VIDE — les trois etats du contrat maison,
        # ici appliques a la lecture des etapes elles-memes. Rendre `[]` sur une
        # base momentanement inaccessible la rendait indiscernable du chemin
        # DIRECT, et la retention seule suffisait alors a ecrire `completed` :
        # une erreur de LECTURE se transformait en preuve de SUCCES.
        # `indetermine` n'accuse pas (ce n'est pas `failed`), ne promet rien
        # (ce n'est pas `completed`) et ne suggere pas qu'un travail continue
        # (ce n'est pas `en_cours`).
        return "indetermine"
    etats = {str(s or ""): str(st or "") for s, st in nodes}
    if any(st in _NODE_EN_COURS for st in etats.values()):
        return "en_cours"
    casses = [s for s, st in etats.items() if st in _NODE_CASSE]
    if casses and int(n_stored or 0) <= 0 and any(s in _STEPS_OBLIGATOIRES for s in casses):
        return "failed"
    if casses:
        return "completed_partial"
    if int(n_stored or 0) > 0:
        return "completed"
    return "completed_dedup" if dedup else "completed_empty"


def _nodes_du_job(conn, job_id: str):
    """(step_name, status) des etapes d'une chaine, ou None si ILLISIBLE.

    TROIS retours, jamais deux :
      [(...)]  les etapes, lues
      []       aucune etape — chemin DIRECT, il n'y a rien a contredire
      None     la lecture a echoue — on ne sait pas, et on refuse de conclure

    Rendre `[]` dans le dernier cas etait le defaut : il faisait passer une base
    inaccessible pour une veille sans etapes, et le verdict retombait sur la
    retention seule. Un echec de lecture n'empeche toujours pas la cloture du
    job — il la rend simplement INDETERMINEE plutot que faussement bonne.
    """
    try:
        return [(r[0], r[1]) for r in conn.execute(
            "SELECT step_name, status FROM agent_chain_nodes WHERE chain_id=?",
            (job_id,)).fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("verdict %s : etapes ILLISIBLES (%s) — verdict indetermine, "
                       "surtout pas rendu sur la retention seule", job_id,
                       type(exc).__name__)
        return None


def _update_job(conn, job_id: str, step: str, status: str, **kwargs) -> None:
    """Met à jour l'état d'un job + broadcast SSE."""
    now = datetime.now(tz=timezone.utc).isoformat()
    sets = ["step=?", "status=?", "updated_at=?"]
    vals = [step, status, now]
    for k, v in kwargs.items():
        sets.append(f"{k}=?")
        vals.append(v if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False))
    vals.append(job_id)
    conn.execute(f"UPDATE watch_jobs SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()
    row = conn.execute("SELECT * FROM watch_jobs WHERE id=?", (job_id,)).fetchone()
    if row:
        cols = [d[0] for d in conn.execute("SELECT * FROM watch_jobs LIMIT 0").description or []]
        evt = dict(zip(cols, row)) if cols else {}
        evt["type"] = "watch_step"
        _broadcast(evt)


# ── LLM swarm helper ─────────────────────────────────────────────────────────


def _llm_call_openai_compat(
    url: str, model: str, key: str, prompt: str, timeout: int = 30, max_tokens: int = 600
) -> str:
    """OpenAI-compatible chat completion (Groq, Cerebras, OpenRouter, etc)."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


def _llm_local(prompt: str, timeout: int = 180) -> str:
    """LLM swarm cloud-first, Ollama fallback. APU Ryzen + iGPU Radeon trop lent
    pour les volumes (60+ jobs veille). Ordre : Cerebras (free, ultra-fast 50k tok/min)
    -> Groq (free, 30 req/min) -> Mistral (free) -> Ollama (fallback local).

    Si env LAFORGE_USE_FRUGAL=1, route via forge_frugal_cascade
    (FrugalGPT small->large escalation, confidence gate ~70% economie tokens)."""
    import sys as _s, os as _o

    _s.path.insert(0, str(ROOT / "app"))
    # Opt-in cascade FrugalGPT via env flag
    if _o.environ.get("LAFORGE_USE_FRUGAL") == "1":
        try:
            from nokido_agent.app.forge_frugal_cascade import cascade as _frugal

            r = _frugal(prompt, use_case="general", max_tokens=600)
            if r.get("response"):
                return r["response"]
        except Exception as e:
            logger.debug(f"frugal cascade KO: {e}, fallback legacy chain")
    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore
    except Exception:
        get_secret = lambda k: os.environ.get(k, "")  # noqa: E731

    # Cerebras llama3.3-70b — ultra fast (~200-500ms), 50k tok/min free
    try:
        k = get_secret("CEREBRAS_API_KEY") or get_secret("CEREBRAS_API_KEY") or ""
        if k:
            return _llm_call_openai_compat(
                "https://api.cerebras.ai/v1/chat/completions", "gpt-oss-120b", k, prompt, timeout=20, max_tokens=600
            )
    except Exception as e:
        logger.debug(f"cerebras KO: {e}")

    # Groq llama-3.3-70b versatile — free 30 req/min
    try:
        k = get_secret("GROQ_API_KEY") or get_secret("GROQ_API_KEY") or ""
        if k:
            return _llm_call_openai_compat(
                "https://api.groq.com/openai/v1/chat/completions",
                "llama-3.3-70b-versatile",
                k,
                prompt,
                timeout=20,
                max_tokens=600,
            )
    except Exception as e:
        logger.debug(f"groq KO: {e}")

    # Mistral small — free
    try:
        k = get_secret("MISTRAL_API_KEY") or get_secret("MISTRAL_API_KEY") or ""
        if k:
            return _llm_call_openai_compat(
                "https://api.mistral.ai/v1/chat/completions",
                "mistral-small-latest",
                k,
                prompt,
                timeout=25,
                max_tokens=600,
            )
    except Exception as e:
        logger.debug(f"mistral KO: {e}")

    # Fallback Ollama local (lent sur APU mais fonctionne hors-ligne)
    try:
        body = json.dumps(
            {
                "model": "qwen2.5-coder:latest",
                "prompt": prompt,
                "stream": False,
                "keep_alive": "15m",
                "options": {"temperature": 0.3},
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read()).get("response", "").strip()
            if resp and not resp.startswith("ERR"):
                return resp
    except Exception as e:
        logger.debug(f"ollama KO: {e}")

    return "ERR:no_llm"


# ── SearXNG helper ────────────────────────────────────────────────────────────

def _urls_deja_possedees() -> frozenset:
    """URL POSSEDEES = en biblio_raw ET contenu present dans rag_chunks.

    Le filtre historique skippait le crawl sur la seule presence en biblio_raw.
    Or une URL peut y vivre en METADONNEE sans que son contenu soit jamais entre
    dans rag_chunks (crawl rate, purge, ou promue en biblio avant vectorisation).
    Elle etait alors ecartee du crawl et rejetee `duplicate_hash` — le contenu
    utile n'entrait JAMAIS. Mesure 2026-08-16 : 15 sources neuves perdues ainsi.
    « Posseder » une source, c'est en avoir le CONTENU, pas la fiche.

    On ne declare donc possedee qu'une URL dont le contenu est reellement en RAG
    (source de chunk = l'URL crawlee). Une URL biblio sans chunk est RE-CRAWLEE.

    Fail-safe : en cas d'erreur on rend un ensemble VIDE — re-crawler est benin
    (le crawl deduplique au niveau chunk) ; croire a tort qu'on possede ferait
    rater du savoir neuf. L'erreur couteuse n'est pas symetrique.
    """
    import sqlite3 as _sq

    def _norm(u: str) -> str:
        return str(u).strip().lower().rstrip("/")

    try:
        from nokido_agent.app.forge_db_path import db_path

        con = _sq.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=15)
        try:
            # sources dont le CONTENU est reellement indexe (URL crawlee)
            rag = set()
            for (src,) in con.execute(
                    # GLOB : indexable la ou LIKE ne l'est pas. Verifie 2026-09-04 :
                    # 3427 sources des deux cotes, aucune perte.
                    "SELECT DISTINCT source FROM rag_chunks WHERE source GLOB 'http*'"):
                if src:
                    rag.add(_norm(src))
            out = set()
            for (u,) in con.execute(
                    "SELECT url FROM biblio_raw WHERE url IS NOT NULL AND url != ''"):
                if u and _norm(u) in rag:
                    out.add(str(u).strip().lower())
            return frozenset(out)
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return frozenset()


# Domaines paywall/anti-bot connus = skip upstream (eviter 403 systematique au crawl)
PAYWALL_DOMAINS = frozenset(
    {
        "sciencedirect.com",
        "springer.com",
        "link.springer.com",
        "link.elsevier.com",
        "elsevier.com",
        "wiley.com",
        "researchgate.net",
        "academia.edu",
        "cell.com",
        "nature.com",
        "science.org",
        "pnas.org",
        "jstor.org",
        "tandfonline.com",
        "ieee.org",  # IEEE Xplore paywall (sauf certains arxiv-cross)
        "dl.acm.org",
        "mitpressjournals.org",
        "preprints.org",  # paywall meme si appele "preprint"
        "scispace.com",
    }
)

# Sources ouvertes a booster (preprints + dev + blogs perso)
OPEN_ACCESS_DOMAINS = frozenset(
    {
        "arxiv.org",
        "openreview.net",
        "biorxiv.org",
        "ssrn.com",
        "github.com",
        "github.io",
        "gist.github.com",
        "openalex.org",
        "semanticscholar.org",
        "huggingface.co",
        "papers.nips.cc",
        "proceedings.mlr.press",
        "aclanthology.org",
        "ar5iv.labs.arxiv.org",
        "en.wikipedia.org",
        "wikipedia.org",
        "stackoverflow.com",
        "stackexchange.com",
        "freecodecamp.org",
        "dev.to",
    }
)


def _filter_paywall(results: list[dict]) -> list[dict]:
    """Skip paywall domains + boost open access first."""
    open_acc, others = [], []
    _connues = _urls_deja_possedees()
    _n_deja = 0
    for r in results:
        url = (r.get("url") or "").lower()
        # Skip paywalls explicites
        if any(dom in url for dom in PAYWALL_DOMAINS):
            continue
        # DEDUP AMONT (2026-07-27) : deja en biblio_raw -> ne PAS re-telecharger.
        # Mesure : sur 12 veilles dites « vides », 22 refus sur 28 etaient des
        # duplicate_hash, et 18 des 21 URL concernees etaient DEJA dans
        # biblio_raw.url en correspondance exacte. On payait donc crawl + chunk +
        # embed pour un contenu possede, avant de le rejeter a l'insert. Le hash
        # reste le filet pour les 3 restantes (meme contenu, URL differente) :
        # ici on economise le transfert, on ne remplace pas le controle.
        if url and url in _connues:
            _n_deja += 1
            continue
        # Boost open access
        if any(dom in url for dom in OPEN_ACCESS_DOMAINS):
            open_acc.append(r)
        else:
            others.append(r)
    if _n_deja:
        logger.info(f"[veille] dedup amont : {_n_deja} URL deja en biblio_raw, non re-telechargees")
    return open_acc + others


def _openalex_search(query: str, n: int = 8) -> list[dict]:
    """OpenAlex API direct (api.openalex.org). 240M+ works DB, JSON, fast.
    Free, no key required, no rate-limit IP issues."""
    params = urllib.parse.urlencode(
        {
            "search": query,
            "per-page": min(n, 25),
            "select": "id,title,abstract_inverted_index,doi,primary_location,authorships",
        }
    )
    url = f"https://api.openalex.org/works?{params}"
    req = urllib.request.Request(
        url,
        headers={
            # Contact du robot = URL du projet, plus l'adresse personnelle (owner 2026-09-30).
            "User-Agent": "Mozilla/5.0 LaForge-WatchAgent (+https://github.com/Nokido-labs)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        results = data.get("results", [])
        out = []
        for w in results[:n]:
            title = (w.get("title") or "")[:300]
            # OpenAlex stocke abstract inversement indexe -> reconstruct
            abstract = ""
            inv = w.get("abstract_inverted_index") or {}
            if inv:
                # Reconstitution position->word
                positions = {}
                for word, idxs in inv.items():
                    for i in idxs:
                        positions[i] = word
                abstract = " ".join(positions[i] for i in sorted(positions))[:1500]
            # URL : primary_location.landing_page > DOI > openalex id
            url_work = ""
            pl = w.get("primary_location") or {}
            url_work = pl.get("landing_page_url") or ""
            if not url_work and w.get("doi"):
                url_work = f"https://doi.org/{w['doi'].replace('https://doi.org/', '')}"
            if not url_work:
                url_work = w.get("id", "")
            if title and url_work:
                out.append(
                    {
                        "title": title,
                        "url": url_work,
                        "content": abstract or title,
                        "engine": "openalex",
                    }
                )
        return out
    except Exception as e:
        logger.warning(f"OpenAlex KO: {e}")
        return []


def _arxiv_search(query: str, n: int = 8) -> list[dict]:
    """arxiv.org direct (https + timeout 30). Fallback si OpenAlex KO."""
    import xml.etree.ElementTree as ET

    params = urllib.parse.urlencode(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": n,
            "sortBy": "relevance",
        }
    )
    url = f"https://export.arxiv.org/api/query?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 LaForge-WatchAgent (+https://github.com/Nokido-labs)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            xml = r.read()
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml)
        out = []
        for entry in root.findall("a:entry", ns):
            title = (entry.findtext("a:title", "", ns) or "").strip().replace("\n", " ")
            summary = (entry.findtext("a:summary", "", ns) or "").strip().replace("\n", " ")
            link = ""
            for l in entry.findall("a:link", ns):
                if l.get("type") == "text/html" or l.get("rel") == "alternate":
                    link = l.get("href", "")
                    break
            if title and link:
                out.append(
                    {
                        "title": title[:300],
                        "url": link,
                        "content": summary[:1500],
                        "engine": "arxiv_direct",
                    }
                )
        return out[:n]
    except Exception as e:
        logger.warning(f"arxiv direct KO: {e}")
        return []


def _gh_get(path: str, accept: str = "application/vnd.github+json"):
    """Appel API GitHub. Jeton du coffre, absent = anonyme (quota reduit, pas KO)."""
    tok = None
    try:
        from nokido_agent.app.forge_secrets import get_secret

        tok = get_secret("GITHUB_TOKEN")
    except Exception:  # noqa: BLE001
        tok = None
    hdr = {"Accept": accept, "User-Agent": "Nokido-WatchAgent"}
    if tok:
        hdr["Authorization"] = "Bearer %s" % tok
    req = urllib.request.Request("https://api.github.com" + path, headers=hdr)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _github_search(query: str, n: int = 4) -> list[dict]:
    """GitHub par API, JAMAIS par crawl : la page rendue est de la chrome.

    Mesure 2026-07-28 (wj_2636bad295) : 41 candidats ingeres -> 2 retenus. Crawler
    github.com rend 21,9 liens/1k (cf. seuil L90) — des menus, pas du savoir. L'API
    rend la description et le README BRUT, c'est-a-dire la matiere. Exactement la
    lecon deja tiree pour arxiv (API directe ~16x le crawl-HTML, 2026-06-24), jamais
    transposee ici : le code savait que le crawl GitHub etait mauvais et s'en
    defendait par un filtre, au lieu d'eviter le crawl.
    """
    try:
        params = urllib.parse.urlencode({"q": query, "sort": "stars", "per_page": n})
        data = json.loads(_gh_get("/search/repositories?" + params).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"github api KO: {e}")
        return []
    out = []
    for it in (data.get("items") or [])[:n]:
        full = it.get("full_name") or ""
        body = it.get("description") or ""
        try:
            raw = _gh_get("/repos/%s/readme" % full, "application/vnd.github.raw")
            body = (body + "\\n\\n" + raw.decode("utf-8", "replace"))[:4000]
        except Exception:  # noqa: BLE001
            pass  # pas de README = on garde la description, on ne jette pas
        out.append({"title": full[:300], "url": it.get("html_url") or "",
                    "content": body, "engine": "github_api"})
    return [r for r in out if r["url"]]


def _academic_search(query: str, n: int = 8) -> list[dict]:
    """Cascade OpenAlex -> arxiv : 1st provider qui retourne resultats wins."""
    res = _openalex_search(query, n)
    if res:
        return res
    return _arxiv_search(query, n)


# Circuit breaker per-engine : track fails et skip engine X minutes apres N fails
_ENGINE_CB: dict = {}  # engine_name -> {fails, opened_until_ts}
_ENGINE_CB_THRESHOLD = 3
_ENGINE_CB_COOLDOWN_S = 900  # 15 min


def _engine_open(name: str) -> bool:
    """True si engine en cooldown (skip)."""
    st = _ENGINE_CB.get(name)
    if not st:
        return False
    return st.get("opened_until_ts", 0) > time.time()


def _engine_record(name: str, ok: bool):
    st = _ENGINE_CB.setdefault(name, {"fails": 0, "opened_until_ts": 0})
    if ok:
        st["fails"] = 0
    else:
        st["fails"] += 1
        if st["fails"] >= _ENGINE_CB_THRESHOLD:
            st["opened_until_ts"] = time.time() + _ENGINE_CB_COOLDOWN_S
            logger.warning(f"engine circuit OPEN {name} for {_ENGINE_CB_COOLDOWN_S}s")


# Anti-rafale partagee entre nodes concurrents (voir _ensure_searxng).
_SEARX_LAST_ENSURE_TS = 0.0
_ENSURE_COOLDOWN_S = 30.0


def _ensure_searxng(wait_s: "int | None" = None) -> bool:
    """Réveil ON-DEMAND de SearXNG via le seam central (superviseur =
    propriétaire du lifecycle), puis attente readiness sur :8080.

    Idempotent & non-fatal : si déjà up -> True immédiat ; si superviseur ou
    daemon Docker injoignable -> log + False, _searxng dégradera en fallback
    academic. Évite d'avoir à lancer SearXNG à la main (le service NokidoSearxng
    est `disabled=true` = on-demand, personne ne le réveillait avant ce hook)."""
    import sys as _sys
    import time as _t
    from pathlib import Path as _Path

    probe = f"{SEARXNG_URL}/search?q=ping&format=json"

    # Anti-rafale : au demarrage d'un job multi-chaines, N nodes appellent
    # _ensure_searxng quasi simultanement. Sans coordination, tous voient SearXNG
    # pas-encore-pret et sollicitent TOUS Docker+superviseur -> rafale de logs
    # docker_keeper pour un reveil deja en cours (mesure 2026-08-28, spam owner).
    # On reserve le reveil au premier node ; les voisins sautent a la readiness.
    global _SEARX_LAST_ENSURE_TS
    _recent_ensure = (_t.time() - _SEARX_LAST_ENSURE_TS) < _ENSURE_COOLDOWN_S
    if not _recent_ensure:
        _SEARX_LAST_ENSURE_TS = _t.time()

    def _up() -> bool:
        try:
            req = urllib.request.Request(probe, headers={"User-Agent": "LaForge-WatchAgent"})
            with urllib.request.urlopen(req, timeout=4) as r:
                return r.status == 200
        except Exception:
            return False

    if _up():
        return True

    tools_dir = str(_Path(__file__).resolve().parent.parent / "tools")
    if tools_dir not in _sys.path:
        _sys.path.insert(0, tools_dir)
    if not _recent_ensure:
        # Niveau daemon (best-effort) : signale docker.wanted -> forge_docker_keeper.
        try:
            from nokido_agent.tools.forge_docker_keeper import ensure_docker

            ensure_docker()
        except Exception as e:
            # MUET jusqu'au 2026-08-12, et c'est ce silence qui a masque la panne :
            # le keeper reste en monitor_only tant que personne ne pose docker.wanted
            # (il regarde alors le daemon mourir sans droit d'agir). Si la demande
            # echoue ici, plus rien au monde ne reveillera Docker -> veille a sec.
            logger.warning(f"[watch] ensure_docker KO -> keeper non sollicite: {e}")
        # Niveau service : réveil on-demand idempotent via le superviseur (:8765).
        try:
            from nokido_agent.tools.forge_supervisor_ctl import _call as _sup_call

            st, _ = _sup_call("/supervisor/service/start/NokidoSearxng", method="POST")
            logger.info(f"[watch] SearXNG ensure via superviseur -> HTTP {st}")
        except Exception as e:
            logger.warning(f"[watch] SearXNG ensure KO (superviseur injoignable): {e}")
            return False
    else:
        logger.debug(
            "[watch] SearXNG ensure deja sollicite <%.0fs -> attente readiness",
            _ENSURE_COOLDOWN_S,
        )
    # Attente readiness : budget DERIVE du keeper, pas un nombre fixe. Le boot de
    # Docker s'allonge avec la pression memoire, et le keeper l'APPREND deja
    # (_boot_timeout_for_load : regression duration ~ a*ram + b sur echantillons).
    # Mesure 2026-08-12 : boot a froid = ~375 s a RAM 85 % ; la veille abandonnait
    # a 90 s -> degradait en academic -> 30/98 jobs `completed_empty`. Deux organes
    # qui modelisent le MEME delai differemment : le plus lent doit decider.
    if wait_s is None:
        wait_s = 90
        try:
            from nokido_agent.tools.forge_docker_keeper import _boot_timeout_for_load, _docker_info_ok

            budget, pourquoi = _boot_timeout_for_load()
            daemon_up, _ = _docker_info_ok()
            # DEUX populations dans les echantillons du keeper, et sa regression
            # unique sur la RAM les melange : redemarrage a CHAUD (mediane 15,2 s,
            # p90 20,1 s, Docker Desktop deja la) et boot a FROID (processus
            # absent -> 227,5 s mesures le 2026-08-12). Elle predit donc 17 s,
            # soit 13x trop peu pour le SEUL cas ou la veille a besoin d'attendre.
            # On discrimine sur l'etat du daemon plutot que d'allonger le cas
            # courant : conteneur seul a relancer -> 90 s ; Docker a booter -> 240 s.
            plancher = 90 if daemon_up else 240
            wait_s = max(plancher, int(budget))
            logger.info(
                f"[watch] budget boot searxng={wait_s}s "
                f"(daemon_up={daemon_up}, {pourquoi})"
            )
        except Exception as e:
            logger.warning(f"[watch] budget keeper indisponible -> 90s fixe ({e})")
    deadline = _t.time() + wait_s
    while _t.time() < deadline:
        if _up():
            logger.info("[watch] SearXNG prêt")
            return True
        _t.sleep(3)
    logger.warning(f"[watch] SearXNG pas prêt après {wait_s}s -> dégrade academic")
    return False


def _searxng(query: str, n: int = 8) -> list[dict]:
    """Query SearXNG + filtre paywalls + boost open access (arxiv/github/etc).
    Fallback academic cascade si SearXNG 0 results OU engine CB OPEN.
    Circuit breaker per-engine tracking : tag fails par moteur unresponsive."""
    if _engine_open("searxng"):
        logger.info("searxng CB open, skip direct fallback academic")
        return _academic_search(query, n)

    params = urllib.parse.urlencode({"q": query, "format": "json", "categories": "general", "language": "en"})
    req = urllib.request.Request(
        f"{SEARXNG_URL}/search?{params}",
        headers={
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
            "User-Agent": "Mozilla/5.0 (LaForge-WatchAgent)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            raw = data.get("results", [])
            # Tag engines unresponsive (anti rate-limit cycles)
            unresp = data.get("unresponsive_engines", [])
            for ue in unresp:
                eng = ue[0] if isinstance(ue, (list, tuple)) and ue else str(ue)
                _engine_record(f"searxng:{eng}", ok=False)

            filtered = _filter_paywall(raw)
            if filtered:
                _engine_record("searxng", ok=True)
                return filtered[:n]
            # 0 results SearXNG -> count partial fail + academic fallback
            _engine_record("searxng", ok=False)
            logger.info(f"SearXNG 0 results for '{query[:40]}', fallback academic")
            return _academic_search(query, n)
    except Exception as e:
        _engine_record("searxng", ok=False)
        logger.warning(f"SearXNG KO: {e}, fallback academic")
        return _academic_search(query, n)


# ── PIPELINE STEPS ────────────────────────────────────────────────────────────


_KW_STOP = {"the", "and", "for", "with", "from", "into", "その", "2024", "2025", "2026",
            "using", "based", "toward", "towards", "about", "over", "under"}


def _anchor_terms(theme: str, strong_only: bool = False) -> list[str]:
    """Termes qui ANCRENT le theme dans son domaine.

    Un mot isole peut appartenir a deux mondes : « homeostasis » designe aussi bien
    la regulation d'un organisme logiciel qu'un mecanisme cellulaire. Sans ancre, la
    requete part dans le mauvais. On garde donc les termes porteurs du theme, en
    privilegiant la sequence capitalisee de tete (« Viable System Model »), qui est
    presque toujours le SUJET.
    """
    mots = re.findall(r"[A-Za-z][\w-]{1,}", theme)
    sig = [m for m in mots if m.lower() not in _KW_STOP and not m.isdigit()]
    if not sig:
        return [theme[:40]]

    # 1. ACRONYMES d'abord — LIDA, ECAN, VSM, RAG : ce sont les termes les PLUS
    #    discriminants d'un domaine, et les plus courts. Un seuil de longueur les
    #    eliminait justement tous (mesure : « LIDA » perdu, alors que c'est le seul
    #    mot qui distingue cette architecture de n'importe quelle autre).
    acronymes = [m for m in sig if m.isupper() and 3 <= len(m) <= 8]
    # 2. Sequence capitalisee de tete = nom propre du sujet (« Viable System Model »).
    tete: list[str] = []
    for m in sig:
        if m[0].isupper() and len(tete) < 3:
            tete.append(m)
        else:
            break
    # 3. Mots longs, en dernier recours. On ECARTE ceux qui vivent dans plusieurs
    #    domaines : ancrer sur « homeostasis » ne desambigue rien, c'est precisement
    #    le mot qui a fait basculer une veille cybernetique vers la biologie.
    ambigus = {"homeostasis", "regulation", "memory", "attention", "network", "agent",
               "system", "model", "energy", "signal", "control", "adaptation"}
    longs = [m for m in sig[:6] if len(m) >= 5 and m.lower() not in ambigus]

    # Ancres FORTES = ce qui identifie le sujet a lui seul (acronyme, nom propre).
    # Les mots longs ordinaires n'en sont PAS : exiger seulement « un mot long du
    # theme » laissait passer la requete fautive, puisqu'elle contenait deja
    # « recursion » et « audit ». Le garde ne doit se satisfaire que du sujet.
    fortes: list[str] = list(acronymes)
    if len(tete) >= 2:
        fortes.append(" ".join(tete))
    elif len(tete) == 1 and tete[0] not in acronymes and len(tete[0]) >= 4:
        fortes.append(tete[0])
    if strong_only:
        # Repli : sans acronyme ni nom propre, le sujet est porte par les mots longs
        # non ambigus — mieux vaut une ancre imparfaite qu'aucune.
        out = [a for a in dict.fromkeys(fortes) if a] or longs[:2]
        return out or [theme[:40]]
    out = [a for a in dict.fromkeys(fortes + longs) if a]
    return out or [theme[:40]]


def _step_keywords(conn, job_id: str, theme: str) -> list[str]:
    """LLM génère 4 mots-clés raffinés depuis le thème, ANCRES dans son domaine."""
    anchors = _anchor_terms(theme, strong_only=True)
    principal = anchors[0] if anchors else theme[:40]
    prompt = (
        f"Thème de veille scientifique : {theme}\n"
        f"Génère exactement 4 requêtes de recherche web optimisées, "
        f"une par ligne, en anglais, 4-8 mots chacune, très spécifiques.\n"
        f"CONTRAINTE : chaque requête DOIT garder le sujet « {principal} » ou un terme "
        f"qui le désambiguïse, sinon la recherche part dans un autre domaine.\n"
        f"Pas d'explication, juste les 4 requêtes."
    )
    raw = _llm_local(prompt)
    kws = [l.strip().strip("•-1234567890.").strip() for l in raw.splitlines() if len(l.strip()) > 5][:4]
    if not kws:
        kws = [theme[:60]]

    # GARDE D'ANCRAGE — le prompt ne suffit pas : mesure 2026-07-25, le thème
    # « Viable System Model Beer recursion audit channel homeostasis » a produit
    # « Beer recursion audit channel homeostasis », requête où « Beer » (nom propre)
    # et « homeostasis » isolés ont ramené un article sur la ferroptose et le cancer
    # ovarien, scoré 7/10 par le LLM. On re-ancre plutôt que de jeter : la requête
    # reste celle du modèle, on lui rend seulement son sujet.
    ancres_bas = [a.lower() for a in anchors]
    recadres = 0
    for i, kw in enumerate(kws):
        if not any(a in kw.lower() for a in ancres_bas):
            kws[i] = f"{principal} {kw}"
            recadres += 1
    if recadres:
        logger.info(f"[watch] {recadres}/{len(kws)} requete(s) re-ancrees sur « {principal} »")

    _update_job(conn, job_id, "verify_kw", "running", keywords_json=kws)
    return kws


def _step_verify_kw(conn, job_id: str, theme: str, kws: list[str]) -> list[str]:
    """LLM vérifie la pertinence des mots-clés."""
    prompt = (
        f"Thème : {theme}\nMots-clés proposés :\n"
        + "\n".join(f"{i + 1}. {k}" for i, k in enumerate(kws))
        + "\nGarde uniquement les 3 plus pertinents. "
        "Réponds avec leurs numéros séparés par des virgules. Ex: 1,3,4"
    )
    raw = _llm_local(prompt)
    import re

    idxs = [int(x) - 1 for x in re.findall(r"\d+", raw) if 0 <= int(x) - 1 < len(kws)]
    verified = [kws[i] for i in idxs[:3]] if idxs else kws[:3]
    _update_job(conn, job_id, "search", "running", keywords_json=verified)
    return verified


# ---------------------------------------------------------------------------
# ZONE MORTE : _step_keywords / _step_verify_kw / _step_search / _step_refine
# ---------------------------------------------------------------------------
# Ces 4 fonctions n'ont AUCUN appelant. Le pipeline de veille VIVANT est le
# ChainExecutor : `create_job` ecrit des `agent_chain_nodes`, que l'executor
# dispatche vers `_call_llm_step` (keywords / verify_kw / refine) et
# `_call_search`. `run_watch_job` n'est plus qu'un stub qui delegue.
#
# De CE module, le ChainExecutor ne reutilise QUE : _llm_local, _academic_search,
# _searxng, _ensure_searxng, _is_binary_payload, _is_boilerplate, _get_conn,
# _step_ingest, _audit_chunks_quality, _step_store. Le reste est inerte.
#
# Conserve (doctrine : on garde le legacy), mais NE PAS corriger un bug de veille
# ICI : le correctif n'aurait aucun effet. Piege verifie le 2026-07-16 -- un fix
# multi-source academique a ete livre dans `_step_search` (commit 454251d2) alors
# que le vrai site etait `_call_search`. Corriger dans app/forge_chain_executor.py.
# ---------------------------------------------------------------------------
def _step_search(conn, job_id: str, kws: list[str]) -> list[dict]:
    """Multi-source par mot-cle : academique (OpenAlex -> arxiv) PUIS SearXNG.

    `_academic_search` rend l'ABSTRACT directement par API : ni crawl, ni chrome
    de nav, ni PDF a extraire, et un corpus relu par les pairs. Il etait ecrit
    mais JAMAIS appele -- le pipeline ne tapait que SearXNG, d'ou la moisson de
    journaux predateurs et de snippets de 400 chars (veilles du 2026-07-16).
    L'academique passe en premier : a URL egale, son abstract prime (dedup).
    """
    all_results = []
    seen_urls = set()
    # BYPASS URLS-DONNEES (2026-07-22, cas ExploitGym wj_fe5f00dd0c) : un theme
    # qui CONTIENT des URLs a des cibles connues — les moteurs (CAPTCHA DDG/
    # Brave, requete longue) rendaient 0 candidat alors que les cibles etaient
    # DONNEES. Injection en tete comme candidats directs : refine les score,
    # store les insere (avec normalisation https). La recherche ne sert plus
    # que pour le contexte autour des cibles.
    try:
        import re as _re

        _theme = (conn.execute("SELECT theme FROM watch_jobs WHERE id=?",
                               (job_id,)).fetchone() or [""])[0]
        for _u in _re.findall(r"https?://[^\s\"'\)\]]+", _theme or ""):
            if _u in seen_urls:
                continue
            seen_urls.add(_u)
            all_results.append({"title": _u[:120], "url": _u,
                                "content": ("cible donnee dans le theme: "
                                            + (_theme or ""))[:400],
                                "keyword": "theme-url", "score": 1.0})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[veille] bypass theme-urls KO: {e}")
    for kw in kws:
        # cap 4000 pour GitHub : c'est du README, donc de la matiere a chunker,
        # pas un snippet. Les 400 de SearXNG etaient calibres pour des extraits.
        for src, n, cap in ((_academic_search, 4, 1500), (_github_search, 3, 4000),
                            (_searxng, 6, 400)):
            try:
                hits = src(kw, n)
            except Exception as e:
                logger.warning(f"[veille] source {src.__name__} KO sur '{kw}': {e}")
                continue
            for r in hits:
                url = r.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append(
                    {
                        "title": r.get("title", "")[:120],
                        "url": url,
                        "content": (r.get("content") or "")[:cap],
                        "keyword": kw,
                        "score": r.get("score", 0.0),
                    }
                )
    _update_job(conn, job_id, "refine", "running", search_results_json=all_results, n_ingested=len(all_results))
    return all_results


# ZONE MORTE (cf banniere ci-dessus). Le refine VIVANT est
# `forge_chain_executor._call_llm_step(step_type="refine")` : heuristique offline
# 3 axes (overlap / freshness / source trust) + veto de source. Celui-ci note sur
# 80 chars de contenu et retient toujours 5 resultats, sans seuil absolu.
def _step_refine(conn, job_id: str, theme: str, results: list[dict]) -> list[dict]:
    """LLM sélectionne et note les résultats par pertinence. NON APPELE."""
    if not results:
        _update_job(conn, job_id, "ingest", "running", refined_json=[])
        return []
    summary = "\n".join(f"{i + 1}. {r['title']} — {r['content'][:80]}" for i, r in enumerate(results[:15]))
    prompt = (
        f"Thème : {theme}\nRésultats de recherche :\n{summary}\n"
        f"Sélectionne les 5 plus pertinents et note leur pertinence (1-10). "
        f"Format: numéro:score ex: 1:9,3:7,5:8,7:6,10:5"
    )
    raw = _llm_local(prompt)
    import re

    pairs = re.findall(r"(\d+):(\d+)", raw)
    refined = []
    for num_s, score_s in pairs[:5]:
        idx = int(num_s) - 1
        if 0 <= idx < len(results):
            r = dict(results[idx])
            r["relevance"] = min(10, int(score_s))
            refined.append(r)
    if not refined:
        # NOTATION INDISPONIBLE != NOTE MEDIOCRE (mesure 2026-07-31). Ce repli
        # posait `relevance = 5`, soit exactement UN POINT sous le seuil de
        # retention (>=6) : tout candidat d'une veille dont la notation avait
        # echoue etait donc rejete, en silence, avec un score qui avait l'air
        # d'un jugement. Mesure : la veille `crawlforge` sortait cinq candidats
        # notes 5,5,5,5,5 — la signature exacte de ce repli, lue a tort comme
        # « le LLM les a juges mediocres ».
        # On distingue desormais les trois etats : note / non note / rejete.
        # `relevance = None` ne franchit aucun seuil par accident et se LIT dans
        # la trace, la ou un 5 se confondait avec une opinion.
        refined = results[:5]
        for r in refined:
            r["relevance"] = None
            r["relevance_indisponible"] = "notation LLM absente ou illisible"
    refined.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    _update_job(conn, job_id, "ingest", "running", refined_json=refined)
    return refined


_INGEST_CHUNK_CHARS = 2000
_INGEST_OVERLAP = 200
# Cap anti-noyade CALIBRE sur la mesure du 2026-07-25 : deux surveys arxiv reels
# rendent 96 k et 119 k caracteres de texte integral, soit 53 et 64 morceaux de 2 k.
# Un cap a 40 les aurait coupes en silence (c'est ce que faisait `text[:3000]`, en
# pire). 80 couvre un survey long tout en restant borne -- un livre entier n'ensevelit
# pas le RAG, et le depassement est journalise, jamais tu.
# CAP RELEVE de 80 a 400 (mesure 2026-09-05). A 80 x 2000 caracteres, un document
# etait ecrete a 160 000 caracteres : le PDF arxiv 2401.05566v3 rendait 135 morceaux
# et n'en gardait que 80, soit 41 % du papier JETES apres avoir ete crawles, extraits
# et payes. La distribution le confirme -- sur 3 429 documents web, le p99 tombe PILE
# sur 80, signature de l'ecretage, et 53 documents sont a 80 ou plus.
# 400 = trois fois le plus gros document reellement mesure (135). La borne reste,
# parce qu'un dump aberrant doit toujours etre arrete ; elle DIT ce qu'elle ecarte
# (cf. le warning ci-dessous), pour qu'un rattrapage reste possible.
_INGEST_MAX_CHUNKS = int(os.environ.get("LAFORGE_VEILLE_MAX_CHUNKS", "400"))
# FILTRE HORS-SUJET : mesure NEGATIVE du 2026-07-25, consignee pour que personne ne
# reperde la journee a la refaire. Un garde LEXICAL (recouvrement de termes du theme
# dans titre+url+corps) a ete ecrit, puis calibre sur les 22 dernieres sources
# reelles AVANT commit. Verdict : faux dans les DEUX sens, donc retire.
#   - il REJETAIT « Retrieval-Augmented Generation: A Comprehensive Survey » (0 terme
#     commun) pour la veille RAG/hybrid-search : les themes portent des mots de META
#     (« manning », « publications », « book », « 2025 ») qui n'apparaissent JAMAIS
#     dans les bonnes sources ;
#   - il GARDAIT « stock price crash risk » pour la veille Docker : « crash » dans le
#     titre + « regression » present dans le corps de n'importe quel papier de ML.
# Le cout des deux erreurs n'est pas symetrique : laisser passer du bruit salit le
# corpus, jeter une source pertinente detruit de l'intelligence. Donc en cas de doute,
# NE PAS filtrer -- et l'incident inverse est deja documente plus bas dans ce fichier
# (des relevance 7-8 rejetes).
# La voie correcte est SEMANTIQUE, pas lexicale : cosinus entre le vecteur du theme et
# celui du chunk (l'embedder :8099 est deja appele ici pour chaque morceau, le vecteur
# du theme coute UN embed par job). A livrer avec son seuil MESURE sur ces memes
# sources, jamais pose a l'aveugle.


def _extract_entities(url: str, content: str) -> dict:
    """Entites TYPEES du document, mais SEULEMENT celles qui sont VERIFIABLES
    (chantier ontologies, owner 2026-07-25).

    On extrait ce qui est deterministe -- identifiants et annee derivee de l'id -- et
    PAS ce qui demande du NLP (methode, dataset, metrique, auteurs). Raison : une
    extraction fragile remplirait `meta` d'entites fausses qu'AUCUN consommateur ne
    pourrait distinguer des vraies. Mieux vaut trois champs surs qu'une ontologie
    plausible : le typage semantique demande un LLM et son propre calibrage, il se
    posera par-dessus celui-ci quand il existera.
    """
    import re as _re

    ent: dict = {}
    m = _re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", url or "", _re.I)
    if m:
        ent["arxiv_id"] = m.group(1)
        # L'identifiant arxiv moderne encode AAMM (format en vigueur depuis 04/2007) :
        # « 2504 » = avril 2025. L'annee est donc DERIVEE, pas devinee. Les identifiants
        # anciens (« hep-th/9901001ustring ») n'ont pas ce format et ne matchent pas --
        # on prefere ne rien dire plutot que de produire une annee fausse.
        ent["year"] = 2000 + int(m.group(1)[:2])
    m = _re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", (content or "")[:4000])
    if m:
        ent["doi"] = m.group(0).rstrip(".,;)")
    return ent


# Aligne sur le seuil de retention de `_step_store` (>=6). Voir la note dans la boucle
# de `_step_ingest` : ingerer sous ce seuil revient a vectoriser du rebut.
_MIN_RELEVANCE_INGEST = int(os.environ.get("LAFORGE_VEILLE_MIN_RELEVANCE", "6"))

# Densite de motifs « [n] » au-dela de laquelle un corps de texte est une
# BIBLIOGRAPHIE et non du contenu. CALIBRE SUR LES CHUNKS REELS (2026-07-27), pas
# choisi a vue : sur 60 chunks de veille conserves la densite vaut 0,00 PARTOUT
# (max 0,00) ; sur les 40 chunks pollues du survey arXiv 2306.10125 la mediane est
# 2,87 et le max 39,5. A 1,0 pour 1000 caracteres : 28 pollues sur 40 attrapes,
# ZERO faux positif. Les 12 restants sont du texte normal du meme papier — non
# detectables par la FORME, c'est au seuil de pertinence de les ecarter.
# SEUILS DE DETECTION D'UNE BIBLIOGRAPHIE — les deux sont exiges (cf.
# `_is_reference_list`). Mesures du 2026-09-05 sur 38 213 chunks web.
#
# ⚠️ LA DENSITE NE SEPARE PAS, et c'est le point qu'il ne faut pas re-perdre.
# J'avais d'abord annonce un temoin bibliographique a 160,5 pour 1000 caracteres :
# c'etait un ARTEFACT DE CALCUL. Une vraie bibliographie porte une reference par
# 100 a 150 caracteres, soit une densite de 7 a 10 -- tandis que les corps
# d'articles montent a 11,2 au p99. Les deux populations se CHEVAUCHENT. Caler un
# seuil de densite dessus reviendrait a trancher dans le bruit.
#
# Le discriminant reel est STRUCTUREL : le ratio de lignes OUVERTES par `[N]`.
# Corps mesures 0,00 a 0,31 ; une bibliographie tient entre 0,33 (references sur
# trois lignes, cas des PDF) et 1,00 (une ligne par reference).
#
# ⚠️ CALIBRAGE PROVISOIRE, ET IL FAUT LE SAVOIR : le corpus ne contient AUCUNE
# bibliographie que ce garde sache reconnaitre, donc mes seuls temoins positifs
# sont FABRIQUES -- et un materiau fabrique ne mesure pas le monde. Ces seuils
# sont donc volontairement conservateurs : mieux vaut ingerer une page de
# references que jeter un article. A recalibrer le jour ou une vraie page de
# bibliographie sera disponible dans le corpus.
#
# L'ancien reglage (densite SEULE, seuil 1,0) rejetait 4 533 chunks sur 38 213 --
# un sur huit, tous legitimes -- et n'attrapait aucune vraie bibliographie.
_REFLIST_DENSITY_MAX = float(os.environ.get("LAFORGE_VEILLE_REFLIST_MAX", "5.0"))
_REFLIST_LINE_RATIO_MIN = float(os.environ.get("LAFORGE_VEILLE_REFLIST_RATIO", "0.30"))


def _is_reference_list(content: str) -> bool:
    """Vrai si le texte EST une liste de references, pas s'il en CITE.

    DEFAUT MESURE le 2026-09-05. Le critere etait la seule densite de `[N]`, seuil
    1,0 pour 1000 caracteres. Or un corps de papier scientifique cite en permanence :
    mesure sur 38 213 chunks web, **4 533 depassaient ce seuil** (un sur huit), avec
    une distribution p50=2,9 / p90=5,9 / p99=11,2 -- c'est-a-dire que la quasi-
    totalite des corps d'articles etait classee « bibliographie » et JETEE. Et le
    rejet ne portait pas sur un chunk : `_step_ingest` ecarte la SOURCE ENTIERE.

    Ce que la mesure a aussi montre : les 17 chunks a densite >= 20 ont un ratio
    debut-de-ligne MEDIAN DE 0,00 -- ce ne sont pas des bibliographies non plus.
    Le corpus n'en contenait donc aucune que ce garde savait reconnaitre : il ne
    rejetait que du legitime.

    LE BON DISCRIMINANT EST STRUCTUREL. Dans une bibliographie, les `[N]` OUVRENT
    la ligne et chaque ligne EST une reference ; dans un corps ils sont au milieu
    du texte. Mesure comparee : temoin bibliographique 160,5 de densite et ratio
    1,00 ; corps reels 1,4 a 4,9 de densite et ratio 0,00 a 0,31.

    On exige donc les DEUX, et le seuil de densite est place a 15 -- au-dessus du
    p99 mesure (11,2) et bien en dessous du temoin (160). Consequence assumee : sur
    le corpus actuel ce garde ne rejette plus rien, ce qui est le comportement
    JUSTE puisqu'il n'y avait rien de legitime a rejeter. Il reste arme pour une
    vraie page de references.
    """
    import re as _re

    if not content or len(content) < 200:
        return False
    densite = 1000.0 * len(_re.findall(r"\[\d{1,3}\]", content)) / len(content)
    if densite < _REFLIST_DENSITY_MAX:
        return False
    lignes = [ligne.strip() for ligne in content.split("\n") if ligne.strip()]
    if not lignes:
        return False
    ouvrent = sum(1 for ligne in lignes if _re.match(r"^\[\d{1,3}\]", ligne))
    return (ouvrent / len(lignes)) >= _REFLIST_LINE_RATIO_MIN


def _step_ingest(conn, job_id: str, theme: str, refined: list[dict]) -> int:
    """Vectorise dans rag_chunks les résultats retenus. Embed inline via
    forge_embed_router cascade (brain_worker > HF > Jina > Modal) pour eviter
    le gap NULL embedding qui necessite re-vectorisation differee."""
    now = datetime.now(tz=timezone.utc).isoformat()
    # Lazy import du router (evite cycle import)
    try:
        import sys as _s

        _s.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_embed_router import embed as _embed, encode_blob as _encode_blob
    except Exception:
        _embed = None
        _encode_blob = None

    n = 0
    n_skipped = 0
    seen_bodies: dict[str, str] = {}
    for r in refined:
        # SEUIL ALIGNE SUR CELUI DE LA RETENTION (2026-07-27, diagnostic AGY verifie).
        # L'ingest acceptait >=4 pendant que le store exige >=6 : on vectorisait donc
        # ce qu'on avait DEJA decide de ne jamais retenir. Ce n'est pas un accident,
        # c'est un ecart de seuils inscrit dans le pipeline — et c'est mecaniquement
        # la source des 82 chunks hors sujet du job wj_ea26989e95 (survey arXiv sur les
        # GAN + apoptose), dont les 3 candidats etaient tous sous 6.
        # Cout paye pour rien a chaque veille : crawl, chunking, embeddings locaux,
        # puis dilution de la recherche hybride par des vecteurs qu'on a juges non
        # pertinents. Surchargeable si l'on veut retrouver du signal faible.
        if r.get("relevance", 0) < _MIN_RELEVANCE_INGEST:
            n_skipped += 1
            continue

        # Garde 1 : pas de corps, pas de chunk (cf _MIN_CONTENT_CHARS).
        content = (r.get("content") or "").strip()
        if len(content) < _MIN_CONTENT_CHARS:
            logger.warning(f"[veille] skip sans corps: {r['url']} (len={len(content)})")
            n_skipped += 1
            continue

        # Garde 2 : un meme corps sur plusieurs URLs = paraphrase du theme, pas
        # une lecture des pages. Signature de la fabrication : on garde la 1ere
        # occurrence, on jette les suivantes.
        body_key = hashlib.md5(content.encode()).hexdigest()
        if body_key in seen_bodies:
            logger.warning(f"[veille] skip corps duplique: {r['url']} == {seen_bodies[body_key]}")
            n_skipped += 1
            continue
        seen_bodies[body_key] = r["url"]

        # Garde 3 : chrome de nav != contenu (cf _is_boilerplate). Sans ca, un
        # crawl de page JS vectorise un menu et empoisonne le retrieval.
        if _is_boilerplate(content):
            logger.warning(f"[veille] skip chrome de nav: {r['url']}")
            n_skipped += 1
            continue

        # Garde 4 : un DOI qui sert le PDF direct rend des octets, pas du texte.
        if _is_binary_payload(content):
            logger.warning(f"[veille] skip payload binaire: {r['url']}")
            n_skipped += 1
            continue

        # Garde 5 : une LISTE DE REFERENCES n'est pas du savoir (2026-07-27).
        # Mesure : les 82 chunks du job wj_ea26989e95 etaient en bonne part des
        # bibliographies arXiv brutes — « [162] X. Miao, Y. Wu, J. Wang, ... » — donc
        # non seulement hors sujet, mais structurellement inexploitables : que des
        # noms propres et des titres tronques, aucune proposition. Vectorises, ils
        # diluent le retrieval sans jamais rien pouvoir repondre.
        if _is_reference_list(content):
            logger.warning(f"[veille] skip liste de references: {r['url']}")
            n_skipped += 1
            continue

        base_id = "watch_" + hashlib.md5(r["url"].encode()).hexdigest()[:10]
        # LE THEME NE POLLUE PLUS LE CONTENANT (owner 2026-07-25). L'ancien code
        # prefixait CHAQUE chunk de « [VEILLE] Theme: <theme> / Keyword / Source /
        # URL / Pertinence », donc :
        #   - le vecteur du chunk melangeait la REQUETE (le theme) et le CONTENU, et
        #     toute requete proche du theme remontait l'integralite de la veille ;
        #   - `_audit_chunks_quality` comparait le theme a un texte qui CONTENAIT le
        #     theme -> mesure : similarite 0,61-0,78 sur les chunks entetes contre
        #     0,457-0,728 sur les corps seuls ; c'est ce biais qui a laisse passer
        #     « stock price crash risk » dans une veille Docker.
        # La provenance n'est pas perdue : elle vit dans les COLONNES (`source` =
        # URL, `role_hint` = veille:<theme>, `author`), que le retrieval renvoie
        # deja. La dupliquer dans le texte etait redondant ET nuisible.

        # CHUNKING (owner 2026-07-25 : « les veilles doivent servir l'intelligence »).
        # Avant : `text[:3000]` = UN chunk tronque par source. Un PDF arxiv extrait a
        # 55 000 caracteres par le tier PDF (MarkerConverter, prouve le 16/07) perdait
        # 52 000 caracteres, et son UNIQUE vecteur moyennait l'article entier -> la
        # veille servait a decouvrir des references, jamais a raisonner sur le fond.
        # On decoupe avec le chunker DEJA la (forge_rag_store.MarkdownChunker : headers
        # + overlap) et on embed chaque morceau. Chaque chunk reste auto-porteur grace
        # a l'en-tete recopie (theme/source/URL), sinon un morceau du milieu d'article
        # remonte au retrieval sans dire d'ou il vient.
        # On conserve les DICTS du chunker, pas seulement leur texte : il calcule
        # deja `header_path` (« ## Section > ### Sous-section ») et le jeter privait
        # le retrieval de la position du passage dans le document.
        pieces: list[dict] = []
        if len(content) > _INGEST_CHUNK_CHARS:
            try:
                from nokido_agent.app.forge_rag_store import MarkdownChunker

                pieces = [{"text": c["text"], "header_path": c.get("header_path"),
                           "level": c.get("level")}
                          for c in MarkdownChunker.chunk(
                              content, max_chunk_chars=_INGEST_CHUNK_CHARS,
                              overlap_chars=_INGEST_OVERLAP)
                          if (c.get("text") or "").strip()]
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[veille] chunker indisponible ({e}) -> tranches fixes")
        if not pieces:
            pieces = [{"text": content[i:i + _INGEST_CHUNK_CHARS]}
                      for i in range(0, len(content), _INGEST_CHUNK_CHARS)] or [{"text": content}]
        if len(pieces) > _INGEST_MAX_CHUNKS:
            logger.warning(f"[veille] {r['url']}: {len(pieces)} morceaux -> cap a "
                           f"{_INGEST_MAX_CHUNKS} (le reste n'est PAS ingere)")
            pieces = pieces[:_INGEST_MAX_CHUNKS]

        # URL CANONIQUE : le meme papier arrivait deux fois, en http:// par le chemin
        # academique et en https:// par le chemin biblio -> deux id md5 distincts, donc
        # un doublon invisible (mesure 2026-07-25 sur arxiv 2504.15965). La colonne
        # `canonical_id` existait et n'etait pas remplie ; un GROUP BY dessus suffit
        # desormais a voir les doublons. On normalise le protocole et le slash final,
        # PAS le numero de version (v1 != v2 : deux revisions differentes du papier).
        _canon = (r["url"] or "").strip()
        if _canon.startswith("http://"):
            _canon = "https://" + _canon[len("http://"):]
        _canon = _canon.rstrip("/")
        # Calcule UNE fois par source (identique pour tous ses morceaux).
        _entities = _extract_entities(r["url"], content)

        for _i, piece_d in enumerate(pieces):
            piece = piece_d["text"]
            # Un seul morceau -> id historique, pour ne pas dupliquer l'existant.
            cid = base_id if len(pieces) == 1 else f"{base_id}_{_i:02d}"
            text_chunk = piece

            # LE LEXICAL PRIME, LE VECTORIEL RAFFINE ENSUITE (doctrine owner 2026-07-25).
            # L'embed etait fait INLINE ici, un appel bloquant par morceau. Mesure du
            # jour : sous rattrapage, :8099 sature, les echecs retombaient en NULL sans
            # bruit et 2008 chunks du tier chaud se sont retrouves sans vecteur -- le
            # corpus etait cherchable en lexical mais aveugle au dense, sans que rien
            # ne le signale. L'ingestion doit donc GARANTIR le lexical (texte + rag_fts,
            # qui ne dependent de personne) et LAISSER la vectorisation a l'organe qui
            # sait la faire par lots : `tools/forge_embed_auto_trigger.py` draine
            # `embedding IS NULL AND HOT_TIER_SQL` via embed_batch_fast (les chunks de
            # veille sont `web-crawl`, donc dans HOT_ORIGINS -> bien repris).
            # Inline reste disponible en OPT-IN pour un ingest unitaire qu'on veut
            # immediatement dense : LAFORGE_VEILLE_EMBED_INLINE=1.
            emb_blob = None
            if _embed and _encode_blob and os.environ.get(
                    "LAFORGE_VEILLE_EMBED_INLINE", "0") == "1":
                for _try in range(2):
                    try:
                        vec = _embed(text_chunk)
                        if vec and len(vec) >= 256:
                            emb_blob = _encode_blob(vec)
                            break
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"inline embed KO chunk={cid} essai {_try + 1}: {e}")
                    if _try == 0:
                        time.sleep(1.5)
                if not emb_blob:
                    logger.warning(f"[veille] chunk sans vecteur apres 2 essais: {cid}"
                                   f" -- le daemon d'embedding le reprendra")

            # created_at renseigne (mesure 2026-07-25 : 97 % des chunks l'avaient NULL,
            # ce qui rend `forge_log_retention` aveugle et interdit toute mesure du
            # rendement d'une veille par date). Le decay du RAG lit ingested_at.
            # La table porte 26 colonnes pensees pour un retrieval structure ; l'ingest
            # n'en remplissait que 9 et laissait vides celles qui donnent du SENS au
            # vectoriel. On renseigne desormais :
            #   sequence_id     -> l'ORDRE du passage (avant : devine en parsant l'id)
            #   meta            -> titre, position i/n, header_path, mot-cle, pertinence
            #   hash            -> empreinte du corps (deduplication de contenu)
            #   canonical_id    -> URL normalisee (deduplication http/https)
            #   embedding_model -> toutes les routes du router servent BAAI/bge-m3 1024D ;
            #                      sans cette trace, un futur changement de modele rendrait
            #                      les anciens vecteurs incomparables SANS qu'on le sache
            _meta = json.dumps({
                "title": (r.get("title") or "")[:300],
                "chunk_index": _i,
                "n_chunks": len(pieces),
                "header_path": piece_d.get("header_path"),
                "keyword": r.get("keyword"),
                "relevance": r.get("relevance"),
                # Entites typees VERIFIABLES (cf. _extract_entities) : elles rendent
                # interrogeable « tous les chunks de tel papier », « ceux de telle
                # annee », sans dependre du texte du chunk.
                "entities": _entities,
            }, ensure_ascii=False)
            # AVANT l'INSERT OR REPLACE : l'id existait-il ? (PK, O(log n)). C'est ce
            # qui decide du DELETE FTS ci-dessous. Mesure 2026-09-05 : `rag_fts` est
            # un FTS5 AUTONOME dont `chunk_id` est UNINDEXED -> `DELETE ... WHERE
            # chunk_id=?` balaie les 2 M lignes, et on le faisait pour CHAQUE chunk,
            # y compris les ids NEUFS (cas nominal : suffixes `_i` d'une source jamais
            # chunkee) ou il n'y a rien a effacer. Un papier de 34 chunks = 34
            # balayages = le disque a 100 % pendant les backfills. Meme famille que
            # 8bcb4f6e (ingesteur GitHub, 04/08). Un orphelin FTS anterieur (chunk
            # retire de rag_chunks sans son FTS) n'est PAS couvert : c'est une
            # reconciliation d'infrastructure, pas 2 M lignes de scan par chunk.
            # L'ANCIEN texte est lu ici, avant l'INSERT OR REPLACE : c'est lui qui permet
            # de purger `rag_fts` par MATCH (`_purger_fts`) au lieu d'un balayage complet.
            _ancien = conn.execute(
                "SELECT text FROM rag_chunks WHERE id=? LIMIT 1", (cid,)).fetchone()
            _existait = _ancien is not None
            conn.execute(
                "INSERT OR REPLACE INTO rag_chunks(id,text,source,domain,role_hint,author,"
                "ingested_at,created_at,embedding,sequence_id,meta,hash,canonical_id,"
                "embedding_model) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, text_chunk, r["url"], "watch_veille", f"veille:{theme[:30]}",
                 "WatchAgent", now, now, emb_blob, _i, _meta,
                 hashlib.md5(piece.encode()).hexdigest(), _canon,
                 "bge-m3" if emb_blob else None),
            )
            # SYNC FTS5 (mesure 2026-07-25) : `rag_fts` n'a NI trigger NI cascade
            # depuis `rag_chunks` -- il se remplit a l'insertion, comme le fait deja
            # `forge_self_correction` pour ses lecons. Sans cette ligne, les chunks de
            # veille etaient trouvables en DENSE (via le vecteur) mais INVISIBLES en
            # lexical : une requete BM25 sur un concept interne a l'article rendait 0,
            # et la moitie du retrieval hybride etait perdue (verifie sur ce meme
            # papier avant correctif). OR IGNORE : un re-run ne duplique pas.
            # DELETE puis INSERT, jamais « OR IGNORE » : la table FTS n'a pas de clef
            # qui declenche un remplacement, donc `INSERT OR IGNORE` laissait en place
            # l'ANCIENNE version du texte quand un chunk etait reecrit. Mesure du jour :
            # apres depollution, `rag_chunks` etait propre mais une requete FTS renvoyait
            # encore l'en-tete « [VEILLE] Theme: ... ». Le lexical PRIME (doctrine owner),
            # il doit donc etre le plus frais, jamais un cache perime.
            try:
                if _existait:
                    # Reecriture d'un chunk connu : l'ancien texte FTS doit partir.
                    if _purger_fts(conn, cid, _ancien[0]):
                        logger.warning(f"[veille] {cid} : ancien texte sans mot exploitable,"
                                       " ligne FTS laissee a purge_rag_fts_fantomes")
                conn.execute(
                    "INSERT INTO rag_fts (chunk_id, text, source, domain)"
                    " VALUES (?, ?, ?, ?)",
                    (cid, text_chunk, r["url"], "watch_veille"),
                )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[veille] sync rag_fts KO chunk={cid}: {e}")

            n += 1   # NB : n compte desormais des CHUNKS, plus des sources.
    if n_skipped:
        logger.warning(f"[veille] job={job_id}: {n_skipped} resultat(s) rejete(s) (sans corps / corps duplique)")
    conn.commit()
    # Fix counter bug : COUNT(*) DB query plutot que increment local.
    # Evite ecrasement n_ingested=0 si re-run d'un job qui avait deja chunks.
    # Compte TOUS chunks de ce job via author='WatchAgent' + role_hint match theme.
    try:
        real_count = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE domain='watch_veille' AND role_hint=?", (f"veille:{theme[:30]}",)
        ).fetchone()[0]
    except Exception:
        real_count = n
    _update_job(conn, job_id, "store", "running", n_ingested=max(n, real_count))
    return n


def _audit_chunks_quality(conn, theme: str, threshold: float = 0.55,
                          k_mad: float = 3.0) -> dict:
    """Audit post-ingest : oubli SEMANTIQUE des chunks etrangers au theme.

    Un seuil ABSOLU seul ne marche pas -- mesure 2026-07-25. Calibre sur un survey
    ou le fosse etait net (3 pages de bibliographie a 0,21-0,23 contre 0,61-0,85 pour
    le corps), il a ensuite supprime 35 chunks sur 67 d'une source dont TOUTE la
    qualite tournait autour de 0,54 : la source etait homogene et modestement proche
    du theme, pas mauvaise. Le seuil n'est pas transposable d'un theme a l'autre,
    parce qu'il melange deux questions : « ce passage est-il hors-sujet ? » et « ce
    theme est-il lexicalement proche de son corpus ? ».

    D'ou une CONJONCTION : on n'oublie un chunk que s'il est a la fois
      (a) sous le plancher absolu `threshold`, et
      (b) un OUTLIER BAS de sa propre source : sous mediane - k_mad x MAD.
    Sur le survey, (a) et (b) ne retiennent que les 3 bibliographies. Sur la source
    homogene a 0,54, (b) descend le vrai seuil vers 0,30 et epargne le corps.
    Le cout des deux erreurs n'est pas symetrique : garder du bruit salit, amputer
    une source detruit.

    Returns {checked, dropped, kept, avg_quality, cut}.
    """
    try:
        import sys as _s, math

        _s.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_embed_router import embed as _emb, decode_blob as _dec
    except Exception:
        return {"skip": "embed_router unavailable"}

    theme_vec = _emb(theme[:1000])
    if not theme_vec:
        return {"skip": "theme embed fail"}

    role_hint = f"veille:{theme[:30]}"
    rows = conn.execute(
        "SELECT id, source, embedding FROM rag_chunks "
        "WHERE domain='watch_veille' AND role_hint=? AND embedding IS NOT NULL",
        (role_hint,),
    ).fetchall()
    if not rows:
        return {"checked": 0, "dropped": 0, "kept": 0}

    TRUST = {
        "doi.org/": 0.2,
        "arxiv.org/": 0.2,
        "openalex.org/": 0.2,
        "semanticscholar.org/": 0.2,
        "github.com/": 0.1,
        "reddit.com/": -0.15,
        "youtube.com/": -0.15,
        "google.com/ads": -0.3,
        "linkedin.com/": -0.1,
    }

    def _cos(a, b):
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na * nb else 0.0

    # 1re passe : on MESURE avant de supprimer (on ne peut pas juger un outlier sans
    # connaitre la distribution de sa source).
    scored: list[tuple[float, str]] = []
    for cid, src, blob in rows:
        vec = _dec(blob)
        if not vec:
            continue
        sim = _cos(theme_vec, vec)
        src_low = (src or "").lower()
        trust_bonus = 0.0
        for needle, w in TRUST.items():
            if needle in src_low:
                trust_bonus = w
                break
        scored.append((sim + trust_bonus, cid))
    if not scored:
        return {"checked": len(rows), "dropped": 0, "kept": len(rows)}

    qualities = sorted(q for q, _ in scored)
    _n = len(qualities)
    median = qualities[_n // 2] if _n % 2 else (qualities[_n // 2 - 1] + qualities[_n // 2]) / 2
    mad = sorted(abs(q - median) for q in qualities)[_n // 2] or 0.0
    # Seuil effectif = le PLUS BAS des deux (conjonction (a) et (b) ci-dessus).
    cut = min(threshold, median - k_mad * mad) if mad else threshold
    dropped = 0
    for q, cid in scored:
        if q < cut:
            # Ancien texte lu AVANT la suppression : purge FTS par MATCH (`_purger_fts`).
            _ancien = conn.execute("SELECT text FROM rag_chunks WHERE id=?", (cid,)).fetchone()
            conn.execute("DELETE FROM rag_chunks WHERE id=?", (cid,))
            try:
                if _ancien is not None:
                    _purger_fts(conn, cid, _ancien[0])
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[veille] purge FTS KO chunk={cid}: {e}")
            dropped += 1
    conn.commit()
    return {
        "checked": len(rows),
        "dropped": dropped,
        "kept": len(scored) - dropped,
        "avg_quality": round(sum(qualities) / _n, 3),
        "median": round(median, 3),
        "mad": round(mad, 3),
        "cut": round(cut, 3),
        "threshold": threshold,
    }


def _step_store(conn, job_id: str, theme: str, refined: list[dict], idea_id: str) -> int:
    """Insère dans biblio_raw les résultats de qualité >= 6."""
    n = 0
    # Pourquoi un candidat n'est PAS retenu : mesure 2026-07-22 — 3 articles arxiv
    # pertinents (relevance 8) refuses sans laisser la moindre trace, l'echec etant
    # avale par le logger.debug ci-dessous. Un refus muet est indiscernable d'une
    # veille a sec ; on enregistre donc le motif par candidat.
    _why: list[dict] = []
    for r in refined:
        _rel = r.get("relevance")
        if _rel is None:
            # NON NOTE : la notation a echoue, on ne SAIT pas si c'est pertinent.
            # Ce n'est ni un rejet de qualite ni une retention : c'est une piece a
            # PARQUER, dont le motif est nommable. `None` ne se compare pas a un
            # seuil (TypeError en Python 3) et ne doit surtout pas etre coerce en 0,
            # ce qui le ferait passer pour un jugement negatif.
            _why.append({"u": r.get("url"), "skip": "PARQUE: notation indisponible",
                         "parked": True})
            continue
        if _rel < 6:
            _why.append({"u": r.get("url"), "skip": "relevance<6"})
            continue
        try:
            import sys as _s

            _s.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_biblio_core import insert_biblio_raw  # type: ignore

            # CAUSE RACINE des veilles sans retention (diagnostic 2026-07-22) :
            # l'API arxiv renvoie des URL en http:// alors que EntrySchema exige
            # https:// -> insert_biblio_raw rejette en schema_invalid, et le rejet
            # etait muet. Consequence : TOUT resultat du chemin academique etait
            # perdu, quelle que soit sa pertinence (mesure : relevance 7-8 rejetes).
            # Normalisation au point d'entree unique, tous chemins de recherche.
            _url = str(r.get("url") or "")
            if _url.startswith("http://"):
                _url = "https://" + _url[len("http://"):]
            entry = {
                "type": "url",
                "title": r["title"],
                "url": _url,
                "description": r["content"][:300],
                "triggered_by_idea_id": idea_id,
                "source_kind": "agent_research",
                "authors": None,
                "year": None,
                "doi": None,
                "pdf_url": None,
            }
            res = insert_biblio_raw(entry)
            if res.get("ok"):
                n += 1
            else:
                _why.append({"u": r.get("url"),
                             "skip": str(res.get("reason") or res.get("error") or res)[:100]})
        except Exception as e:
            _why.append({"u": r.get("url"), "skip": "EXC %s: %s" % (type(e).__name__, str(e)[:70])})
            logger.debug(f"store skip: {e}")
    # INVARIANT DE RETENTION (audit 2026-07-22) — rapatrier puis ne RIEN garder n'est
    # pas un succes. Mesure : 16 veilles sur 69 rendaient status=completed avec
    # n_stored=0, sans aucune erreur pour le signaler ; le lot AI-safety du 24/06 est
    # ainsi perdu en silence. Un echec qui se declare reussi est pire qu'un echec.
    # Le statut distinct rend les 23 % visibles A L'INSTANT ou ils se produisent.
    _n_cand = len(refined or [])
    _empty = n == 0
    # DEJA-CONNU != A SEC (mesure 2026-07-22) : un rejeu dont tous les candidats
    # au-dessus du seuil sont refuses en duplicate_hash n'a pas echoue — la base
    # possede deja ces documents. completed_empty le comptait en faux rouge
    # (6 rejeux du 22/07 lus comme echecs alors que la retention etait acquise).
    _dups = [w for w in _why if "duplicate_hash" in str(w.get("skip", ""))]
    _hard = [w for w in _why
             if w.get("skip") != "relevance<6"
             and "duplicate_hash" not in str(w.get("skip", ""))]
    def _hard_reason(w) -> str:
        """Raison lisible d'un refus dur : `rejection_reason` plutot que le dict brut.

        Sans ca le message rendait « [{'id': 'blr_95e6bee', 'ok': False, » — tronque
        au milieu d'un repr, illisible et non regroupable. La seule chose qui compte
        au diagnostic est le MOTIF (mesure du jour : `url_blacklist`).
        """
        import re as _re
        sk = str(w.get("skip", ""))
        m = _re.search(r"'rejection_reason':\s*'([^']+)'", sk)
        return m.group(1) if m else sk[:40]

    _dedup = _empty and bool(_dups) and not _hard
    # n_ingested du job : il DEMENT souvent le mot « vide ». Lecture best-effort,
    # un compteur d'affichage ne doit jamais faire echouer la cloture du job.
    try:
        _row = conn.execute("SELECT n_ingested FROM watch_jobs WHERE id=?", (job_id,)).fetchone()
        _n_ing_trace = int(_row[0]) if _row and _row[0] is not None else 0
    except Exception:  # noqa: BLE001
        _n_ing_trace = -1
    # AUDITABILITE : le chemin ChainExecutor ne persistait aucun intermediaire
    # (keywords/search/refined NULL sur 100 % des jobs) -> provenance invérifiable
    # a posteriori. On gate une trace COMPACTE (titre/url/score, 20 max) : assez
    # pour rejouer et pour distinguer une veille a sec d'un filtrage legitime.
    _trace = json.dumps(
        {"candidats": [{"t": (r.get("title") or "")[:120], "u": r.get("url"),
                        "rel": r.get("relevance")} for r in (refined or [])][:20],
         "refus": _why[:20]},
        ensure_ascii=False,
    )
    _update_job(
        conn, job_id, "done",
        verdict_chaine(_nodes_du_job(conn, job_id), n, dedup=_dedup),
        n_stored=n,
        refined_json=_trace,
        # Le message d'origine ecrasait TROIS situations sous un « seuil OU insert
        # refuse » : deja-possede, sous-seuil, et refus dur. Mesure 2026-07-27 sur
        # 12 veilles dites vides : 22 duplicate_hash, 4 relevance<6, 2 url_blacklist
        # — soit 79 % de doublons. Le lecteur concluait « le seuil est trop haut »
        # (moi le premier) alors que les candidats notaient 10, 9, 8, 9, 6. On ne
        # pilote pas un tri dont on ignore le motif : on compte, et on le dit.
        # n_ingested est rappele car il DEMENT souvent le mot « vide » : le job
        # wj_df44dcf99f porte n_stored=0 et n_ingested=706.
        error=("RETENTION_ZERO: %d candidats refines, 0 retenu — "
               "%d deja possede(duplicate_hash), %d sous seuil(<6), %d refus dur%s"
               " ; %d chunks ingeres malgre tout"
               % (_n_cand, len(_dups), len(_why) - len(_dups) - len(_hard), len(_hard),
                  (" [" + ", ".join(sorted({_hard_reason(w) for w in _hard})) + "]")
                  if _hard else "",
                  _n_ing_trace))
        if (_empty and not _dedup) else None,
    )
    return n


# ── PIPELINE PRINCIPAL ─────────────────────────────────────────────────────────


def run_watch_job(job_id: str) -> dict:
    """
    OBSOLETE: La logique est maintenant dans ChainExecutor.
    Maintenu uniquement pour éviter des erreurs d'import si appelé ailleurs.
    """
    print(f"[WATCH] Job {job_id} délégué au ChainExecutor (agent_chain_nodes)")
    return {"ok": True, "job_id": job_id, "status": "delegated"}


def create_job(theme: str, idea_id: str = "veille_active", agent: str = "SYSTEM") -> str:
    """Crée un nouveau job via agent_chain_nodes."""
    import secrets

    chain_id = "wj_" + secrets.token_hex(5)
    now = datetime.now(tz=timezone.utc).isoformat()

    from nokido_agent.app.forge_db_path import write_retry

    nodes = [
        ("keywords", "KeywordAgent", "ollama", "keywords"),
        ("verify_kw", "VerifyAgent", "groq/llama-8b", "keywords_verified"),
        ("search", "SearchAgent", "native", "search_results"),
        ("refine", "RefineAgent", "groq/llama-70b", "refined"),
        ("crawl", "CrawlAgent", "native", "crawled_results"),
        ("ingest", "IngestAgent", "native", "n_ingested"),
        ("store", "StoreAgent", "native", "n_stored"),
    ]

    def _tx(conn):
        # Transaction EXPLICITE sur la connexion AUTOCOMMIT d'open_writer : l'atomicite
        # compte (une chaine a moitie creee serait reprise comme valide par l'executor).
        # Mais BEGIN IMMEDIATE + busy_timeout NE SUFFIT PAS quand un voisin (ingestion
        # RAG) tient une transaction plus longue -> « database is locked » et la veille
        # etait PERDUE (mesure 2026-07-28, curiosity_driver bloque au push). write_retry
        # REPREND tout le bloc sur verrou (backoff + jitter), fix prouve
        # forge_swarm_blackboard / RULES_SHARED. Seul un verrou est repris ; une
        # contrainte violee remonte tout de suite.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO watch_jobs(id,theme,idea_id,step,status,agent,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (chain_id, theme, idea_id, "keywords", "pending", agent, now, now),
        )
        conn.execute(
            "INSERT INTO agent_chain_context (chain_id, global_vars, updated_at) VALUES (?, ?, ?)",
            (chain_id, json.dumps({"theme": theme, "idea_id": idea_id}, ensure_ascii=False), now),
        )
        for i, (name, role, llm, out_key) in enumerate(nodes):
            node_id = f"node_{chain_id[:8]}_{name}"
            conn.execute(
                "INSERT INTO agent_chain_nodes (id, chain_id, step_index, step_name, agent_role, llm_preferred, output_key, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (node_id, chain_id, i, name, role, llm, out_key, "pending", now),
            )
        conn.execute("COMMIT")

    write_retry(_tx)

    print(f"[WATCH] Chain lancée: {chain_id} — {theme[:50]} (7 nodes créés)", flush=True)
    return chain_id


def list_jobs(limit: int = 20) -> list[dict]:
    """Liste les jobs récents avec leur état."""
    conn = _get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id,theme,step,status,n_ingested,n_stored,agent,created_at,updated_at,error "
        "FROM watch_jobs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resume_pending() -> list[str]:
    """
    OBSOLETE: Géré par la boucle autonome de ChainExecutor.
    """
    print("[WATCH] Reprise automatique gérée par ChainExecutor.")
    return []
