# Conception : Système de Microglie Logicielle pour Nokido

> 🧭 **IMPLÉMENTÉ SOUS D'AUTRES NOMS (réconciliation 2026-08-21).** Pas de module « microglie » ni de démon « active_decay » par ce nom ; 3 des 4 concepts existent : pruning hot/cold = `app/forge_rag_engine.py` (access_count, lambda_decay, action `pruned`) ; garde/nettoyage = `SkillGuardian` (`forge_clawhub_bridge`) + `NoiseGuardian` (`forge_silo_fragmenter`). Doc = design conceptuel, pas un module à créer.

**Date** : 2026-07-16  
**Auteur** : ANTIGRAVITY (LaForge Agent)  
**Sujet** : Identification des verrous mémoriels, immunologiques et de régulation du métabolisme de Nokido par analogie biologique.

---

## 1. Élagage Mémoriel Actif (Pruning RAG)
*   **Problématique** : Indexation permanente sans oubli dans `embeddings.db`. Pollution de contexte par les débris mémoriels (anciennes versions de docs, commits obsolètes).
*   **Design Microglie** : Un démon d'oubli sélectif (`active_decay`). Il analyse `access_count` dans `rag_chunks` et dégrade la pondération des vecteurs. Retrait ou compression sémantique des chunks inutilisés après $N$ cycles.

## 2. Phagocytose des "Pathogènes" (Anti-Poisoning)
*   **Problématique** : Les injections de prompts issues des veilles externes (ex: code ou docs tierces polluées) sont ingérées en clair dans le RAG et menacent les futures étapes du Senior.
*   **Design Microglie** : Analyse à froid continue de `rag_chunks`. Quarantaine ou neutralisation des signatures suspectes avant qu'elles ne soient extraites dans le contexte du modèle de raisonnement.

## 3. Garbage Collector Cognitif (Nettoyage de débris)
*   **Problématique** : Tâches bloquées à l'état `running` ou `claimed` (ex: résidus de sessions abandonnées) et verrous d'écriture orphelins.
*   **Design Microglie** : Recyclage automatique. Tout processus orphelin sans battement de cœur pendant $T$ secondes est réinitialisé et remis en file d'attente.

## 4. Rétroaction Inflammatoire (Endocrine Tuning)
*   **Problématique** : Manque de couplage mécanique entre les alertes de télémétrie (RAM, CPU, erreurs de compilation) et le comportement des modèles (température, filtres AST).
*   **Design Microglie** : Émission de cytokines système (flags de crise) forçant la réduction de la température des LLMs (déterminisme accru) et le renforcement des garde-fous de l'AST en cas de crise.
