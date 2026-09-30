"""
forge_web_fetch.py - Fetcher + extracteur texte + ingestion RAG qualifiee
Pipeline: URL -> fetch HTML -> extract texte -> chunk -> qualifier -> rag_chunks
"""

import re, json, sqlite3, hashlib
import urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
DB = ROOT / "RAG" / "embeddings.db"


def extract_text(html: str) -> str:
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&[a-z]+;", " ", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def classify_url(url: str) -> tuple:
    """Retourne (domain, role_hint) qualifies selon l URL"""
    u = url.lower()
    if "modelcontextprotocol.io/specification" in u:
        ver = re.search(r"(\d{4}-\d{2}-\d{2})", u)
        section = u.split("/")[-1] or u.split("/")[-2]
        return "knowledge_mcp", f"mcp:spec:{ver.group(1) if ver else 'latest'}:{section}"
    if "modelcontextprotocol.io" in u:
        return "knowledge_mcp", "mcp:docs:" + u.split("/")[-1]
    if "searxng.org" in u:
        section = u.split("/")[-1] or "general"
        return "knowledge_searxng", f"searxng:docs:{section}"
    if "arxiv.org" in u:
        arxiv_id = re.search(r"(\d{4}\.\d+)", u)
        return "knowledge_papers", f"arxiv:{arxiv_id.group(1) if arxiv_id else 'unknown'}"
    if "github.com" in u:
        parts = u.replace("https://github.com/", "").split("/")
        return "knowledge_github", f"github:{'/'.join(parts[:3])}"
    if "docs." in u or "/docs/" in u or "/documentation" in u:
        domain_name = urllib.parse.urlparse(url).netloc.replace("www.", "").replace("docs.", "")
        return f"knowledge_{domain_name.split('.')[0]}", f"docs:{domain_name}"
    domain_name = urllib.parse.urlparse(url).netloc.replace("www.", "").split(".")[0]
    return f"web_{domain_name}", f"web:{domain_name}"


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        if len(chunk.strip()) > 100:
            chunks.append(chunk)
        i += chunk_size - overlap
    return chunks


# Ce module n'avait AUCUN logger : le durcissement SSRF ci-dessous en utilisait
# un, et la premiere execution a leve `NameError: name 'logger' is not defined`.
# Ni l'AST ni la relecture ne voient un nom non lie — seul l'appel le montre
# (meme famille que `os` contre `_os`, 2026-09-18). Un garde qui casse a son
# premier declenchement est une panne, pas une protection.
import logging as _logging  # noqa: E402

logger = _logging.getLogger(__name__)


def _url_interdite(url: str) -> str:
    """Rend le motif de refus, ou une chaine vide si l'adresse est admissible.

    Delegue a `tools.forge_web_egress._ssrf_blocked`, seule source de verite.
    Import DIFFERE : `forge_web_egress` importe ce module, un import en tete de
    fichier creerait un cycle.

    Fail-CLOSED sur le cas dangereux : si le garde complet est indisponible, on
    refuse quand meme l'hote local et on DIT que la verification etait reduite.
    Laisser passer reviendrait a ouvrir les 37 ports en boucle locale a une URL
    fournie par un tiers.
    """
    try:
        from nokido_agent.tools.forge_web_egress import _ssrf_blocked  # noqa: PLC0415

        motif = _ssrf_blocked(url)
        if not motif:
            return ""
        if isinstance(motif, str):
            return motif
        # `_ssrf_blocked` rend un booleen : on NOMME l'hote pour que le refus
        # soit diagnosticable. « interdite : interdite » n'aide personne.
        from urllib.parse import urlparse

        return "hote local ou prive (%s)" % ((urlparse(url).hostname or "?"))
    except Exception as e:  # noqa: BLE001
        from urllib.parse import urlparse

        hote = (urlparse(url).hostname or "").lower()
        logger.error("[web_fetch] garde SSRF indisponible (%s: %s) — repli minimal",
                     type(e).__name__, str(e)[:80])
        if hote in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or hote.startswith("127."):
            return "hote local refuse (garde complet indisponible)"
        return ""


