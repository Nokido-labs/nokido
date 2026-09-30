# Qu'est-ce que Nokido — définition honnête

> Document de positionnement non-marketing. Objectif : décrire ce que Nokido **est
> réellement aujourd'hui**, ce qu'il **n'est pas**, et ce que la souveraineté débloque
> **selon le matériel**. Pas de superlatifs invérifiables.

## En une phrase

**Nokido est un substrat d'orchestration souverain pour agents de code et de
raisonnement** : un hub local qui route des tâches entre des modèles **locaux** et des
modèles **cloud free-tier**, à travers un pare-feu sémantique qui garantit qu'aucune
donnée sensible ne sort de la machine. Ce n'est ni un modèle, ni (encore) un produit
packagé — c'est la **couche d'exploitation** au-dessus des modèles.

## Ce que Nokido EST (vérifiable dans le code)

- **Un hub MCP** (`:8766`) qui expose **42 outils** (lecture, run sandboxé, RAG, git, web)
  à n'importe quel client parlant le protocole — Claude Code, Claude Desktop, Antigravity
  (`agy`), Codex CLI, Cline, Mistral Vibe, Mammouth Code — ou à ses propres agents.
- **Un routeur multi-provider** (**39 slots**, ~20 fournisseurs dont 3 locaux) qui
  dispatche un appel LLM vers le bon backend : local (Ollama / llama.cpp / LM Studio)
  **ou** cloud gratuit (Cerebras, Groq, Gemini, GitHub Models, Cohere, NVIDIA NIM,
  SambaNova, OpenRouter, Z.ai GLM, Moonshot Kimi…), selon le coût, la sensibilité et le
  use-case. Recompte : `python -c "from app.forge_provider_specs import PROVIDER_SPECS;
  print(len(PROVIDER_SPECS))"`.
- **Un pare-feu sémantique + membrane** (`forge_semantic_firewall`,
  `forge_sovereign_membrane`) : DLP/anonymisation pré-envoi, détection d'injection,
  alias HMAC. C'est le mécanisme qui rend le routage cloud **sûr** pour du non-sensible
  et **force le local** pour le sensible.
- **Un chiffrement at-rest effectif** sur les bases du RAG : `RAG/` est une **jonction NTFS
  vers `V:`**, volume **VeraCrypt** monté (mesure 2026-08-30 : aucune partition physique
  derrière `V:`, donc un conteneur ; pilote `veracrypt` en service système `Running`).
  Outillage : `tools/forge_at_rest_veracrypt.py`, plus deux voies complémentaires —
  EFS NTFS (`tools/forge_at_rest_efs.py`) et SQLCipher (`app/forge_db_conn.py` +
  `tools/forge_db_encrypt_migrate.py`, qui attend que les ~631 sites `sqlite3.connect()`
  convergent vers un point unique). Les secrets vivent à part, dans un **coffre DPAPI
  machine**. Portée honnête : ce qui est chiffré, ce sont les bases servies par `V:` ; les
  bases hors RAG (`sandbox/*.db`) restent sur `C:`, où BitLocker est désactivé sur ce
  poste — et le chiffrement de champ (`app/forge_encrypt.py`, Fernet AES-256) existe mais
  ne couvre aujourd'hui aucun chunk (0 sur 1 331 060, faute de domaine `private`).
- **Des anneaux de sécurité zero-trust** (6 rings, `forge_integrity`) + une **sandbox
  d'exécution** dé-privilégiée (comptes Windows non-admin, réseau coupé en mode offline).
- **Un moteur RAG** (BGE-M3 1024D + FTS5 BM25 + rerank cross-encoder + pondération par
  autorité de la source) sur le code et la mémoire du projet, avec un **sidecar vectoriel
  Qdrant** tenu à jour par une outbox continue. Le reranker local `:8100` est **arrêté par
  le boot-trim RAM depuis le 2026-08-10** : le rerank passe alors par son repli (Cohere
  `/v2/rerank`, puis lexical). Un rerank de qualité n'est donc pas garanti sans réveil du
  service.
- **Un planificateur GOAP** + couche d'intuition + **une boucle d'auto-amélioration**
  (traces d'exécution → entraînement offline de réseaux value/policy/cost).
- **Un superviseur** déclaratif (`proxy_deno/core/services.toml`) qui orchestre
  **86 services déclarés** par vagues, avec rechargement à chaud (`/supervisor/reload`).
  Déclaré n'est pas actif : l'état vivant d'un service se lit sur son port et son
  heartbeat, jamais sur ce fichier seul.
- **Un substrat spiking** (`snntorch`, `forge_snn_core`) en production sur la détection
  de détresse, où il apporte de la **sobriété** — moins de faux positifs — plutôt que de
  l'anticipation (mesure du 2026-08-28 : 16 épisodes détectés sur 16, 4,57 faux positifs
  par jour contre 6,14 pour le repli statique).

## Ce que Nokido N'EST PAS (honnêteté)

