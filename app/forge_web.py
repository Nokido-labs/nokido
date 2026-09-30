"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_web
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_web.py — Recherche web pour La Forge
==========================================
Stack : duckduckgo-search (DDGS) + trafilatura (extraction contenu)
Fallback extraction : httpx + BeautifulSoup4 (déjà installés)

Pas de LangChain — trop lourd pour un besoin simple.
duckduckgo-search  : recherche sans API key
trafilatura        : extraction contenu HTML (remplace newspaper3k mort)
httpx              : HTTP/2 async natif (déjà présent)
beautifulsoup4     : fallback extraction (déjà présent)

Installation minimale :
    pip install duckduckgo-search trafilatura --break-system-packages
"""


import asyncio
import hashlib
import logging
import os as _os

# ── Flag global WEB_SEARCH ────────────────────────────────────────────────────
# OFF par défaut — activable depuis la TUI via @web on/off ou toggle_web_search()
# Peut aussi être forcé via env : LAFORGE_WEB_SEARCH=1
_WEB_SEARCH_ENABLED: bool = _os.environ.get("LAFORGE_WEB_SEARCH", "0") == "1"


def is_web_search_enabled(config: dict[str, object]) -> bool:
    """Retourne l'état actuel du flag web search."""
    return config.get("WEB_SEARCH_ENABLED", False)


def toggle_web_search(enabled: bool | None = None) -> bool:
    """
    Active/désactive la recherche web.
    Si enabled=None → bascule l'état actuel.
    Retourne le nouvel état.
    """
    global _WEB_SEARCH_ENABLED
    if enabled is None:
        _WEB_SEARCH_ENABLED = not _WEB_SEARCH_ENABLED
    else:
        _WEB_SEARCH_ENABLED = bool(enabled)
    import logging as _lg

    _lg.getLogger("Nokido.Web").info(f"[WebSearch] {'✅ ACTIVÉ' if _WEB_SEARCH_ENABLED else '⛔ DÉSACTIVÉ'}")
    return _WEB_SEARCH_ENABLED


import time
from collections import OrderedDict
from typing import List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# DÉPENDANCES — toutes optionnelles avec dégradé gracieux
# =============================================================================

try:
    from duckduckgo_search import DDGS

    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    logger.warning("duckduckgo_search non installé — pip install duckduckgo-search")

try:
    import trafilatura

    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    from bs4 import BeautifulSoup

    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# newspaper3k conservé pour compat si déjà installé, mais non requis
try:
    from newspaper import Article

    HAS_NEWSPAPER = True
except ImportError:
    HAS_NEWSPAPER = False

# =============================================================================
# CACHE LRU
# =============================================================================

_CACHE_TTL = 300  # secondes avant expiration
_CACHE_MAX = 64  # entrées max
_search_cache: OrderedDict = OrderedDict()


def _cache_key(query: str, max_results: int) -> str:
    """Cache key.

    Args:
        query: Description.
        max_results: Description.
    """
    return hashlib.md5(f"{query}|{max_results}".encode()).hexdigest()


def _cache_get(key: str) -> Optional[List[str]]:
    """Cache get.

    Args:
        key: Description.
    """
    if key not in _search_cache:
        return None
    ts, results = _search_cache[key]
    if time.monotonic() - ts > _CACHE_TTL:
        del _search_cache[key]
        return None
    _search_cache.move_to_end(key)
    return results


def _cache_set(key: str, results: List[str]) -> None:
    """Cache set.

    Args:
        key: Description.
        results: Description.
    """
    _search_cache[key] = (time.monotonic(), results)
    _search_cache.move_to_end(key)
    while len(_search_cache) > _CACHE_MAX:
        _search_cache.popitem(last=False)


# =============================================================================
# EXTRACTION DE CONTENU — trafilatura > bs4 > newspaper3k
# =============================================================================

# =============================================================================
# QUALITÉ DES SOURCES — whitelist / blacklist domaines
# =============================================================================

