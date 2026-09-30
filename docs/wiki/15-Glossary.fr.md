---
type: guide
title: 15 — Glossaire
status: draft
resource: repo://docs/wiki/15-Glossary.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 15 — Glossaire

<!-- revu-le: 2026-08-30 -->
> Mise à jour : 2026-08-30

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


> 🌐 [English](15-Glossary.md) · **Français**

Termes et acronymes utilisés dans Nokido. Définitions adaptées à l'usage Nokido — peuvent différer légèrement de l'usage générique.

## A

**Active Inference**
Théorie cognition de Karl Friston : agents minimisent **énergie libre attendue** (divergence KL prédictions vs observations). Dans Nokido : `forge_active_inference_agent.py` pour cyber-defense (surprise = signal attaque).

**AGPLv3**
Licence Nokido. *Affero General Public License v3*. Le "A" ajoute : si tu hostes Nokido en service réseau, tu dois publier tes modifs. Garde un système souverain souverain.

**AMI** *(Autonomous Machine Intelligence)*
Framework LeCun 2022 pour agents autonomes : perception → modèle du monde → coût → acteur → MPC planner. Pile cognitive Nokido.

**`anchor_solution()`** / `anchor_error()`
Fonctions dans `forge_self_correction.py` qui persistent décision (ou erreur) dans le RAG avec SHA id déterministe. Le système **se souvient littéralement** de ses décisions cross-sessions.

**Akida**
Puce neuromorphique BrainChip. Form factor M.2. Support continual learning unsupervised on-chip. Hardware cible Phase B.

## B

**BGE-M3**
*Beijing Academy of AI's General Embedding* model v M3. Embeddings 1024-D, multilingues. Embedder défaut Nokido, run via `brain_worker` sur ONNX/NPU.

**BM25**
*Best-Match 25*, fonction scoring IR classique. Utilisé alongside vecteurs denses FAISS via Reciprocal Rank Fusion (RRF) pour retrieval hybride.

**`brain_worker`**
Service Rust qui run ONNX inference pour BGE-M3 embeddings. Communique avec hub via ZMQ sur `:5557`. Auto-détecte backend DirectML / Vulkan / OpenVINO / CoreML / CPU.

## C

**Cascade**
Chaîne fallback dans `forge_llm_router.call_cascade()` : essaye providers dans l'ordre (local → free → payant), skip sur quota / clé absente / health failure.

**`CfC`** *(Closed-form Continuous-time)*
Variante Liquid Neural Network (Hasani 2022). Résout l'ODE en forme close — pas de solver à l'inférence. Nokido utilise CfC pour télémétrie edge (`forge_lnn_monitor`).

**Chunks**
Morceaux de texte indexés dans `rag_chunks` (SQLite + FTS5). Chaque chunk : id déterministe, embedding (BLOB float32), domain, trust weight, timestamps.

**Claude Code**
Agent dev-focused Anthropic (NPM `@anthropic-ai/claude-code` + extension VS Code). MCP-compatible. Hérite config STDIO de Claude Desktop.

**Cline**
Extension VS Code (`saoudrizwan.claude-dev`) pour coding assisté IA. MCP-compatible via STDIO bridges (`Nokido_Plan`, `Nokido_Act`).

**Codex CLI**
Agent CLI OpenAI. MCP-compatible via HTTP + Bearer + whitelist per-tool.

## D

**Daemon**
Process arrière-plan. Nokido en a beaucoup : `brain_worker`, `forge_embed_auto_trigger`, `forge_auto_compact`, `forge_auto_evolution_loop`, `gemini_poll_daemon`. Tick **24/7** pour enrichir RAG + consolider.

**Bus Deno**
Bus event Deno-based (`proxy_deno/core/nervous_system.ts`) sur `:7401`. Pub/sub pour chorégraphie cross-organes. Profil `full` le lance.

**DPAPI** *(Data Protection API)*
API Windows pour chiffrer/déchiffrer. Flag `CRYPTPROTECT_LOCAL_MACHINE` = machine-scope (lisible par tous comptes locaux).