def fetch_and_ingest(url: str, extra_role: str = "") -> dict:
    """Fetch URL -> extract -> chunk -> ingere dans RAG qualifie"""
    # SSRF — mesure du 2026-09-19 : ce module ne passait pas par le gateway
    # d'egress, alors qu'il recoit des URL de tiers (veille, payload MCP). Le
    # garde va sur l'organe qui AGIT, pas sur ses appelants.
    _refus = _url_interdite(url)
    if _refus:
        logger.warning("[web_fetch] refus SSRF sur %s — %s", url, _refus)
        return {"ok": False, "error": "adresse interdite : %s" % _refus, "chunks": 0}

    # Fetch
    try:
        req = urllib.request.Request(
            url,
            headers={
                # Les CDN (HuggingFace derriere Cloudflare, doi.org) repondent 40x
                # a tout agent qui ne ressemble pas a un navigateur. Mesure du
                # 2026-08-17 : 948 des 983 URLs manquantes sont des docs HF, toutes
                # en echec ici, alors que le crawl Crawl4AI du hub (navigateur reel)
                # sert la MEME page sans difficulte — 13 617 caracteres, 9 chunks.
                # Pages PUBLIQUES : aucun contournement d'authentification, et le
                # crawler reste identifiable par le suffixe LaForge-RAG.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 LaForge-RAG/1.0"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}

    title = extract_title(html)
    # Markdown ÉPURÉ (trafilatura, plus de texte brut) + firewall injection
    from nokido_agent.app.forge_crawl_tool import firewall_web, html_to_markdown

    md = html_to_markdown(html)
    md, injected = firewall_web(md, url)
    domain, role_hint = classify_url(url)
    if injected:  # page piégée -> domaine dédié + tag untrusted (RAG downweight)
        domain = "web_untrusted_" + domain.split("_", 1)[-1]
        role_hint = "untrusted:" + role_hint
    if extra_role:
        role_hint = extra_role + ":" + role_hint

    # Chunking structuré par headers markdown (préserve la sémantique)
    from nokido_agent.app.forge_rag_store import MarkdownChunker

    md_chunks = [
        c for c in MarkdownChunker.chunk(md, max_chunk_chars=2000, overlap_chars=200) if c.get("text", "").strip()
    ]
    if not md_chunks:
        return {"ok": False, "error": "no content extracted", "url": url}

    # timeout : la base est en WAL, donc un seul ECRIVAIN a la fois. Les daemons
    # du hub (COAGULATION, ORGAN_PULSE, POST_COMMIT...) ecrivent en continu ; sans
    # attente, la connexion abandonne des 5 s et rend « database is locked ».
    # Mesure du 2026-08-17 : c'est ce qui faisait echouer TOUTES les pages valides
    # d'une passe de rattrapage, en laissant croire a un probleme de crawl.
    conn = sqlite3.connect(str(DB), timeout=30)
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

    for i, c in enumerate(md_chunks[:20]):  # max 20 chunks par URL
        uid = f"wf_{url_hash}_{i:02d}"
        hpath = c.get("header_path", "")
        head = f"{title} — {hpath}" if hpath else title
        full = f"{head}\n\n{c['text']}"
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks "
            "(id,text,source,domain,role_hint,author,ingested_at) VALUES (?,?,?,?,?,?,?)",
            # 2026-09-12 : `full[:4000]` jetait la fin des pages crawlees sans
            # trace. `title[:100]` borne la colonne `author` et reste.
            (uid, full, url, domain, role_hint, title[:100] or url, now),
        )
        inserted += 1

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "url": url,
        "title": title,
        "domain": domain,
        "role_hint": role_hint,
        "chunks": inserted,
        "injected": injected,
        "md_len": len(md),
    }


if __name__ == "__main__":
    urls = [
        "https://modelcontextprotocol.io/specification/2025-11-25/basic/transports",
        "https://modelcontextprotocol.io/specification/2025-11-25/server/tools",
        "https://docs.searxng.org/dev/engines/json_engine.html",
        "https://modelcontextprotocol.io/specification/2025-11-25",
    ]
    for url in urls:
        r = fetch_and_ingest(url)
        if r["ok"]:
            print(f"OK  {r['chunks']:2d} chunks | {r['domain']:25s} | {r['title'][:50]}")
        else:
            print(f"ERR {url[:60]} -> {r['error']}")
