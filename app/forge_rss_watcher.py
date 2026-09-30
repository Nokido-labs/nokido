"""
forge_rss_watcher.py - Veille technologique autonome Nokido
=============================================================
Surveille : GitHub releases, PyPI, ArXiv, HuggingFace papers
Pipeline  : fetch -> ingest_pipeline L1-L3 -> RAG embeddings.db
Sortie    : COMMUNICATIONS.md + domain=watch_alerts/rag_research/ai_papers

Usage:
    python app/forge_rss_watcher.py          # run once
    python app/forge_rss_watcher.py --daemon  # boucle toutes les 6h
"""

from __future__ import annotations
import argparse, hashlib, json, logging, os, re, sqlite3, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.RSSWatcher")
ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
COMMS = ROOT / "COMMUNICATIONS.md"
DB_PATH = ROOT / "RAG" / "embeddings.db"
STATE = SANDBOX / "rss_watcher_state.json"
SANDBOX.mkdir(exist_ok=True)

# ── Cibles de veille ──────────────────────────────────────────────────────────

GITHUB_REPOS = [
    # Core deps Nokido
    "encode/starlette",
    "tiangolo/fastapi",
    "microsoft/onnxruntime",
    "huggingface/transformers",
    "abetlen/llama-cpp-python",
    "ggml-org/llama.cpp",
    "openai/tiktoken",
    "anthropics/anthropic-sdk-python",
    # RAG ecosystem
    "chroma-core/chroma",
    "qdrant/qdrant",
    "langchain-ai/langchain",
    "run-llama/llama_index",
    "microsoft/graphrag",
    # Agents / MCP
    "openai/openai-python",
]

PYPI_PACKAGES = [
    "starlette",
    "uvicorn",
    "anthropic",
    "tiktoken",
    "llama-cpp-python",
    "onnxruntime",
    "transformers",
    "chromadb",
    "sentence-transformers",
    "langchain",
]

ARXIV_QUERIES = [
    "Agentic RAG retrieval augmented generation 2025 2026",
    "GraphRAG knowledge graph hybrid retrieval",
    "prompt caching KV cache LLM inference",
    "chunking semantic late chunking embedding",
]

# Sites surveilles via fetch direct + diff (re-ingestion si contenu change).
# Format : (label, url, domain_hint, role_hint, summary)
# Le daemon poll toutes les 6h. Le forge_ingest_pipeline detecte les nouveautes.
#
# PRINCIPE intention-aware (cf. feedback delegate_local 2026-04-30) :
# On NE scrappe PAS les pages marketing/pricing (zero info technique).
# On cible : changelog (releases tech), docs API (architecture), blog tech (decisions),
# discussions techniques (forum/HN/youtube embed), changelogs comparatifs.
WATCH_URLS = [
    # === Gumloop : pages techniques uniquement ===
    (
        "gumloop_changelog",
        "https://www.gumloop.com/changelog",
        "ai_tools",
        "release_notes",
        "Gumloop changelog — nouvelles features tech",
    ),
    (
        "gumloop_docs_api",
        "https://docs.gumloop.com/api/quickstart",
        "ai_tools",
        "api_doc",
        "Gumloop API quickstart — endpoints/auth",
    ),
    (
        "gumloop_docs_intro",
        "https://docs.gumloop.com/getting-started/introduction",
        "ai_tools",
        "concept",
        "Gumloop concepts — node types, DAG model",
    ),
    # === Reverse-engineering par ANALOGIE : alternatives open-source du meme espace ===
    (
        "n8n_changelog",
        "https://docs.n8n.io/release-notes/",
        "ai_tools",
        "release_notes",
        "n8n release notes — patterns d execution workflow open-source",
    ),
    (
        "activepieces_chlog",
        "https://github.com/activepieces/activepieces/releases",
        "ai_tools",
        "release_notes",
        "Activepieces (open-source AI workflow) releases",
    ),
    (
        "windmill_blog",
        "https://www.windmill.dev/blog",
        "ai_tools",
        "tech_blog",
        "Windmill blog — patterns d orchestration scriptable",
    ),
    # === AMD RyzenAI — docs NPU/DML, changelog, migration guides ===
    (
        "ryzenai_docs",
        "https://ryzenai.docs.amd.com/en/latest/",
        "ryzenai",
        "api_doc",
        "AMD RyzenAI docs — NPU inference, ORT providers, quantization, migration",
    ),
    (
        "ryzenai_changelog",
        "https://ryzenai.docs.amd.com/en/latest/release_notes.html",
        "ryzenai",
        "release_notes",
        "AMD RyzenAI release notes — DML/VitisAI EP, vai_q_onnx, ryzen-ai conda",
    ),
]

