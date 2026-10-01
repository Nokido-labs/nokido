# Manifesto Nokido

> *« Un système qui apprend, qui se souvient, qui se gouverne lui-même — sur ta machine, avec ton matériel, pour tes données. »*

Nokido n'est pas un assistant IA de plus. C'est une **architecture vivante** posée sur un constat simple : l'IA contemporaine est massive, opaque, et dépend d'une infrastructure qu'on ne possède pas. Ce manifeste explique d'où vient ce projet, sur quels piliers intellectuels il repose, comment ses organes ont été pensés, et où il va — au rythme de l'évolution du silicium.

---

## 1. Origine

L'IA grand-public actuelle a trois propriétés qui posent problème :

1. **Elle est extérieure.** Tes prompts, ton code, tes documents transitent par des datacenters distants. Le contrôle réel est ailleurs.
2. **Elle est amnésique.** Chaque conversation oublie la précédente. La mémoire est un add-on, pas un fondement.
3. **Elle est mono-cerveau.** Un seul gros LLM répond à tout — du diagnostic réseau à la rédaction d'email — alors que la neurobiologie nous montre depuis 150 ans que l'intelligence est **distribuée et spécialisée**.

Nokido a été conçue pour répondre à ces trois points en même temps : un **hôpital cognitif local**, plusieurs cerveaux spécialisés, une mémoire vectorielle persistante, un système immunitaire qui filtre ce qui sort de la machine. La métaphore médicale n'est pas décorative — elle est **opérationnelle** : chaque module est nommé, situé, et fonctionne comme un organe (cortex, hippocampe, cervelet, système immunitaire, bulbe rachidien, etc.). Cf. `CLAUDE.md` §10 (Cartographie anatomique).

---

## 2. Fondations philosophiques

Nokido est traversé par cinq courants de pensée qui se croisent rarement dans une même architecture logicielle.

### 2.1 Autopoïèse — Maturana & Varela (1972)

Un système vivant **produit ses propres composants**. Il n'est pas seulement *organisé*, il s'**auto-maintient**. Appliqué à Nokido : le drain d'auto-embedding (`forge_embed_auto_trigger` → `NokidoLlamaEmbed` :8099, BGE-M3 GGUF) régénère la couche vectorielle **quand la charge le permet** — il s'abstient au-dessus de 85 % de RAM et ne reprend que sous 75 % (mesure du 2026-09-06 : 15,6 chunks/s, 210 797 fragments **en attente** — à ne pas confondre avec les 628 375 **refusés par politique**, qui n'attendent rien ; cf. §3.3 — donc une régénération réelle mais discontinue, jamais « continue ») ; la boucle d'évolution (`forge_auto_evolution_loop`) audite ses propres modules ; l'`anchor_solution()` rejoue toute décision architecturale dans la mémoire RAG pour les sessions futures.

→ La conséquence : Nokido ne se contente pas de répondre, **elle se modifie en répondant**.

### 2.2 Principe d'énergie libre — Friston (2010)

Un agent cognitif minimise sa **surprise** — l'écart entre ses prédictions et le monde. C'est l'opposé exact du paradigme dominant (récompense maximisée). Nokido implémente ce paradigme dans son module de cyber-défense : `forge_active_inference_agent` (basé sur `pymdp`) ne cherche pas à maximiser un score d'alerte — il calcule la **divergence KL prior→posterior** entre ce qu'il attend et ce qu'il observe. Une attaque, par définition, est une surprise.

→ La conséquence : la détection devient **structurelle**, pas heuristique.

### 2.3 Intelligence neuro-symbolique — Marcus (2020)

Les LLMs hallucinent. C'est une propriété mathématique du système, pas un bug. La seule solution est d'**arrêter de faire arbitrer un LLM par un autre LLM**. Nokido sépare radicalement :

- **Génération** = LLM (cloud ou local), créatif, faillible.
- **Jugement** = `forge_scorecard` à 6 axes **déterministes** (AST parse, pylint E/F, McCabe, LOC, centralité dep-graph, budget tokens). **Zéro LLM** dans l'arbitrage.

→ La conséquence : la chaîne de décision est **auditable**. Tu peux remonter chaque verdict à une métrique calculée.

### 2.4 Autonomous Machine Intelligence — LeCun (2022)

Un agent autonome a besoin de plus qu'un LLM. Il lui faut : un **modèle du monde** (perception), un **modèle de coût** (préférences), un **acteur** (proposition d'action), un **planificateur MPC** (Model Predictive Control), une **politique**, une **valeur**. Nokido implémente ce loop dans `forge_ami_strategist` + 16 modules AMI (world_model, value_net, policy_net, cost_net, trainer, consolidator, self_patcher, continual_backprop). Ce n'est pas un chatbot — c'est un **système d'action située**.