**DSPy**
Framework Stanford pour interactions LLM typées (Khattab et al.). Nokido utilise DSPy `Signature` pour prompts cloud-side JSON-strict.

## E

**Embedding**
Représentation vectorielle texte. Nokido défaut : 1024-D BGE-M3. Stocké `BLOB float32` (4096 bytes par chunk) dans `rag_chunks`.

**Event bus**
Voir *Bus Deno*. Aussi `forge_event_stream.py` pour publishers Python-side.

**EVOLUTION_TREE**
Pane TUI (v13.6) montrant skill tree + dependency graph + lessons récentes.

## F

**FAISS** *(Facebook AI Similarity Search)*
Librairie pour search similarité efficace + clustering vecteurs denses. Nokido utilise `IndexFlatIP` (cosine similarity via inner product sur L2-normalized vectors).

**Firewall (sémantique)**
Voir `SemanticFirewall`. Protection 2-stages : *avant* (anonymise) + *après* (sniff drift).

**`forge_secrets`** / **`forge_machine_vault`**
Sous-système vault. Voir [08 — Vault & secrets](08-Vault-and-Secrets.fr.md).

**`forge_scorecard`**
Le juge déterministe 6-axes (`AST + pylint E/F + LOC + dep-graph centrality + McCabe + tokens`). **Zéro LLM** dans le verdict.

**Free Energy Principle**
Théorie unifiée fonction cerveau de Karl Friston. Cognition = minimisation surprise. Nokido applique via `pymdp` pour cyber-defense. Voir *Active Inference*.

**FTS5**
Full-Text Search v5 de SQLite. Pour search keyword style-BM25 dans virtual table `rag_fts`.

## G

**Gemini CLI**
Agent CLI Google. MCP-compatible via HTTP + Bearer + hooks.

**GOAP** *(Goal-Oriented Action Planning)*
Planificateur symbolique utilisé dans `forge_goap.py`. Forward-chaining BFS sur action graph. Utilisé par `forge_ami_strategist` pour routing `close / refine / ban`.

**Groq**
Provider LLM connu pour inférence ultra-rapide (hardware LPU). Free tier ~30k appels/mois. Utilisé massivement dans cascade.

## H

**Hailo**
Compagnie israélienne puces. Hailo-8 / Hailo-10 = accelerators IA edge dédiés (26-40 TOPS, ~2 W). Hardware cible Phase A.

**Hub** (capitale)
Le process central Nokido sur `:8766`. Built sur Starlette. Owne l'endpoint MCP, le RAG, le firewall, le router, et tout le middleware.

**HMAC** *(Hash-based Message Authentication Code)*
Utilisé pour : capability tokens (`forge_integrity`), génération alias (`SovereignMembrane`), dérivation bearer token.

## J

**JEPA** *(Joint-Embedding Predictive Architecture)*
Paradigme self-supervised LeCun 2023. Prédire l'*embedding* d'une vue target, pas les pixels/texte raw. Nokido utilise JEPA comme loss auxiliaire pour training brain_worker.

## K

**Keychain**
Store secrets macOS. Utilisé par `keyring` pour vault sur macOS.

**Divergence KL** *(Kullback-Leibler)*
Mesure information-theoretic distance entre 2 distributions probabilité. Utilisé dans Active Inference pour compute "surprise".

## L

**LaForge-Master**
Service supervisor NSSM Windows. Owne `LaForgeMCP` (le hub). Ne JAMAIS restart `LaForgeMCP` direct — passer par `LaForge-Master`.

**LeCun, Yann**
Chief AI Scientist Meta AI. Auteur framework AMI + JEPA + SIGReg (2026). Influence intellectuelle majeure sur Nokido.

**`libsecret`**
Librairie GNOME secret service. Utilisé par `keyring` pour vault Linux.

**`litellm`**
Lib client LLM unifié — abstract différences provider (OpenAI / Anthropic / Google / Groq / …). Dépendance routage primaire Nokido.

**LLM** *(Large Language Model)*
Self-explanatory. Nokido route vers 29 d'entre eux.

