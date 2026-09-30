# Design C1 : Orchestrateur Déporté & Centralisation des Assets (Sync Générique)

## 1. Objectif (Vision actualisée)
L'objectif n'est pas seulement de synchroniser des fichiers statiques. Il s'agit de **déployer un orchestrateur déporté sur les surfaces CLI et agents (Claude, Gemini, Copilot)**. Ce pont, matérialisé par des hooks/plugins synchronisés, agit comme un "gate" appelable par le Hub Nokido. 
Il permet de :
1. **Forcer des actions natives** spécifiques aux CLI.
2. **Déporter les actions externes coûteuses en tokens** (recherche massive, ingestion, réflexion profonde) vers le Hub Nokido qui orchestre ces workflows en arrière-plan.
3. **Privilégier l'exécution locale** systématique dès que les performances le permettent.
4. Maintenir un profil d'agent hautement performant sur des tâches complexes tout en maximisant l'**économie de tokens cloud**.

## 2. Principes Architecturaux
- **Gate d'Orchestration** : Les assets synchronisés (hooks) agissent comme des intercepteurs intelligents. Ils capturent les intentions lourdes et les routent vers le Hub Nokido.
- **Types d'assets génériques** : Abstraction de la logique de copie via une classe de base `AssetType` (définissant src, dest, method) pour couvrir hooks, scripts d'orchestration et workflows.
- **Manifest + Rollback réutilisés** : Le manifeste de synchronisation existant est étendu pour tracer le type de chaque asset, permettant un rollback universel et idempotent.
- **Discover Inverse** : Capacité à scanner les dossiers de destination (ex: ~/.claude/hooks) pour détecter les modifications locales de l'orchestrateur déporté, avant d'écraser.
- **Zéro apply auto** : Le processus génère un plan d'exécution strict. Aucune mutation sans approbation explicite (`apply=True`).

## 3. Plan d'Implémentation
- **Phase A** : Refactoring de `forge_skill_sync.py` pour intégrer l'énumération des assets génériques (dont les hooks d'orchestration).
- **Phase B** : Câblage de la logique de "Gate" : s'assurer que les hooks déployés incluent la logique de délégation vers l'API Hub (`/mcp` ou `/task`).
- **Phase C** : Mise à jour du manifeste et intégration de la logique de discover inverse (comparaison empreintes Nokido vs Surface).
- **Phase D** : Déploiement des 9 scripts `hook_*.py` existants transformés en relais d'orchestration locaux.
