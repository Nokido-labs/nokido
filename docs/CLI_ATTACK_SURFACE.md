# Audit de la Surface d'Attaque des CLI Clients face au Hub Nokido
**Date :** 5 juillet 2026  
**Auteur :** Antigravity (`agt_antigravity`, reprise de tâche `job_e0769384`)  
**Méthodologie :** Analyse statique SSoT (RBAC, Videur, Confinement d'écriture, Hooks d'exécution) sans dump, 0-token.

---

## 1. Matrice de Sécurité par CLI Client (`CLI x Privilèges`)

| CLI Client | Ring Assigné | Source d'Identité / Token | Périmètre Outils (RBAC) | Confinement Écriture (`AGENT_WRITE_PATHS`) | Exécution Native (Hors-Hub) |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **CLAUDE** *(Claude Code / Desktop)* | **Ring 1** *(DEV)* | Vault `FORGE_TOKEN_CLAUDE` (ou mcp_stdio_bridge) | Tous outils Ring 1+ (`run`, `write`, `secret`, `execute`) | `['*']` (Wildcard complet sauf `CRITICAL_FILES`) | Stdio bridge / hook-less (risque modéré si prompt injecté) |
| **ANTIGRAVITY / GEMINI** (`gy` / `agy`) | **Ring 2** *(TRUSTED)* / Ring 3 | Vault `FORGE_TOKEN_ANTIGRAVITY` | Outils Ring 2+ (`orchestrate`, `browser`, `run`) | `['sandbox/', 'docs/', 'tests/', 'logs/', 'migrations/', 'config/']` | **CRITIQUE :** `approvalMode=yolo` active l'auto-exec natif sans confirmation |
| **CODEX** | **Ring 2** *(TRUSTED)* / Ring 3 | Vault `FORGE_TOKEN_CODEX` | Outils Ring 2+ | `['sandbox/', 'docs/', 'tests/', 'logs/', 'migrations/', 'config/']` | Hook-less, confinement standard |
| **CLINE** | **Ring 3** *(COLLAB)* | Vault `FORGE_TOKEN_CLINE` | Outils Ring 3+ (`ask`, `task`, `event`, `memory`) | `['app/', 'tests/', 'src/', 'sandbox/', 'docs/']` *(Anomalie : accès `app/`)* | Hook-less, exécution via IDE |
| **COPILOT / VSCODE** | **Ring 3 / 4** | En-tête `X-Agent-Name` (ou env) | Outils Ring 3+ ou Ring 4 (`read`, `query`, `rag`) | `default` : `['sandbox/']` | Terminal IDE contrôlé par l'utilisateur |
| **VIBE** *(mistral-vibe, binaire `vibe`)* | **Ring 2** *(TRUSTED, vérifié 29-07)* | `FORGE_MCP_TOKEN` lu dans l'env via `auth.api_key_env` — **jamais** dans le fichier ; identité par en-tête `X-Agent-Name: VIBE` | Outils Ring 2+ | `['app/', 'tools/', 'proxy_deno/', 'src/', 'tests/', 'docs/', 'config/', 'migrations/', 'logs/', 'sandbox/']` | **COUPÉE ET VÉRIFIÉE** : `permission = "never"` sur `bash` / `git_bash` / `powershell` / `write_file` / `edit`, doublé par `disabled_tools` du profil `laforge` |

| **MAMMOUTH** *(mammouth-ai/code, binaire `mammouth`)* | **Ring 3** *(COLLAB, provisoire)* | `FORGE_MCP_TOKEN` interpolé par `{env:…}` — **jamais** dans le fichier ; identité par en-tête `X-Agent-Name: MAMMOUTH` | Outils Ring 3+ | `['sandbox/', 'docs/', 'tests/']` | **REFUSÉE** : `permission` → `bash: deny`, `edit: deny`, `external_directory: deny` (`config/clients/mammouth/mammouth.jsonc`) |

> **Note MAMMOUTH (2026-07-29).** Fork d'**opencode** (son `package.json` porte
> `name: "opencode"`, son schéma vient de `@opencode-ai/core`). Son modèle de permissions
> est le plus fin du parc : `ask | allow | deny` sur `read`, `edit`, `glob`, `grep`,
> `list`, `bash`, `task`, `external_directory`, `webfetch`, `websearch`, `skill`, avec
> des règles PAR PATTERN (`bash: {"*.sh": "allow"}`). Il n'existe pas de clé `write`
> distincte : `edit` couvre l'écriture. Second client, après vibe, dont le secret n'est
> écrit nulle part — `{env:VAR}` est substitué avant le parsing, y compris dans les
> en-têtes HTTP.
>
> **Piège de format, symétrique de celui de vibe** : ici `mcp` est un **record keyé par
> nom** (`{"laforge": {…}}`), là-bas `mcp_servers` est un **tableau**. Recopier l'une sur
> l'autre casse le démarrage — vérifié dans le schéma, pas supposé.