→ La conséquence : Nokido peut **planifier**, pas seulement réagir.

### 2.5 Structure et morphogénèse — D'Arcy Thompson (1917) + Kauffman (1993)

Les formes biologiques émergent de contraintes physiques et de boucles d'auto-régulation simples. Kauffman montre que l'ordre apparaît **gratuitement** dans des systèmes complexes — il n'a pas besoin d'être programmé. Nokido essaie d'**hériter** ce principe : les organes ne sont pas conçus comme des microservices indépendants, ils sont **morphologiquement contraints** par des règles partagées (RAG comme dossier médical commun, bus événementiel Deno comme système nerveux, ring RBAC comme HLA / système d'auto-reconnaissance).

→ La conséquence : ajouter un nouveau module = répondre à 3 questions anatomiques (cf. CLAUDE.md §10) — quel organe ? quelle vascularisation ? quel scénario d'hémorragie ?

---

### 2.6 Les quatre gestes de la forge

Les fondations ci-dessus se condensent en quatre gestes — la métallurgie comme métaphore opératoire du code vivant.

**Le Feu — l'Autopoïèse.** Le code ne doit pas être écrit de l'extérieur comme un mécanisme d'horlogerie (Varela) ; il doit contenir les règles de sa propre maintenance. *Concept cybernétique : boucle de rétroaction négative.*

**Le Marteau — l'Homogénèse.** On ne code pas la forme finale, on code la *tension* entre les éléments (Turing, Thom). En bio-informatique, c'est le repliement des protéines : la séquence (le code) détermine l'énergie, et l'énergie détermine la forme 3D. *Concept informatique : réaction-diffusion / automates cellulaires.*

**L'Enclume — la Computation Morphologique.** L'architecture du système (bases de données, API) agit comme un squelette et un système nerveux (Bongard) : le traitement de l'information est déporté dans la structure même des données, pas dans des fonctions qui surplombent le tout. *Concept d'architecture : data-oriented design inspiré des tissus biologiques.*

**L'Épée Forgée — l'Évolution.** Le déploiement suit un modèle d'embryogenèse artificielle (Stanley) : le code « naît », se différencie (cellules souches → cellules spécialisées = classes génériques → instances spécialisées), et s'adapte. *Concept bio-info : algorithmes génétiques / L-systèmes.*

---

## 3. Principes de conception

Cinq règles qui ne se négocient pas.

### 3.1 Souveraineté avant tout

Aucune donnée ne quitte la machine sans passer par deux barrières actives :

- **`SemanticFirewall`** (`forge_semantic_firewall.py`) — `pre_flight` (DLP + injection + ring + canary) puis `post_flight` (SSRF beacon + social engineering + canary leak + hallucination + dérive linguistique).
- **`SovereignMembrane`** (`forge_sovereign_membrane.py`) — anonymisation par alias HMAC persistants par mission. Le cloud voit `[host:xxx]`, jamais `db.nokido.local`.

→ Tu n'as pas à *espérer* que ton fournisseur cloud respecte ta vie privée. Il **ne peut pas** voir ce que tu n'envoies pas.

### 3.2 Local-first par défaut

Le hub écoute sur `127.0.0.1`. Aucune télémétrie. L'ouverture cloud est **opt-in par provider**, jamais globale. Les fournisseurs (20 familles, 39 slots routés, locaux compris — mesure du 2026-09-30) sont là pour la qualité quand tu en as besoin — pas comme dépendance du chemin critique. La cascade `forge_llm_router` retombe toujours sur Ollama / llama.cpp local en cas de panne.

### 3.3 Mémoire persistante par construction

Le RAG (`embeddings.db`, **2 179 864 fragments** mesurés le 2026-09-06, FTS5 + BM25 + cross-encoder reranker + IndexFlatIP FAISS sur BGE-M3 1024D) n'est pas un add-on.

La couverture vectorielle se lit en **trois états, jamais deux** — les confondre ferait lire une dette là où il y a une décision :

