# Analyse architecturale Nokido - par gemini-2.5-flash

**Finish reason**: STOP
**Length**: 26319 chars

---

Excellent projet, Nokido est une architecture ambitieuse et très riche en fonctionnalités ! La documentation fournie est d'une qualité exceptionnelle et m'a permis de plonger rapidement dans les détails de votre système. Le `PANORAMA.md` et `PLAN_REFACTO.md` montrent que vous avez déjà une conscience aiguë des défis architecturaux et avez initié des efforts de refactoring, ce qui est un excellent point de départ.

Voici mon analyse et mes propositions, structurées selon vos questions.

## ANALYSE GENERALE DE L'ARCHITECTURE

Nokido est un système complexe et puissant, intégrant de multiples facettes de l'IA agentique, de la sécurité et de l'orchestration. Les points forts incluent :
*   **Souveraineté et Confidentialité :** Le `NoiseGuardian` et l'approche "local-first" sont des piliers architecturaux solides et différenciants.
*   **Orchestration Multi-LLM :** La cascade `call_cascade()` et les `USE_CASE_CHAINS` sont très bien pensées pour la résilience et l'optimisation des coûts/performances.
*   **Agentique Avancée :** Les silos cognitifs, le mode CTF auto-évolutif, et le `ClawHub` sont des fonctionnalités de pointe.
*   **Documentation Interne :** Les fichiers `.md` sont une mine d'or, détaillant l'architecture, les décisions de refactoring, les roadmaps et les APIs dormantes. C'est rare et précieux.

Les défis majeurs, que vous avez déjà identifiés, résident dans la **complexité du codebase**, la **granularité des modules**, et la **gestion de la dette technique**. La taille de `app/` (207 modules) est le symptôme principal.

---

## 1. FICHIERS MASSIFS : Découpage et Simplification

Ces fichiers sont des "god objects" qui concentrent trop de responsabilités. Le plan est de les décomposer en modules plus petits et plus spécialisés, en suivant le principe de la *Single Responsibility Principle*.

### **`Nokido.py` (194KB)**
*   **Problème :** C'est le point d'entrée principal, la TUI, l'orchestrateur central. Il gère probablement l'initialisation, la boucle événementielle, l'affichage, l'interaction utilisateur et la coordination des agents.
*   **Plan de découpage :**
    1.  **`app/ui/tui_app.py` :** Extraire la classe principale de l'application Textual (`NokidoApp`), la gestion du layout, des widgets (sidebar, chat, terminal), et les raccourcis clavier.
    2.  **`app/ui/widgets.py` :** Déplacer les widgets Textual spécifiques (`RichLog`, `SkillTreeDisplay`, `AgentPanel`, etc.) qui sont actuellement dans `forge_ui_widgets.py` (si ce n'est pas déjà fait) ou directement dans `Nokido.py`.
    3.  **`app/core/bootstrap.py` :** Renforcer ce module pour gérer *toute* l'initialisation de Nokido (chargement config, démarrage services, RAG warmup, etc.), en le séparant de la logique de la TUI.
    4.  **`app/orchestration/main_orchestrator.py` :** Extraire la logique de haut niveau de l'orchestration (gestion des modes, coordination des agents CHEF/CLINE/DEBAT/AUTO PILOT, boucles d'auto-amélioration `@loop`, `@audit`, etc.). `forge_autonomous_orchestrator.py` et `forge_orchestrator.py` pourraient être fusionnés ici ou servir de base.
    5.  **`app/commands/cli_parser.py` :** Si `Nokido.py` gère aussi le parsing des commandes `@`, extraire cette logique.

### **`forge_agents.py` (128KB)**
*   **Problème :** Comme le suggère `Nokido_FEATURES.md`, il contient "Rôles IA, scoring modèles, routage intent, orchestration parallèle". C'est un hub pour tout ce qui touche aux agents.
*   **Plan de découpage :** Créer un sous-package `app/agents/`.
    1.  **`app/agents/core.py` :** La classe de base `NokidoAgent` et les mécanismes fondamentaux d'interaction.
    2.  **`app/agents/roles.py` :** Déplacer les définitions de rôles (`CHEF`, `CLINE`, `DEBAT`, `AUTO PILOT`) et leur logique spécifique. Fusionner avec `forge_agent_roles.py`.
    3.  **`app/agents/scoring.py` :** La logique de scoring des modèles et des compétences.
    4.  **`app/agents/routing.py` :** La logique de routage des intentions vers les agents ou silos appropriés.
    5.  **`app/agents/orchestration.py` :** Les mécanismes d'orchestration parallèle des agents. Fusionner avec `forge_autonomous_orchestrator.py` et `forge_orchestrator.py` si pertinent.
    6.  **`app/agents/authority.py` :** Déplacer la logique de gouvernance et de permissions (`forge_agent_authority.py`).

