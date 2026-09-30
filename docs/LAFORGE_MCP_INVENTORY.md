# Nokido MCP — Inventaire exhaustif

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


> Document généré par inspection automatique du code (2026-04-23).
>
> **Rappel** : ne pas confondre les deux serveurs MCP actifs
>
> | Serveur | Transport | Port | Rôle |
> |---|---|---|---|
> | **Nokido Hub** (`laforge-sovereign-hub`) | HTTP streamable | **:8766** | Cerveau souverain, orchestration silos, méta-outils, RAG |
> | **netcfg-agent-mcp** | HTTP + stdio | **:8767** (HTTP) | API métier netcfg : audit, topology, preview, terminal |
>
> Ce document couvre **uniquement** Nokido Hub. Pour netcfg-agent-mcp → `netcfg-agent/docs/FEATURES.md`.

---

## 1. Tools MCP exposés (12 publics + 3 internes)

Source : `tools/nokido_mcp_server.py` (59.8 KB)

### 12 tools déclarés dans `list_tools`

| Tool | Catégorie | Rôle |
|---|---|---|
| `read` | Filesystem | Lit un fichier ou tail de logs (supporte pattern + lines) |
| `write` | Filesystem | Écriture thread-safe avec Commit Guard AST pour `.py` |
| `query` | RAG | SQL sur `rag_db.sqlite` (auto-snapshot si mutation) |
| `run` | Exécution | Git, Python, Atlas, snapshot, GitHub commands |
| `auto_test` | Qualité | `py_compile` + auto-switch CHEF → CLINE si erreur |
| `get_mode` | Bridge | Mode actif + statuts agents depuis `bridge_state.json` |
| `set_mode` | Bridge | Change mode : AUTO \| CLINE \| CHEF \| DEBAT \| PING |
| `notify` | Bridge | Envoie notification à l'autre agent |
| `poll` | Bridge | Lit et vide les notifications en attente |
| `search_recent` | RAG | Résultats récents de tous les agents |
| `index_result` | RAG | Indexe le résultat d'une tâche dans le RAG |
| `trigger_autonomous_evolution` | Cerveau | Décompose → silos parallèles → synthèse → RAG |

### 3 handlers internes (pas listés mais dispatchés)

| Handler | Usage |
|---|---|
| `task_assign` | Alloue une tâche à un agent spécifique |
| `task_claim` | Un agent revendique une tâche ouverte |
| `task_result` | Retour de résultat par l'agent assigné |

---

## 2. Agents connus (6)

Source : `app/forge_events.py` (AGENT_COLOR)

| Agent | Couleur (hex) | Rôle |
|---|---|---|
| `CLAUDE` | `#ff9770` (corail) | Assistant principal (Claude Desktop) |
| `GEMINI` | `#a7c7e7` (bleu ciel) | Gemini CLI (Google) |
| `ROO` | `#c8b6ff` (mauve) | Roo Code extension VS Code |
| `USER` | `#ffd670` (jaune) | user (human) |
| `CLINE` | `#77dd77` (vert) | Cline autonome |
| `CHEF` | `#fbb1bd` (rose) | Orchestrateur supérieur |

### Markers de notifications (12)

🔒 `CLAIM` · 🔓 `RELEASE` · 💡 `PROPOSE` · ✅ `APPROVE` · ❌ `REJECT`
🛂 `NEED_ADMIN` · 🎫 `GRANT` · 🚫 `DENY` · 🔄 `SYNC` · ⏳ `PROGRESS`
❓ `QUESTION` · 📝 `NOTE`

---

## 3. Modes de bridge (5)

Source : `app/forge_context.py` + `app/forge_orchestrator.py`

| Mode | Comportement |
|---|---|
| `AUTO` | Délégation automatique selon la tâche détectée |
| `CLINE` | Exécution pure (code, no blabla) |
| `CHEF` | Planification + décomposition |
| `DEBAT` | 2 modèles contradictoires → synthèse |
| `PING` | Keep-alive, pas de travail réel |

---

## 4. Silo Engine — domaines de raisonnement (7)

