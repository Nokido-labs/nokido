"""
forge_source_discovery.py — Enrichissement RAG par découverte web ciblée
=========================================================================
Recherche des sources pertinentes sur le web et les injecte dans le RAG
de Nokido pour enrichir le contexte des mutations.

Sources supportées (sans clé API) :
  - DuckDuckGo Search (100% gratuit, pas de quota)
  - Extraction de contenu via trafilatura (texte propre depuis HTML)
  - Fallback BeautifulSoup si trafilatura échoue

Sources avec clé API (optionnel) :
  - Google Custom Search (100 req/jour gratuit)
  - Serper.dev (2500 req/mois gratuit)
  - Brave Search API (2000 req/mois gratuit)

Usage :
    from tools.forge_source_discovery import ForgeSourceDiscovery
    disc = ForgeSourceDiscovery()

    # Enrichir le RAG sur un sujet
    results = disc.discover_and_ingest(
        query="Python asyncio best practices performance",
        max_results=5,
        domain_filter=["docs.python.org", "realpython.com"],
    )

    # Chercher sans ingérer
    snippets = disc.search("DuckDB vs SQLite performance benchmarks", max_results=3)
    for r in snippets:
        print(r["title"], r["url"])
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
RAG_DIR = ROOT / "RAG"
DISCOVERY_CACHE = ROOT / "shadow_mutation" / "source_discovery_cache.jsonl"
EP_MEMORY = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"

# Domaines de confiance pour Nokido (bonus de priorité)
TRUSTED_DOMAINS = {
    "docs.python.org",
    "realpython.com",
    "stackoverflow.com",
    "github.com",
    "arxiv.org",
    "huggingface.co",
    "pytorch.org",
    "numpy.org",
    "duckdb.org",
    "sqlite.org",
    "ollama.com",
    "anthropic.com",
}

# Domaines à exclure (bruit SEO)
EXCLUDED_DOMAINS = {
    "pinterest.com",
    "quora.com",
    "reddit.com",
    "medium.com",
    "dev.to",
    "hashnode.com",
}


class ForgeSourceDiscovery:
    """Enrichit le RAG Nokido par découverte web ciblée."""

    def __init__(self, summary_model: str = "ollama/qwen2.5-coder:7b") -> None:
        """Initialise le moteur de découverte.

        Args:
            summary_model: Modèle LiteLLM pour la synthèse avant ingestion RAG.
                           Défaut : qwen2.5-coder:7b local (gratuit, rapide).
                           Exemples : "groq/llama-3.3-70b-versatile", "gemini/gemini-2.5-flash-lite"
        """
        DISCOVERY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        self._cache = self._load_cache()
        self._ingested = 0
        self._errors = 0
        self._summary_model = summary_model

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict]:
        """Charge le cache des URLs déjà découvertes.

        Returns:
            Dict URL → métadonnées.
        """
        cache: dict[str, dict] = {}
        if DISCOVERY_CACHE.exists():
            for line in DISCOVERY_CACHE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        entry = json.loads(line)
                        cache[entry.get("url", "")] = entry
                    except Exception:
                        pass
        return cache

    def _is_cached(self, url: str, max_age_days: int = 7) -> bool:
        """Vérifie si une URL est dans le cache et encore valide.

        Args:
            url:          URL à vérifier.
            max_age_days: Âge maximum du cache en jours.

        Returns:
            True si en cache et valide.
        """
        entry = self._cache.get(url)
        if not entry:
            return False
        ts = datetime.fromisoformat(entry.get("timestamp", "2000-01-01"))
        age = (datetime.now() - ts).days
        return age < max_age_days

    def _cache_url(self, url: str, meta: dict) -> None:
        """Enregistre une URL dans le cache.

        Args:
            url:  URL à cacher.
            meta: Métadonnées associées.
        """
        entry = {"url": url, "timestamp": datetime.now().isoformat(), **meta}
        self._cache[url] = entry
        with DISCOVERY_CACHE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── Recherche ─────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_results: int = 5,
        domain_filter: list[str] | None = None,
        backend: str = "duckduckgo",
    ) -> list[dict]:
        """Recherche des sources web pertinentes.

        Args:
            query:         Requête de recherche.
            max_results:   Nombre maximum de résultats.
            domain_filter: Limiter à certains domaines (ex: ['docs.python.org']).
            backend:       Moteur de recherche ('duckduckgo', 'google', 'serper').

        Returns:
            Liste de dicts {title, url, snippet, score}.
        """
        if backend == "duckduckgo":
            results = self._search_ddg(query, max_results * 2)
        elif backend == "google":
            results = self._search_google(query, max_results * 2)
        elif backend == "serper":
            results = self._search_serper(query, max_results * 2)
        elif backend == "arxiv":
            results = self._search_arxiv(query, max_results * 2)
        elif backend == "github":
            results = self._search_github(query, max_results * 2)
        elif backend == "pypi":
            results = self._search_pypi(query, max_results * 2)
        elif backend == "huggingface":
            results = self._search_huggingface(query, max_results * 2)
        else:
            # Auto : DDG d'abord, fallback GitHub si 0 résultats
            results = self._search_ddg(query, max_results * 2)
            if not results:
                results = self._search_github(query, max_results * 2)

        # Filtrer et scorer
        scored = []
        for r in results:
            host = urlparse(r.get("url", "")).netloc
            domain = host[4:] if host.startswith("www.") else host
            if domain in EXCLUDED_DOMAINS:
                continue
            if domain_filter and not any(d in r.get("url", "") for d in domain_filter):
                continue

            score = 1.0
            if domain in TRUSTED_DOMAINS:
                score += 0.5
            if query.lower().split()[0] in r.get("title", "").lower():
                score += 0.3

            scored.append({**r, "score": score, "domain": domain})

        scored.sort(key=lambda x: -x["score"])
        return scored[:max_results]

    def _search_ddg(self, query: str, max_results: int) -> list[dict]:
        """Recherche via DuckDuckGo (sans clé API).

        Args:
            query:       Requête de recherche.
            max_results: Nombre maximum de résultats bruts.

        Returns:
            Liste de résultats bruts.
        """
        try:
            from duckduckgo_search import DDGS  # noqa: PLC0415

            results = []
            with DDGS() as ddg:
                for r in ddg.text(query, max_results=max_results):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", "")[:500],
                        }
                    )
            return results
        except Exception as e:
            self._errors += 1
            print(f"  ⚠️  DDG search error: {e}")
            return []

    def _search_google(self, query: str, max_results: int) -> list[dict]:
        """Recherche via Google Custom Search API.

        Nécessite GOOGLE_API_KEY et GOOGLE_CSE_ID dans Nokido.env.

        Args:
            query:       Requête de recherche.
            max_results: Nombre maximum de résultats.

        Returns:
            Liste de résultats ou [] si clé absente.
        """
        env = (ROOT / "Nokido.env").read_text(encoding="utf-8", errors="replace")
        api_k = next(
            (
                l.split("=", 1)[1].strip()
                for l in env.splitlines()
                if l.startswith("GOOGLE_API_KEY=")
            ),
            None,
        )
        cse_id = next(
            (
                l.split("=", 1)[1].strip()
                for l in env.splitlines()
                if l.startswith("GOOGLE_CSE_ID=")
            ),
            None,
        )

        if not api_k or not cse_id:
            print("  ⚠️  GOOGLE_API_KEY/GOOGLE_CSE_ID absents — fallback DDG")
            return self._search_ddg(query, max_results)

        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {"key": api_k, "cx": cse_id, "q": query, "num": min(max_results, 10)}
            resp = httpx.get(url, params=params, timeout=10)
            items = resp.json().get("items", [])
            return [
                {"title": i["title"], "url": i["link"], "snippet": i.get("snippet", "")[:500]}
                for i in items
            ]
        except Exception:
            self._errors += 1
            return self._search_ddg(query, max_results)

    def _search_serper(self, query: str, max_results: int) -> list[dict]:
        """Recherche via Serper.dev (2500 req/mois gratuit).

        Nécessite SERPER_API_KEY dans Nokido.env.

        Args:
            query:       Requête de recherche.
            max_results: Nombre maximum de résultats.

        Returns:
            Liste de résultats ou [] si clé absente.
        """
        env = (ROOT / "Nokido.env").read_text(encoding="utf-8", errors="replace")
        api_k = next(
            (
                l.split("=", 1)[1].strip()
                for l in env.splitlines()
                if l.startswith("SERPER_API_KEY=")
            ),
            None,
        )

        if not api_k:
            return self._search_ddg(query, max_results)

        try:
            resp = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_k, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
                timeout=10,
            )
            items = resp.json().get("organic", [])
            return [
                {"title": i["title"], "url": i["link"], "snippet": i.get("snippet", "")[:500]}
                for i in items
            ]
        except Exception:
            self._errors += 1
            return self._search_ddg(query, max_results)

    # ── Extraction de contenu ─────────────────────────────────────────────────

    def extract_content(
        self,
        url: str,
        max_chars: int = 8000,
        use_crawl4ai: bool = True,
    ) -> str | None:
        """Extrait le contenu textuel propre d'une URL en Markdown.

        Priorité d'extraction :
          1. Crawl4AI (si Playwright installé) → Markdown propre, anti-bot
          2. trafilatura (httpx) → extraction légère sans navigateur
          3. BeautifulSoup → fallback minimal

        Args:
            url:          URL à extraire.
            max_chars:    Taille maximale du contenu extrait.
            use_crawl4ai: Tenter Crawl4AI en priorité.

        Returns:
            Contenu Markdown ou texte, ou None si impossible.
        """
        # ── Méthode 1 : Crawl4AI (Playwright) ────────────────────────────
        if use_crawl4ai:
            result = self._extract_crawl4ai(url, max_chars)
            if result:
                return result

        # ── Méthode 2 : trafilatura (httpx) ──────────────────────────────
        try:
            resp = httpx.get(
                url,
                follow_redirects=True,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (LaForge-RAG/1.0)"},
            )
            if resp.status_code == 200:
                try:
                    import trafilatura  # noqa: PLC0415

                    text = trafilatura.extract(
                        resp.text,
                        include_comments=False,
                        include_tables=True,
                        no_fallback=False,
                    )
                    if text and len(text) > 200:
                        return text[:max_chars]
                except Exception:
                    pass

                # ── Méthode 3 : BeautifulSoup ────────────────────────────
                from bs4 import BeautifulSoup  # noqa: PLC0415

                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = " ".join(soup.get_text(separator="\n").split())
                return text[:max_chars] if text else None

        except Exception:
            self._errors += 1

        return None

    def _extract_crawl4ai(self, url: str, max_chars: int) -> str | None:
        """Extraction via Crawl4AI (Playwright requis).

        Génère du Markdown propre depuis le HTML dynamique.
        Anti-bot intégré, gestion JS, extraction structurée.

        Args:
            url:       URL à crawler.
            max_chars: Taille maximale du contenu.

        Returns:
            Markdown ou None si Playwright absent/erreur.
        """
        import asyncio  # noqa: PLC0415

        try:
            from crawl4ai import AsyncWebCrawler  # noqa: PLC0415
            from crawl4ai.async_configs import CrawlerRunConfig  # noqa: PLC0415
            from crawl4ai.content_filter_strategy import PruningContentFilter  # noqa: PLC0415
            from crawl4ai.markdown_generation_strategy import (
                DefaultMarkdownGenerator,  # noqa: PLC0415
            )
        except ImportError:
            return None

        async def _crawl() -> str | None:
            config = CrawlerRunConfig(
                markdown_generator=DefaultMarkdownGenerator(
                    content_filter=PruningContentFilter(
                        threshold=0.45,
                        threshold_type="fixed",
                        min_word_threshold=20,
                    )
                ),
                word_count_threshold=30,
                exclude_external_links=True,
                remove_overlay_elements=True,
                wait_until="domcontentloaded",
                page_timeout=15000,
            )
            try:
                async with AsyncWebCrawler(headless=True, verbose=False) as crawler:
                    result = await crawler.arun(url, config=config)
                    if not result.success:
                        return None
                    md = result.markdown
                    if md is None:
                        return None
                    text = md if isinstance(md, str) else getattr(md, "raw_markdown", str(md))
                    return text[:max_chars] if text and len(text) > 100 else None
            except Exception:
                return None

        try:
            # Tenter d'utiliser la loop existante ou en créer une
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Context async → créer une task
                    import concurrent.futures  # noqa: PLC0415

                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, _crawl())
                        return future.result(timeout=20)
                else:
                    return loop.run_until_complete(_crawl())
            except RuntimeError:
                return asyncio.run(_crawl())
        except Exception:
            return None

    # ── Synthèse LiteLLM ─────────────────────────────────────────────────────

    async def _summarize_with_litellm(self, content: str, topic: str) -> str:
        """Résume le contenu web via LiteLLM avant ingestion RAG.

        Réduit le bruit HTML/web en Markdown technique dense.
        Utilise le modèle local (Ollama) par défaut — gratuit, sans quota.

        Args:
            content: Contenu brut extrait du web.
            topic:   Sujet technique pour guider la synthèse.

        Returns:
            Markdown synthétisé ou contenu brut si échec.
        """
        try:
            import litellm  # noqa: PLC0415

            print(f"  🧠 [LITELLM] Synthèse via {self._summary_model}...")
            resp = await litellm.acompletion(
                model=self._summary_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Tu es un documentaliste technique pour Nokido. "
                            "Extrais UNIQUEMENT : fonctions/classes clés, contraintes, "
                            "exemples de code, limitations. Format Markdown concis."
                        ),
                    },
                    {
                        "role": "user",
                        # Borne LEGITIME (fenetre du modele, max_tokens=1500) mais
                        # elle etait MUETTE : un contenu coupe ici produisait une
                        # analyse partielle indiscernable d'une analyse complete.
                        # La limite reste, elle se declare.
                        "content": (
                            f"Sujet : {topic}\nContenu :\n{content[:6000]}"
                            + ("\n\n[TRONQUE : %d caracteres sur %d transmis au "
                               "modele — l analyse ne porte PAS sur la fin du "
                               "document]" % (6000, len(content))
                               if len(content) > 6000 else "")
                        ),
                    },
                ],
                temperature=0.1,
                max_tokens=1500,
            )
            summary = resp.choices[0].message.content
            if summary and len(summary) > 100:
                ratio = round(len(content) / max(len(summary), 1), 1)
                print(f"  ✅ Synthèse : {len(content)}→{len(summary)} chars (×{ratio} compression)")
                return summary
        except Exception as e:
            print(f"  ⚠️  Synthèse échouée : {e} — contenu brut conservé")
        return content

    def summarize(self, content: str, topic: str) -> str:
        """Version synchrone de _summarize_with_litellm.

        Args:
            content: Contenu brut.
            topic:   Sujet.

        Returns:
            Contenu synthétisé.
        """
        import asyncio  # noqa: PLC0415

        try:
            return asyncio.run(self._summarize_with_litellm(content, topic))
        except Exception:
            return content

    async def _reverse_engineer_with_litellm(self, code: str, context: str) -> str:
        """Analyse un code opaque et reconstruit son intention via LiteLLM.

        Prompt spécialisé pour déobfuscation/documentation de code legacy
        ou minifié. Différence avec summarize : le modèle déduit l'intention
        plutôt que de résumer.

        Args:
            code:    Code source opaque, minifié ou mal documenté.
            context: Contexte d'origine (ex: 'lib legacy sans doc').

        Returns:
            Documentation Markdown reconstruite.
        """
        import litellm  # noqa: PLC0415

        system_prompt = (
            "Tu es un expert en reverse engineering Python pour Nokido. "
            "Face à un code opaque, minifié ou sans documentation, tu dois :\n"
            "1. Déduire l'intention réelle de chaque fonction/classe\n"
            "2. Proposer des noms de variables et fonctions explicites\n"
            "3. Identifier le pattern de design utilisé\n"
            "4. Lister les contraintes et effets de bord cachés\n"
            "5. Produire une documentation Markdown structurée\n"
            "Format : ## Intention | ## Fonctions clés | ## Contraintes | ## Exemple d'usage"
        )
        user_prompt = f"Contexte : {context}\nCode à analyser :\n```python\n{code[:10000]}\n```"

        # Ordre de priorité : modèle configuré → Groq (clé souvent dispo) → fallback
        candidates = [self._summary_model]
        env_path = Path(__file__).parent.parent / "Nokido.env"
        try:
            env_txt = env_path.read_text(encoding="utf-8", errors="replace")
            groq_key = next(
                (
                    l.split("=", 1)[1].strip()
                    for l in env_txt.splitlines()
                    if l.startswith("GROQ_API_KEY=") and len(l.split("=", 1)[1].strip()) > 10
                ),
                None,
            )
            if groq_key:
                import os

                os.environ.setdefault("GROQ_API_KEY", groq_key)
                candidates.append("groq/llama-3.3-70b-versatile")
        except Exception:
            pass

        for model in candidates:
            try:
                print(f"  🧬 [REVERSE] Analyse via {model}...")
                resp = await litellm.acompletion(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.15,
                    max_tokens=2000,
                )
                result = resp.choices[0].message.content
                if result and len(result) > 50:
                    print(f"  ✅ Reverse ({model}) : {len(code)} → {len(result)} chars")
                    return result
            except Exception as e:
                err = str(e)[:80]
                print(f"  ⚠️  {model} : {err}")
                continue

        return f"# Reverse Engineering\n\nCode source :\n```python\n{code}\n```"

    async def reverse_engineer_code(
        self,
        code: str,
        context: str = "Code inconnu",
        ingest: bool = True,
    ) -> dict:
        """Déobfusque un code opaque et l'indexe optionnellement dans le RAG.

        Cas d'usage :
          - Librairie sans documentation (ex: bytecode décompilé)
          - Code legacy avec noms de variables cryptiques (a, b, c...)
          - Code minifié ou auto-généré
          - Snippets extraits de binaires

        Args:
            code:    Code source à analyser.
            context: Description du contexte d'origine.
            ingest:  Si True, ingère la documentation dans le RAG.

        Returns:
            Dict avec 'doc' (Markdown), 'status', 'chars_in', 'chars_out'.
        """
        doc = await self._reverse_engineer_with_litellm(code, context)

        result = {
            "doc": doc,
            "status": "ok",
            "chars_in": len(code),
            "chars_out": len(doc),
            "context": context,
        }

        if ingest:
            ok = self.ingest_to_rag(
                content=doc,
                url=f"reverse://{context[:40].replace(' ', '_')}",
                title=f"[Reverse] {context[:60]}",
                query=context,
                meta={"mode": "reversed", "original_chars": len(code)},
            )
            result["ingested"] = ok

        return result

    def reverse_engineer_code_sync(
        self, code: str, context: str = "Code inconnu", ingest: bool = True
    ) -> dict:
        """Version synchrone de reverse_engineer_code.

        Args:
            code:    Code source à analyser.
            context: Contexte d'origine.
            ingest:  Ingérer dans le RAG.

        Returns:
            Dict avec 'doc', 'status', 'chars_in', 'chars_out'.
        """
        import asyncio  # noqa: PLC0415

        try:
            return asyncio.run(self.reverse_engineer_code(code, context, ingest))
        except Exception as e:
            return {"doc": code, "status": f"error: {e}", "chars_in": len(code)}

    # ── Ingestion RAG ─────────────────────────────────────────────────────────

    def ingest_to_rag(
        self,
        content: str,
        url: str,
        title: str,
        query: str,
        meta: dict | None = None,
    ) -> bool:
        """Injecte un contenu dans le RAG Nokido.

        Utilise forge_rag_engine si disponible, sinon écrit dans
        le fichier de texte externe du RAG.

        Args:
            content: Contenu textuel à ingérer.
            url:     URL source.
            title:   Titre de la page.
            query:   Requête qui a conduit à cette découverte.
            meta:    Métadonnées additionnelles.

        Returns:
            True si ingestion réussie.
        """
        if not content or len(content) < 100:
            return False

        # Essayer via forge_rag_engine (chemin officiel)
        try:
            import sys  # noqa: PLC0415

            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_rag_engine import RAGEngine  # noqa: PLC0415

            rag = RAGEngine()
            doc_id = hashlib.md5(url.encode()).hexdigest()[:12]
            rag.ingest_text(
                text=content,
                doc_id=f"web_{doc_id}",
                metadata={
                    "source": "web",
                    "url": url,
                    "title": title,
                    "query": query,
                    "ts": datetime.now().isoformat(),
                    **(meta or {}),
                },
            )
            self._ingested += 1
            return True
        except Exception:
            pass

        # Fallback : écriture dans RAG/external_sources.jsonl
        ext_file = RAG_DIR / "external_sources.jsonl"
        ext_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "url": url,
            "title": title,
            "query": query,
            # 2026-09-12 : DEFAUT. Cet enregistrement est PERSISTE (append JSONL),
            # c'est un artefact de veille — pas un affichage. Il stockait 4 000
            # caracteres tout en hashant le contenu COMPLET : le `hash` ne
            # correspondait donc pas au `content` conserve, et toute reprise
            # fondee sur lui repartait d'un texte ampute qu'elle croyait entier.
            "content": content,
            "hash": hashlib.md5(content.encode()).hexdigest(),
            **(meta or {}),
        }
        try:
            with ext_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._ingested += 1
            return True
        except Exception:
            return False

    # ── Pipeline principal ────────────────────────────────────────────────────

    def discover_and_ingest(
        self,
        query: str,
        max_results: int = 5,
        domain_filter: list[str] | None = None,
        backend: str = "duckduckgo",
        skip_cached: bool = True,
        max_chars: int = 6000,
        summarize: bool = False,
        verbose: bool = True,
    ) -> list[dict]:
        """Pipeline complet : recherche → extraction → [synthèse] → ingestion RAG.

        Args:
            query:         Requête de recherche ciblée.
            max_results:   Nombre maximum de sources à ingérer.
            domain_filter: Restreindre à certains domaines.
            backend:       Moteur de recherche.
            skip_cached:   Ignorer les URLs déjà traitées.
            max_chars:     Taille max du contenu extrait par source.
            summarize:     Si True, synthétise via LiteLLM avant ingestion.
                           Réduit tokens RAG de 3-5× mais nécessite Ollama actif.
            verbose:       Afficher la progression.

        Returns:
            Liste de résultats ingérés avec statut.
        """
        if verbose:
            print(f"🔍 [DISCOVERY] Recherche : '{query}' ({backend})")

        # 1. Recherche
        results = self.search(query, max_results, domain_filter, backend)

        if not results:
            print("  ⚠️  Aucun résultat trouvé")
            return []

        ingested = []
        for i, r in enumerate(results, 1):
            url = r.get("url", "")
            title = r.get("title", url)
            score = r.get("score", 1.0)

            if verbose:
                print(f"\n  [{i}/{len(results)}] {title[:60]}")
                print(f"  URL   : {url[:80]}")
                print(f"  Score : {score:.1f} | Domain: {r.get('domain', '?')}")

            # Skip cache
            if skip_cached and self._is_cached(url):
                if verbose:
                    print("  ⏭️  Déjà en cache — skip")
                continue

            # 2. Extraction du contenu
            content = self.extract_content(url, max_chars=max_chars)
            if not content:
                if verbose:
                    print("  ❌ Extraction impossible")
                self._cache_url(url, {"status": "extraction_failed", "title": title})
                continue

            if verbose:
                print(f"  📄 {len(content)} chars extraits")

            # 2b. Synthèse LiteLLM (optionnelle)
            if summarize and content:
                content = self.summarize(content, query)

            # 3. Ingestion RAG
            ok = self.ingest_to_rag(
                content=content,
                url=url,
                title=title,
                query=query,
                meta={"score": score, "snippet": r.get("snippet", "")},
            )

            status = "ingested" if ok else "failed"
            self._cache_url(url, {"status": status, "title": title, "query": query})

            ingested.append({**r, "content_len": len(content), "status": status})
            if verbose:
                print(f"  {'✅' if ok else '❌'} RAG {status}")

            # Pause polie entre les requêtes
            time.sleep(0.5)

        # 4. Log épisodique
        self._log_to_episodic(query, len(ingested), backend)

        if verbose:
            print(f"\n🎯 [DISCOVERY] {len(ingested)}/{len(results)} sources ingérées dans le RAG")

        return ingested

    def _log_to_episodic(self, query: str, n_ingested: int, backend: str) -> None:
        """Enregistre la session de découverte dans la mémoire épisodique.

        Args:
            query:      Requête utilisée.
            n_ingested: Nombre de sources ingérées.
            backend:    Moteur utilisé.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "source_discovery",
            "query": query,
            "n_ingested": n_ingested,
            "n_errors": self._errors,
            "backend": backend,
        }
        try:
            with EP_MEMORY.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── Backends APIs natives (sans clé) ─────────────────────────────────────

    def _search_arxiv(self, query: str, max_results: int) -> list[dict]:
        """Recherche sur Arxiv (papers ML/AI/CS).

        Args:
            query:       Requête de recherche.
            max_results: Nombre de résultats.

        Returns:
            Liste de résultats Arxiv.
        """
        import xml.etree.ElementTree as ET  # noqa: PLC0415

        try:
            r = httpx.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": f"all:{query}",
                    "max_results": max_results,
                    "sortBy": "relevance",
                },
                timeout=10,
            )
            root = ET.fromstring(r.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = []
            for entry in root.findall("atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                title = (title_el.text if title_el is not None else "") or ""
                summary = (summary_el.text if summary_el is not None else "") or ""
                # Lien HTML de l'article
                link = ""
                for lnk in entry.findall("atom:link", ns):
                    if lnk.get("type") == "text/html":
                        link = lnk.get("href", "")
                        break
                if not link:
                    for lnk in entry.findall("atom:link", ns):
                        link = lnk.get("href", "")
                        break
                items.append(
                    {"title": title.strip(), "url": link, "snippet": summary.strip()[:400]}
                )
            return items
        except Exception:
            self._errors += 1
            return []

    def _search_github(self, query: str, max_results: int) -> list[dict]:
        """Recherche de repositories GitHub.

        Args:
            query:       Requête de recherche.
            max_results: Nombre de résultats.

        Returns:
            Liste de repos GitHub.
        """
        try:
            r = httpx.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "order": "desc", "per_page": max_results},
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=10,
            )
            items = r.json().get("items", [])
            return [
                {
                    "title": f"{i['full_name']} ⭐{i['stargazers_count']}",
                    "url": i["html_url"],
                    "snippet": (i.get("description") or "")[:300],
                }
                for i in items
            ]
        except Exception:
            self._errors += 1
            return []

    def _search_pypi(self, query: str, max_results: int) -> list[dict]:
        """Recherche de packages PyPI.

        Args:
            query:       Nom ou description du package.
            max_results: Nombre de résultats.

        Returns:
            Liste de packages PyPI avec info de version.
        """
        try:
            r = httpx.get(
                "https://pypi.org/search/",
                params={"q": query, "o": "-zscore", "c": ""},
                headers={"Accept": "application/json"},
                timeout=10,
            )
            # PyPI retourne du HTML — parser le JSON de la page
            # Fallback : utiliser l'API JSON directe sur un package connu
            pkg_r = httpx.get(f"https://pypi.org/pypi/{query}/json", timeout=8)
            if pkg_r.status_code == 200:
                data = pkg_r.json()
                info = data.get("info", {})
                return [
                    {
                        "title": f"{info.get('name')} v{info.get('version')}",
                        "url": info.get("project_url", f"https://pypi.org/project/{query}"),
                        "snippet": (info.get("summary") or "")[:300]
                        + " | "
                        + (info.get("description") or "")[:200],
                    }
                ]
            return []
        except Exception:
            self._errors += 1
            return []

    def _search_huggingface(self, query: str, max_results: int) -> list[dict]:
        """Recherche de modèles HuggingFace.

        Args:
            query:       Nom ou tâche du modèle.
            max_results: Nombre de résultats.

        Returns:
            Liste de modèles HuggingFace.
        """
        try:
            r = httpx.get(
                "https://huggingface.co/api/models",
                params={
                    "search": query,
                    "limit": max_results,
                    "sort": "downloads",
                    "direction": -1,
                },
                timeout=10,
            )
            items = r.json()
            return [
                {
                    "title": i.get("modelId", "?"),
                    "url": f"https://huggingface.co/{i.get('modelId', '')}",
                    "snippet": f"Downloads: {i.get('downloads', 0):,} | Tags: {', '.join(i.get('tags', [])[:5])}",
                }
                for i in items
            ]
        except Exception:
            self._errors += 1
            return []

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def bulk_discover(
        self,
        queries: list[str],
        max_per_query: int = 3,
        verbose: bool = True,
    ) -> dict[str, list[dict]]:
        """Lance plusieurs recherches en séquence.

        Args:
            queries:       Liste de requêtes.
            max_per_query: Résultats max par requête.
            verbose:       Afficher la progression.

        Returns:
            Dict {query: [résultats ingérés]}.
        """
        all_results: dict[str, list[dict]] = {}
        for q in queries:
            all_results[q] = self.discover_and_ingest(q, max_results=max_per_query, verbose=verbose)
            time.sleep(1.0)  # Pause entre les requêtes
        return all_results

    @property
    def stats(self) -> dict:
        """Retourne les statistiques de la session.

        Returns:
            Dict avec ingested, errors, cached.
        """
        return {
            "ingested": self._ingested,
            "errors": self._errors,
            "cached": len(self._cache),
        }