# Domaines documentaires de qualité — sources prioritaires pour @disco
_QUALITY_DOMAINS = frozenset(
    [
        "docs.python.org",
        "docs.docker.com",
        "kubernetes.io",
        "helm.sh",
        "docs.ansible.com",
        "registry.terraform.io",
        "docs.github.com",
        "docs.gitlab.com",
        "nginx.org",
        "httpd.apache.org",
        "wiki.archlinux.org",
        "debian.org",
        "ubuntu.com",
        "man7.org",
        "linux.die.net",
        "developer.mozilla.org",
        "devdocs.io",
        "github.com",
        "stackoverflow.com",
        "serverfault.com",
        "superuser.com",
        "packaging.python.org",
        "pypi.org",
        "aws.amazon.com",
        "cloud.google.com",
        "learn.microsoft.com",
        "grafana.com",
        "prometheus.io",
        "elastic.co",
    ]
)

# Domaines bloqués — inutile d'essayer (CF/WAF/JS-only)
_BLOCKED_DOMAINS = frozenset(
    [
        "medium.com",
        "substack.com",
        "dev.to",
        "towardsdatascience.com",
        "hackernoon.com",
        "reddit.com",
        "quora.com",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "facebook.com",
    ]
)

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
}


def _url_domain(url: str) -> str:
    """Url domain.

    Args:
        url: Description.
    """
    try:
        host = url.split("//", 1)[1].split("/")[0].lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _url_quality_score(url: str) -> int:
    """Score de priorité d'une URL (plus haut = meilleure qualité attendue)."""
    domain = _url_domain(url)
    if any(domain == d or domain.endswith("." + d) for d in _BLOCKED_DOMAINS):
        return -1
    if any(domain == d or domain.endswith("." + d) for d in _QUALITY_DOMAINS):
        return 10
    if "/docs/" in url or "readthedocs" in domain or domain.endswith(".io"):
        return 7
    if "/wiki/" in url or "/tutorial" in url or "/guide" in url:
        return 5
    return 3


# =============================================================================
# FETCH ARTICLE
# =============================================================================


def _get_proxy_url(name: str = "") -> str:
    """
    Retourne l'URL SOCKS5 du proxy Nokido.
    name="" → meilleur proxy disponible (nommé ou principal)
    name="vps-fr" → proxy nommé spécifique
    Import paresseux pour éviter la circularité.
    """
    try:
        import sys

        m = sys.modules.get("__main__") or sys.modules.get("Nokido")
        if name:
            fn = getattr(m, "get_proxy_url", None)
            return fn(name) if fn else ""
        else:
            # Préférer get_best_proxy_url si disponible
            fn = getattr(m, "get_best_proxy_url", None) or getattr(m, "get_proxy_url", None)
            return fn() if fn else ""
    except Exception:
        return ""


