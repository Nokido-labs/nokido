# Protocole de mesure du profil « client + SSoT » Nokido

Date : 2026-10-30  
Auteur : Agent Antigravity (`agt_antigravity`)  
Contexte : Item `P1_profil_client_ssot_mesure_20261026` — Mesurer un profil « client + SSoT » (hub MCP + memoire partagee, SANS l'organisme complet) et le publier comme une option chiffree.

---

## 1. Perimetre des services : services.toml

Analyse issue de la lecture de [`proxy_deno/core/services.toml`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/proxy_deno/core/services.toml) (2 532 lignes) definissant le registre declaratif du superviseur Nokido.

### 1.1 Services strictement necessaires au profil « client + SSoT »
Le profil cible vise exclusivement le hub MCP sur le port :8766, la memoire partagee (tableau noir / SSoT) et la lecture RAG (BM25 / sqlite ou consultation dense).

| Service (`name`) | Ligne dans `services.toml` | Role / Justification |
| :--- | :--- | :--- |
| `NokidoMCP` | Ligne 105 | Hub principal FastAPI/Starlette MCP ecoutant sur le port :8766 (`cmd = "${PY314}"`, `args = ["tools/nokido_hub.py"]`, `capabilities = ["hub"]`). C'est le point d'entree unifie servant le protocole MCP, le tableau noir et la consultation RAG. |
| `NokidoSSoTMaintainer` | Ligne 1322 | Daemon de synchronisation et de maintien du SSoT (`args = ["app/forge_ssot_maintainer.py", "--daemon", "--interval", "300"]`). Maintient a jour les etats JSON structures (`roadmap_state.json`, `rules_state.json`, `memory_state.json`). |
| `NokidoQdrantServer` *(Optionnel RAG dense)* | Ligne 488 | Serveur natif Qdrant HNSW INT8 sur le port 6333 (`args = ["tools/forge_qdrant_server.py"]`), requis uniquement si la recherche vectorielle dense locale Qdrant est activee sans se limiter a BM25 SQLite. |
| `NokidoQdrantSidecar` *(Optionnel RAG dense)* | Ligne 470 | Sidecar REST sur le port 8098 (`args = ["tools/forge_qdrant_sidecar.py", "--serve", "--port", "8098"]`), servant d'adaptateur pour le cutover RAG dense du hub. |

*Note sur le tableau noir :* Le tableau noir (`app/forge_swarm_blackboard.py`) ne dispose pas d'un service superviseur dedie car il est embarque directement comme module in-process au sein du hub (`tools/nokido_hub.py`), beneficiant de son propre verrou `asyncio.Lock` et de la base `RAG/swarm.db`.

### 1.2 Services exclus du profil (organisme lourd / supervision complete)
L'ensemble des autres services de `services.toml` appartient a l'organisme lourd, a la generation LLM locale, aux daemons cognitifs ou aux passerelles annexes et **ne doit pas** etre charge pour le profil client :

- **Cognition & Ingestion lourde :** `NokidoOllama` (l.236), `NokidoLlamaKeeper` (l.437), `NokidoLlamaNative` (l.1119), `NokidoLlamaEmbed` (l.1141), `NokidoLlamaReranker` (l.1233), `NokidoLlamaRouter` (l.1246), `NokidoLlamaBitnet` (l.1217), `NokidoLMStudioServer` (l.539), `NokidoLMStudioKeeper` (l.582), `NokidoIngestDaemon` (l.921), `NokidoDeportEmbed` (l.1059), `NokidoEpistemicSoif` (l.936), `NokidoParietalFusion` (l.1359).
- **Reseau & Proxies annexes :** `NokidoNetcfgProxy` (l.264), `NokidoNetcfgMCP` (l.278), `NokidoDenoProxy` (l.752), `NokidoDenoHubMCP` (l.767), `NokidoDenoWebHub` (l.1283), `NokidoWebHub` (l.1297), `NokidoNetcfgUI` (l.1640), `NokidoOpenAIProxy` (l.1408), `NokidoAnthropicIngress` (l.1558), `NokidoGeminiIngress` (l.1579), `NokidoWebEgress` (l.1593), `NokidoCaddyTLS` (l.1028), `NokidoGithubBridgeMCP` (l.1442), `NokidoPairMCP` (l.1484), `NokidoOpenAITunnel` (l.1530).
- **Supervision & Homeostasie :** `NokidoHubBlackbox` (l.315), `NokidoCardiacNode` (l.350), `NokidoDockerKeeper` (l.373), `NokidoAfferent` (l.418), `NokidoLogGuard` (l.507), `NokidoHomeostasis` (l.781), `NokidoOrganPulse` (l.633), `NokidoCoagulation` (l.668), `NokidoTdrSentinel` (l.692), `NokidoSecretary` (l.597), `NokidoHormonesListener` (l.615), `NokidoLogRetention` (l.2085), `NokidoServiceCrashWatcher` (l.2523), `NokidoWatchdog` (l.2222), `NokidoQuotaAlertDaemon` (l.2237).
- **Executeurs de taches autonomes & Workers :** `NokidoTaskExecutor` (l.1687), `NokidoTaskExecutorAgy` (l.1719), `NokidoTaskExecutorAntigravity` (l.1737), `NokidoTaskExecutorCodex` (l.1766), `NokidoTaskExecutorMistral` (l.1787), `NokidoTaskExecutorClaude` (l.1808), `NokidoTaskExecutorOpencodeGptoss` (l.1827), `NokidoTaskExecutorOpencodeDefaut2` a `Defaut5` (l.1845-1889), `NokidoTaskExecutorOpencodeNemotron` (l.1905), `NokidoTaskExecutorOpencodeGlm` (l.1920), `NokidoHarnessWorker` (l.2357), `NokidoAcpWorker` (l.2382), `NokidoChainExecutor` (l.1935), `NokidoCIRunner` (l.2453).

---

## 2. Analyse des imports reels et requirements minimaux proposes

Lectures effectuees sur les fichiers reels du worktree :

### 2.1 Imports reels constates

1. **Point d'entree du hub : [`tools/nokido_hub.py`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/tools/nokido_hub.py)**
   - Lignes 15 a 28 : `import asyncio`, `import hmac`, `import importlib.util`, `import json`, `import logging`, `import os`, `import queue`, `import sqlite3`, `import sys`, `import threading`, `import time`, `from datetime import UTC, datetime`, `from pathlib import Path` (stdlib).
   - Lignes 73-74 : `import atexit`, `import signal` (stdlib).
   - Lignes 268-270 : `from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener` (stdlib).
   - Ligne 516 : `import psutil` (externe, optionnel/fallback).
   - Ligne 1477 : `import ipaddress` (stdlib).
   - Ligne 7382 : `import uvicorn` (`uvicorn.Config`, `uvicorn.Server`).
   - Ligne 7630 : `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` (stdlib Windows).
   - Middleware & framework web (via `tools/hub_middleware.py` et `app/forge_ingress_adapter.py`) : `fastapi`, `starlette`, `pydantic`.
   - Couche CLI : [`tools/nokido_hub_cli.py`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/tools/nokido_hub_cli.py) ligne 79 : verifie la presence de `("uvicorn", "fastapi", "starlette", "mcp")`.

2. **Couche SSoT : [`app/forge_ssot.py`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/app/forge_ssot.py)**
   - Lignes 31-34 : `import json`, `import time`, `from pathlib import Path`, `from typing import Any, Callable, Dict, Optional` (stdlib pur).
   - Lignes 39-43 : `import sys`, `from pathlib import Path` (stdlib pur).
   - Ligne 189 : Import interne differe `from nokido_agent.app.forge_keeper_base import consult` (fallback markdown, stdlib + sqlite3).
   - Aucune dependance PyPI tierce lourde obligatoire : la validation de schema (`enforce_schema` l.133) est codee manuellement sans `jsonschema`.

3. **Tableau noir : [`app/forge_swarm_blackboard.py`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/app/forge_swarm_blackboard.py)**
   - Lignes 28-36 : `import asyncio`, `import hashlib`, `import json`, `import os`, `import sqlite3`, `import sys`, `import time`, `from pathlib import Path`, `from typing import Any, Optional` (stdlib pur).
   - Lignes 41-45 : `import sys`, `from pathlib import Path` (stdlib pur).
   - Ligne 50 : `from nokido_agent.app.forge_db_path import db_path` (resolution de chemin interne).
   - Utilise SQLite WAL (`sqlite3`) en mode mono-writer natif via `asyncio.Lock` et `asyncio.to_thread`.

### 2.2 Requirements minimal propose (PyPI) pour le profil « client + SSoT »

| Paquet PyPI | Version recommandee (alignee depot) | Import / Role exigeant |
| :--- | :--- | :--- |
| `fastapi` | `>=0.116.0` (reel : `0.136.1`) | Serveur MCP HTTP / routes de `tools/nokido_hub.py` |
| `starlette` | `>=1.0.1` (reel : `1.3.1`) | Moteur ASGI sous-jacent de FastAPI (`request`, `headers`, middlewares) |
| `uvicorn[standard]` | `>=0.30.0` (reel : `0.46.0`) | Serveur ASGI d'execution (`uvicorn.Server`, `uvicorn.Config` dans `nokido_hub.py` l.7382) |
| `pydantic` | `>=2.0.0` (reel : `2.12.5`) | Schemas de validation MCP (`tools/hub_middleware.py`) |
| `mcp` | `>=1.30.0` | Standard MCP SDK (Streamable HTTP sessions du hub) |
| `psutil` | `>=5.9.0` (reel : `7.2.2`) | Resolution d'origine des processus appelants (`nokido_hub.py` l.516) et mesure RSS |
| `httpx` | `>=0.27.0` (reel : `0.28.1`) | Client HTTP de test et de requetage pour le client MCP |

*Note d'exclusion :* Pas besoin de `torch`, `torch-geometric`, `transformers`, `jax`, `faiss-cpu`, `sentence-transformers`, `textual` ni `PySide6`.

---

## 3. Points d'entree et configuration du port

Lectures realisees sur [`pyproject.toml`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/pyproject.toml) et [`tools/nokido_hub.py`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/tools/nokido_hub.py) :

1. **Nom du paquet et Entry Points :**
   - Nom du paquet : `nokido-agent` (version `0.20.15`, `pyproject.toml` l.6-7).
   - Section `[project.scripts]` (`pyproject.toml` l.223-240) :
     ```toml
     [project.scripts]
     nokido           = "nokido_agent.tools.llama_cli:main"
     nokido-hub       = "nokido_agent.tools.nokido_hub_cli:main"
     nokido-cli       = "nokido_agent.tools.llama_cli:main"
     nokido-doctor    = "nokido_agent.tools.nokido_doctor:main"
     nokido-vault     = "nokido_agent.app.forge_machine_vault:main"
     nokido-secrets   = "nokido_agent.app.forge_secrets:main"
     nokido-composants = "nokido_agent.tools.forge_composants:main"
     ```
   - Le point d'entree console pour le hub est `nokido-hub`, implemente par [`tools/nokido_hub_cli.py`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/tools/nokido_hub_cli.py) (`nokido_agent.tools.nokido_hub_cli:main`).

2. **Option de PORT du hub (lu dans `tools/nokido_hub.py`) :**
   - Lu a la ligne 243 :
     ```python
     HUB_PORT = int(os.environ.get("LAFORGE_HUB_PORT", "8766"))
     ```
   - Et l'hote d'ecoute :
     ```python
     HUB_HOST = os.environ.get("LAFORGE_HUB_HOST", "127.0.0.1")
     ```
   - **Argument / Variable :** La surcharge de port s'effectue via la variable d'environnement `LAFORGE_HUB_PORT`. Le hub ne possede pas d'argument CLI `--port` direct dans `nokido_hub.py` (qui lit `os.environ.get("LAFORGE_HUB_PORT", "8766")`), il faut donc positionner `LAFORGE_HUB_PORT=<port_libre>` (ex: `8798`) lors du lancement du processus.

---

## 4. Script de mesure

Le script de mesure autonome et chronometre a ete ecrit dans :  
[`tools/bench/mesure_profil_client.py`](file:///%NOKIDO_ROOT%_worktrees/taches/antigravity_585075e641e7/tools/bench/mesure_profil_client.py)

### Caracteristiques implementees :
- Creation d'un environnement virtuel neuf (`python -m venv`) dans un dossier temporaire isole.
- Installation chronometree du profil reduit (`pip install -e .[hub,rag]`).
- Calcul de l'empreinte disque en Mo du venv produit.
- Demarrage du hub sur un port libre detecte dynamiquement (`LAFORGE_HUB_PORT`).
- Attente active de disponibilite applicative sur `http://127.0.0.1:<port>/health`.
- Mesure du RSS de processus au repos apres 60 secondes via `psutil`.
- Arret propre du hub via `SIGTERM` / `proc.terminate()`.
- Nettoyage des dossiers temporaires.
- 3 repetitions automatiques avec calcul des medianes.
- Emission stricte de la ligne finale de synthese :
  ```text
  BILAN mesure_profil_client: install_median_s=<X> disque_median_mo=<Y> boot_median_s=<Z> rss_median_mo=<W>
  ```
