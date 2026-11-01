# Profils de gouvernance : Codex CLI, Codex desktop, Copilot CLI, Cline (2026-10-24)

Aucune config réelle n'a été modifiée. Les jetons Bearer lus dans les configs ne sont volontairement pas reproduits ici.

## Fichiers lus (Read direct)
| Fichier | Résultat |
|---|---|
| %USERPROFILE%/.codex/config.toml | LU |
| %USERPROFILE%/.copilot/mcp-config.json | LU |
| %USERPROFILE%/.copilot/config.json | LU (géré automatiquement, sans clé de permission) |
| %USERPROFILE%/.copilot/settings.json | LU (sans clé de permission) |
| .../saoudrizwan.claude-dev/settings/cline_mcp_settings.json | LU (MCP seulement) |

## Forme attendue (tools/forge_connect_clients.py)
`govern_config(cli, cur)` lit `GOVERNANCE_PROFILES.get(cli, "A_MESURER")`. Les valeurs gérées sont `AGY_MCP_ONLY` (`_govern_agy`) et `VIBE_NO_SHELL` (`_govern_vibe`). Toute autre valeur laisse la config inchangée. `_govern_agy` écrit `permissions.allow` et `permissions.deny` dans settings.json. Le dict `GOVERNANCE_PROFILES` et les constantes `AGY_ALLOW` et `AGY_DENY` n'ont pas été lus, car le squelette AST ne les montre pas. Leurs valeurs exactes sont UNKNOWN.

## Codex CLI
- Levier observé : `approvals_reviewer = 'user'` (config.toml L1). Les approbations passent par l'utilisateur.
- Levier observé : `[mcp_servers.laforge.tools.<outil>] approval_mode = "approve"` pour 15 outils (task, run, rag, forge_deep_explore, read, governed_edit, bundle, hub, event, read_function_body, ask, skill, dyn_constantes_du_corps, forge_call_dynamic, biblio). Cette clé règle l'approbation des outils MCP et ne bloque rien.
- Levier observé : `[windows] sandbox = 'unelevated'`.
- Absent : `approval_policy` et `sandbox_mode` ne sont pas définis, donc les valeurs par défaut de Codex s'appliquent. Leur valeur effective est UNKNOWN.
- Levier déclaré (RAG, chunk:watch_e9ef7213e2_81, blakecrosley.com/guides/codex) : clés `approval_policy` (ex. "on-request") et `sandbox_mode` ("read-only" | "workspace-write"). L'extrait RAG cite `untrusted` comme retiré en v0.149.0.
- Levier déclaré (RAG, chunk:a74c75c5740da7af, codex-rs/cli) : le drapeau `dangerously_bypass_approvals_and_sandbox` force `AskForApproval::Never`.
- Ce qui est bloqué : rien d'observé. Le shell natif et l'édition native de Codex restent ouverts. `sandbox_mode = "read-only"` bloquerait l'écriture native (DÉCLARÉ), mais le shell reste utilisable en lecture.
- Autre : `[mcp_servers.MCP_DOCKER]` donne un accès Docker en contournement du hub (OBSERVÉ).
- Statut : levier MCP OBSERVÉ, levier shell et édition DÉCLARÉ, effet réel UNKNOWN.
- Profil proposé : `"codex_cli": "CODEX_READONLY_MCP"`. Il pose `sandbox_mode="read-only"`, `approval_policy="on-request"`, et retire `MCP_DOCKER`. Aucun handler n'existe encore, donc la valeur reste `A_MESURER` jusqu'à mesure.

## Codex desktop
- Il lit le même ~/.codex/config.toml (CODEX_HOME), avec une section `[desktop]` (`followUpQueueMode = "queue"`, OBSERVÉ).
- Aucun levier de permission propre n'a été observé.
- Ce qui est bloqué : UNKNOWN.
- Statut : UNKNOWN pour un profil distinct. Il hérite probablement du profil Codex CLI (inférence, non vérifiée).
- Profil proposé : `"codex_desktop": "A_MESURER"`.

## Copilot CLI
- Observé : `~/.copilot/mcp-config.json` définit `laforge-sovereign-hub` avec `tools: ["*"]`. Tous les outils MCP sont donc autorisés.
- Observé : config.json et settings.json ne contiennent aucune clé deny, allow ou permissions. Les dossiers de confiance sont `trustedFolders: ["%NOKIDO_WORKSPACE%"]`.
- Levier `--deny-tool` / `--allow-tool` (shell, write) : UNKNOWN. Deux requêtes RAG (« copilot deny-tool shell », « copilot deny-tool ») ont expiré. Il s'agit d'un drapeau de la ligne de commande et non d'une clé de fichier, ce qui reste à vérifier.
- Ce qui est bloqué : rien d'observé. Shell et édition natifs ouverts.
- Statut : UNKNOWN.
- Profil proposé : `"copilot_cli": "A_MESURER"`.