async def _fetch_article(url: str, timeout: int = 10) -> str:
    """
    Télécharge et extrait le contenu textuel d'une URL.
    - Ignore les domaines connus pour bloquer (Cloudflare, JS-only)
    - Headers réalistes pour éviter les refus 403
    - Proxy SOCKS5 utilisé si @proxy start est actif dans Nokido
    - Priorité : trafilatura (deduplicate=True) → bs4 → newspaper3k
    """
    if not url:
        return ""
    domain = _url_domain(url)
    if any(domain == d or domain.endswith("." + d) for d in _BLOCKED_DOMAINS):
        logger.debug(f"fetch: domaine bloqué ignoré {domain}")
        return ""

    loop = asyncio.get_event_loop()
    proxy_url = _get_proxy_url()  # vide si @proxy inactif

    def _extract_sync() -> str:
        """Extract sync."""
        html = ""
        if HAS_HTTPX:
            try:
                client_kwargs = dict(
                    timeout=timeout,
                    follow_redirects=True,
                    headers=_FETCH_HEADERS,
                    http2=True,
                )
                if proxy_url:
                    client_kwargs["proxy"] = proxy_url
                    logger.debug(f"fetch via proxy {proxy_url}: {domain}")
                with httpx.Client(**client_kwargs) as client:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        html = resp.text
                    elif resp.status_code in (403, 429, 451):
                        logger.debug(f"fetch {domain}: HTTP {resp.status_code}")
                        return ""
            except Exception as e:
                logger.debug(f"httpx {url[:60]}: {e}")

        if html and HAS_TRAFILATURA:
            try:
                text = trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False,
                    favor_precision=True,
                    deduplicate=True,
                )
                # 2026-09-12 : `[:4000]` coupait ICI, a la SOURCE, avant tout
                # chunking. Une page de 30 000 caracteres perdait 87 % de son
                # contenu, et c'etait INVISIBLE en base : le chunker redecoupe
                # les 4 000 restants en blocs de ~800, donc aucun chunk ne porte
                # la signature de la coupe. Une troncature en amont ne laisse
                # aucune trace en aval — c'est ce qui l'a fait survivre.
                if text and len(text) > 150:
                    return text
            except Exception as e:
                logger.debug(f"trafilatura {url[:60]}: {e}")

        if html and HAS_BS4:
            try:
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "button"]):
                    tag.decompose()
                paragraphs = [
                    p.get_text(strip=True)
                    for p in soup.find_all(["p", "li", "pre", "code"])
                    if len(p.get_text(strip=True)) > 40
                ]
                # 2026-09-12 : DEUX bornes cumulees ici — `[:40]` ne gardait que
                # les 40 premiers paragraphes (une doc technique en compte des
                # centaines), puis `[:4000]` recoupait le resultat. Le repli bs4
                # rendait donc systematiquement le HAUT de la page : menus,
                # introduction, et rien du corps technique.
                text = "\n".join(paragraphs)
                if text:
                    return text
            except Exception as e:
                logger.debug(f"bs4 {url[:60]}: {e}")

        if HAS_NEWSPAPER:
            try:
                article = Article(url)
                article.download()
                article.parse()
                if article.text:
                    return article.text
            except Exception as e:
                logger.debug(f"newspaper3k {url[:60]}: {e}")

        return ""

    return await loop.run_in_executor(None, _extract_sync)


# =============================================================================
# WEBSEARCHENGINE — singleton DDGS avec session persistante
# =============================================================================


