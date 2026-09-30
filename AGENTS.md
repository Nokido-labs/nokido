# Nokido — AGENTS.md (instructions agent, tool-agnostic)

@RULES_SHARED.md

> `@RULES_SHARED.md` ci-dessus est expansé par Claude Code / Gemini CLI.
> **GitHub Copilot CLI** (et tout agent qui n'expanse pas `@import`) : **lis et applique
> d'abord `RULES_SHARED.md`** (socle commun, source unique). Ne duplique PAS les règles ici.

## Spécifique GitHub Copilot CLI

- **TOUT via le hub MCP `:8766`** (configuré comme serveur MCP) : `read` / `run` / `rag` /
  `query`. Jamais d'accès direct fichier / shell / LLM sur le système Nokido.
- `LAFORGE_PYTHON = ~/miniforge3/python.exe` — jamais `python` brut.
- **Anti-dup PRÉFILTRANT** avant créer OU modifier `app/forge_*.py` / `tools/forge_*.py` :
  `rag_fts` sur le domaine + lire les `[[liens]]` des memory + lire le module existant.
  Sans ces 3 étapes → STOP, pas d'édition.
- **Jamais d'envoi cloud sans `SemanticFirewall` `pre_flight` + `post_flight`** (Golden Rule #4).
- **Confirmer l'irréversible** (migration secrets, suppression, ACL, kill/restart service/job) :
  annoncer → demander → agir. En headless, `--deny-tool='shell(git push)'` par défaut.
- Réutiliser avant de reconstruire : un script/appel qui marche déjà → le relancer tel quel.

### Modèles Nokido — voir / switcher TOUS les modèles via MCP

Copilot CLI verrouille son picker natif (`settings.json` `model: auto` = modèles GitHub
seulement, **pas de BYOK endpoint**). Pour utiliser **n'importe quel modèle Nokido** (local
ou cloud OAuth) → passe par le **hub MCP**, pas le picker natif :

- **Lister les modèles dispo** : tool `hub` action=`list_providers` (ou `route_task`).
  Renvoie : local (`ollama` qwen2.5-coder/deepseek, `llamacpp`), cloud OAuth
  (`claude_cli`, `gemini_cli`), rapides (`groq`, `cerebras`, `mistral`).
- **Utiliser / switcher** : tool `ask(provider="<nom>", message="...")`.
  - `provider="ollama"` → local (préserve ton quota Haiku free-tier).
  - `provider="claude_cli"` / `"gemini_cli"` → Claude/Gemini OAuth (Max/Ultra), **PAS** l'API payante.
  - `provider="auto"` → **switchboard** (`forge_cognitive_router`/`call_cascade`) : déporte la
    micro-tâche en local, garde le cloud pour le lourd = préservation auto des quotas.
- **Règle quota** : tout ce qui est déportable (relecture, docstring, typecheck, recherche,
  reformulation) → `ask(provider="ollama"|"auto")`. Garde le Haiku natif pour l'interactif
  court. Ne brûle pas le quota cloud sur du déportable.

## Spécifique Mistral Vibe (binaire `vibe`)

Tu lis CE fichier automatiquement : vibe REMONTE l'arborescence en collectant les
`AGENTS.md` (`_collect_agents_md`). Le socle `RULES_SHARED.md` ci-dessus s'applique donc
intégralement — il n'est recopié nulle part ailleurs.

- **Tes outils natifs d'exécution et d'écriture sont COUPÉS** (`permission = "never"` sur
  `bash`, `git_bash`, `powershell`, `write_file`, `edit`). Ce n'est pas une panne : le hub
  est le seul chemin d'action, et il est gouverné. Exécuter → `run`. Écrire →
  `governed_edit` (blocs SEARCH/REPLACE : AST + scan secret + claim tree_lock).
  Lire reste natif, mais `read` / `read_function_body` / `rag` du hub servent une FENÊTRE
  au lieu de rapatrier un fichier entier — chaque tour re-facture tout l'historique.
- **Ton identité est `VIBE`, ring 3**, écriture bornée à `sandbox/`, `docs/`, `tests/`
  (`config/agent_identities.json`). Elle voyage par l'en-tête `X-Agent-Name`, et le token
  du hub est lu dans l'ENVIRONNEMENT (`auth.api_key_env = "FORGE_MCP_TOKEN"`) : il n'est
  écrit dans aucun fichier, ne l'y écris jamais.
- **Configuration** : `VIBE_HOME` pointe sur `config/clients/vibe/`, donc elle est
  VERSIONNÉE et relue. La modifier = modifier le dépôt, avec les mêmes gardes que le code.
- **Piège de format payé le 2026-07-29** : `mcp_servers` est une LISTE en fusion UNION —
  il faut `[[mcp_servers]]`. Un `[mcp_servers.<nom>]` produit un dict et fait échouer le
  démarrage sur « UNION requires list operands », sans nommer le champ fautif.
- **Le working tree est PARTAGÉ** avec Claude Code, Antigravity et des tâches autonomes :
  lis `blackboard_read_zone zone_name=tree_locks` et pose ton claim AVANT d'éditer.
  Jamais de `git add -A` — tu balaierais l'uncommitted des autres.

## Spécifique Mammouth (binaire `mammouth`)

Tu lis CE fichier : `AGENTS.md` est la convention que ton socle (opencode) charge depuis
le projet. Le socle `RULES_SHARED.md` ci-dessus s'applique donc intégralement.

- **Tes outils natifs d'exécution et d'écriture sont REFUSÉS** (`permission`: `bash` et
  `edit` à `deny`, `external_directory` à `deny`). Le hub est le seul chemin d'action :
  exécuter → `run`, écrire → `governed_edit`. La lecture (`read`, `glob`, `grep`, `list`)
  reste native, mais `read` / `read_function_body` / `rag` du hub servent une FENÊTRE au
  lieu de rapatrier un fichier entier — chaque tour re-facture tout l'historique.
- **`webfetch` et `websearch` sont en `ask`** : la sortie réseau souveraine passe par le
  `crawl` du hub (SearXNG), pas par un fetch direct.
- **Ton identité est `MAMMOUTH`, ring 3**, écriture bornée à `sandbox/`, `docs/`,
  `tests/`. Elle voyage par l'en-tête `X-Agent-Name`, et le token du hub est interpolé
  depuis l'ENVIRONNEMENT (`{env:FORGE_MCP_TOKEN}`) : il n'est écrit dans aucun fichier,
  ne l'y écris jamais.
- **Configuration** : `OPENCODE_CONFIG_DIR` pointe sur `config/clients/mammouth/`, donc
  elle est VERSIONNÉE. La modifier = modifier le dépôt, avec les mêmes gardes que le code.
- **Piège de format** : `mcp` est un **record keyé par nom** (`"mcp": {"laforge": {…}}`).
  C'est l'INVERSE de vibe, dont le champ équivalent est un tableau — ne recopie pas l'une
  sur l'autre.
- **Le working tree est PARTAGÉ** : lis `tree_locks`, pose ton claim avant d'éditer,
  jamais de `git add -A`.
