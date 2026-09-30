# RFC : Detached Progress Hook (Subagent UI) pour Nokido

**Date:** 2026-06-12
**Auteur:** Gemini (Agent Nokido)
**Contexte:** Basé sur la veille approfondie "Claude Fable 5" et les concepts de "Background Routines" / "Lead-Subagent Orchestration".

## 1. Le Problème Actuel
Dans l'architecture actuelle, lorsqu'un agent CLI (comme Gemini ou Claude) lance une tâche asynchrone complexe via le `ChainExecutor` (ex: `forge-veille-approfondie`), l'agent est obligé :
- Soit de bloquer et d'attendre passivement (gaspillage de tokens de contexte et de temps).
- Soit de générer et d'exécuter un script Python temporaire local (via `run_shell_command`) pour afficher une barre de progression dans le terminal, ce qui pollue le flux d'exécution et pose des risques de sécurité (injections shell bloquées).

## 2. Le Concept (Inspiré de Fable 5)
L'état de l'art (Pattern Lead-Subagent) prône l'**isolation totale entre le raisonnement (le LLM) et l'UI/Background**. 
Nous devons implémenter un **Detached Progress Hook**. L'idée est qu'un processus léger (un sous-agent UI) gère exclusivement la communication visuelle de la tâche de fond, pendant que l'agent LLM (le Lead) peut continuer à réfléchir ou s'endormir pour économiser des ressources.

## 3. Architecture Proposée

### A. Côté Hub (`http://127.0.0.1:8766`)
Le Hub Nokido doit exposer un point de terminaison de flux (Server-Sent Events - SSE) ou un polling ultra-rapide pour l'état des jobs.
- **Endpoint:** `GET /api/watch/stream?job_id=wj_12345`
- **Output:** `{ "step": "refine", "progress_pct": 60, "status": "running" }`

### B. Côté Wrapper CLI (Client-Side)
Le wrapper CLI qui encapsule l'agent (le script qui fait tourner Gemini/Claude dans le terminal) doit écouter les commandes émises.
- Si le Hub répond à un tool `run_job` ou `create_job` par un payload contenant `{ "job_id": "...", "detached_hook": true }`, le wrapper CLI intercepte ce signal.
- Le wrapper lance un **worker thread natif** (en Python brut, pas un script généré par le LLM).
- Ce thread dessine une barre de progression asynchrone (via ANSI escape codes ou `rich`/`textual`) directement sur la sortie standard (stdout) de l'utilisateur.

### C. Côté Agent (LLM)
L'agent LLM se contente de l'action primitive (Dispatch & Forget) :
```json
{
  "name": "create_job",
  "arguments": {
    "theme": "...",
    "stream_progress": true 
  }
}
```
Une fois le job lancé, l'agent peut informer l'utilisateur "La tâche est lancée en tâche de fond" et **terminer son tour**. Le terminal prend le relai visuel. Quand la tâche est finie, le job envoie un message dans l'Inbox de l'agent via `hub action=notify`.

## 4. Bénéfices
1. **Zéro Token Cost :** L'animation de la barre de progression ne coûte aucun token d'inférence LLM.
2. **True Async :** L'agent n'est pas bloqué. Il peut faire d'autres recherches en parallèle.
3. **Sécurité :** Plus besoin de générer des scripts Python/Shell à la volée qui risquent d'être bloqués par les pares-feux (ex: PowerShell command injection guards).
4. **UX de Classe Mondiale :** L'expérience terminal rejoint les standards des "Background Routines" de Fable 5.