# Queries SearXNG pour le worker biblio — chaque query est une INTENTION CROISEE
# entre le sujet (gumloop) et les centres d interet Nokido (multi-agent, MCP,
# RAG, local-first, DAG, secrets, observability). Le worker biblio_worker poll
# les biblio_raw queued, lance SearXNG, extrait les topics via laforge-qwen Ollama,
# et anchor dans le RAG. Aucun travail manuel cote Claude cloud.
WATCH_QUERIES_GUMLOOP = [
    "Gumloop AI no-code workflow architecture DAG execution engine",
    "Gumloop YC founders interview tech stack backend Max Brodeur-Urbas",
    "Gumloop vs n8n vs Make vs Zapier vs Activepieces vs Windmill comparison architecture",
    "no-code AI agent visual builder credentials vault secrets management pattern",
    "AI workflow versioning rollback retry pattern open-source LangChain alternative",
    "no-code automation platform LLM cost tracking caching observability",
    "MCP server integration no-code automation builder",
]

SINCE_DAYS = 7  # ignorer les releases > 7 jours

# Queries SearXNG pour veille technologique AMD RyzenAI / NPU / ORT
# Exécutées toutes les 6h via run(). Résultats ingestés si jamais vus.
WATCH_QUERIES_RYZENAI = [
    "AMD RyzenAI NPU ONNX Runtime DirectML quantization 2025 2026",
    "ryzen-ai-software conda ORT VitisAI ExecutionProvider update",
    "vai_q_onnx quantization BERT transformer NPU deployment",
    "AMD Ryzen AI 300 Phoenix NPU inference benchmark LLM edge",
    "ryzenai.docs.amd.com release changelog migration",
]

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8080")


# ── Fetchers ──────────────────────────────────────────────────────────────────


def _get(url: str, timeout: int = 10, headers: dict = None) -> str:
    try:
        h = {"User-Agent": "LaForge-Watcher/1.0", **(headers or {})}
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"fetch error {url}: {e}")
        return ""


def _searxng_search(query: str, n: int = 8) -> list[dict]:
    import urllib.parse

    params = urllib.parse.urlencode({"q": query, "format": "json", "categories": "general", "language": "en"})
    body = _get(f"{SEARXNG_URL}/search?{params}", timeout=10)
    if not body:
        return []
    try:
        data = json.loads(body)
        return data.get("results", [])[:n]
    except Exception:
        return []