### **`forge_code.py` (100KB)**
*   **Problème :** Contient `DangerGuard`, `CodeSandbox`, boucles d'amélioration, `ErrorMemory`. Ce sont des préoccupations distinctes.
*   **Plan de découpage :**
    1.  **`app/security/code_guard.py` :** Extraire la logique de `DangerGuard` (analyse AST, détection de patterns dangereux, blocage d'appels). Fusionner avec `forge_code_guard.py` (voir section 2).
    2.  **`app/sandbox/code_sandbox.py` :** Extraire la gestion de l'exécution de code en sandbox.
    3.  **`app/agents/auto_improve.py` :** Déplacer les boucles d'auto-amélioration du code.
    4.  **`app/core/error_memory.py` :** Extraire la gestion de la mémoire des erreurs.

### **`forge_collab_modes.py` (70KB)**
*   **Problème :** Gère les différents modes de collaboration multi-agents.
*   **Plan de découpage :**
    1.  **`app/orchestration/collab_modes.py` :** Renommer et simplifier, en se concentrant sur la définition et la transition entre les modes (`AUTO`, `CLINE`, `CHEF`, `DEBAT`, `PING`).
    2.  **`app/orchestration/mode_handlers/` (sous-package) :** Créer des modules spécifiques pour la logique de chaque mode (ex: `chef_mode.py`, `cline_mode.py`, `debat_mode.py`).

### **`brain_worker.py` (57KB)**
*   **Problème :** C'est un sidecar ML via ZeroMQ. Il expose des services comme embeddings, tree-sitter, Phi-3.5 ONNX.
*   **Plan de découpage :** Créer un sous-package `brain_worker/` à la racine du projet (car c'est un processus séparé).
    1.  **`brain_worker/__main__.py` :** Le point d'entrée du worker, gérant la boucle ZMQ.
    2.  **`brain_worker/services/embeddings.py` :** La logique d'embeddings (MiniLM, Ollama bge-m3).
    3.  **`brain_worker/services/tree_sitter_analyzer.py` :** La logique tree-sitter (audit sécurité, chirurgie).
    4.  **`brain_worker/services/onnx_generator.py` :** La logique de génération ONNX (Phi-3.5).
    5.  **`brain_worker/core/priority_queue.py` :** La gestion de la PriorityQueue.

### **`forge_at_dispatch.py` (59KB)**
*   **Problème :** Fait partie du système de dispatch. `PANEL_ORCHESTRATION.md` liste `forge_dispatch`, `forge_dispatch_ai`, `forge_dispatch_network`.
*   **Plan de découpage :**
    1.  **`app/orchestration/dispatch_core.py` :** Le cœur du système de dispatch.
    2.  **`app/orchestration/dispatch_ai.py` :** Logique de dispatch spécifique à l'IA.
    3.  **`app/orchestration/dispatch_network.py` :** Logique de dispatch spécifique au réseau.
    4.  **`app/orchestration/at_dispatcher.py` :** Renommer et intégrer la logique spécifique de `forge_at_dispatch.py` dans le système de dispatch unifié.

---

## 2. REDONDANCE DE NOMS : Regroupement des modules agentiques

La confusion autour des modules `forge_agent*` est un signe clair de manque de structure. La création d'un sous-package `app/agents/` est la solution la plus propre.

*   **`app/agents/__init__.py` :** Contiendrait la classe de base `Agent` et les configurations globales des agents.
*   **`app/agents/engine.py` :** Fusionner `forge_agentic.py` (moteur agentique général) et `forge_autonomous_orchestrator.py` (orchestrateur autonome).
*   **`app/agents/core_agents.py` :** Fusionner `forge_agents.py` (rôles IA, scoring, routage) et `forge_core_agents.py` (agents de base).
*   **`app/agents/roles.py` :** Fusionner `forge_agent_roles.py` (définitions de rôles) et `forge_triad_authority.py` (si lié aux rôles d'autorité).
*   **`app/agents/governance.py` :** Fusionner `forge_agent_authority.py` (gouvernance des agents) et potentiellement des aspects de `forge_metacognition_gate.py` (filtre méta-cognitif pour la prise de décision des agents).
*   **`app/agents/benchmarking.py` :** Déplacer `forge_agent_benchmarker.py`.
*   **`app/agents/hardware.py` :** Déplacer `forge_agent_hardware.py` (allocation hardware pour les agents).
*   **`app/agents/ctf_agent.py` :** Déplacer `forge_ctf_agent.py` (agent spécifique CTF).
*   **`app/agents/swarm.py` :** Fusionner `forge_swarm.py` et `forge_swarm_team.py` pour la logique d'orchestration en essaim.

**Action concrète :**
1.  Créer le dossier `app/agents/`.
2.  Pour chaque module listé ci-dessus, créer le fichier cible dans `app/agents/`.
3.  Déplacer le code pertinent des modules sources vers les modules cibles.
4.  Supprimer les modules sources originaux (ou les déplacer dans `_attic/` si des doutes subsistent).
5.  Mettre à jour tous les imports.

---

## 3. DETTES TECHNIQUES : Purge et Archivage

Le `PLAN_REFACTO.md` est déjà très clair sur le processus de `KILL` et `_attic/`.

*   **Fichiers `.bak`, `_tmp.py`, `Nokido_tmp.py` :** **Suppression immédiate.** Ce sont des artefacts de développement qui n'ont pas leur place dans un codebase propre.
*   **Dossiers `_attic/`, `_internal/` :**
    *   **`_attic/` :** Le `PLAN_REFACTO.md` mentionne 67 fichiers. Le manifest `KILL_20260416_105323.txt` est un bon point de départ.
        *   **Processus :**
            1.  **Vérification finale :** Pour chaque fichier dans `_attic/`, faire une recherche globale dans le projet pour s'assurer qu'il n'est *absolument plus importé ou référencé*.
            2.  **Suppression :** Si la vérification est positive, **supprimer définitivement** les fichiers de `_attic/`.
            3.  **Archivage :** Si vous souhaitez conserver une trace historique *hors du projet actif*, créez un dossier `archive/` à la racine du projet (ex: `archive/2026-04-audit/`) et déplacez-y les fichiers supprimés. Cela permet de garder le dépôt propre tout en ayant une "sauvegarde" si nécessaire.
    *   **`_internal/` :** Si ce dossier existe et contient des fichiers non utilisés, appliquer le même processus.
*   **`failed_mutation/`, `shadow_mutation/` :** Ces dossiers semblent liés à des tests ou expérimentations d'auto-amélioration.
    *   **Processus :**
        1.  **Revoir leur utilité :** Sont-ils encore actifs ? Sont-ils nécessaires pour le debug ou l'audit ?
        2.  **Nettoyage :** Si ce sont des logs ou des résultats temporaires, les vider régulièrement.
        3.  **Déplacement :** Si ce sont des outils ou des scripts, les déplacer dans `tools/` ou `sandbox/` si leur nature est expérimentale.

---

## 4. ARCHITECTURE GLOBALE : Nouvelle Structure de Dossiers/Sous-packages

L'objectif est de passer d'une structure `app/` plate à une organisation modulaire et hiérarchique, améliorant la découvrabilité, la maintenabilité et la clarté.

**Structure Racine Proposée :**

```
LaForge/
├── .git/
├── .vscode/ (ou autre IDE config)
├── .pre-commit-config.yaml
├── LICENSE
├── Nokido.env
├── pyproject.toml
├── README.md
├── environment.yml
├── RAG/
├── __pycache__/
├── app/                  <-- Le cœur de l'application
├── archive/              <-- Anciens fichiers supprimés (dette technique)
├── backups/
├── benchmarks/
├── config/               <-- Fichiers de configuration (ex: claude_desktop_config.json)
├── data/                 <-- Données persistantes (ex: project_atlas.json)
├── docs/                 <-- Toute la documentation (y compris les .md actuels)
├── logs/
├── models/               <-- Modèles LLM locaux (gguf, ONNX)
├── recon_silo/           <-- Le silo de reconnaissance (processus potentiellement séparé)
├── sandbox/              <-- Espace de travail temporaire, scripts d'expérimentation
├── skills/               <-- ClawHub skills
├── tests/
├── tools/                <-- Scripts utilitaires, outils CLI (ex: nokido_mcp_server.py)
├── workspace/            <-- Espace de travail pour les agents (clones de repos, etc.)
├── brain_worker/         <-- Le sidecar ML (si c'est un processus distinct)
```

**Structure Détaillée de `app/` :**

```
app/
├── __init__.py
├── core/                 <-- Fondations de l'application
│   ├── __init__.py
│   ├── bootstrap.py      (forge_boot.py, bootstrap.py)
│   ├── settings.py       (forge_settings.py, Nokido.env parsing)
│   ├── logging.py        (forge_logging.py)
│   ├── versioning.py     (forge_version.py, forge_versioning.py)
│   ├── state.py          (forge_state.py - FIX BUG ici)
│   ├── context.py        (forge_context.py, forge_app_context.py, forge_mmap_context.py)
│   └── utils.py          (forge_utils.py, forge_retry_strategies.py, forge_events.py)
│
├── agents/               <-- Tout ce qui concerne les agents
│   ├── __init__.py
│   ├── engine.py         (forge_agentic.py, forge_autonomous_orchestrator.py)
│   ├── core_agents.py    (forge_agents.py, forge_core_agents.py)
│   ├── roles.py          (forge_agent_roles.py, forge_triad_authority.py)
│   ├── governance.py     (forge_agent_authority.py, forge_metacognition_gate.py)
│   ├── benchmarking.py   (forge_agent_benchmarker.py)
│   ├── hardware.py       (forge_agent_hardware.py)
│   ├── ctf_agent.py      (forge_ctf_agent.py)
│   └── swarm.py          (forge_swarm.py, forge_swarm_team.py)
│
├── llm/                  <-- Gestion des modèles de langage
│   ├── __init__.py
│   ├── router.py         (forge_llm_router.py, forge_cognitive_router.py, forge_ghost_router.py, forge_router_gateway.py, forge_spike_router.py)
│   ├── backends/         <-- Modules spécifiques aux backends LLM
│   │   ├── __init__.py
│   │   ├── ollama.py     (forge_ollama.py, forge_ollama_bridge.py)
│   │   ├── llamacpp.py   (forge_llamacpp.py)
│   │   ├── gemini.py     (forge_gemini_bridge.py)
│   │   ├── litellm.py    (forge_litellm_bridge.py, forge_litellm_connector.py)
│   │   └── openrouter.py (forge_openrouter.py)
│   ├── prompt_builder.py (forge_prompt_builder.py)
│   └── prompt_guard.py   (forge_prompt_guard.py)
│
├── rag/                  <-- Retrieval-Augmented Generation
│   ├── __init__.py
│   ├── engine.py         (forge_rag_engine.py)
│   ├── store.py          (forge_rag_store.py, forge_rag_cache.py)
│   ├── indexer.py        (forge_rag_index_app.py, forge_hot_ingest.py)
│   ├── embeddings.py     (forge_npu_embedder.py)
│   ├── graph.py          (forge_graph_rag.py, forge_graph_search.py, forge_graph_explorer.py, forge_graph_studio.py, forge_graph_universal.py)
│   ├── warmup.py         (forge_rag_warmup.py, patch_rag_warmup.py)
│   ├── qualify.py        (forge_rag_qualify.py)
│   └── truth.py          (forge_rag_truth.py, forge_vec_ledger.py)
│
├── mcp/                  <-- Model Context Protocol
│   ├── __init__.py
│   ├── server.py         (mcp_server_tools.py)
│   ├── bridge.py         (mcp_bridge.py)
│   ├── security.py       (forge_mcp_security.py)
│   └── github_connector.py (forge_github_mcp_connector.py)
│
├── security/             <-- Fonctions de sécurité transversales
│   ├── __init__.py
│   ├── noise_guardian.py (forge_noise_guardian.py, forge_sovereign_mapper.py, forge_sovereign_membrane.py)
│   ├── integrity.py      (forge_integrity.py)
│   ├── sentinel.py       (forge_sentinel.py, forge_semantic_firewall.py)
│   ├── sanitizer.py      (forge_conv_sanitizer.py, forge_sanitizer_analyst.py)
│   └── code_guard.py     (DangerGuard, AST analysis from forge_code.py, forge_code_guard.py)
│
├── orchestration/        <-- Logique d'orchestration et de dispatch
│   ├── __init__.py
│   ├── silo_engine.py    (forge_silo_engine.py, forge_silo_fragmenter.py)
│   ├── dispatch.py       (forge_dispatch.py, forge_dispatch_ai.py, forge_dispatch_network.py, forge_at_dispatch.py)
│   ├── collab_modes.py   (forge_collab_modes.py)
│   ├── cascade_oracle.py (forge_cascade_oracle.py)
│   └── prefect_workflows.py (forge_prefect.py)
│
├── ctf/                  <-- Fonctions spécifiques aux CTF
│   ├── __init__.py
│   ├── brain.py          (forge_ctf_brain.py)
│   ├── adaptive.py       (forge_ctf_adaptive.py)
│   ├── benchmark.py      (forge_ctf_benchmark.py)
│   ├── pwn_engine.py     (forge_adaptive_pwn.py, forge_cyber_pivot.py, forge_cyber_pivot_engine.py, forge_libc_resolver.py)
│   └── ghidra.py         (ctf_ghidra.py, ctf_layout.py, ctf_planner.py, ctf_rag.py, ctf_validator.py)
│
├── ui/                   <-- Composants de l'interface utilisateur (TUI)
│   ├── __init__.py
│   ├── tui_app.py        (Nokido.py - la classe Textual App)
│   ├── widgets.py        (forge_ui_widgets.py, parties de Nokido.py)
│   └── pty_terminal.py   (forge_pty.py)
│
├── hardware/             <-- Gestion du hardware (NPU, GPU, CPU)
│   ├── __init__.py
│   ├── allocator.py      (forge_hw_allocator.py)
│   ├── monitor.py        (hardware_monitor.py, forge_mem_watchdog.py, forge_idle_watchdog.py)
│   ├── npu.py            (forge_npu.py, forge_npu_env.py, forge_phi3_npu.py)
│   └── performance.py    (forge_performance_tuner.py)
│
├── web/                  <-- Services web et intégrations
│   ├── __init__.py
│   ├── service.py        (forge_web.py, forge_web_service.py)
│   └── kaggle_bridge.py  (forge_kaggle_bridge.py)
│
├── data_sync/            <-- Synchronisation de données et environnements
│   ├── __init__.py
│   ├── dataset_sync.py   (forge_dataset_sync.py)
│   ├── env_sync.py       (forge_env_sync.py, forge_env_crypt.py)
│   └── codeberg_sync.py  (forge_codeberg_sync.py)
│
├── skills/               <-- Gestion des compétences ClawHub
│   ├── __init__.py
│   ├── bridge.py         (forge_clawhub_bridge.py)
│   ├── autoinstall.py    (forge_clawhub_autoinstall.py)
│   └── skill_rag_bridge.py (forge_skill_rag_bridge.py)
│
├── sandbox/              <-- Fonctions de sandbox (distinctes de app/sandbox)
│   ├── __init__.py
│   └── code_sandbox.py   (CodeSandbox from forge_code.py)
│
└── diagnostics/          <-- Outils de diagnostic et de monitoring
    ├── __init__.py
    ├── health.py         (forge_health.py)
    ├── metrics.py        (forge_metrics.py)
    └── debug.py          (debug.py, diag_nokido.py, forge_gui_debug.py)
```

**Note sur `brain_worker/` :** Si `brain_worker.py` est un processus Python distinct, il devrait être un package de premier niveau à côté de `app/`, avec sa propre structure interne (comme proposé dans la section 1).

---

## 5. POINTS FAIBLES DE L'ARCHITECTURE ACTUELLE ET RISQUES

1.  **Bug critique dans `forge_state.py` (Dette Technique / Risque de Bug Silencieux) :**
    *   **Problème :** `PLAN_REFACTO.md` identifie des constantes dupliquées avec des valeurs *différentes* (`_T_BOOL`, `_T_INT`, `_T_STR`, `_T_EMPTY`). Ce module est "déjà actif via `bootstrap.py`".
    *   **Risque :** Comportement imprévisible et difficile à débugger, car des parties du code pourraient utiliser des définitions de constantes différentes, menant à des erreurs logiques silencieuses ou des corruptions de données. C'est une bombe à retardement.
    *   **Impact :** Élevé.

2.  **Fichiers Monolithiques (`Nokido.py`, `forge_agents.py`, `forge_code.py`, etc.) (Maintenabilité / Risque de Régression) :**
    *   **Problème :** Trop de responsabilités dans un seul fichier.
    *   **Risque :** Toute modification peut avoir des effets de bord inattendus. Difficile de tester des unités isolément. Augmente la complexité cognitive pour les développeurs. Ralentit le développement et augmente le risque de régression.
    *   **Impact :** Élevé à moyen terme.

3.  **Structure `app/` Plate (Découvrabilité / Maintenabilité / Risque de Duplication) :**
    *   **Problème :** 207 modules dans un seul dossier.
    *   **Risque :** Très difficile de trouver le code pertinent, de comprendre les dépendances, et d'éviter la duplication de fonctionnalités (comme vu avec les modules `forge_agent*`). Le risque de "code mort" ou d'API dormantes non intentionnelles est accru.
    *   **Impact :** Élevé à moyen terme.

4.  **Redondance `forge_code.py` vs `forge_code_guard.py` (Dette Technique / Risque de Sécurité / Incohérence) :**
    *   **Problème :** `PLAN_REFACTO.md` mentionne un "doublon de migration partielle" où `forge_code_guard.py` semble plus récent mais non importé, tandis que `forge_code.py` est actif.
    *   **Risque :** Si `forge_code_guard.py` contient des améliorations de sécurité ou des corrections de bugs non appliquées à `forge_code.py`, le système pourrait être vulnérable. Inversement, si `forge_code.py` est l'ancienne version, il pourrait y avoir des failles. Incohérence dans la logique de sécurité.
    *   **Impact :** Élevé (surtout si lié à la sécurité).

5.  **Fiabilité des Backends Cloud (Disponibilité / Performance) :**
    *   **Problème :** `map.md` et `PANEL_ORCHESTRATION.md` signalent des problèmes récurrents avec les clés API (Gemini quota, Groq clé bannie, xAI permissions).
    *   **Risque :** Bien que la cascade `call_cascade()` soit une excellente mesure d'atténuation, une défaillance fréquente des premiers maillons de la chaîne peut dégrader les performances globales et la fiabilité perçue du système.
    *   **Impact :** Moyen à élevé (sur l'expérience utilisateur et la performance).

---

## 6. TOP 5 AMELIORATIONS PRIORITAIRES

Voici les 5 améliorations les plus prioritaires, avec un focus sur l'impact et l'effort, et des actions concrètes.

### **PRIORITÉ 1 : Correction du Bug Critique dans `forge_state.py`**
*   **Impact :** ÉLEVÉ (stabilité, fiabilité, prévention de bugs silencieux).
*   **Effort :** FAIBLE (identification et correction ciblée).
*   **Action :**
    1.  **Localiser :** Ouvrir `app/forge_state.py`.
    2.  **Identifier :** Trouver les lignes 79-82, 88-91, 93-96 et les constantes `_T_BOOL`, `_T_INT`, `_T_STR`, `_T_EMPTY`.
    3.  **Corriger :** Harmoniser ces définitions pour qu'il n'y ait qu'une seule source de vérité pour chaque constante, avec la valeur correcte. Supprimer les doublons.
    4.  **Tester :** Exécuter les tests unitaires et fonctionnels pour s'assurer qu'aucune régression n'est introduite.

### **PRIORITÉ 2 : Consolidation et Modularisation des Modules Agentiques**
*   **Impact :** ÉLEVÉ (clarté architecturale, maintenabilité, réduction de la duplication, facilité de développement de nouvelles fonctionnalités agentiques).
*   **Effort :** MOYEN (nécessite de déplacer et de refactorer du code, de mettre à jour les imports).
*   **Action :**
    1.  **Créer `app/agents/` :** Mettre en place la structure de sous-packages comme détaillé dans la section 4.
    2.  **Fusionner `forge_agents.py` et `forge_core_agents.py` :** Créer `app/agents/core_agents.py` et y déplacer le code pertinent.
    3.  **Fusionner `forge_agentic.py` et `forge_autonomous_orchestrator.py` :** Créer `app/agents/engine.py`.
    4.  **Déplacer les modules spécifiques :** Déplacer `forge_agent_roles.py` vers `app/agents/roles.py`, `forge_agent_authority.py` vers `app/agents/governance.py`, etc.
    5.  **Mettre à jour les imports :** Utiliser les nouveaux chemins (`from app.agents.core_agents import ...`).

### **PRIORITÉ 3 : Découpage de `Nokido.py` (TUI et Orchestration Principale)**
*   **Impact :** ÉLEVÉ (amélioration de la maintenabilité de l'interface utilisateur, séparation des préoccupations, facilitation des tests UI).
*   **Effort :** MOYEN (nécessite une bonne compréhension de Textual et de la boucle principale).
*   **Action :**
    1.  **Créer `app/ui/` et `app/orchestration/` :** Mettre en place ces sous-packages.
    2.  **Extraire la TUI :** Créer `app/ui/tui_app.py` et y déplacer la classe `NokidoApp` de Textual, ainsi que toute la logique d'affichage et d'interaction directe avec l'utilisateur.
    3.  **Extraire l'Orchestrateur Principal :** Créer `app/orchestration/main_orchestrator.py` et y déplacer la logique de haut niveau de coordination des agents et des boucles d'auto-amélioration.
    4.  **Mettre à jour `Nokido.py` :** Le transformer en un simple point d'entrée qui initialise l'orchestrateur et lance l'application TUI.

### **PRIORITÉ 4 : Nettoyage de la Dette Technique (`_attic/` et fichiers temporaires)**
*   **Impact :** MOYEN (réduction de l'encombrement, amélioration de la clarté du projet, réduction du "bruit" dans les recherches de code).
*   **Effort :** FAIBLE à MOYEN (nécessite une revue systématique).
*   **Action :**
    1.  **Supprimer les fichiers temporaires :** Supprimer immédiatement tous les `.bak`, `_tmp.py`, `Nokido_tmp.py` et autres fichiers non versionnés.
    2.  **Purger `_attic/` :**
        *   Pour chaque fichier dans `_attic/`, effectuer une recherche globale dans le projet pour confirmer qu'il n'est plus utilisé.
        *   Si confirmé, supprimer le fichier de `_attic/`.
        *   Envisager de déplacer les fichiers supprimés vers un dossier `archive/` à la racine du projet pour une conservation historique hors du dépôt actif.
    3.  **Résoudre la duplication `forge_code.py` vs `forge_code_guard.py` :**
        *   Analyser les deux fichiers pour déterminer lequel est le plus à jour et complet.
        *   Fusionner les fonctionnalités dans `app/security/code_guard.py` (ou `app/sandbox/code_sandbox.py` si la logique de sandbox est prédominante).
        *   Supprimer l'ancien fichier ou le déplacer dans `archive/`.

### **PRIORITÉ 5 : Amélioration de la Fiabilité des Backends Cloud**
*   **Impact :** MOYEN à ÉLEVÉ (performance, disponibilité, expérience utilisateur).
*   **Effort :** MOYEN (nécessite des actions externes et des ajustements de code).
*   **Action :**
    1.  **Vérifier et Renouveler les Clés API :** Obtenir de nouvelles clés pour Gemini, Groq, xAI, et tout autre fournisseur défaillant. S'assurer qu'elles sont correctement configurées dans `Nokido.env`.
    2.  **Implémenter des Stratégies de Retry Avancées :** Renforcer `forge_retry_strategies.py` avec des backoffs exponentiels et des jitter pour les appels aux APIs cloud, afin de mieux gérer les `429 Too Many Requests`.
    3.  **Monitoring Actif des Quotas :** Si possible, intégrer un monitoring des quotas d'API (si les fournisseurs exposent cette information) pour ajuster dynamiquement les `USE_CASE_CHAINS` ou alerter l'utilisateur.
    4.  **Diversifier les Fournisseurs Gratuits :** Continuer à explorer et intégrer de nouveaux fournisseurs avec des tiers gratuits généreux (comme OpenRouter) pour augmenter la résilience de la cascade.

---

Ce plan est ambitieux mais nécessaire pour la pérennité et l'évolutivité de Nokido. En commençant par les priorités les plus critiques, vous poserez des bases solides pour les futures évolutions. Bonne forge !