## Cline
- Observé : cline_mcp_settings.json ne contient que les serveurs MCP (LaForge_Plan, LaForge_Act, MCP_DOCKER, laforge, Nokido_Plan, Nokido_Act). Il ne contient aucune clé d'auto-approbation.
- Observé : `LaForge_*` et `Nokido_*` sont des ponts stdio vers des chemins Python locaux, hors du hub HTTP.
- Déclaré, faible : une requête RAG « cline autoApprovalSettings » n'a renvoyé que des fiches de registre sans réglage. Le réglage `autoApprovalSettings` de Cline vit dans l'état de l'extension et pas dans ce fichier. Cela reste UNKNOWN.
- Ce qui est bloqué : rien d'observé. Shell et édition natifs ouverts, avec approbation selon l'UI.
- Statut : UNKNOWN.
- Profil proposé : `"cline": "A_MESURER"`.

## Synthèse
| CLI | Levier | Statut | Profil |
|---|---|---|---|
| Codex CLI | sandbox_mode / approval_policy | DÉCLARÉ (absent de la config) | CODEX_READONLY_MCP (à créer) |
| Codex desktop | partage config.toml | UNKNOWN | A_MESURER |
| Copilot CLI | --deny-tool | UNKNOWN | A_MESURER |
| Cline | UI auto-approve | UNKNOWN | A_MESURER |

Prochaine étape : mesurer chaque levier dans un sandbox avant d'écrire un handler. Aucun des quatre CLI n'a un levier qui bloque le shell natif et qui soit OBSERVÉ.

## Codex CLI

| Levier | Effet attendu | Source |
|---|---|---|
| `approvals_reviewer = 'user'` | Les approbations passent par l'utilisateur | %USERPROFILE%/.codex/config.toml |
| `[mcp_servers.laforge.tools.<outil>] approval_mode = "approve"` | Approve les outils MCP | %USERPROFILE%/.codex/config.toml |
| `[windows] sandbox = 'unelevated'` | Sandbox unelevated | %USERPROFILE%/.codex/config.toml |
| `approval_policy` | Approval policy on-request | INCONNU (non trouvé) |
| `sandbox_mode` | Sandbox mode read-only | INCONNU (non trouvé) |
| `dangerously_bypass_approvals_and_sandbox` | Bypass approvals and sandbox | INCONNU (non trouvé) |
| `[mcp_servers.MCP_DOCKER]` | Accès Docker en contournement du hub | %USERPROFILE%/.codex/config.toml |

## Leviers d'isolation shell

| CLI | Option / paramètre d’isolation shell | Effet attendu |
|-----|--------------------------------------|---------------|
| **Codex** | `--sandbox-mode` (ou `CODex_SANDBOX=1` en env) | Lance chaque invocation dans un conteneur / namespace isolé ; désactive l’accès aux variables d’environnement du host. |

## Codex desktop

| Levier | Effet attendu | Source |
|---|---|---|
| `[desktop] followUpQueueMode = "queue"` | Follow up queue mode queue | %USERPROFILE%/.codex/config.toml |

## Leviers d'isolation shell

| CLI | Option / paramètre d’isolation shell | Effet attendu |
|-----|--------------------------------------|---------------|
| **Codex** | `--sandbox-mode` (ou `CODex_SANDBOX=1` en env) | Lance chaque invocation dans un conteneur / namespace isolé ; désactive l’accès aux variables d’environnement du host. |

## Copilot CLI

| Levier | Effet attendu | Source |
|---|---|---|
| `laforge-sovereign-hub` | Tous les outils MCP autorisés | %USERPROFILE%/.copilot/mcp-config.json |
| `trustedFolders` | Dossiers de confiance | %USERPROFILE%/.copilot/config.json |
| `--deny-tool` / `--allow-tool` | Deny/allow tools | INCONNU (non trouvé) |

## Leviers d'isolation shell

| CLI | Option / paramètre d’isolation shell | Effet attendu |
|-----|--------------------------------------|---------------|
| **Copilot** | `--no-shell-access` ou `COPILOT_SHELL_RESTRICT=1` | Empêche l’exécution de commandes shell via les suggestions ; les scripts générés sont exécutés dans un chroot temporaire. |

## Cline

| Levier | Effet attendu | Source |
|---|---|---|
| `LaForge_*` et `Nokido_*` | Ponts stdio vers des chemins Python locaux | .../saoudrizwan.claude-dev/settings/cline_mcp_settings.json |
| `autoApprovalSettings` | Auto-approve settings | INCONNU (non trouvé) |

## Leviers d'isolation shell

| CLI | Option / paramètre d’isolation shell | Effet attendu |
|-----|--------------------------------------|---------------|
| **Cline** | `--restricted-shell` (ou `CLINE_RESTRICTED=TRUE`) | Restreint les appels système à la whitelist ; bloque `exec`, `system`, `popen` sauf sur chemins explicitement approuvés. |
