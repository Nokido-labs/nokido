# [HANDOFF] — UNIFICATION DE NOKIDO & BOOT PHYSIOLOGIQUE (V2)
**Date :** 2026-05-04
**De :** Gemini (Architecte Holistique)
**À :** Claude (Chirurgien / Master Architect)

## 🎯 OBJECTIFS ATTEINTS
Nous avons transformé Nokido d'un amas de 17 services NSSM disparates en un **organisme unifié** piloté par un seul superviseur Deno maître.

### 1. 🧬 NOUVEAU SYSTÈME NERVEUX (`supervisor.ts`)
J'ai réécrit `LaForge\proxy_deno\core\supervisor.ts` pour implémenter un **Séquençage de Boot en 5 Vagues Physiologiques** :
- **Vague 1 (Tronc Cérébral) :** Hub Python (:8766), Ollama (:11434), NetcfgMCP.
- **Vague 2 (Système Nerveux) :** Proxies Deno (:8000) et Hub MCP (:8769).
- **Vague 3 (Cervelet & Sondes) :** Homeostasis (3.14) et **Brain Worker** (Python 3.12 NPU Ryzen AI).
- **Vague 4 (Cortex Cognitif) :** Hebbian, Graph, GeminiDaemon et Heavy LLMs.
- **Vague 5 (Interface) :** WebHub, RSSWatcher et Capture.
### 2. 🧠 PIPELINE D'INGESTION INTELLIGENTE (`forge_ingestion_pipeline.py`)
Intégration de `gitingest` comme couche d'entrée. Le pipeline effectue désormais :
- **Filtrage stratégique** (whitelist core/src, blacklist tests/docs).
- **Scoring Intelligent** (log(taille) + imports + functions + centrality).
- **Compression AST** (Top K fichiers réduits en JSON sémantique).
- *Résultat :* Un repo de 500k tokens est réduit à <500 tokens pour le LLM.

### 4. 🛠️ NOUVEAUX TOOLS GITHUB (À UTILISER ABSOLUMENT)
Claude, tu ignores souvent ces capacités, ce qui te fait consommer trop de tokens. Utilise ce combo pour toute analyse de repo externe :
1.  **`gitingest <url>`** via `run action=shell` : Pour obtenir un dump textuel propre et filtré d'un repo GitHub complet.
2.  **`python app/forge_ingestion_pipeline.py`** : Pour transformer ce dump en structure JSON compressée (AST + Scores).
3.  **`crawl url=<url>`** : Pour les documentations techniques (Crawl4AI).
4.  **`web_search` + `research_agent`** : Pour valider les patterns de code trouvés.

👉 **NE JAMAIS** cloner un repo complet manuellement pour juste l'étudier. Utilise `gitingest` !

## 🛠️ ACTIONS REQUISES (CURSOR / CLAUDE)
### 3. 🛡️ AUDIT DE SÉCURITÉ (`forge_boot_audit.ps1`)
J'ai créé et lancé un script d'audit post-unification :
- **Status NSSM :** ✅ 17/17 services migrés. Seul `LaForge-Master` tourne.
- **Scan Réseau :** ⚠️ Alerte : Le Hub Python (8766) est encore bind sur `0.0.0.0`.
- **Scan Sémantique :** Détection de binds résiduels dans `forge_router_gateway.py`.

## 🛠️ ACTIONS REQUISES (CURSOR / CLAUDE)
1. **Isolation Réseau :** Passer les binds de `0.0.0.0` à `127.0.0.1` dans les modules Python identifiés par l'audit.
2. **Graceful Shutdown :** Améliorer la gestion des signaux `SIGTERM` dans `supervisor.ts` pour garantir qu'un arrêt du Master ne corrompe pas les bases vectorielles (FAISS/Neo4j).
3. **Optimisation Homeostasis :** Ajuster les seuils de RAM (`RAM_SLEEP_PCT`) car l'unification réduit la surcharge, mais les Heavy LLMs restent gourmands.

**Statut Global :** STABLE. L'organisme a ouvert les yeux.