def _github_token() -> dict:
    # Mesure 2026-09-19 : `get_secret` etait appele sans etre importe -> NameError
    # SYSTEMATIQUE, donc AUCUNE requete GitHub n'etait authentifiee (rate limit
    # anonyme). Le meme defaut avait deja ete corrige plus bas dans CE fichier,
    # avec un commentaire qui le decrit -- mais sur UNE porte seulement.
    # Un correctif ne vaut que par le nombre d'appels qu'il couvre.
    from nokido_agent.app.forge_secrets import get_secret  # noqa: PLC0415

    tok = get_secret("GITHUB_TOKEN") or ""
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def fetch_github_release(repo: str) -> dict | None:
    """Dernière release GitHub si publiée dans SINCE_DAYS."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    body = _get(url, headers=_github_token())
    if not body or body.startswith("ERR"):
        return None
    try:
        data = json.loads(body)
        pub = datetime.fromisoformat(data["published_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - pub).days
        if age > SINCE_DAYS:
            return None
        return {
            "repo": repo,
            "version": data.get("tag_name", ""),
            "title": data.get("name", ""),
            "body": data.get("body", "")[:3000],
            "url": data.get("html_url", ""),
            "date": data["published_at"],
            "age_days": age,
        }
    except Exception:
        return None


def fetch_pypi_release(package: str) -> dict | None:
    """Dernière version PyPI si publiée dans SINCE_DAYS."""
    url = f"https://pypi.org/pypi/{package}/json"
    body = _get(url)
    if not body:
        return None
    try:
        data = json.loads(body)
        info = data["info"]
        version = info["version"]
        # Trouver la date du dernier upload
        releases = data.get("releases", {}).get(version, [])
        if not releases:
            return None
        upload_time = releases[0].get("upload_time_iso_8601", "")
        if upload_time:
            pub = datetime.fromisoformat(upload_time.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - pub).days
            if age > SINCE_DAYS:
                return None
        return {
            "package": package,
            "version": version,
            "summary": info.get("summary", ""),
            "url": info.get("project_url", f"https://pypi.org/project/{package}/"),
            "date": upload_time,
        }
    except Exception:
        return None


def fetch_arxiv(query: str, max_results: int = 5) -> list[dict]:
    """Recherche ArXiv via API Atom."""
    q = urllib.request.quote(query)
    url = (
        f"https://export.arxiv.org/api/query?"
        f"search_query=all:{q}&sortBy=submittedDate"
        f"&sortOrder=descending&max_results={max_results}"
    )
    body = _get(url, timeout=15)
    if not body:
        return []

    results = []
    # Parse Atom XML minimal sans lxml
    entries = re.findall(r"<entry>(.*?)</entry>", body, re.DOTALL)
    cutoff = datetime.now(timezone.utc) - timedelta(days=SINCE_DAYS * 4)  # ArXiv = délai plus long

    for entry in entries:

        def tag(t: str) -> str:
            m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", entry, re.DOTALL)
            return m.group(1).strip() if m else ""

        published = tag("published")
        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if pub_dt < cutoff:
                continue
        except Exception:
            pass

        authors = re.findall(r"<name>(.*?)</name>", entry)
        results.append(
            {
                "arxiv_id": tag("id").split("/")[-1],
                "title": re.sub(r"\s+", " ", tag("title")),
                "abstract": re.sub(r"\s+", " ", tag("summary"))[:2000],
                "authors": ", ".join(authors[:3]),
                "published": published,
                "url": tag("id"),
            }
        )
    return results


# ── État persistant (anti-doublons inter-sessions) ────────────────────────────


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"seen": []}


def _save_state(state: dict):
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _already_seen(state: dict, uid: str) -> bool:
    return uid in state.get("seen", [])


def _mark_seen(state: dict, uid: str):
    seen = state.setdefault("seen", [])
    seen.append(uid)
    if len(seen) > 500:
        state["seen"] = seen[-400:]


# ── Verdict d'ingestion (C_06b, owner 2026-09-24) ────────────────────────────
# Mesure : depuis le 19/09, 34/34 releases vues ressortaient a « 0 chunk » ET etaient marquees
# vues quand meme -> perdues pour toujours, sans une ligne d'erreur. `_ingest` rendait 0 pour
# toute reponse non reconnue (« inconnu » lu comme « rien »). Protocole LU dans
# forge_mcp_registry (branche rag/ingest) : « ingest OK: N chunks -> M inseres » /
# « ingest: 0 chunks (...) » / « ingest error: ... ». Vocabulaire aligne sur verdict_bloc de la CI
# (qui vit dans ci_local : on ne tire pas la CI dans un demon). Seul INSERE marque « vu ».
INSERE, REJETE, ERREUR, INCONNU = "INSERE", "REJETE", "ERREUR", "INCONNU"


def _verdict_reponse(texte: str) -> tuple:
    """(statut, n, detail) d'une reponse de rag(action=ingest)."""
    t = texte or ""
    m = re.match(r"ingest OK: (\d+) chunks -> (\d+) inseres", t)
    if m and int(m.group(2)) > 0:
        return (INSERE, int(m.group(2)), t[:300])
    if m:
        # 0 insere sur N chunks : doublon deja present OU echec d'ecriture -- le protocole ne les
        # distingue pas ; « deja present » n'est pas ecrit, donc pas prouve : INCONNU, retente.
        return (INCONNU, 0, "0 inseres sur %s chunks : doublon OU echec, indistinguables" % m.group(1))
    if t.startswith("ingest: 0 chunks"):
        return (REJETE, 0, t[:300])
    if t.startswith("GATE_DENIED"):
        # Refus EXPLICITE du gate du hub, observe en production le 24/09 22:35 :
        # « GATE_DENIED: ring:ring 4 <= requis 3 » (identite SERVICES). Rejete, pas inconnu ;
        # toujours rejouable. La politique d'acces n'est PAS modifiee ici (decision owner).
        return (REJETE, 0, t[:300])
    if t.startswith("ingest error:"):
        return (ERREUR, 0, t[:300])
    return (INCONNU, 0, "reponse non reconnue : %s" % (t[:300] or "<vide>"))