- **Pas un modèle de fondation.** Il ne rivalise pas avec Claude/GPT-4 en capacité brute.
  Sa force est l'orchestration et la gouvernance, pas l'intelligence du modèle sous-jacent.
- **Pas « gratuit et tout-local » au sens fort.** Les meilleurs résultats s'appuient sur
  le **cloud free-tier** routé par le firewall. Le pur-local (modèles 1.5–7B sur APU)
  est nettement plus faible. Le modèle réel = **local pour le sensible, cloud-gratuit
  pour la capacité, le firewall arbitre**.
- **Pas (encore) un produit commercial.** C'est un système souverain personnel mûr mais
  mono-utilisateur. Manquent pour le B2B : TLS du hub, multi-tenant, MFA, support.
  Le chiffrement at-rest, lui, n'est **plus** un manque (voir ci-dessus). L'installation existe
  déjà par trois chemins — `install.sh`, `install.ps1` et `pip`/`pipx` avec 15 extras —
  ce qui manque est un installeur **packagé et signé** pour un poste non technique.
  Voir la roadmap produit.
- **Pas un égal prouvé de Devin/OpenHands.** L'architecture task-to-code existe ; les
  scores sur benchmarks complets (SWE-bench) ne sont pas au niveau des leaders, qui
  s'appuient sur de grosses infra. Le harness d'éval est en cours de durcissement.

## Le différenciateur réel (le « moat »)

Pas « mieux coder que Devin ». Le moat est la **souveraineté gouvernée** :
**zero-data-leak + rings zero-trust + pare-feu/membrane + routage hétérogène frugal**.

La proposition de valeur tient en une question : *« Votre organisation peut-elle
légalement faire un `git push` de son code vers les serveurs d'OpenAI/Anthropic ? »*
Pour la Défense, la Santé (HDS/HIPAA), la Banque — la réponse est **non**. Nokido est
conçu pour ce cas : l'enclave EST la machine.

## Possibilités souveraines selon le matériel

La capacité **pur-local** (sans cloud) dépend directement du matériel. Paliers honnêtes :

| Palier | Matériel type | Ce que le PUR-LOCAL débloque |
|---|---|---|
| **Frugal** | APU Ryzen AI (Radeon 780M, 32–64 Go unifiés, NPU XDNA1) | Orchestration complète + RAG + modèles **1.5–7B** locaux + routage cloud-gratuit. Coding léger, planification, retrieval. NPU = inférence légère only (pas d'entraînement, pas de gros embeddings batch). **C'est le matériel de dev actuel.** Le sensible reste local ; la capacité vient du cloud free-tier routé. |
| **Intermédiaire** | GPU dédié 16–24 Go (RTX 4090 / 7900 XTX) ou Mac M-series 32–64 Go | Modèles **14–32B** locaux, **SFT/LoRA local réel**, coding correct **sans cloud**. Le firewall devient optionnel pour beaucoup de tâches : on peut tout garder local. |
| **Souverain plein** | Multi-GPU / 48 Go+ VRAM (A100/H100) ou Mac 64–128 Go | Modèles **70B+** locaux, capacité approchant le cloud, fine-tuning à l'échelle, **zéro dépendance cloud même pour le PHI**. C'est la cible pour une enclave Santé/Défense certifiée. |

**À retenir :** l'architecture Nokido est constante d'un palier à l'autre ; seul le
**plafond de capacité pur-local** monte avec le matériel. Sur APU frugal, la souveraineté
porte sur les **données** (le sensible ne sort jamais) plus que sur la capacité (empruntée
au cloud gratuit). Sur GPU souverain, souveraineté **données ET capacité** : plus rien ne
sort, et la capacité locale suffit.

## Comparaison honnête au marché

| Catégorie | Concurrent | Ce que Nokido apporte en plus | Où Nokido est en retard |
|---|---|---|---|
| Agent autonome | Devin, OpenHands (MIT), Devika (MIT) | Local, zero-data-leak, validateur déterministe, rings | Robustesse, maturité du harness d'éval, communauté |
| CLI d'orchestration | Claude Code | Frugalité (APU vs H100 facturés), souveraineté | Capacité brute du modèle |
| Workspace planifié | GitHub Copilot Workspace | Agnostique (tout dépôt/outil MCP), pas de cloud MS | Écosystème, intégration produit |
| IDE augmenté | Cursor | Démon asynchrone (≠ assistance synchrone) | UX, polish, adoption |

**Leçons des pairs open-source** : OpenHands (MIT) = référence à imiter sur la **rigueur
d'éval** et la **portabilité runtime** ; Devika = avertissement contre l'**éparpillement**
(approfondir la boucle cœur plutôt que multiplier les verticales). Les deux étant MIT,
leurs patterns sont légalement réutilisables dans Nokido (AGPLv3).

## Licence & gouvernance

Nokido est **AGPLv3**. Un garde-fou (`tools/forge_license_guard.py`, câblé pre-commit +
CI) bloque l'introduction de dépendances de licence incompatible (SSPL, BSL, Elastic,
propriétaire, CC-NC, GPLv2-only). Au dernier audit : **aucune dépendance incompatible**.