class WebSearchEngine:
    """
    Moteur de recherche web.
    - Backend : DuckDuckGo (sans API key)
    - Extraction contenu : trafilatura > bs4 > newspaper3k
    - Cache LRU 5 min / 64 entrées
    - Singleton thread-safe
    """

    _instance: Optional["WebSearchEngine"] = None

    def __init__(self) -> None:
        """Init."""
        self._ddgs: Optional[DDGS] = None
        self._lock = asyncio.Lock()
        self._ready = HAS_DDGS

    @classmethod
    def get(cls) -> "WebSearchEngine":
        """Get.

        Args:
            cls: Description.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_ddgs(self) -> DDGS:
        """Get ddgs."""
        if self._ddgs is None:
            self._ddgs = DDGS()
        return self._ddgs

    async def search(
        self,
        query: str,
        max_results: int = 5,
        fetch_full: bool = False,
        fetch_content: bool = False,  # alias compat SmartRouter
        rerank: bool = False,  # réservé futur
    ) -> List[str]:
        """
        Recherche DuckDuckGo.
        fetch_full/fetch_content=True : extrait le contenu complet des pages (lent ~2s/page).
        fetch_full/fetch_content=False : snippets uniquement (rapide <200ms).
        """
        if not self._ready:
            logger.warning("WebSearchEngine: duckduckgo-search non installé")
            return []
        _fetch = fetch_full or fetch_content

        key = _cache_key(query, max_results)
        cached = _cache_get(key)
        if cached is not None:
            return cached

        async with self._lock:
            cached = _cache_get(key)
            if cached is not None:
                return cached

            try:
                loop = asyncio.get_event_loop()

                _proxy = _get_proxy_url()

                def _ddg_search() -> object:
                    """Ddg search."""
                    import time as _t

                    ddgs_kwargs = {}
                    if _proxy:
                        ddgs_kwargs["proxies"] = _proxy

                    # Tentative 1 : DDGS() frais (session propre)
                    for _attempt in range(2):
                        try:
                            _t.sleep(0.5 + _attempt * 1.5)  # backoff
                            ddgs = DDGS(**ddgs_kwargs)
                            items = list(ddgs.text(query, max_results=max_results))
                            if items:
                                # Filtrer le bruit (zhihu, baidu, etc.)
                                _noise = {"zhihu.com", "baidu.com", "weibo.com", "csdn.net", "cnblogs.com", "163.com"}
                                items = [it for it in items if not any(n in it.get("href", "") for n in _noise)]
                            if items:
                                return items
                        except Exception as e:
                            logger.debug(f"DDG tentative {_attempt + 1}: {e}")

                    # Fallback : fetch direct des URLs canoniques connues
                    logger.warning(f"DDG vide pour '{query}' — fallback URLs canoniques")
                    return _canonical_fallback(query)

                def _canonical_fallback(q: str) -> list:
                    """
                    Si DDG échoue, construire des URLs directement depuis
                    les sources canoniques connues selon les mots-clés.
                    """
                    q_low = q.lower()
                    urls = []
                    if "python" in q_low:
                        kw = (
                            q_low.replace("python", "").replace("documentation", "").strip().split()[0]
                            if len(q_low.split()) > 1
                            else ""
                        )
                        if kw:
                            urls.append(f"https://docs.python.org/3/library/{kw}.html")
                        urls.append("https://docs.python.org/3/")
                    if any(x in q_low for x in ["docker", "dockerfile", "compose"]):
                        urls.append("https://docs.docker.com/get-started/overview/")
                    if any(x in q_low for x in ["kubernetes", "kubectl", "helm", "k8s"]):
                        urls.append("https://kubernetes.io/docs/concepts/overview/")
                    if any(x in q_low for x in ["ansible"]):
                        urls.append("https://docs.ansible.com/ansible/latest/getting_started/")
                    if any(x in q_low for x in ["terraform"]):
                        urls.append("https://developer.hashicorp.com/terraform/intro")
                    if any(x in q_low for x in ["git", "github"]):
                        urls.append("https://docs.github.com/en/get-started")
                    if any(x in q_low for x in ["linux", "systemd", "bash", "shell"]):
                        urls.append("https://wiki.archlinux.org/title/General_recommendations")
                    if any(x in q_low for x in ["rust"]):
                        urls.append("https://doc.rust-lang.org/book/")
                        urls.append("https://doc.rust-lang.org/std/")
                    if any(x in q_low for x in ["go", "golang"]):
                        urls.append("https://go.dev/doc/")
                    if any(x in q_low for x in ["node", "nodejs", "javascript", "typescript"]):
                        urls.append("https://nodejs.org/en/docs/")
                        urls.append("https://developer.mozilla.org/en-US/docs/Web/JavaScript")
                    if any(x in q_low for x in ["sql", "postgres", "mysql", "sqlite"]):
                        urls.append("https://www.postgresql.org/docs/current/")
                    if any(x in q_low for x in ["nginx"]):
                        urls.append("https://nginx.org/en/docs/")
                    if any(x in q_low for x in ["redis"]):
                        urls.append("https://redis.io/docs/")
                    # Retourner comme items DDG factices pour le pipeline
                    return [{"href": u, "title": u, "body": ""} for u in urls[:3]]

                items = await loop.run_in_executor(None, _ddg_search)
                results: List[str] = []

                if _fetch:
                    # Trier les URLs par score de qualité avant fetch
                    items_sorted = sorted(items, key=lambda r: _url_quality_score(r.get("href", "")), reverse=True)
                    # Ignorer les URLs de domaines bloqués
                    items_sorted = [r for r in items_sorted if _url_quality_score(r.get("href", "")) >= 0]
                    urls = [item.get("href", "") for item in items_sorted[:4]]
                    texts = await asyncio.gather(*[_fetch_article(u) for u in urls], return_exceptions=True)
                    for item, text in zip(items[:3], texts):
                        if isinstance(text, str) and len(text) > 100:
                            title = item.get("title", "")
                            url = item.get("href", "")
                            results.append(f"[{title}]\n{text}\n{url}")
                    # Compléter avec snippets si moins de 3 résultats complets
                    for item in items[3:]:
                        snippet = item.get("body", "") or item.get("title", "")
                        if snippet:
                            results.append(f"[{item.get('title', '')}] {snippet}\n{item.get('href', '')}")
                else:
                    # Snippets uniquement
                    for item in items:
                        title = item.get("title", "")
                        snippet = item.get("body", "") or title
                        url = item.get("href", "")
                        if snippet:
                            results.append(f"[{title}] {snippet}\n{url}")

                _cache_set(key, results)
                logger.debug(
                    f"web_search '{query[:40]}' → {len(results)} résultats ({'contenu' if _fetch else 'snippets'})"
                )
                return results

            except Exception as e:
                logger.error(f"WebSearchEngine.search exception: {e}")
                self._ddgs = None
                return []

    def clear_cache(self) -> None:
        """Clear cache."""
        _search_cache.clear()

    @property
    def ready(self) -> bool:
        """Ready."""
        return self._ready and HAS_DDGS and _WEB_SEARCH_ENABLED

    # ------------------------------------------------------------------
    # Heuristique SmartRouter
    # ------------------------------------------------------------------

    _SEARCH_TRIGGERS = frozenset(
        [
            "actualité",
            "news",
            "récent",
            "dernier",
            "dernière",
            "maintenant",
            "aujourd",
            "today",
            "current",
            "latest",
            "recent",
            "update",
            "comment faire",
            "tutoriel",
            "tuto",
            "guide",
            "howto",
            "erreur",
            "bug",
            "solution",
            "stackoverflow",
            "github",
            "version",
            "release",
            "changelog",
            "prix",
            "disponible",
            "qu'est-ce",
            "c'est quoi",
            "définition",
            "documentation",
        ]
    )

    def should_search(self, text: str) -> bool:
        """Should search.

        Args:
            text: Description.
        """
        if not self._ready or not text:
            return False
        lower = text.lower()
        if "?" in text:
            return True
        words = set(lower.split())
        return bool(words & self._SEARCH_TRIGGERS)

    @staticmethod
    def format_for_prompt(results: List[str]) -> str:
        """Format for prompt.

        Args:
            results: Description.
        """
        if not results:
            return ""
        lines = ["[Sources web]"]
        for i, r in enumerate(results[:5], 1):
            snippet = r.strip()[:400].replace("\n", " ")
            lines.append(f"{i}. {snippet}")
        return "\n".join(lines)

    async def enrich_rag(self, rag_engine, results: List[str]) -> None:
        """Ingère les résultats web dans le RAG (enrichissement contextuel)."""
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        rag_engine = _ac.rag_engine
        if not rag_engine or not results:
            return
        try:
            combined = "\n\n".join(r[:1000] for r in results[:3] if r)
            if combined and hasattr(rag_engine, "add_session_message"):
                await rag_engine.add_session_message(
                    session="web_enrichment",
                    role="system",
                    content=combined,
                    meta={"source": "web_search", "type": "enrichment"},
                )
        except Exception as e:
            logger.debug(f"enrich_rag: {e}")

    @staticmethod
    def install_hint() -> str:
        """Message d'aide si les dépendances manquent."""
        missing = []
        if not _WEB_SEARCH_ENABLED:
            return []  # Web search désactivé — activer via @web on
        if not HAS_DDGS:
            missing.append("duckduckgo-search")
        if not HAS_TRAFILATURA:
            missing.append("trafilatura")
        if not missing:
            return ""
        return f"pip install {' '.join(missing)} --break-system-packages"


# =============================================================================
# INTERFACE PUBLIQUE
# =============================================================================


def get_web_engine() -> WebSearchEngine:
    """Get web engine."""
    return WebSearchEngine.get()


async def web_search(
    query: str,
    max_results: int = 5,
    fetch_full: bool = False,
) -> List[str]:
    """Interface principale — compatible avec _web_search_fn dans Nokido."""
    return await get_web_engine().search(query, max_results, fetch_full)


__all__ = ["WebSearchEngine", "web_search", "get_web_engine"]