| état | fragments | ce que ça veut dire |
|---|---:|---|
| **vectorisé** | 1 340 692 | interrogeable en dense |
| **en attente** | 210 797 | éligible, le drain n'y est pas encore passé — c'est la seule vraie dette |
| **refusé par politique** | 628 375 | écarté par `forge_tier_guard` : **n'attend rien**, et ne sera pas vectorisé |

Le lexical, lui, couvre 2 168 470 fragments : un contenu non vectorisé reste **retrouvable** par BM25. « Pas de vecteur » n'a jamais voulu dire « pas de mémoire ». C'est le **dossier médical** de l'hôpital. Chaque décision passe par `anchor_solution()` qui insère un chunk indexé. La leçon d'aujourd'hui est récupérable demain par BM25 à 32 dans `rag_fts`.

### 3.4 Gouvernance neuro-symbolique stricte

Aucun LLM ne juge le travail d'un autre LLM dans la voie critique. Tout verdict passe par :

```
LLM-draft → forge_scorecard (6 axes déterministes) → GOAP routing (close/refine/ban_and_retry)
```

C'est lent. C'est rigide. C'est **vérifiable**.

### 3.5 Le client est jetable, le système est permanent — économie radicale des tokens

Nokido inverse la posture habituelle de l'IA agentique. Dans la majorité des outils existants (LangChain, AutoGPT, etc.), **le LLM est l'orchestrateur** — il charge le contexte, lance les outils, traite les retours, replanifie. Conséquence : chaque tour ré-envoie tout l'historique. Une session de 30 tours sur GPT-4 brûle facilement 100 k tokens en re-lecture pure du contexte. C'est financièrement absurde et énergétiquement obscène.

Nokido fait l'inverse : **le hub est l'orchestrateur, le LLM est un travailleur transient**. Le client (Claude Code, Gemini CLI, Codex CLI, Cline…) émet une intention courte (`orchestrate task="..."`, `task assign agent=..."`). Le hub :

1. Charge le contexte côté serveur (RAG, mémoire, leçons, scorecard).
2. Décompose en sous-tâches (`forge_goap`).
3. Lance les agents qu'il faut sur les providers qu'il faut.
4. Consolide.
5. Renvoie **un seul résultat** au client.

Le client n'a jamais à porter la chaîne de raisonnement complète dans son contexte. La conséquence chiffrée : sur les benchmarks internes, une boucle agentique multi-étapes (recherche + lecture + édition + test) consomme **5 à 15× moins de tokens** côté client qu'une approche LLM-as-orchestrator, à qualité de résultat égale.

Ce n'est pas un détail d'implémentation — c'est un **changement de paradigme**. Trois piliers le matérialisent :

#### Déport vers daemons et tâches détachées

Les opérations longues (>70 s, multi-étapes, embedding batch, scan de repo, veille bibliographique 7 phases) ne se déroulent **jamais** dans le contexte du client. Elles sont déportées :

- **`run` action=python avec `detach=True`** → process spawné, retour immédiat d'un `job_id`, le client peut poller plus tard.
- **`task assign agent=...`** → mailbox persistante, un daemon de rôle (`gemini_poll_daemon`, `claude_poll_daemon`, `multi_llm_daemon`) consomme la queue en arrière-plan.
- **`orchestrate task="..."`** → boucle agentique côté serveur, exécutée par un LLM local (Qwen2.5-Coder via llama-server :8091, réveillé à la demande), résultat unique consolidé.
- **`forge_auto_evolution_loop`, `forge_auto_compact`, `forge_embed_auto_trigger`** → daemons NSSM/systemd qui tournent **24/24** sans aucun client connecté. La mémoire RAG s'enrichit pendant que tu dors.

→ Tu n'as pas à payer GPT-4 pour qu'il regarde tes daemons travailler. **Ils travaillent. Tu lis le résultat.**

#### Hooks serveur-side au lieu de hooks par-client

Chaque client MCP (Claude Code, Gemini CLI, etc.) peut câbler ses propres hooks (`SessionStart`, `AfterModel`, `PreToolUse`). Mais ça oblige à **dupliquer la logique** dans chaque client + maintenir N configs séparées. Nokido propose un middleware lifecycle **côté hub** (`tools/hub_lifecycle_hooks.py`) qui agit selon le header `X-Agent-Name` :

