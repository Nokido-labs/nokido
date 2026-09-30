# PLAN_CONVERGENCE_QUALIXAR.md - Vers l'Intention Originelle

> 🕰️ **PRÉMISSES PÉRIMÉES (audit 2026-08-21).** Les fondations existent déjà sous des noms Nokido différents : BM25 Okapi = `app/forge_rag_engine.py` ; Graph-Linker = `app/forge_graph_linker.py` (pas `forge_gnn.py`) ; service Windows = LaForge-Master/NSSM. L'unification décrite reste à câbler, mais plusieurs items se croient « à faire » alors qu'ils sont réalisés ailleurs.

## 🎯 Vision : Le Cerveau Souverain Unifié
L'objectif est de supprimer la fragmentation entre les 6 "Galaxies" du projet pour créer un agent unique, capable de basculer du CTF au DevOps sans perte de contexte, tout en garantissant une étanchéité totale des données.

---

### Phase 1 : Consolidation de la Mémoire (Priorité 1)
*Objectif : Passer d'un RAG "bruyant" à une intelligence structurée.*
- [ ] **Déploiement du BM25 Okapi natif** (Fait : 24/04) : Prioriser les termes techniques.
- [ ] **RAG Janitor** : Créer un script de nettoyage qui exclut les `.bak`, `__pycache__` et les logs de plus de 48h du processus d'indexation.
- [ ] **Graph-Linker** : Activer le module `forge_gnn.py` pour lier les chunks non plus par similarité cosinus, mais par **dépendance structurelle** (ex: lier un handler MCP à sa définition de sécurité dans `mcp_server_tools.py`).

### Phase 2 : Stabilité du Hub & "Mode Dégradé"
*Objectif : Supprimer le SPOF (Single Point of Failure).*
- [ ] **Service Windows (NSSM)** : Automatiser l'installation du Hub en tant que service persistant.
- [ ] **Failsafe Router** : Si le Hub MCP ne répond pas, permettre à l'agent d'utiliser un mode "Lite" via des appels `subprocess` directs sur les outils critiques (netcfg, fs).
- [ ] **Canary Healthcheck** : Étendre le mécanisme de "Canari" à la santé du Hub. Si un canari détecte une corruption de mémoire, redémarrer automatiquement le service.

### Phase 3 : Unification des Interfaces (MoA)
*Objectif : Fusionner CodeViber, Inception et Nokido.*
- [ ] **MoA Consensus Protocol** : Intégrer la logique de "Mixture of Agents" de `CodeViber` dans le `SiloEngine`. Avant de valider une action de sécurité, faire voter deux modèles locaux (Qwen vs DeepSeek).
- [ ] **Unified UI Gateway** : Centraliser les 3 interfaces vers une API unique (le Hub). Forge Desktop, TUI et Web doivent consommer la même logique métier.

### Phase 4 : Autonomie Offensive (CTF & Recon)
*Objectif : Transformer les scripts statiques en agents dynamiques.*
- [ ] **ChainEngine Evolution** : Porter le `chain_engine.py` de `recon_silo` vers le `SiloEngine`. L'IA doit pouvoir enchaîner seule : Recon -> Scan -> Exploit -> Post-Exploit sans intervention humaine, via des "Capability Tokens" temporaires.

---

## 🔗 Liens & Idées Suggérées à Récupérer
- **Lien avec Claude Code** : Utiliser le pattern `Lead-Subagent` pour les tâches de longue durée (ex: audit de 1400 fichiers).
- **Le "Canari" Sémantique** : Utiliser des fichiers "canaris" contenant des secrets bidon pour détecter si un modèle Cloud essaie d'exfiltrer des données (Honeytokens).
- **L'Inception Logic** : Garder l'idée du proxy Ollama déporté pour permettre à Nokido de piloter des machines distantes via SSH sans installer de Python sur la cible.

## 🚀 Prochaine Étape Immédiate
- Tester la robustesse du **Fast-Track SiloEngine** sur une intention de type "Audit réseau Visio" pour voir s'il bascule correctement en mode complexe.