def _marquer_si_succes(state: dict, uid: str, verdict: tuple, etiquette: str = "") -> bool:
    """Marque `uid` vu SEULEMENT si l'ingestion est prouvee ; sinon le DIT et le laisse rejouable."""
    statut, _n, detail = verdict
    if statut == INSERE:
        _mark_seen(state, uid)
        return True
    logger.warning("[watch] %s %s : %s -- NON marque vu, retente au prochain cycle",
                   statut, etiquette or uid, detail)
    return False


# ── Conversion -> RefinedChunk via ingest_pipeline ───────────────────────────


def _ingest(text: str, source: str, domain: str, role: str, author: str, summary: str) -> tuple:
    """
    Passe le texte dans le hub MCP rag(action=ingest). Rend un VERDICT (statut, n, detail).
    Option B retenue : hub local 8766 -> store_chunks -> BM25 lazy rebuild.
    Zéro dépendance forge_app_context depuis le daemon standalone.
    """
    import urllib.request, json as _j

    # token : jeton A BAIL (1800 s, revocable) echange contre le credential
    # statique, qui reste le secret d'echange sans plus etre le bearer presente.
    # Un statique est PERMANENT : ni expiration, ni revocation (2026-09-02).
    #
    # Le `except` d'origine rappelait `get_secret` alors que l'import venait
    # d'echouer : ce chemin d'erreur levait NameError au lieu de rattraper quoi
    # que ce soit. Chaque repli est desormais DIT, avec sa consequence.
    token = ""
    try:
        from nokido_agent.app.forge_agent_credential import jeton_pour

        token = jeton_pour("SERVICES")
    except Exception as _e:  # noqa: BLE001
        logger.info("[rss_watcher] pont jeton a bail indisponible (%s) — repli "
                    "sur le credential statique, PERMANENT donc non revocable",
                    type(_e).__name__)
    if not token:
        try:
            from nokido_agent.app.forge_secrets import get_secret

            token = get_secret("FORGE_TOKEN_SERVICES") or ""
        except Exception as _e:  # noqa: BLE001
            logger.warning(
                "[rss_watcher] credential illisible (%s) — l'appel partira SANS "
                "jeton et sera rejete en 401 | remede: provisionner "
                "FORGE_TOKEN_SERVICES au coffre", type(_e).__name__)
            token = ""
    body = _j.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "rag",
                "arguments": {
                    "action": "ingest",
                    "text": text,
                    "source": source,
                    "domain": domain,
                    "role": role,
                    "author": author,
                    "summary": summary,
                },
            },
        }
    ).encode()
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8766/mcp",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Agent-Name": "SERVICES",
                "Authorization": f"Bearer {token}",
            },
        )
        r = urllib.request.urlopen(req, timeout=60)
        rep = _j.loads(r.read())
        if rep.get("error"):
            return (ERREUR, 0, "erreur JSON-RPC : %s" % str(rep["error"])[:300])
        result = ((rep.get("result") or {}).get("content") or [{}])[0].get("text", "")
        return _verdict_reponse(result)
    except urllib.error.HTTPError as e:
        # Le hub REPOND et REFUSE (401/403/...) : surtout pas de repli direct -- ce serait
        # contourner son autorisation par un ecrivain de plus sur la base RAG.
        return (REJETE, 0, "hub HTTP %s : %s" % (e.code, str(e)[:200]))
    except Exception as e:
        logger.warning(f"[watcher] hub ingest error: {e}")
        # Repli direct si hub INJOIGNABLE seulement (connexion refusee, delai depasse)
        try:
            from nokido_agent.app.forge_ingest_pipeline import process_document, store_chunks

            chunks = process_document(
                text=text, source=source, domain_hint=domain, role_hint=role, author=author, doc_summary=summary
            )
            n = store_chunks(chunks) if chunks else 0
            if n:
                return (INSERE, n, "repli direct (hub injoignable)")
            return (INCONNU, 0, "repli direct : 0 stocke (doublon OU echec, indistinguables)")
        except Exception as e2:
            logger.error(f"[watcher] fallback store error: {e2}")
            return (ERREUR, 0, "repli direct en echec : %s" % str(e2)[:200])


