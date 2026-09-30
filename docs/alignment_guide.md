# 🤖 Guide d'Alignement Technique — Nokido (Mai 2026)

Ce guide définit les standards d'orchestration entre les agents **Gemini** et **Claude**.

## 1. Stack d'Orchestration
- **Système Nerveux (Deno :8000)** : 
    - Usage : Tâches asynchrones, lourdes ou nécessitant un "Organe" spécifique.
    - Appel : `POST http://127.0.0.1:8000/intent` avec un payload `{message, tools, traceId}`.
    - Résultat : Renvoie un `jobId`.
- **Rein (Kidney Monitor)** : 
    - Usage : Persistance des JobIDs et statuts dans `data/nervous_system.db` (SQLite).
    - Consultation : Utiliser l'outil MCP `check_job_status(job_id)`.
- **Hub Nokido (Python :7400)** :
    - Usage : Dashboard central et EventBus.
    - Notification : Publier les événements via `POST /api/events/publish` (Bypass localhost actif).

## 2. Standards de Communication
- **Économie de Tokens** : 
    - Regrouper les actions : `read_file`, `glob`, `grep_search` doivent être parallélisées dans un seul tour quand possible.
    - Éviter les excuses et le bavardage.
- **Affichage ToDo** : 
    - Inclure une barre de progression ASCII dans chaque ToDo list.
    - Format : `[██████░░░░] 60%`.
- **Visibilité** : Rester sur la fenêtre ToDo pour les tâches complexes.

## 3. Usage des LLM Locaux
- **Ollama / llama.cpp** : 
    - Accessibles via le Hub (provider `ollama` ou `llamacpp`).
    - Usage recommandé : Formatage JSON, extractions simples, résumé de logs, vérifications de syntaxe.
    - Objectif : Préserver les crédits/quotas des modèles "Cloud" pour le codage et le raisonnement de haut niveau.

## 4. Intégration Deno
Le proxy Deno est le point d'entrée pour les nouveaux "Organes". Si tu crées un nouveau worker (ex: script TS indépendant), il doit s'abonner au `SystemBus` dans Deno et notifier le Hub Python pour la visibilité.

---
*Alignement généré par Gemini CLI. Objectif : Orchestration Atomique.*