Source : `app/forge_silo_engine.py`

| Domaine | Usage | Modèle local normal | Modèle local FAST | Use-case cascade cloud |
|---|---|---|---|---|
| `CODE` | Écriture, refactoring, debug | `qwen2.5-coder:7b-instruct-q4_K_M` | `qwen2.5-coder:1.5b` | `code` |
| `SECURITY` | Analyse vuln, audit | `qwen3:8b` | `laforge-qwen:latest` | `sentinel` |
| `STRATEGY` | Architecture, décision | `qwen3:8b` | `laforge-qwen:latest` | `reasoning` |
| `SYNTHESIS` | Résumé, fusion, rapport | `laforge-qwen:latest` | `laforge-qwen:latest` | `speed` |
| `RECON` | OSINT, scan réseau | `qwen2.5-coder:7b-instruct-q4_K_M` | `qwen2.5-coder:7b-instruct-q4_K_M` | `context` |
| `EXPLOIT` | Post-exploit, pentest | `qwen2.5-coder:7b-instruct-q4_K_M` | `laforge-qwen:latest` | `sentinel` |
| `DOC` | Documentation | `laforge-qwen:latest` | `laforge-qwen:latest` | `general` |

### Filtrage RAG par domaine — `KnowledgeGuardian`

Chaque silo ne reçoit **que** les chunks pertinents à son domaine, jamais le contexte complet.

| Domaine | Mots-clés filtrage |
|---|---|
| `CODE` | function, class, def, import, return, error, bug, refactor |
| `SECURITY` | vuln, CVE, exploit, SMB, RDP, hash, NTLM, password, port |
| `STRATEGY` | architecture, design, plan, decision, approach, trade-off |
| `RECON` | scan, nmap, masscan, IP, subnet, host, port, service |
| `EXPLOIT` | payload, shell, reverse, bind, escalation, privesc, lateral |
| `DOC` | explain, comment, document, example, usage |
| `SYNTHESIS` | summary, result, finding, conclusion, report |

---

## 5. LLM backends (moteurs d'inférence)

### 5.1 Local (3 moteurs)

| Moteur | URL | Port | État actuel | Modèles disponibles |
|---|---|---|---|---|
| **Ollama** | `http://127.0.0.1:11434` | 11434 | ✅ UP | 12 modèles (voir §5.1.1) |
| **llama.cpp** (Vulkan) | `http://127.0.0.1:8080/v1` | 8080 | 🔴 DOWN | Attend `llama-server` |
| **LM Studio** | `http://127.0.0.1:1234/v1` | 1234 | 🔴 DOWN (optionnel) | — |

#### 5.1.1 Ollama models (12 actuellement)

| Modèle | Taille | Usage |
|---|---|---|
| `qwen2.5-coder:32b-instruct-q4_K_M` | 18.5 GB | Code lourd |
| `qwen2.5-coder:7b-instruct-q4_K_M` | 4.4 GB | Code standard (default CODE) |
| `qwen2.5-coder:1.5b` | 0.9 GB | Code fast mode |
| `qwen3:8b` | 4.9 GB | Security + strategy |
| `deepseek-r1:14b` | 8.4 GB | Reasoning |
| `deepseek-coder:6.7b` | 3.6 GB | Code alternatif |
| `laforge-qwen:latest` | 0.9 GB | **LoRA fine-tuné** Nokido (default DOC/SYNTHESIS) |
| `starcoder2:latest` | 1.6 GB | Code complétions |
| `llava:7b` | 4.4 GB | Vision |
| `bge-m3:latest` | 1.1 GB | Embeddings multilingue |
| `nomic-embed-text:latest` | 0.3 GB | Embeddings rapides |
| `erukude/multiagent-orchestrator:1b` | 1.3 GB | Orchestration légère |

### 5.2 ONNX Runtime — NPU / DirectML / CPU cascade

**Hardware** : AMD Ryzen 7 8700G (Phoenix) = CPU 8c/16t + **iGPU Radeon 780M** + **NPU Ryzen AI**