**LNN** *(Liquid Neural Network)*
Réseau récurrent temps continu (Hasani, MIT). ~100× plus léger qu'un LLM pour time-series. Voir *CfC*.

**Loihi 2**
Puce neuromorphique recherche Intel. 1M neurones. Cible Phase B.

## M

**Marcus, Gary**
Cognitive scientist et critique IA. Plaide pour hybrides **neuro-symboliques** plutôt que systems pure-LLM. `forge_scorecard` Nokido inspiré de ses arguments.

**`mcp_stdio_bridge.py`**
Adapter Python qui convertit STDIO ↔ HTTP pour clients qui veulent STDIO (Claude Desktop) parlant au hub HTTP.

**MCP** *(Model Context Protocol)*
Standard ouvert Anthropic pour interaction client-LLM tool. Hub Nokido implémente MCP 2025-03-26.

**Complexité McCabe** *(complexité cyclomatique)*
Nombre de chemins linéairement indépendants à travers un programme. Un des 6 axes de `forge_scorecard`.

**Membrane**
Voir *`SovereignMembrane`*.

**MPC** *(Model Predictive Control)*
Technique théorie du contrôle : prédire états futurs sur un horizon, pick action minimisant coût prédit. Utilisé dans `forge_mpc`.

**MCTS** *(Monte Carlo Tree Search)*
Sélection action style DeepMind par sampling rollouts. Utilisé dans `forge_mcts_engine.py` sur world model.

**Mythic**
Startup IA (Austin TX). Puce M1076 fait matmul en analogique — 25 TOPS à 3 W. Cible Phase C.

## N

**NPU** *(Neural Processing Unit)*
Terme générique pour accelerators IA dédiés. Nokido utilise actuellement le **AMD XDNA1** NPU dans Radeon 780M — mais seulement ops light.

**netcfg-agent**
Agent config réseau multi-vendor — hub séparé sur `:8767`. Manage Cisco, Huawei, Aruba, HPE, Netgear via SSH.

**NeuRRAM**
Puce neural compute ReRAM-based UC San Diego (2023). 256 KB cellules ReRAM avec recall associatif natif.

**NorthPole**
Puce neuromorphique IBM (2023). 256 cores, ~26B ops/s, **pas de DRAM externe**. ResNet-50 à 25 ms / 74 W.

**NSSM** *(Non-Sucking Service Manager)*
Supervisor service Windows. Nokido l'utilise pour manager `LaForge-Master`, `LaForgeMCP`, `BrainWorker`, etc.

## O

**Ollama**
Runtime LLM local (`:11434`). Défaut pour tier local cascade.

**ONNX** *(Open Neural Network Exchange)*
Format réseau neuronal cross-framework. BGE-M3 shipped en ONNX dans `brain_worker`. Runtime par OS : DirectML (Win), OpenVINO (Linux), CoreML (macOS).

**OpenVINO**
Toolkit inférence Intel. Utilisé pour CPUs AMD/Intel et le NPU Lunar Lake upcoming.

## P

**PII** *(Personally Identifiable Information)*
Trucs que `SovereignMembrane` redacte avant tout appel cloud : hostnames, IPs, paths, usernames, UUIDs, tokens.

**PPR** *(Personalized PageRank)*
Algorithme graph — pick noeuds les plus "centraux" depuis un seed. Nokido l'utilise dans `forge_graph_ppr.py` pour surface modules code reliés à une cible.

**pymdp**
Lib Python pour active inference (Heins 2024). Wrap math de minimisation énergie libre Friston.

## Q

**Quota**
Budget appels/tokens per-provider. Tracké dans `forge_provider_quota.py`. `should_skip()` trigger cascade fallback quand > 80%.

## R

**RAG** *(Retrieval-Augmented Generation)*
Sous-système mémoire persistante Nokido. ~380k chunks indexés via FTS5 + BM25 + FAISS + reranker cross-encoder. DB : `RAG/embeddings.db`.

**ReRAM** *(Resistive RAM)*
Tech mémoire non-volatile enabling in-memory compute. NeuRRAM = exemple canonique. Cible Phase C.

