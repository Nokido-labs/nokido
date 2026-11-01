# Conception & Enquête : Cache Partagé des Lectures et Résultats d'Outils Multi-Agents (MCP/ACP)

**Date :** 30 octobre 2026  
**Auteur :** Antigravity (`agt_antigravity`, Ring 1)  
**Contexte & Motivation :** Chasse aux tokens (owner 30/10, point 6) ; mutualisation des lectures et résultats d'outils redondants entre agents hétérogènes (`agt_claude`, `agt_antigravity`, `agt_opencode`, `agt_codex`, `agt_vibe`, et essaims cloud) via le Hub MCP (`:8766`) et ACP.  
**Fondements théoriques :**
- *« Persistent Shared Memory against Redundant Tool Calls »* (arXiv:2606.21228) : mutualisation cross-agent et déduplication des exécutions déterministes.
- *« Hierarchical Two-Level Memory: Private vs Shared Workspaces »* (arXiv:2507.00672) : étanchéité de session locale (L1 privé) vs cache partagé souverain (L2 commun indexé par empreinte d'état).

---

## 1. État des Lieux & Anti-Doublon (Existant vs Manquant)

### 1.1 Ce qui existe déjà dans le dépôt

1. **`app/forge_rag_cache.py` (`RagCache`) :**
   - **Rôle :** Cache RAM vectoriel L1/L2 (embeddings et recherche cosinus) pour la base RAG `RAG/embeddings.db`.
   - **Mécanisme :** Charge en RAM (`numpy.ndarray`) les vecteurs normalisés, gère un timestamp de dernière modification du fichier SQLite et invalide la mémoire si la base change (`maybe_reload`, `invalidate`).
   - **Périmètre & Limites :** Strictement dédié aux vecteurs RAG sémantiques. N'a aucune prise sur les lectures de fichiers de code (`read`, `read_function_body`, `get_file_skeleton`) ni sur les résultats d'outils RPC/shell/SQL.

2. **`app/forge_cache_aligner.py` :**
   - **Rôle :** Stabilisation de préfixes textuels pour optimiser le prompt caching côté fournisseurs LLM (ex: Anthropic Prompt Caching).
   - **Mécanisme :** Élimination de bruit dynamique (timestamps, IDs éphémères), extraction de `prefix_hash(text)` pour regrouper les blocs invariants en tête de contexte.
   - **Périmètre & Limites :** C'est un préprocesseur de texte/prompt destiné au cache LLM fournisseur. Il ne stocke aucun résultat d'outil ni contenu de fichier lu en local.

3. **`app/forge_mcp_registry.py` (Handlers de lecture MCP) :**
   - `handle_read(self, args, agent, ring)` (L3461–L3541) :
     - Reçoit `path` ou `action='tail_logs'` / `action='archived'`.
     - Applique `assert_can_read` (SecretGuard), puis lit directement sur disque (`path.read_text(...)`).
     - *Constat :* Chaque appel de chaque agent lit le fichier sur le disque sans mise en cache. Si 4 agents inspectent tour à tour `app/forge_ssot.py` (100 Ko), le fichier est lu et retransféré 4 fois sur le bus sans aucune déduplication locale ni métrique d'économie.
   - `handle_read_function_body(self, args, agent, ring)` (L6618–L6644) :
     - Reçoit `file_path` et `function_name`.
     - Ouvre le fichier sur disque, parse l'arbre AST via `ast.parse(source)`, itère sur les noeuds, et extrait le corps de la fonction.
     - *Constat :* Même si 3 agents demandent la même fonction sur le même commit/fichier invariant, l'AST est re-parsé à chaque appel.
   - `handle_get_file_skeleton(self, args, agent, ring)` (L6671–L6689) :
     - Délègue à `forge_repo_map.file_skeleton(path, root)`.
     - *Constat :* Pas de cache partagé multi-agents du squelette AST calculé.

4. **Mécanismes connexes partiels :**
   - `_archive_blob` / CCR (L522–L540) : Stash sous `sandbox/ccr/<id>.txt` pour récupérer de gros blobs sans tronquer, mais sans déduplication par contenu ni clé de requête.
   - `_WHOAMI_DOMAINES` (L5180–L5197) : Cache en mémoire de 10 min avec verrou `threading.Lock` pour un comptage SQL lourd.

### 1.2 Ce qui manque

Il n'existe actuellement **aucun cache persistant unifié partagé entre agents** qui indexe le couple `(outil, arguments, état_cible)` pour :
1. Éviter de re-parser/re-lire les fichiers invariants.
2. Court-circuiter des résultats d'outils idempotents/déterministes (lectures, introspections, AST, requêtes de schéma).
3. Permettre à l'exécuteur ACP (`forge_acp_hub` / `handle_acp`) et aux agents CLI (Claude, AGY, OpenCode, Vibe, Codex) de puiser dans un puits de résultats déjà validés.

---

## 2. Conception Détaillée de l'Architecture

### 2.1 Clé de Cache Canonique Normalisée
Pour garantir l'exactitude sans collision, la clé primaire de cache `cache_key` doit être un hash déterministe (SHA-256) composé de :

$$\text{cache\_key} = \text{SHA256}(\text{tool\_name} \parallel \text{normalized\_args} \parallel \text{target\_fingerprint} \parallel \text{git\_scope})$$

1. **`tool_name` :** Nom canonique de l'outil (`read`, `read_function_body`, `get_file_skeleton`, `introspect`).
2. **`normalized_args` :** JSON canonique trié par clé (`json.dumps(args, sort_keys=True, separators=(',', ':'))`). Les chemins relatifs sont résolus en chemins normalisés relatifs à la racine du worktree (`/` sous Windows et POSIX).
3. **`target_fingerprint` (Empreinte du fichier cible) :**
   - Mode rapide (stratégie 2-tiers) : `mtime_ns` + `file_size_bytes`.
   - Si `mtime` ou `size` change, ou pour vérification forte : `sha256(file_content)`.
   - Pour les outils sans fichier cible unique (ex: `introspect`) : empreinte de l'index de graphe ou HEAD git commit.
4. **`git_scope` (Portée de version) :** Commit SHA courant (`git rev-parse HEAD`) ou identifiant de worktree.

### 2.2 Stockage SQLite Déporté sous `sandbox/`
Conformément aux règles d'architecture et de permissions Nokido :
- **Emplacement :** `sandbox/shared_tool_cache.db`.
- **Mode SQLite :** `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`.
- **Schéma relationnel suggéré :**
  ```sql
  CREATE TABLE IF NOT EXISTS tool_cache (
      cache_key TEXT PRIMARY KEY,
      tool_name TEXT NOT NULL,
      worktree_root TEXT NOT NULL,
      commit_sha TEXT NOT NULL,
      file_path TEXT,
      file_fingerprint TEXT,
      args_json TEXT NOT NULL,
      result_payload TEXT NOT NULL,
      payload_type TEXT NOT NULL, -- 'text' ou 'json'
      tokens_saved_estimate INTEGER NOT NULL DEFAULT 0,
      hit_count INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      last_accessed_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_tool_cache_path ON tool_cache(file_path);
  CREATE INDEX IF NOT EXISTS idx_tool_cache_scope ON tool_cache(worktree_root, commit_sha);
  ```

### 2.3 Mécanisme d'Invalidation
- **Invalidation par Empreinte Fichier (File-level) :**
  À chaque requête de lecture, avant de rendre le cache, un `os.stat(resolved_path)` vérifie `st_mtime_ns` et `st_size`. Si l'un des deux diffère de `file_fingerprint`, l'entrée est déclarée périmée (STALE) et invalidée/mise à jour.
- **Invalidation lors des Mutations Gouvernées :**
  Dans `handle_write` et `handle_governed_edit`, un hook direct purge ou met à jour les entrées associées au `file_path` modifié.
- **Portée Worktree / Commit (Branch isolation) :**
  Les worktrees git distincts (`nokido_worktrees/taches/...`) peuvent être sur des branches ou commits différents. L'inclusion du `worktree_root` et du `commit_sha` empêche un agent travaillant sur une branche feature de recevoir les lectures d'un fichier modifié sur la branche principale sans commit commun.

### 2.4 Acteurs et Alimentation (Producteurs & Consommateurs)
1. **Le Hub MCP (`:8766`) - Couche de Dispatch Centrale :**
   - Intercepte les outils en amont (`ToolRegistry.dispatch`) ou spécifiquement dans les handlers de lecture (`handle_read`, `handle_read_function_body`, `handle_get_file_skeleton`).
   - Si HIT : log l'économie de tokens, incrémente `hit_count`, renvoie immédiatement le résultat sans accès disque ni calcul AST.
   - Si MISS : exécute le handler normal, stocke le résultat dans `shared_tool_cache.db`, et retourne le résultat.
2. **L'Exécuteur ACP (`forge_acp_hub.py` / `handle_acp`) :**
   - Lors de la transmission de contextes ou de prompts partagés entre sessions agents (Claude, Codex, OpenCode, AGY), consulte le cache partagé pour éluder les relectures de fichiers déjà injectés dans l'arbre d'exécution du même job (`job_id`).
3. **Consommateurs :**
   - Tous les agents (Claude Code, Antigravity, OpenCode, Codex, Vibe, agents légers de veille). Le cache est transparent et ne requiert aucune modification de contrat côté client MCP.

### 2.5 Mesure du Gain et Économie de Tokens
- **Estimation des tokens évités :**
  Pour chaque cache HIT :
  $$\text{tokens\_saved} \approx \lceil \text{len}(\text{result\_payload}) / 3.8 \rceil$$
- **Comptabilité agrégée :**
  Le champ `tokens_saved_estimate` cumulé permet à `handle_forge_stats` et `hub action=quota_report` de quantifier exactement le volume de tokens cloud/locaux épargnés par l'infrastructure mutualisée.

---

## 3. Fichiers Cibles à Modifier (Cartographie Précise)

| Fichier | Emplacement / Fonction | Lignes Actuelles | Modification Prévue |
|---|---|---|---|
| **`app/forge_shared_cache.py`** *(Nouveau module)* | Nouveau service autonome | L1+ | Implémentation du moteur SQLite `SharedToolCache` : normalisation des clés, calcul d'empreinte `mtime+size+sha`, lecture/écriture avec verrou WAL, métriques de tokens. |
| **`app/forge_mcp_registry.py`** | `handle_read` | L3461–L3541 | Consultation du cache partagé avant `path.read_text` (pour `action='file'`), alimentation en sortie. |
| **`app/forge_mcp_registry.py`** | `handle_read_function_body` | L6618–L6644 | Consultation du cache sur `(file_path, function_name, file_fingerprint)` avant parsing AST ; enregistrement du snippet extrait. |
| **`app/forge_mcp_registry.py`** | `handle_get_file_skeleton` | L6671–L6689 | Mise en cache du squelette retourné par `forge_repo_map.file_skeleton`. |
| **`app/forge_mcp_registry.py`** | `handle_write` & `handle_governed_edit` | L3542+ & L2129+ | Invalidation ciblée des entrées du fichier modifié dans `tool_cache`. |
| **`app/forge_mcp_registry.py`** | `handle_forge_stats` | L6645–L6670 | Exposition des métriques `tool_cache_stats` : taux de hit, entrées actives, total tokens économisés. |
| **`tools/forge_acp_hub.py`** | Session / Exécution de tâche | Handlers de jobs | Consultation du cache pour éviter de réexpédier des lectures de fichiers identiques entre tours d'agents. |

---

## 4. Synthèse Stratégique

Ce dispositif comble exactement le vide entre le cache vectoriel sémantique (`forge_rag_cache.py`) et l'aligneur de prompts (`forge_cache_aligner.py`). Il matérialise l'architecture L1 (privé à l'agent) / L2 (partagé persistant sous `sandbox/shared_tool_cache.db`), protège la boucle d'événements du Hub, et réduit drastiquement l'empreinte token globale du swarm multi-agents.