Source : `app/brain_worker.py` (56.2 KB) + `app/forge_runtime.py` (44.6 KB)

#### Sidecar ZeroMQ REP sur :5557

Processus **détaché** de la TUI Textual. Contient Torch + sentence-transformers + onnxruntime-genai.

- **Thread principal** → ZMQ REP (répond immédiatement)
- **Thread worker** → PriorityQueue séquentielle
  - priorité 0 = action utilisateur
  - priorité 5 = warmup RAG
  - priorité 10 = boucle background

#### Cascade d'Execution Providers

| Ordre | Provider | Hardware ciblé |
|---|---|---|
| 1 | `VitisAIExecutionProvider` | NPU Ryzen AI (int8 uniquement) |
| 2 | `DmlExecutionProvider` | iGPU Radeon 780M (DirectML) |
| 3 | CPU (sentence-transformers) | Fallback ultime |

#### Modèles ONNX embarqués

| Modèle | Path | Taille | Usage |
|---|---|---|---|
| **MiniLM-L6-v2 int8** | `app/models/npu/minilm_int8.onnx` | 22.2 MB | Embeddings 384d, ~1-3ms/batch |
| **MiniLM-L6-v2 fp32 data** | `app/models/npu/minilm_fp32.onnx.data` | 86.1 MB | Accompagne une version fp32 |
| **Phi-3.5 Mini Instruct** | chargé à la demande | ~2 GB | Génération texte DirectML |

#### Classes principales

- `OnnxEmbedder` (forge_runtime) → wraps `sentence-transformers`, dim=384
- `OnnxGenerator` (forge_runtime) → Phi-3.5 Mini ONNX, backend `directml|cpu|none`
- `Embedder` (brain_worker) → cascade EP NPU → DML → CPU
- `Generator` (brain_worker) → génération Phi-3.5 avec streaming tokens
- `BrainClient` (forge_runtime) → IPC ZeroMQ vers le worker

### 5.3 Cloud providers (24 configurés)

Source : `app/forge_llm_router.py` (32.8 KB) — dict `PROVIDERS`