> **Note VIBE (2026-07-29).** Premier client dont l'exécution native est *désactivable par
> son propre mécanisme* plutôt que par la seule discipline : `vibe` expose `permission =
> always|ask|never` par outil, et des hooks `pre_tool` capables de refuser un appel. Il est
> donc structurellement plus contraignable qu'un client hook-less — mais la coupure n'a pas
> encore été **vérifiée sur la machine**, d'où le ring 3 provisoire et non un ring 2.
> Aucun Bearer dans sa configuration : `MCPStaticAuth.api_key_env` nomme la variable
> d'environnement et vibe lit le token au lancement — c'est le premier client du parc dont
> le secret n'est écrit nulle part. Les autres portent leur Bearer en clair dans un fichier
> de config (gitignoré, mais en clair), et l'un d'eux en portait un DIFFÉRENT d'un autre :
> plusieurs jetons hub coexistent, ce qui reste à instruire.
>
> **Piège de configuration payé le 2026-07-29** : `mcp_servers` est déclaré
> `list[MCPServer]` avec fusion UNION, donc il faut `[[mcp_servers]]` (tableau de tables).
> Un `[mcp_servers.<nom>]` produit un dict et fait échouer le démarrage sur
> « UNION requires list operands, got list and dict », sans nommer le champ fautif — et la
> migration automatique de vibe ne convertit pas l'ancien format.

---

## 2. Classification des Vulnérabilités et Failles Détectées

### 🔴 CRITIQUE (Score : 10/10) — RBAC en mode WARN par défaut (`app/forge_mcp_rbac.py`)
* **Constat :** Dans `forge_mcp_rbac.py`, la variable de contrôle `LAFORGE_RBAC_MODE` est initialisée sur `"warn"` par défaut (`_ENFORCE = _MODE == "enforce"`).
* **Impact :** Lorsqu'un agent de Ring 3 (COLLAB) ou Ring 4 (UNTRUSTED) tente d'appeler un outil restreint au Ring 1 ou 2 (ex: `run`, `write`, `execute`), le système se contente d'émettre un log d'avertissement (`[RBAC WARN-only mode] would deny...`) mais **autorise l'exécution de l'outil**.
* **Scénario d'attaque :** Un script externe ou un prompt malveillant injecté dans une tâche de veille RAG appelle l'action `run` ou `write` via un client Ring 4 et parvient à exécuter du code arbitraire sur le Hub.

### 🟠 ÉLEVÉE (Score : 8/10) — Usurpation d'en-tête vers Ring 3 au lieu de Ring 4 (`app/forge_videur.py`)
* **Constat :** Dans `forge_videur.resolve_identity`, lorsqu'un en-tête HTTP `X-Agent-Name` est fourni sans le token cryptographique associé (`token` absent ou invalide), le mécanisme anti-spoofing abaisse le privilège à `_HEADER_FLOOR_RING = 3`.
* **Impact :** Une requête anonyme sans token, simplement parée de l'en-tête `X-Agent-Name: CLAUDE`, n'est pas rétrogradée en Ring 4 (UNTRUSTED / Lecture seule) mais obtient un statut **Ring 3 (COLLAB)**, lui donnant accès aux outils inter-agents (`task`, `event`, `memory`, `crawl`, `emit_telemetry`).

### 🟠 ÉLEVÉE (Score : 7.5/10) — Surface d'exécution YOLO d'Antigravity CLI (`agy` / `gy`)
* **Constat :** Le client Antigravity CLI utilise souvent le paramètre `approvalMode=yolo` dans les workflows automatisés ou les boucles d'orchestration pour éviter de bloquer sur des prompts utilisateur.
* **Impact :** En cas d'ingestion d'une instruction malveillante par le modèle (ex: via un chunk RAG ou un résultat SearXNG empoisonné), le CLI exécute directement les commandes bash/pwsh proposées par le LLM sur la machine hôte sans passer par le filtre de sécurité du Hub (`forge_sandbox_exec`).

### 🟡 MOYENNE (Score : 5/10) — Disparité et privilège excessif dans AGENT_WRITE_PATHS (`app/forge_mcp_security.py`)
* **Constat :** La table `AGENT_WRITE_PATHS` accorde à `CLINE` les droits d'écriture sur `['app/', 'tests/', 'src/', 'sandbox/', 'docs/']`, alors que les agents souverains du cœur (`ANTIGRAVITY`, `CODEX`, `GEMINI`) sont formellement confinés à `['sandbox/', 'docs/', 'tests/', 'logs/', 'migrations/', 'config/']`.
* **Impact :** Un agent `CLINE` compromis ou mal aligné pourrait modifier directement le code source du moteur Nokido (`app/` et `src/`), contournant la gouvernance souveraine.

---

## 3. Plan de Remédiation et Recommandations Architecturales

1. **Activation du Mode Enforce par Défaut (Urgence 1) :**
   * Modifier `app/forge_mcp_rbac.py` ou injecter `LAFORGE_RBAC_MODE=enforce` dans `Nokido.env` et `.env` afin d'imposer un blocage strict et immédiat de tout franchissement d'anneau inter-périmètres.
2. **Durcissement du Videur Anti-Spoofing (Urgence 2) :**
   * Dans `app/forge_videur.py`, modifier la règle de plancher : si `via == "header"` sans authentification par token valide, imposer `ring = _UNTRUSTED_RING` (Ring 4) au lieu de Ring 3.
3. **Confinement Harmonisé des Écritures :**
   * Rétrograder les accès d'écriture de `CLINE` dans `app/forge_mcp_security.py` pour l'aligner strictement sur la politique de moindre privilège : `['sandbox/', 'docs/', 'tests/', 'logs/']`.
4. **Garde-Fou YOLO Contextuel :**
   * Intégrer dans les hooks Antigravity CLI (`after_model_hook.py`) une détection de contexte RAG non fiable qui force la désactivation temporaire de `approvalMode=yolo` ou bascule l'exécution sur `mcp_run` confiné dans le Hub.
