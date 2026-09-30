# SUBAGENT_RULES.md — Lecture obligatoire au démarrage

Tout subagent (Claude/Gemini/Codex/…) lancé sur le code Nokido doit lire ce
fichier AVANT toute action. Brief court possible : "Read SUBAGENT_RULES.md
puis fais X".

## 1. Économie tokens — non-négociable

- `read_function_body` (hub :8766) > `Read` natif. Si hub UP, utilise hub.
- `Grep` AVANT `Read`. Cible la zone, jamais file entier > 150 lignes.
- `Agent(Explore)` pour recon multi-fichiers (dumps hors contexte).
- Une commande shell longue (>70s, multi-étapes) → script + `run_job` détaché.
- JAMAIS Python inline > 5 lignes dans un tool call — crée tools/tmp_X.py.
- `hook_search_guard` bloque Read brut > 150 lignes (Settings hook actif).

## 2. Hub MCP :8766 — accès via curl (token requis)

Si tools `mcp__laforge-sovereign-hub__*` indisponibles (registry non-rechargé) :
```bash
TOK=$(python -c "from forge_machine_vault import vault_get; print(vault_get('FORGE_MCP_TOKEN'))")
curl -sS -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"rag","arguments":{"action":"fts","q":"<terme>","limit":5}}}' \
     http://127.0.0.1:8766/mcp
```
Helper Python : `tools/hub_call.py call <method> <json_params>` (charge token auto).

## 3. Règles d'or Nokido (CLAUDE.md §7)

1. JAMAIS SQL LIKE primitif → `rag_fts` ou `RAGEngine.search`.
2. JAMAIS création `app/forge_*.py` sans query `rag_fts` préalable.
3. JAMAIS INSERT `rag_chunks` sans `id TEXT PRIMARY KEY` explicite (sha256[:16]).
4. JAMAIS envoi cloud sans `SemanticFirewall.pre_flight + post_flight`.
5. TOUJOURS `LAFORGE_PYTHON = ~/miniforge3/python.exe`, jamais `python` brut.
6. TOUJOURS `anchor_solution` après décision architecturale.
7. PAS de Co-Authored-By Claude dans les commits (repo Nokido = user solo).
8. Parent repo `Script python IA` = local-only, JAMAIS `git push` parent.
9. Branche Nokido cible : `alpha`. Push direct alpha + bump gitlink parent local.
10. `bash_guard` actif : seuls `git`, `gh`, `nssm restart Nokido*`,
    `curl http://127.0.0.1:8766/*`, `schtasks Nokido-*` passent direct.

## 4. Anti-dup PRÉFILTRANT — STOP sinon

Avant création OU modification d'un `forge_*.py` :
1. `rag_fts` query sur le domaine.
2. Read des `[[liens]]` Obsidian dans memory.md pertinents.
3. Read du module Nokido existant qui couvre le domaine.
Sans ces 3 étapes → STOP. Pas d'édition.

## 5. Confirmation irréversible

Migration secrets / suppression / ACL système / kill-restart service-job :
annoncer → demander → agir. Jamais d'action destructive sans accord explicite.

## 6. Pattern subagent recommandé

```
Étape 1 : Read SUBAGENT_RULES.md (ce fichier)
Étape 2 : Read CLAUDE.md projet pour règles spécifiques tâche
Étape 3 : Anti-dup check (rag_fts + Grep)
Étape 4 : Plan court annoncé (1-3 phrases)
Étape 5 : EXECUTE (parallèle si indépendant)
Étape 6 : Commit + push alpha + bump parent local
Étape 7 : Memory anchor si décision architecturale
```

## 7. Memory user (auto-RAM persistante)

Path : `~/.claude/projects/C--Users-user-Script-python-IA/memory/`
- `MEMORY.md` = index (1 ligne/mémoire, < 150 chars)
- Fichiers individuels = type=user|feedback|project|reference
- Update index si nouvelle mémoire ; éviter doublons.