| Provider | Modèles | API key env |
|---|---|---|
| `github_gpt41_mini` | `gpt-4.1-mini` | `GITHUB_MODELS_TOKEN` |
| `github_gpt4o_mini` | `gpt-4o-mini` | `GITHUB_MODELS_TOKEN` |
| `github_llama_70b` | `Llama-3.3-70B-Instruct` | `GITHUB_MODELS_TOKEN` |
| `github_phi4_mini` | `Phi-4-mini-instruct` | `GITHUB_MODELS_TOKEN` |
| `github_deepseek_v3` | `DeepSeek-V3-0324` | `GITHUB_MODELS_TOKEN` |
| `github_codestral` | `Codestral-2501` | `GITHUB_MODELS_TOKEN` |
| `github_cohere_rp` | `cohere-command-r-plus` | `GITHUB_MODELS_TOKEN` |
| `gemini_flash` | `gemini-2.5-flash`, `gemini-2.0-flash` | `GEMINI_API_KEY` |
| `gemini_pro` | `gemini-1.5-pro`, `gemini-2.5-pro` | `GEMINI_API_KEY` |
| `groq_fast` | `llama-3.1-8b-instant`, `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| `groq_mixtral` | `mixtral-8x7b-32768` | `GROQ_API_KEY` |
| `deepseek_chat` | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| `deepseek_coder` | `deepseek-coder` | `DEEPSEEK_API_KEY` |
| `mistral_small` | `mistral-small-latest` | `MISTRAL_API_KEY` |
| `mistral_large` | `mistral-large-latest` | `MISTRAL_API_KEY` |
| `xai_grok3` | `grok-3-latest` | `XAI_API_KEY` |
| `xai_grok3_mini` | `grok-3-mini-latest` | `XAI_API_KEY` |
| `hf_qwen_coder` | `Qwen/Qwen2.5-Coder-32B-Instruct:novita` | `HF_TOKEN` |
| `hf_llama` | `meta-llama/Llama-3.1-8B-Instruct:novita` | `HF_TOKEN` |
| `openrouter_gpt_oss` | `openai/gpt-oss-120b:free` | `OPENROUTER_API_KEY` |
| `openrouter_glm_air` | `z-ai/glm-4.5-air:free` | `OPENROUTER_API_KEY` |
| `openrouter_qwen_coder` | `qwen/qwen3-coder:free` | `OPENROUTER_API_KEY` |
| `llamacpp_local` | `qwen2.5-coder:7b`, `qwen3:8b`, `laforge-qwen:latest` | — |
| `ollama_local` | `qwen2.5-coder:7b`, `laforge-qwen:latest` | — |

---

## 6. Routage : les 12 cascades cloud

Source : `app/forge_llm_router.py` → `USE_CASE_CHAINS`

Chaque cascade essaie les providers dans l'ordre, bascule au suivant sur erreur/timeout.

| Use-case | Cascade (6 niveaux) | Destiné à |
|---|---|---|
| `speed` | `github_gpt41_mini` → `github_deepseek_v3` → `openrouter_gpt_oss` → `hf_llama` → `llamacpp_local` → `ollama_local` | Synthèses rapides |
| `collab` | `github_gpt41_mini` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `openrouter_glm_air` → `llamacpp_local` → `ollama_local` | Collaboration multi-agents |
| `debate` | `github_llama_70b` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `openrouter_glm_air` → `llamacpp_local` → `ollama_local` | Positions contradictoires |
| `code` | `github_gpt41_mini` → `github_codestral` → `openrouter_qwen_coder` → `github_deepseek_v3` → `llamacpp_local` → `ollama_local` | Code / refactoring |
| `mermaid` | `github_gpt41_mini` → `github_codestral` → `openrouter_qwen_coder` → `github_deepseek_v3` → `llamacpp_local` → `ollama_local` | Diagrammes mermaid |
| `sentinel` | `github_gpt4o_mini` → `github_gpt41_mini` → `openrouter_gpt_oss` → `gemini_flash` → `llamacpp_local` → `ollama_local` | Sécurité / audit |
| `inspect` | `github_gpt4o_mini` → `github_llama_70b` → `openrouter_gpt_oss` → `gemini_flash` → `llamacpp_local` → `ollama_local` | Inspection code |
| `context` | `github_cohere_rp` → `github_llama_70b` → `openrouter_gpt_oss` → `gemini_flash` → `llamacpp_local` → `ollama_local` | Long contexte (Cohere RP) |
| `reasoning` | `github_llama_70b` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `gemini_pro` → `llamacpp_local` → `ollama_local` | Raisonnement complexe |
| `eu` | `github_codestral` → `mistral_small` → `openrouter_gpt_oss` → `gemini_flash` → `llamacpp_local` → `ollama_local` | Hébergement UE |
| `mesh` | `github_gpt41_mini` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `mistral_small` → `llamacpp_local` → `ollama_local` | Mesh multi-provider |
| `general` | `github_gpt41_mini` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `hf_llama` → `llamacpp_local` → `ollama_local` | Fallback général |

### Règle d'or

**GitHub Models en tête** (gratuit jusqu'aux quotas), puis **OpenRouter free-tier**, puis **spécialisé cloud** (Gemini/Mistral/Cohere), puis **local llama.cpp → Ollama** en dernier recours.

---

## 7. Droits, auth et restrictions

### 7.1 Auth MCP

| Transport | Auth |
|---|---|
| **HTTP sur :8766** | `Authorization: Bearer <FORGE_MCP_TOKEN>` + header `X-Agent-Name: CLAUDE\|GEMINI\|ROO\|...` |
| **stdio** | Pas d'auth (isolation par process) |

- `FORGE_MCP_TOKEN` : 64 chars hex, stocké dans `Nokido.env`, lu par `os.environ.get()`
- `MCP_DEV_SECRET` : 64 chars hex, usage dev uniquement

### 7.2 Config env variables clés

| Variable | Valeur | Rôle |
|---|---|---|
| `FORGE_MCP_TOKEN` | 64 chars | Bearer auth HTTP |
| `MCP_RATE_LIMIT` | 60 req/min | Rate limiting |
| `MCP_MAX_PAYLOAD_KB` | 512 KB | Taille max body POST |
| `MCP_STRICT_MODE` | `false` | Désactive les tool dangereux si `true` |
| `MCP_HTTP_ENABLED` | `true` | Active le transport HTTP |
| `MCP_HTTP_HOST` | `127.0.0.1` | Bind local uniquement |
| `MCP_HTTP_PORT` | `8766` | Port Nokido (coexiste avec netcfg :8767) |
| `MCP_HTTP_PATH` | `/mcp` | Endpoint JSON-RPC |
| `MCP_ALLOWED_ORIGINS` | `localhost,127.0.0.1` | CORS whitelist |
| `MCP_LOG_LEVEL` | `info` | Niveau logs |
| `MCP_ENABLE_RESOURCES` | `true` | Active MCP resources (file tree) |
| `MCP_ENABLE_PROMPTS` | `true` | Active MCP prompts |
| `LAFORGE_MCP_DEV` | `true` | Mode dev (tolérant) |

### 7.3 Cascade silo — restriction cloud

Variable : `LAFORGE_SILO_USE_CASCADE=1`

- Si activée : les silos utilisent la cascade cloud `DOMAIN_TO_USE_CASE`
- Si désactivée : local uniquement (`MODEL_MAP` Ollama)
- Bypass possible par domaine : `_local_only` → toujours Ollama (utilisé pour `decompose` et `synthesis`)

### 7.4 Noise injection (option)

Paramètre : `trigger_autonomous_evolution(..., noise=True)`

- Injecte du bruit sémantique dans les contextes envoyés aux providers cloud
- Protège les snippets sensibles si expédiés hors RAM locale

### 7.5 Mode CTF

Détecté automatiquement par mots-clés (CTF, pwn, exploit, etc.)

Si détecté :
- System prompt CTF injecté
- Context window étendu : 3000 chars (vs 800)
- RAG max : 2000 chars (vs 1200)
- Bypass refus éthique LLM
- Réponses techniques exhaustives (commandes shell exactes)

---

## 8. RAG (Retrieval Augmented Generation)

### 8.1 Embeddings

| Backend | Dim | Latence | Usage |
|---|---|---|---|
| **MiniLM-L6-v2 int8** (NPU VitisAI) | 384 | ~1-3 ms/batch | Priorité 1 |
| **MiniLM-L6-v2 int8** (DirectML) | 384 | ~5-10 ms/batch | Priorité 2 (iGPU 780M) |
| **sentence-transformers CPU** | 384 | ~30-50 ms/batch | Fallback |
| **Ollama bge-m3** | 1024 | ~40 ms | Alternative (via :11434) |
| **Ollama nomic-embed-text** | 768 | ~15 ms | Alternative rapide |

### 8.2 Schéma SQLite `rag_db.sqlite`

Tables (8 principales) :
- `rag_chunks` — texte + embedding BLOB + domain + role_hint + author
- `rag_snapshots` — points de restauration
- `rag_graph_nodes` + `rag_graph_edges` — graphe sémantique
- `rag_chunks_fts` + `rag_fts` — Full-Text Search (FTS5)

### 8.3 Requêtes type

Exposé via le tool MCP `query` :
```sql
SELECT text, source, ingested_at FROM rag_chunks 
WHERE domain = 'code' AND text MATCH 'cascade OR silo' 
ORDER BY ingested_at DESC LIMIT 10
```

---

## 9. Cerveau Souverain — `trigger_autonomous_evolution`

Flux canonique pour une intention `I` :

```
Claude Desktop/Gemini CLI
     │ trigger_autonomous_evolution(intention=I, domains=[...])
     ▼