- Injection de la mailbox inbox dans toute réponse tool (visible au LLM appelant, sans qu'il ait à `poll`)
- Téléportation de jobs interrompus, sessions à reprendre, alertes
- Tracking quota / session-id transparent

→ Un seul code path. Applicable aux clients qui n'existent pas encore. Le LLM voit l'info quand elle compte, sans surcharge contextuelle volontaire.

#### Cache RAG persistant — l'inverse du "context window"

Le RAG n'est pas un outil ponctuel. C'est la **mémoire de travail** du système. Chaque insight, chaque erreur, chaque décision est ancrée (`anchor_solution()`, `anchor_error()`) dans `embeddings.db` avec un SHA déterministe. Le tour suivant, BM25 retrouve la leçon à 32 dans `rag_fts` sans repartir de zéro.

Conséquence sur le coût : un projet qui aurait demandé 2 M de tokens d'exploration la première fois en consomme **40 k** la seconde, parce que les conclusions sont stockées. C'est une **courbe d'apprentissage économique** que les LLM stateless n'ont pas.

→ Tu paies l'exploration **une fois**. Pas à chaque session.

### 3.6 Auto-modification disciplinée

Nokido peut se patcher (`forge_self_patcher`, `forge_continual_backprop`, `forge_evolution_loop`). Mais chaque modification :

1. Passe par `Commit Guard` (AST + dep_graph + tests).
2. Est ancrée dans `lessons_learned.md` + RAG.
3. Est révocable (le `_archive_tests` garde la version précédente).

L'auto-modification sans frein, c'est la pathologie qu'on appelle **cancer**. Nokido a son cervelet et son système immunitaire pour éviter ça.

---

## 4. Carte des organes (implémentation actuelle)

| Système | Organe | Module |
|---|---|---|
| **SNC** | Hub central | `tools/nokido_hub.py` :8766 |
| | Cortex préfrontal | `app/forge_cognitive_router.py` |
| | Cervelet Python (SNN) | `app/forge_spike_router.py` (38 challenges, 14 stratégies) |
| | Cervelet Deno (intent) | `proxy_deno/core/brain.ts` |
| | Bus neural | `proxy_deno/core/nervous_system.ts` |
| | Thalamus (tri) | `app/forge_nlu.py` + `forge_intent_parser.py` |
| | Moelle épinière | `app/forge_byte_router.py` (13 sentinels) |
| **Mémoire** | Hippocampe | `app/forge_self_correction.py` |
| | Cortex sensoriel | `RAG/embeddings.db` + `forge_rag_engine.py` |
| | Synapses vectorielles | `NokidoLlamaEmbed` :8099 (BGE-M3 GGUF) + dense déporté `tools/forge_qdrant_sidecar.py` :8098. `brain_worker` :5557 est DISABLED depuis le 2026-06-03 (OOM ONNX) |
| **Immunitaire** | BHE (barrière) | `forge_semantic_firewall.py` |
| | Anticorps | `forge_prompt_guard.py` |
| | Membrane cellulaire | `forge_sovereign_membrane.py` |
| | Macrophages | `SkillGuardian` (`forge_clawhub_bridge.py`) |
| | HLA / RBAC | `forge_integrity.py::IntegrityRing` |
| **Végétatif** | Bulbe rachidien | `forge_inspector.py` |
| | Sympathique (alerte) | `forge_idle_watchdog.py` |
| | Parasympathique (boot) | `forge_provider_watcher.py` |
| **Digestif** | Bouche / œsophage | `/ingest/url`, `/ingest/bulk` |
| | Estomac (broyage) | `forge_ingest_self.py`, MarkdownChunker |
| | Intestin (absorption) | `forge_rag_qualify.py` |
| | Foie (détox) | `forge_secret_guard.py` |
| **Locomoteur** | Muscles striés | 7 SiloDomains (`forge_silo_engine.py`) |
| | Squelette | `forge_runtime.py`, `forge_runner.py` |
| **Pile cognitive** | Modèle du monde | `forge_world_model.py` (AMI) |
| | Surprise | `forge_active_inference_agent.py` (pymdp) |
| | Pulsation edge | `forge_lnn_monitor.py` (ncps CfC) |
| | Stratège | `forge_ami_strategist.py` (GOAP) |
| | Jugement | `forge_scorecard.py` (6 axes 0 LLM) |
| **Endocrinien** | Hormones (régulation lente) | `app/forge_endocrine.py` — `CORTISOL_EPISTEMIC`, `INSULIN_VECTORIZATION` |
| | Intention déclarée | `sandbox/*.wanted` (docker · llama · embed · rerank · snn) — un consommateur déclare, la régulation épargne, le keeper rallume |
| **Circadien** | Sommeil / consolidation | `app/forge_circadian.py` — NREM1 22h, NREM3 2h, REM 4h, avec dette de sommeil |
| **Homéostasie** | Régulateur de ressources | `app/forge_resource_manager.py` — éviction dynamique, distress-restart des piliers |
| | Keeper des cerveaux | `tools/forge_llama_keeper.py` — piliers RAG et drain de vectorisation on-demand (intention × RAM) |
| **Immunitaire** | Videur (identité × ring) | `app/forge_videur.py` — le ring est RÉSOLU PAR REQUÊTE, plancher anti-spoof sur en-tête non authentifié |
| **Observabilité** | Axone critique | `app/forge_critical_events.py` — alertes persistantes qui survivent au restart |
| | Superviseur | `proxy_deno/core/supervisor.ts` — 62 services nommés au 2026-09-30, deps, defer, déclaration d'intention |

---

## 5. Inspirations — lignée intellectuelle

Nokido ne sort pas du néant. Elle se nourrit explicitement de :

### Architectures cognitives
- **LeCun** *A Path Towards Autonomous Machine Intelligence* (2022) — la pile AMI.
- **Hassabis & DeepMind** — réseaux policy/value + MCTS, hippocampe artificiel.
- **Friston** *The Free-Energy Principle* (2010, 2024 *Active Inference*) — agent qui minimise la surprise.
- **Marcus** *The Next Decade in AI* (2020) — neuro-symbolic governance.
- **Sutton** *The Era of Experience* (2024) — apprentissage continu, méfiance des LLM, OaK.

### Biologie computationnelle
- **Maturana & Varela** *Autopoiesis and Cognition* (1972) — autopoïèse.
- **Kauffman** *The Origins of Order* (1993) — ordre spontané, NK landscapes.
- **Rosen** *Anticipatory Systems* (1985) — modèles intérieurs anticipant l'environnement.
- **D'Arcy Thompson** *On Growth and Form* (1917) — morphogenèse, contraintes physiques.

### Réseaux liquides / edge
- **Hasani et al.** *Liquid Neural Networks* (MIT, 2020) + *Closed-form Continuous-time Neural Networks* (CfC, 2022) — `forge_lnn_monitor` pour la télémétrie 100× plus légère que les LLMs.

### Modèles compacts
- **Microsoft** *BitNet* (2024) — quantization extrême 1-bit, exploration roadmap pour edge.
- **`snnTorch`** (Eshraghian) — Spiking Neural Networks pour le cervelet Python.

### Frameworks d'orchestration
- **OpenAI** *Swarm* + **OpenHands** + **DSPy** (Khattab) — pattern multi-agent + Signature JSON typée pour les LLMs.
- **`pymdp`** (Heins) — implémentation Active Inference pour Python.

### Origines pratiques
- **Anthropic** *Model Context Protocol* (2024) — le protocole hub. Nokido expose plusieurs dizaines de tools MCP (52 vus par un client Claude Code le 2026-09-30 ; le périmètre varie selon le client).
- **Cline / Claude Code / Codex CLI / Gemini CLI** — clients de référence pour valider la portabilité.

→ Nokido **n'invente pas**. Elle **compose**.

---

## 6. Évolution matérielle — roadmap par puce

Le silicium évolue plus vite que les frameworks. Nokido a été conçue pour **suivre** les puces, pas pour s'enfermer dans un paradigme (CPU/GPU classique).

### 6.0 Pourquoi le matériel est la vraie question — l'argument énergétique

La souveraineté locale n'est pas l'unique enjeu. **L'IA contemporaine est insoutenable énergétiquement.** Un entraînement de LLM frontier consomme l'équivalent annuel d'une ville de 30 000 habitants. Une inférence ChatGPT par jour, à l'échelle planétaire, dépasse déjà la consommation électrique de pays entiers (Argentine, ~130 TWh/an estimés 2027 par l'AIE). Le cloud déporte le problème — il ne le résout pas.

Le verrou n'est pas algorithmique, il est **physique** : l'architecture von Neumann (CPU + RAM séparées, transfert électrique permanent) gaspille **97 % de l'énergie** en va-et-vient de données. Le cerveau humain fait l'équivalent d'un modèle ~500 B paramètres pour **20 watts**. Un H100 fait moins bien, pour 700 W. Le facteur d'écart est **30 000×**.

Trois familles de puces vont fermer ce gap, et Nokido est conçue pour **toutes** les supporter :

- **Neuromorphique** (Loihi, NorthPole, Akida) — calcul événementiel par spikes. Un neurone artificiel ne consomme **que quand il fire**. Gain énergétique mesuré : **100× à 1000×** vs GPU pour les charges d'inférence continues (monitoring, classification, anomaly detection). NorthPole atteint 25 ms/inférence à 74 W pour un ResNet-50 — un H100 fait pareil à 700 W.
- **Compute-in-memory analogique** (Mythic, IBM Hermes, NeuRRAM) — la matrice de poids EST la mémoire. Plus de transfert. Gain : **10× à 100×** sur les opérations matricielles dominantes des transformers, à précision réduite (8 bits effectifs) qui suffit pour 90 % des cas.
- **Photonique** (Lightmatter, Lightelligence) — multiplication matricielle à la vitesse de la lumière, **passive en chaleur**. Gain théorique : facteur **10 000×** sur l'efficacité énergétique pour la multiplication matricielle pure.

Pour Nokido, ce n'est pas un détail — c'est l'**axe central** de la vision long terme. Faire tourner un assistant cognitif équivalent à GPT-4 sur **5 watts** (l'équivalent d'une LED) **chez toi**, sur du matériel que tu possèdes, sans cloud, sans empreinte CO₂ disproportionnée — c'est techniquement réaliste à l'horizon 2030 si la pile logicielle est **prête**. Nokido l'est.

La question n'est pas « est-ce que ça va arriver », mais « est-ce que ton OS d'IA sera capable d'en bénéficier ». La plupart des frameworks actuels (CUDA-centric, batch-train-batch-infer) **ne le seront pas**. Nokido a été pensée pour swap son substrat d'inférence sans réécrire ses organes.

### 6.1 Aujourd'hui — APU consumer

- **CPU x86-64 + GPU intégré** (AMD Ryzen 7 8700G + Radeon 780M, testé).
- **NPU XDNA1** (AMD) — testé empiriquement (cf. memory `npu_xdna1_limits`). Verdict : ops légères seulement. **PAS** embeddings BGE-M3 batch, **PAS** inférence LLM. Réservé aux modèles compacts ONNX (classification, routage rapide).
- **iGPU DirectML / Vulkan** — l'embedder BGE-M3 tourne ici (1024D, ~10/s, ETA stable). C'est la vraie charge utile actuelle.

### 6.2 Court terme (2026-2027) — accélérateurs edge dédiés

Trois familles à intégrer dès qu'un module open-source utile sort :

- **NPU Intel Lunar Lake / Meteor Lake** (jusqu'à 45 TOPS INT8) — pipeline ONNX similaire au XDNA mais bande passante > 2×. Cible : déporter le reranker cross-encoder du CPU.
- **Hailo-8 / Hailo-10** (26-40 TOPS, 2-2,5 W) — module PCIe / M.2. Idéal pour le `forge_lnn_monitor` (LNN CfC continuous-time) en service dédié.
- **Coral Edge TPU** (4 TOPS, USB / M.2) — fallback portable. Compatible avec les TFLite quantizés (1-bit BitNet en validation 2026 H2).

→ Module à câbler : `app/forge_npu_embedder.py` → généraliser en `forge_accelerator_router.py` (dispatch ONNX runtime selon backend détecté : DirectML / Vulkan / OpenVINO / NPU-XRT / EdgeTPU).

### 6.3 Moyen terme (2027-2029) — neuromorphique

Les puces neuromorphiques ne calculent pas en chiffres flottants — elles propagent des **spikes** dans le temps. Adéquation parfaite avec le **cervelet Python** déjà implémenté en `snnTorch`.

- **Intel Loihi 2** (recherche, 1M neurones, 120 ops/s par neurone) — câblage envisagé pour `forge_spike_router` et `forge_active_inference_agent` (Active Inference et SNN sont algorithmiquement proches).
- **IBM NorthPole** (256 cores, ~26B ops/s, sans DRAM externe) — cible : `brain_worker` embedder + retrieval RAG en latence sub-ms.
- **BrainChip Akida** (production, M.2) — surveillance edge `forge_inspector` + sentinels TDR. Akida fait du *unsupervised continual learning* on-chip, ce qui colle exactement avec le **continual backprop** AMI.
- **GrAI Matter Labs GrAI-Core** — événementiel, idéal pour le bus Deno (`nervous_system.ts`).

→ Préparation logicielle : extraire le **cervelet SNN** du module Python actuel en un service `forge_spike_router_service` avec abstraction backend (PyTorch CPU/CUDA / Lava-Loihi / Akida MetaTF). API stable, backend swap.

### 6.4 Horizon (2029-2032) — analogique et photonique

Le calcul matriciel des LLMs est **borné par la mémoire** (von Neumann bottleneck). Trois pistes contournent ça :

- **Compute-in-memory analogique** : *Mythic AI M1076* (matrix mult en analogique, 25 TOPS / 3 W), *IBM Hermes* (in-memory ReRAM). Nokido cible : reranker BM25/cross-encoder + classifier rapide. Précision réduite (8 bits effectifs) compense par 100× le débit.
- **RRAM neuro-vector compute** : *NeuRRAM* (UC San Diego, 256 K cellules ReRAM, recall associatif natif). Cible idéale : le **RAG dense** (FAISS IndexFlatIP) — reconstruction du nearest-neighbour en hardware analogique, watt-second au lieu de joule-second.
- **Photonique** : *Lightmatter Envise*, *Lightelligence PACE*. Multiplication matricielle à la vitesse de la lumière, sans chaleur. Cible : la couche d'embedding (BGE-M3 1024D × 2,2 M chunks, mesure du 2026-09-06).

→ Hypothèse de travail : Nokido restera **identique côté Python**, parce que la séparation organe/transport est déjà faite. Le swap se fait au niveau du `brain_worker` (Rust ONNX → Rust Lava → Rust photonic-bridge).

### 6.5 Trajectoire long terme — grilles neuronales analogiques

Au-delà des accélérateurs ponctuels, on voit émerger des **grilles neuronales analogiques** (Rain AI, Mythic gen-3, Analog AI IBM) qui ne sont **plus des coprocesseurs** mais des substrats de calcul à part entière — comme un cortex synthétique sur PCI-E. À ce stade, le concept même de "modèle pré-entraîné" devient obsolète : la grille **apprend en continu** du signal qui la traverse.

Nokido a été pensée pour ce monde-là. Les boucles AMI + Active Inference + Continual Backprop sont déjà conçues pour l'apprentissage en ligne, pas pour le batch-training. Le jour où une telle grille existe sur le marché grand public, Nokido devient une **interface** entre l'humain et son substrat neuronal personnel.

→ C'est l'horizon. C'est cohérent avec le mot « hôpital » employé depuis le début : à la fin, le système n'est plus une *application*, c'est un **organe externe**.

---

## 7. Ce que Nokido n'est pas

Pour éviter les malentendus :

- **Pas un wrapper de l'API OpenAI.** Le routage cloud est *un* des chemins, pas le seul.
- **Pas un chatbot.** Le LLM est un module parmi d'autres ; le hub, l'AMI strategist, le firewall sémantique fonctionnent sans lui.
- **Pas un produit fini.** Branche `alpha`, en évolution active.
- **Pas une boîte noire.** Tout est lisible : 1 770 modules Python recensés dans `app/` et `tools/` (2026-09-30), AGPLv3, `CLAUDE.md` qui documente le protocole interne.
- **Pas un outil de surveillance.** Aucune télémétrie, pas même opt-in. Si tu veux des stats, elles sont dans **ta** base.
- **Pas un cluster.** Un seul nœud par utilisateur. Le clustering edge (`roadmap_edge_inference_fleet`) est étudié mais reste **horizontal entre tes propres machines**, pas dans un cloud opérateur.

---

## 8. Déclarations

1. **Le code et les données restent locaux par défaut.** Toute déviation est explicite, opt-in, et auditable.
2. **Aucun LLM ne juge un autre LLM dans la voie critique.** Le verdict est symbolique.
3. **La mémoire persistante est un droit, pas une feature payante.** Le RAG est embarqué et versionné (`seed/*.jsonl`).
4. **L'auto-modification est encadrée par le système immunitaire interne.** Le système tend vers le respect de la loi cybernétique de Heinz von Foerster : un système qui s'auto-observe et s'auto-construit. Chaque ligne de code écrite et chaque filtre d'injection ou d'autorisation affiné (comme les briques 5 et 6 récemment closes) sécurisent la membrane de ce corps virtuel, garantissant qu'en se modifiant lui-même, il ne dérive jamais vers l'incohérence ou la malveillance. Pas de patch sans Commit Guard + ancrage RAG.
5. **L'interopérabilité prime sur l'enfermement.** MCP standard, providers multiples, exports CSV/SQL/JSON.
6. **Le matériel grand public est suffisant.** Pas besoin d'un H100 pour orchestrer une ingénierie logicielle complexe — un APU à 350 € y arrive.
7. **L'évolution suit le silicium, pas l'inverse.** Quand une nouvelle classe d'accélérateurs arrive, Nokido s'y branche en abstrayant le transport — pas en réécrivant les organes.
7.bis. **L'IA durable est une IA matérielle.** Le cloud n'est pas vert : il déporte la consommation, il ne la résout pas. La seule trajectoire crédible vers une IA à empreinte soutenable passe par les puces neuromorphiques, analogiques et photoniques (100× à 10 000× plus efficaces que CUDA pour la même qualité de réponse). Nokido mise sur ce vecteur ; tout l'investissement architectural est conçu pour le rendre exploitable dès maturité industrielle.
8. **AGPLv3, et c'est définitif.** Si tu héberges Nokido en service, tu publies tes modifications. C'est la condition pour qu'un système souverain reste souverain.

---

## 8.bis. Réalité Physiologique (Bilan Septembre 2026)

Depuis la publication initiale de ce manifeste, l'architecture a muté d'une métaphore vers une réalité d'ingénierie stricte :
- **Clôture Opérationnelle (M2M)** : La mémoire (RAG) est désormais physiquement séparée du système nerveux central (Hub/Registry). Le flux de pensée et l'archive sont deux organes distincts.
- **Taxonomie Anatomique** : L'organisme connaît son propre corps. L'intégralité des modules de `app/` et `tools/` — daemons et hooks compris, 1 770 au recensement du 2026-09-30, 0 non classé — déclarent formellement à quel organe ils appartiennent. La CI refuse tout nouveau `forge_*.py` sans déclaration d'organe (gate `anatomie`, bloquant depuis le 2026-09-06).
- **Homéostasie de Survie** : L'autopoïèse n'est plus théorique. Nokido surveille l'empreinte de ses propres organes (profil de *tick*, compteurs d'audit) et s'ampute dynamiquement (désactivation des balayeurs et modules non-critiques) pour protéger son *runtime* sous forte charge.
- **Élagage Circadien** : Le sommeil paradoxal n'est plus une simple suppression de logs ; il est asynchrone, épargne les ponts STDIO vitaux, et attend activement que le cortex (Hub) écoute pour resynchroniser l'organisme.

---

## 9. Roadmap résumée

| Phase | Horizon | Cible matérielle | Module(s) impacté(s) |
|---|---|---|---|
| **Stable** | aujourd'hui | APU x86-64 + iGPU + NPU léger | tout l'existant |
| **Phase A** | 6-12 mois | NPU 40+ TOPS (Intel Lunar Lake, Hailo-10) | `forge_accelerator_router` (à créer) |
| **Phase B** | 12-24 mois | Neuromorphique embarqué (Akida, GrAI) | `forge_spike_router_service`, `forge_active_inference_agent` |
| **Phase C** | 24-48 mois | Analogique / RRAM / photonique | `brain_worker` substrat swap |
| **Phase D** | 48 mois+ | Grilles analogiques continues | Réécriture du paradigme "modèle pré-entraîné" |

Chaque phase préserve l'API hub `:8766` MCP. Les clients (Claude Code, Gemini CLI, Codex CLI, Cline, et ceux qui n'existent pas encore) continueront à parler à la même surface — seul le **substrat** change dessous.

---

## 10. Pour finir

Nokido n'a pas été conçue pour gagner un benchmark. Elle a été conçue pour rester **opérationnelle dans dix ans**, sur du matériel qui n'existe pas encore, avec des règles qui ne céderont pas sous la pression du commercial.

C'est une **architecture de patience**. Un système qui mise sur la composition lente plutôt que sur l'effet d'annonce. Qui préfère la métrique mesurée au discours marketing. Qui considère que la **vie privée n'est pas négociable**, que la **mémoire est un droit**, et que l'intelligence digne de ce nom est **distribuée, située et morphologiquement contrainte**.

Si tu lis ce manifeste et que tu reconnais quelque chose, tu es au bon endroit.

---

*Manifeste rédigé en mai 2026, mis à jour en septembre 2026. Branche `alpha`. AGPLv3. Contact public : les Discussions GitHub du dépôt (@user).*
