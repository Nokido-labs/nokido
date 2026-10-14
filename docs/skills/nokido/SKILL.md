---
name: nokido
description: >
  Nokido — runtime d'organisme local-first : hub HTTP :8766, bridge stdio, RAG SQLite,
  modules forge_*.py (carte : sandbox/workspace/organ_map_full.json),
  forge_task_queue, forge_roles, forge_trust_score, forge_mailbox.
  Journal des commits tenu à jour localement dans JOURNAL_COMMITS.md.
---

# Nokido — Knowledge Base pour IAs collaboratrices

## Architecture rapide
- Hub : `tools/nokido_hub.py` — Starlette :8766
- Bridge : `tools/mcp_stdio_bridge.py` — stdio → HTTP
- Rôles : `app/forge_roles.py` — PLANNER/EXECUTOR/REVIEWER/ROUTER/SUMMARIZER/SENTINEL/MONITOR
- Queue : `app/forge_task_queue.py` — SQLite persistant, Semaphore(2)
- RAG : `RAG/embeddings.db` — chunks bge-m3 1024d (volume : le lire, `rag` stats)
- Rescue : `tools/forge_rescue.py` — canal de secours admin on-demand

## Changelog automatique (post-commit)

Le journal des commits vit dans `JOURNAL_COMMITS.md`, à côté de ce fichier : écrit après chaque commit par
`tools/forge_post_commit.py`, **non versionné**. Il réécrivait ce fichier à chaque commit, et l'arbre partagé n'était
jamais propre (décision owner du 2026-10-14). L'historique qui fait foi reste `git log` ; les versions antérieures de ce
fichier, qui portaient le journal, restent dans l'historique git.