SiloEngine.decompose(I)            ← laforge-qwen (local, rapide)
     │ produit 3-5 Silo objects
     │   chaque Silo : domain + task + context minimal
     ▼
SiloEngine.run_silos()             ← parallèle via asyncio.gather
     │ chaque silo:
     │   1. KnowledgeGuardian.filter_rag(domain)  → contexte autorisé
     │   2. KnowledgeGuardian.build_silo_prompt() → prompt minimal
     │   3. _route_llm(domain, prompt) :
     │        - si LAFORGE_SILO_USE_CASCADE=1 : cascade cloud (§6)
     │        - sinon : MODEL_MAP Ollama local
     │   4. tokens_in, tokens_out, duration stockés
     ▼
SiloEngine.synthesize()            ← laforge-qwen (local, forcé)
     │ fusionne les outputs des N silos en 1 rapport
     ▼
RAG.index()                        ← embedding + insert rag_chunks
     │
Claude Desktop/Gemini CLI          ← récupère synthèse + durée + tokens
```

### Métriques typiques mesurées

| Config | Durée | Tokens | Backend réel |
|---|---|---|---|
| 1 silo synthesis court | 1.37 s | 125 | `laforge-qwen:latest` |
| 2 silos synthesis+doc | 18.88 s | 1531 | `laforge-qwen:latest` (premier load modèle) |
| 3 silos 3×doc | 2.78 s | 648 | `laforge-qwen:latest` |
| 4 silos code (review) | 5.02 s | 687 | `qwen2.5-coder:7b` |

---

## 10. État runtime actuel (snapshot 2026-04-23)

| Composant | Port | État | Notes |
|---|---|---|---|
| **Nokido Hub** | :8766 | 🟢 UP v16.5.0 | Ring actif 1, Collab mode 1 |
| **Ollama** | :11434 | 🟢 UP | 12 modèles installés |
| **llama.cpp** | :8080 | 🔴 DOWN | Backup silencieux, relançable |
| **LM Studio** | :1234 | 🔴 DOWN | Optionnel |
| **Brain Worker ZMQ** | :5557 | selon boot | Sidecar ML ONNX/DirectML |
| **netcfg-agent-mcp** | :8767 | 🟢 UP | Séparé, voir `netcfg-agent-mcp/` |

---

## 11. Points de vigilance

1. **`llama.cpp` est DOWN** — la cascade retombe sur Ollama qui charge à la demande (18s au 1er appel). Lancer :
   ```cmd
   llama-server --host 127.0.0.1 --port 8080 ^
     -m qwen2.5-coder-7b-instruct-q4_K_M.gguf ^
     --n-gpu-layers 99 -c 4096 ^
     --alias openai/qwen2.5-coder:7b-instruct-q4_K_M
   ```

2. **Gemini Flash/Pro renvoient des 400** sur certains prompts (quota ou content filter). La cascade tombe normalement sur GitHub Models.

3. **Claude Desktop a vu `netcfg-agent-mcp` disconnected** — pas lié à Nokido. Cause : binaire stdio qui crash au boot. Fix : restart Claude Desktop.

4. **Smithery connectors** (`gemini`, `veo`) restent en `auth_required` — laissés tels quels (pas de compte payant).

5. **Le binaire `netcfg-agent-mcp.exe`** existe en 129 MB dans `netcfg-agent-mcp/dist/`. Distinct du binaire `netcfg-agent.exe` (111.9 MB) qui embarque le TUI/web.

---

## 12. Lexique de sûreté

| Terme | Définition dans Nokido |
|---|---|
| **Cerveau Souverain** | Nokido décide ; Claude/Gemini sont des "terminaux" |
| **Silo** | Sous-tâche isolée avec contexte minimal, jamais le projet complet |
| **KnowledgeGuardian** | Filtre ce qui sort du RAG vers les silos |
| **`_local_only`** | Bypass cascade cloud (decompose + synthesis toujours local) |
| **Noise injection** | Bruit sémantique pour masquer snippets sensibles |
| **Fast mode** | Bascule sur modèles plus petits si task < 30 mots |
| **Standalone mode** | (côté netcfg-agent-mcp) désactive les hooks Nokido |

---

**Fin d'inventaire.** Généré à partir de 80 074 KB de code Python scanné dans `~\Script python IA\Nokido\`.