# ── Run veille ────────────────────────────────────────────────────────────────


def run_watch(since_days: int = SINCE_DAYS) -> dict:
    """
    Lance un cycle complet de veille.
    Retourne un résumé {ingested, alerts, repos_checked, ...}.
    """
    global SINCE_DAYS
    SINCE_DAYS = since_days

    state = _load_state()
    ingested = 0
    alerts = []  # tuples (type, name, version, role)

    # ── GitHub releases ───────────────────────────────────────────────────────
    logger.info(f"[watch] GitHub releases ({len(GITHUB_REPOS)} repos)")
    for repo in GITHUB_REPOS:
        uid = f"gh:{repo}"
        rel = fetch_github_release(repo)
        if not rel:
            continue
        ver_uid = f"{uid}:{rel['version']}"
        if _already_seen(state, ver_uid):
            continue
        body = rel["body"] or f"{repo} {rel['version']} released."
        role = _infer_release_role(body)
        v = _ingest(
            text=f"{rel['title']}\n\n{body}",
            source=rel["url"],
            domain="watch_alerts",
            role=role,
            author=repo,
            summary=f"{repo} {rel['version']} ({rel['age_days']}d ago)",
        )
        n = v[1]
        ingested += n
        _marquer_si_succes(state, ver_uid, v, f"{repo} {rel['version']}")
        if "breaking" in role or "security" in role:
            alerts.append(("GITHUB", repo, rel["version"], role))
        logger.info(f"  [{role}] {repo} {rel['version']} -> {n} chunks")
        time.sleep(0.5)  # rate limit GitHub API

    # ── PyPI releases ─────────────────────────────────────────────────────────
    logger.info(f"[watch] PyPI packages ({len(PYPI_PACKAGES)} packages)")
    for pkg in PYPI_PACKAGES:
        uid = f"pypi:{pkg}"
        rel = fetch_pypi_release(pkg)
        if not rel:
            continue
        ver_uid = f"{uid}:{rel['version']}"
        if _already_seen(state, ver_uid):
            continue
        v = _ingest(
            text=f"{pkg} {rel['version']}: {rel['summary']}",
            source=rel["url"],
            domain="watch_alerts",
            role="release:pypi",
            author=pkg,
            summary=f"PyPI {pkg} {rel['version']}",
        )
        n = v[1]
        ingested += n
        _marquer_si_succes(state, ver_uid, v, f"pypi {pkg} {rel['version']}")
        logger.info(f"  [pypi] {pkg} {rel['version']} -> {n} chunks")
        time.sleep(0.3)

    # ── ArXiv papers ──────────────────────────────────────────────────────────
    logger.info(f"[watch] ArXiv ({len(ARXIV_QUERIES)} queries)")
    for query in ARXIV_QUERIES:
        papers = fetch_arxiv(query)
        for p in papers:
            uid = f"arxiv:{p['arxiv_id']}"
            if _already_seen(state, uid):
                continue
            v = _ingest(
                text=f"{p['title']}\n\n{p['abstract']}",
                source=p["url"],
                domain="ai_papers",
                role="paper:abstract",
                author=p["authors"],
                summary=p["title"][:120],
            )
            n = v[1]
            ingested += n
            _marquer_si_succes(state, uid, v, f"arxiv {p['arxiv_id']}")
            logger.info(f"  [arxiv] {p['arxiv_id']} -> {n} chunks")
        time.sleep(1)

    # ── SearXNG queries (veille rapide) ──────────────────────────────────────
    logger.info(f"[watch] SearXNG queries ({len(WATCH_QUERIES_RYZENAI)} queries)")
    for query in WATCH_QUERIES_RYZENAI:
        results = _searxng_search(query, n=8)
        for r in results:
            url = r.get("url", "")
            if not url:
                continue
            uid = f"searxng:{hashlib.sha256(url.encode()).hexdigest()[:12]}"
            if _already_seen(state, uid):
                continue
            title = r.get("title", "")
            snippet = r.get("content", "")
            text = f"{title}\n\n{snippet}\n\nURL: {url}"
            v = _ingest(
                text=text, source=url, domain="ryzenai", role="watch:searxng", author=query[:60], summary=title[:100]
            )
            n = v[1]
            ingested += n
            _marquer_si_succes(state, uid, v, f"searxng {title[:40]}")
            if n:
                logger.info(f"  [searxng] {title[:60]} -> {n} chunks")
        time.sleep(1)

    # ── Sites surveilles (WATCH_URLS) ─────────────────────────────────────────
    # Fetch + sha256 diff. Re-ingestion uniquement si contenu change.
    logger.info(f"[watch] Sites surveilles ({len(WATCH_URLS)} URLs)")
    for label, url, domain, role, summary in WATCH_URLS:
        try:
            html = _get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 Nokido-watcher/1.0"})
            if not html:
                logger.info(f"  [watch_url] {label}: fetch vide (skip)")
                continue
            # Diff par hash : skip si le contenu n'a pas change depuis le dernier cycle
            content_hash = hashlib.sha256(html.encode("utf-8", "replace")).hexdigest()[:16]
            uid = f"watch:{label}:{content_hash}"
            if _already_seen(state, uid):
                logger.debug(f"  [watch_url] {label}: hash inchange, skip")
                continue
            # Strip HTML grossier pour ingerer du texte
            text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()[:50000]
            v = _ingest(
                text=f"{summary}\n\nURL: {url}\n\n{text}",
                source=url,
                domain=domain,
                role=role,
                author=label,
                summary=summary,
            )
            n = v[1]
            ingested += n
            _marquer_si_succes(state, uid, v, f"watch_url {label}")
            logger.info(f"  [watch_url] {label} (hash={content_hash}) -> {n} chunks")
        except Exception as e:
            logger.warning(f"  [watch_url] {label} fetch err: {e}")
        time.sleep(0.5)

    _save_state(state)

    summary = {
        "ts": datetime.now().isoformat(),
        "ingested": ingested,
        "alerts": len(alerts),
        "repos_checked": len(GITHUB_REPOS),
        "pypi_checked": len(PYPI_PACKAGES),
        "arxiv_queries": len(ARXIV_QUERIES),
        "watch_urls": len(WATCH_URLS),
        "searxng_queries": len(WATCH_QUERIES_RYZENAI),
        "breaking_alerts": [f"{t} {n} {v}" for t, n, v, _ in alerts],
    }
    logger.info(f"[watch] DONE: {ingested} chunks ingérés, {len(alerts)} alertes")
    return summary