**Reranker**
Modèle cross-encoder qui score paires `(query, candidate)` après le retrieval rapide FAISS+BM25. Améliore précision @top-K.

**Ring**
Niveau RBAC (0-5). 0 = MASTER, 5 = UNTRUSTED. Set par `X-Agent-Name`. Enforced au middleware hub. Voir [07 — Modèle de sécurité](07-Security-Model.fr.md).

**RRF** *(Reciprocal Rank Fusion)*
Scoring hybride : combine rankings de multiple systèmes retrieval (dense + sparse) sans normaliser scores. Nokido utilise k=60.

## S

**Scorecard**
Le juge 6-axes. Voir *`forge_scorecard`*.

**`SemanticFirewall`**
L'inspector pre/post flight pour appels LLM cloud. 2 stages, 9 layers.

**SIGReg**
Signal Regularization pour training SSL (LeCun 2026). Trick anti-collapse utilisé dans engine RAG Nokido.

**SNN** *(Spiking Neural Network)*
Réseaux qui calculent via spikes discrets dans le temps. Utilisé dans le "cervelet Python" (`forge_spike_router.py` via `snntorch`). Cible Phase B neuromorphique.

**`SovereignMembrane`**
Couche anonymisation par alias HMAC pour appels cloud. Voir [07 — Modèle de sécurité](07-Security-Model.fr.md#2-membrane-souveraine-forge_sovereign_membranepy).

**SSRF** *(Server-Side Request Forgery)*
Pattern attaque : trick le serveur à faire requests vers ressources internes. `SemanticFirewall.post_flight` détecte patterns beacon.

**STDIO**
Standard input/output. Un des 2 transports MCP. L'autre = HTTP. Claude Desktop / Cline utilisent STDIO ; Gemini CLI / Codex CLI utilisent HTTP.

**SWE-bench**
Benchmark coding LLM avec real issues GitHub. Nokido scoré 10/50 sur mixed sample.

## T

**`tiktoken`**
Lib tokenizer OpenAI. `forge_tokenizer.py` Nokido dispatch vers elle pour providers famille OpenAI/Llama, avec fallback ±15% accuracy.

**TUI** *(Terminal User Interface)*
Client terminal Nokido (`tools/nokido_tui.py`). 6 panes, 20 slash commands, EVOLUTION_TREE pane. Voir [09 — Référence TUI](09-TUI-Reference.fr.md).

## V

**Vault**
Le store secrets OS-encrypted. DPAPI (Win) / Keychain (macOS) / libsecret (Linux). Voir [08 — Vault & secrets](08-Vault-and-Secrets.fr.md).

**Vulkan**
API GPU cross-platform. Un des backends pour runtime ONNX `brain_worker`.

## W

**WCM** *(Windows Credential Manager)*
Store credential per-user Windows. **Legacy** dans Nokido — superseded par vault DPAPI machine-wide, mais toujours lisible comme fallback dans chaîne `forge_secrets.get_secret()`.

**World Model**
Le modèle prédictif de l'environnement dans la boucle AMI. Implémenté dans `forge_world_model.py`.

## X

**X-Agent-Name**
Header HTTP envoyé par clients MCP pour s'identifier. Hub mappe ce header à un ring via lookup `_AGENT_RING`.

**XDNA1**
Architecture NPU AMD (dans Strix Point / Radeon 780M). Testé empiriquement : ops-light only. Pas suitable BGE-M3 batch ni LLM inference.

## Z

**ZMQ** *(ZeroMQ)*
Lib messaging utilisée entre hub et `brain_worker` sur `:5557`.

## Symboles

**`@all`** / `@<agent>`
Préfixe compose-box TUI pour broadcast ou direct-message à un agent spécifique.

**`[HOOK:INBOX]`**
Marker injecté par `hub_lifecycle_hooks.py::post_dispatch()` quand un agent a messages unread dans sa mailbox. Visible au LLM dans le response text du tool.

**`forge_*.py`**
Convention naming pour modules organes Nokido. Règle anti-duplication s'applique : query `rag_fts` avant d'en créer un nouveau. Voir CLAUDE.md §3.