def _infer_release_role(body: str) -> str:
    b = body.lower()
    if any(x in b for x in ["breaking", "removed", "deprecated", "migration required"]):
        return "release:breaking_change"
    if any(x in b for x in ["security", "cve", "advisory", "vulnerability"]):
        return "alert:security"
    if any(x in b for x in ["fix", "bug", "patch", "resolved"]):
        return "release:bugfix"
    return "release:feature"


# ── Rapport COMMUNICATIONS.md ─────────────────────────────────────────────────


def write_report(summary: dict):
    """Écrit un bloc de rapport dans COMMUNICATIONS.md."""
    ts = summary["ts"][:16]
    alerts = summary.get("breaking_alerts", [])
    alert_str = "\n".join(f"  - {a}" for a in alerts) if alerts else "  (aucune)"

    block = (
        f"\n### [WATCHER @ {ts}]\n"
        f"**Cycle veille technologique**\n\n"
        f"- Chunks ingérés : {summary['ingested']}\n"
        f"- Repos GitHub vérifiés : {summary['repos_checked']}\n"
        f"- Packages PyPI vérifiés : {summary['pypi_checked']}\n"
        f"- Queries ArXiv : {summary['arxiv_queries']}\n"
        f"- Alertes breaking : {summary['alerts']}\n"
        f"\n**Alertes prioritaires :**\n{alert_str}\n\n---\n"
    )
    try:
        with COMMS.open("a", encoding="utf-8") as f:
            f.write(block)
        logger.info("[watch] rapport écrit dans COMMUNICATIONS.md")
    except PermissionError:
        # Compte sandbox sans write à la racine du repo -> fallback dans
        # sandbox/ (writable). Non-fatal : le rapport est secondaire, un
        # daemon ne doit pas crash-looper pour un fichier de rapport.
        fallback = COMMS.parent / "sandbox" / "rss_watcher_report.md"
        try:
            with fallback.open("a", encoding="utf-8") as f:
                f.write(block)
            logger.warning(f"[watch] COMMUNICATIONS.md non accessible -> rapport dans {fallback}")
        except OSError as e:
            logger.warning(f"[watch] rapport non écrit (racine + sandbox KO) : {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)5s %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true", help="boucle toutes les 6h")
    ap.add_argument("--interval", type=int, default=360, help="intervalle en minutes")
    ap.add_argument("--days", type=int, default=7, help="fenêtre temporelle en jours")
    args = ap.parse_args()

    if args.daemon:
        # Le pouls suit le rythme du COEUR ; la passe de veille reste une fonction
        # lente (6 h par defaut). Avant cette bascule, l'organe ne battait qu'une fois
        # par passe pour un seuil de supervision de 3600 s : il etait declare fige
        # entre deux passes alors qu'il attendait normalement.
        #
        # Rappel de ce qui reste vrai (mesure 2026-07-28) : ce daemon ecrivait
        # `rss_watcher_state.json`, un fichier d'ETAT, que le capteur de sante lisait
        # comme un pouls sans y trouver de champ `ts` -- il le declarait MORT alors
        # qu'il tournait. Un fichier d'etat n'est pas un pouls.
        from nokido_agent.app.forge_heartbeat import Cadence

        logger.info(f"[watch] daemon mode -- interval={args.interval}min")
        cad = Cadence("rss_watcher", cycle_s=args.interval * 60)
        while True:
            if cad.tour():
                summary = run_watch(since_days=args.days)
                write_report(summary)
                cad.cycle_termine(ok=True)
            cad.dormir()
    else:
        summary = run_watch(since_days=args.days)
        write_report(summary)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
