# Conception & Architecture : Cache Partagé Dédié à l'Économie de Tokens Multi-Agents (MCP / ACP / A2A)

**Date :** 30 octobre 2026  
**Auteur :** Antigravity (`agt_antigravity`, Ring 1)  
**Référence :** Suite et correction de fond de `docs/enquetes/cache_partage_agents_20261030.md`.  
**Contexte impératif (owner 30/10, Chasse aux tokens) :** Un cache côté hub qui renvoie le contenu complet d'un fichier en réponse RPC/MCP n'économise **aucun token LLM**, car l'agent client reçoit le payload intégral, le réinjecte dans sa fenêtre de contexte et le repaye à chaque tour de prompt. L'optimisation doit se faire **au niveau de la charge utile transmise au modèle LLM**.

---

## 1. Analyse Préliminaire : Rôle et Capacité du Protocole A2A pour le Partage de Digests

L'inspection de `tools/forge_a2a_server.py` et `tools/forge_a2a_card.py` établit les faits architecturaux suivants :

1. **Structure actuelle d'A2A dans Nokido :**
   - Le serveur implémente le Tier 1 de la spécification A2A (`message/send`, `tasks/get`, `tasks/cancel`) sur le port `:7783` avec authentification stricte Fail-Closed (`FORGE_A2A_TOKEN` / `FORGE_MCP_TOKEN`).
   - L'unité fondamentale d'échange dans `message/send` et `tasks/get` est la tâche (`Task`), contenant un historique (`history`), un contexte (`contextId`), un statut (`status`), et surtout une collection d'**`artifacts`** :
     ```python
     tache["artifacts"].append({
         "artifactId": "a-" + secrets.token_hex(6),
         "parts": [{"kind": "text", "text": "..."}],
     })
     ```
   - La carte d'agent (`forge_a2a_card.py`) expose l'état vivant selon la doctrine Nokido des trois états (`DECLARE`, `AVAILABLE`, `VERIFIED`), ne publiant dans `skills` que les capacités couvertes par des Non-Régression Tests (`NR`).

2. **Aptitude d'A2A à porter le volet (c) (Partage de Digests entre agents) :**
   - **OUI, A2A est parfaitement taillé pour porter le partage de digests.**
   - En protocole A2A, un agent délégant (ex: un orchestrateur d'essaim ou `agt_claude`) soumet une sous-tâche d'exploration ou d'analyse d'un module volumineux à un worker (ex: worker local Ollama, ou `agt_antigravity`).
   - Plutôt que de retourner le fichier brut (qui saturerait la mémoire partagée et le contexte du demandeur), le worker produit un artefact typé : `kind="application/vnd.nokido.digest+json"` ou texte structuré contenant le squelette AST (`get_file_skeleton`), les signatures publiques, les résumés de dépendances (`get_function_dependencies`), ou le corps d'une fonction ciblée (`read_function_body`).
   - Les artefacts A2A sont attachés à la tâche et référençables par URI/ID sans ré-ingestion de texte brut, permettant aux agents pairs d'interroger la tâche (`tasks/get`) pour récupérer uniquement le digest produit.

---

## 2. Piliers d'Économie de Tokens (a, b, c)

Pour abaisser de 80 % à 98 % la facture de tokens des agents lors des cycles de développement et d'investigation, le Hub MCP (`:8766`), l'adaptateur ACP (`handle_acp`) et la passerelle A2A appliquent trois mécanismes sélectifs :

```
                        Requête agent: read(path="app/forge_ssot.py")
                                            │
                                  [Résolution Contexte]
                               (agent, session_id, worktree)
                                            │
                                  [Calcul Empreinte]
                              sha256(content), mtime, size
                                            │
                   ┌────────────────────────┴────────────────────────┐
                   │                                                 │
          Première lecture                                   Déjà lu en session ?
                   │                                                 │
                   ▼                                      ┌──────────┴──────────┐
          Stockage registre                               ▼                     ▼
          Envoi Contenu Complet                    Empreinte identique?   Empreinte modifiée?
             (100% tokens)                                │                     │
                                                          ▼                     ▼
                                                    (a) MARQUEUR          (b) DIFF UNIFIÉ
                                                     « INCHANGÉ »        patch unifié seul
                                                    (~15 tokens)          (~100-300 tokens)
```

### 2.1 (a) Marqueur « Inchangé » (Token Zero-Reload)
* **Problème :** Un agent relit `app/forge_ssot.py` (2 500 lignes, ~25 000 tokens) à chaque étape de raisonnement pour vérifier un détail ou par réflexe de boucle réactive.
* **Solution :** Si le tuple `(agent, session_id, resolved_path)` a déjà été lu au cours de la session active et que l'empreinte cryptographique du fichier sur disque est strictement identique à celle enregistrée lors de la dernière lecture :
  - Le hub **ne renvoie pas** le corps du fichier.
  - Le hub renvoie un message atomique d'invariance d'une seule ligne :
    ```text
    [INCHANGÉ] app/forge_ssot.py — identique à ta lecture de 14:32:05 (sha256: 7a8f...3e12, 112 450 octets). Utilise ton contexte précédent.
    ```
  - **Gain :** Passage de 25 000 tokens à 22 tokens (économie de 99,9 %).
  - *Option d'échappement :* Si l'agent a perdu son contexte (ex: compactage), l'argument explicite `force_reload=True` dans `args` permet de forcer la restitution intégrale.

### 2.2 (b) Différentiel Unifié (Delta-Only Updates)
* **Problème :** Un fichier de 3 000 lignes a été modifié de 4 lignes (ex: correction d'une typo ou ajustement d'un garde par un agent ou un outil). L'agent relit tout le fichier.
* **Solution :** Si le fichier a déjà été lu par cet agent dans cette session, mais que son empreinte courante diffère de l'empreinte mémorisée :
  - Le hub génère le diff unifié via `difflib.unified_diff` entre le contenu lors de la dernière lecture (conservé en cache compressé) et le contenu actuel sur disque.
  - Le hub renvoie le diff unifié annoté :
    ```text
    [DIFFÉRENTIEL] app/forge_ssot.py — modifié depuis ta lecture de 14:15:00 (+4 lignes, -2 lignes) :
    --- app/forge_ssot.py (ta lecture de 14:15:00)
    +++ app/forge_ssot.py (actuel)
    @@ -142,4 +142,6 @@
    -    return False
    +    # Fix fail-closed guard
    +    if not token:
    +        return False
    ```
  - Le registre met à jour l'empreinte et le contenu de référence de l'agent pour ce fichier.
  - **Gain :** 300 tokens au lieu de 25 000 tokens (économie de 98,8 %).

### 2.3 (c) Partage Transversal de Digests (AST Skeletons & Function Bodies)
* **Problème :** Plusieurs agents explorent le même grand fichier. Si chacun demande le fichier complet pour découvrir son API ou une seule méthode, la bande passante et les contextes explosent.
* **Solution :**
  - Favoriser et mettre en cache L2 multi-agents les représentations condensées :
    - `get_file_skeleton` : arbre des imports, classes et signatures de fonctions avec corps élidé (`...`).
    - `read_function_body` : extraction chirurgicale de la fonction ou classe ciblée.
  - Le hub maintient un registre de digests partagé entre tous les agents du même worktree. Si `agt_claude` a extrait le squelette ou la fonction `handle_read` d'`app/forge_mcp_registry.py`, le digest est directement disponible en RAM/cache sans re-parser l'AST.
  - Dans A2A, les agents s'échangent des références d'artefacts de type `application/vnd.nokido.digest+json` contenant le squelette et la cartographie d'appels.

---

## 3. Identifiant de Session par Transport (Résolution d'Identité)

Pour que le hub sache avec certitude « qui a déjà lu quoi », l'identité doit combiner **l'agent**, **le canal de transport**, **la session**, et **l'espace de travail** :

| Transport | En-tête / Source d'identité | Extraction du `session_id` | Détection de fin de session |
|---|---|---|---|
| **MCP (HTTP :8766)** | `X-Agent-Name` ou `LaForge-Agent-Name` + Bearer token | `X-Session-ID` ou `Mcp-Session-Id` transmis par le client. Si absent, hachage de l'IP cliente + PID du wrapper + fenêtre glissante d'inactivité de 30 minutes. | Timeout glissant (30 min sans requête) ou signal de reboot. |
| **MCP (Stdio Bridge)** | Configuration du sub-process stdio (`agt_gemini`, `agt_claude`) | PID du processus parent stdio + UUID de lancement injecté dans l'environnement (`NOKIDO_SESSION_ID`). | Mort du tube stdin/stdout ou terminaison du processus enfant. |
| **ACP (`handle_acp`)** | Identifiant de contexte agent ACP | `session_id` natif présent dans la payload JSON-RPC ACP (`params.sessionId` ou `contextId`). | Événement ACP `session/close` ou suppression de contexte. |
| **A2A (`:7783`)** | Bearer authentifié + `X-Agent-Name` | `contextId` obligatoire dans `message/send` ou `taskId`. | État de tâche `completed`, `canceled` ou `failed`. |

### Règle de Clé Composite de Session :
$$\text{session\_key} = (\text{agent\_name}, \text{session\_id}, \text{worktree\_canonical\_path})$$

---

## 4. Sécurité et Confinement Absolu des Worktrees

Nokido opère avec des worktrees git concurrents (`nokido_worktrees/taches/...`, dépôt maître `Script python IA/Nokido`). L'étanchéité stricte est une contrainte de sécurité non négociable :

1. **Isolation stricte par Racine Canonique :**
   - Tout chemin de fichier passé en argument est obligatoirement résolu via `os.path.realpath()` ou `Path.resolve()`.
   - Le hub vérifie que le fichier résolu appartient strictement au répertoire racine (`worktree_root`) associé à la session de l'agent demandeur.
   - **Règle absolue :** Le cache d'un agent travaillant dans le worktree $W_1$ (`nokido_worktrees/taches/tache_A`) ne doit **jamais** renvoyer le contenu, le diff ou le squelette d'un fichier appartenant au worktree $W_2$ (`nokido_worktrees/taches/tache_B`), même si le chemin relatif (`app/forge_ssot.py`) est identique.
2. **Garde de Secret & Ring Enforcement :**
   - `assert_can_read(path, agent, ring)` est toujours exécuté **avant** toute interrogation de cache ou de disque. Si le ring ou SecretGuard refuse l'accès, le cache est totalement inerte (fail-closed).
3. **Périmètre du Cache SQLite :**
   - La base de métadonnées du cache est stockée sous `sandbox/token_cache.db` avec des tables indexées obligatoirement par `worktree_root`.

---

## 5. Schéma de Données et Registre de Session (`sandbox/token_cache.db`)

Le registre est géré par SQLite en mode WAL ultra-rapide et sécurisé :

```sql
-- 1. Registre des lectures de session (pour les règles a et b)
CREATE TABLE IF NOT EXISTS agent_file_reads (
    agent_name TEXT NOT NULL,
    session_id TEXT NOT NULL,
    worktree_root TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    last_read_at REAL NOT NULL,
    content_hash TEXT NOT NULL,        -- SHA-256 du contenu lu
    file_size INTEGER NOT NULL,
    compressed_content BLOB,           -- zlib/zstd du contenu pour calcul de diff unifié
    PRIMARY KEY (agent_name, session_id, worktree_root, relative_path)
);

-- 2. Cache L2 partagé de digests (pour la règle c)
CREATE TABLE IF NOT EXISTS shared_digests (
    worktree_root TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    digest_type TEXT NOT NULL,         -- 'skeleton', 'function_body', 'ast_summary'
    symbol_name TEXT NOT NULL,         -- nom de fonction/classe ou '*' pour squelette complet
    content_hash TEXT NOT NULL,        -- hash du fichier source pour invalidation
    digest_payload TEXT NOT NULL,      -- le squelette ou le corps de fonction extrait
    tokens_estimate INTEGER NOT NULL,  -- coût en tokens du digest
    created_at REAL NOT NULL,
    hit_count INTEGER DEFAULT 1,
    PRIMARY KEY (worktree_root, relative_path, digest_type, symbol_name)
);

-- 3. Observabilité et audit d'économie de tokens
CREATE TABLE IF NOT EXISTS token_savings_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    agent_name TEXT NOT NULL,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    optimization_type TEXT NOT NULL,   -- 'UNCHANGED_MARKER', 'UNIFIED_DIFF', 'SHARED_DIGEST'
    raw_tokens_estimate INTEGER NOT NULL,
    sent_tokens_estimate INTEGER NOT NULL,
    tokens_saved INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token_savings_ts ON token_savings_log(timestamp);
```

---

## 6. Mesure du Gain et Observabilité (Tokens Évités)

### 6.1 Algorithme d'Estimation des Tokens
* Estimation déterministe standardisée sans dépendance lourde :
  $$\text{tokens} = \max\left(1, \frac{\text{len}(text)}{3.8}\right)$$
* À chaque intervention du cache, le hub calcule :
  $$\text{tokens\_saved} = \text{tokens\_estimate}(\text{raw\_content}) - \text{tokens\_estimate}(\text{payload\_sent})$$

### 6.2 Journalisation et Exposition Métrique
* **Fichier de log dédié :** `logs/token_savings.log` (ou repli sous `sandbox/token_savings.log` en environnement contraint).
* **Format de trace :**
  ```text
  2026-10-30T15:30:12+01:00 [TOKEN_SAVED] agent=agt_claude tool=read opt=UNCHANGED_MARKER file=app/forge_ssot.py raw_tok=24800 sent_tok=21 saved=24779 session=sess_9f12
  2026-10-30T15:31:05+01:00 [TOKEN_SAVED] agent=agt_antigravity tool=read opt=UNIFIED_DIFF file=tools/nokido_hub.py raw_tok=18500 sent_tok=220 saved=18280 session=sess_a4b1
  2026-10-30T15:32:18+01:00 [TOKEN_SAVED] agent=agt_vibe tool=get_file_skeleton opt=SHARED_DIGEST file=app/forge_mcp_registry.py raw_tok=98000 sent_tok=850 saved=97150 session=sess_c83d
  ```
* **Endpoint MCP d'observabilité :** Action intégrée dans `handle_forge_stats` (L6645) retournant le cumul des tokens économisés par heure/jour/agent.

---

## 7. Plan de Mise en Œuvre Détaillé (3 à 5 Tâches S/M)

### Tâche 1 (Taille S) : Module Fondateur `app/forge_token_cache.py`
* **Emplacement :** Nouveau module `app/forge_token_cache.py` (créé sous la racine du dépôt / worktree).
* **Contenu :**
  - Initialisation de `sandbox/token_cache.db` (tables `agent_file_reads`, `shared_digests`, `token_savings_log`).
  - Fonctions canoniques :
    - `get_read_verdict(agent, session_id, worktree_root, abs_path, force_reload=False) -> tuple[str, str, int]` : retourne `("FULL", content, saved)`, `("UNCHANGED", marker_str, saved)` ou `("DIFF", diff_str, saved)`.
    - `get_or_set_digest(worktree_root, abs_path, digest_type, symbol_name, compute_fn) -> str`.
    - `log_token_savings(agent, session_id, tool_name, rel_path, opt_type, raw_tok, sent_tok)`.
* **Tests :** `tests/nr/test_token_cache_nr.py` (test unitaire des calculs de hash, invariance, diff unifié et isolation worktree).

### Tâche 2 (Taille M) : Intégration dans `handle_read` de `app/forge_mcp_registry.py`
* **Emplacement :** `app/forge_mcp_registry.py`, fonction `handle_read` (autour des lignes L3461–L3540).
* **Contenu :**
  - Extraction de `session_id` depuis `args` ou le contexte de requête (`getattr(self, 'current_session_id', 'default')`).
  - Après les gardes `assert_can_read(path_str, ...)` et le cas `tail_logs` :
    - Si l'action est standard (lecture de fichier texte ordinaire), appel à `get_read_verdict()`.
    - Si verdict `UNCHANGED` : retour immédiat du marqueur textuel sans lecture disque lourde.
    - Si verdict `DIFF` : retour du patch unifié.
    - Si verdict `FULL` : lecture normale, mise en mémoire compressée dans le registre et retour.
  - Prise en charge du paramètre optionnel `args.get("force_reload", False)`.

### Tâche 3 (Taille S) : Intégration dans `handle_read_function_body` et `handle_get_file_skeleton`
* **Emplacement :** `app/forge_mcp_registry.py` :
  - `handle_read_function_body` (autour des lignes L6618–L6644).
  - `handle_get_file_skeleton` (autour des lignes L6671–L6689).
* **Contenu :**
  - Encapsuler l'extraction AST dans `get_or_set_digest` avec `digest_type="function_body"` ou `digest_type="skeleton"`.
  - Vérification de l'empreinte `mtime` / `sha256` du fichier source. Si invariant, retour instantané du squelette / corps mis en cache L2 sans relancer `_ast.parse()`.
  - Journalisation des tokens économisés via `log_token_savings`.

### Tâche 4 (Taille S) : Pont ACP et Transport A2A pour Artefacts de Digest
* **Emplacement :**
  - `tools/forge_a2a_server.py` : fonction `traiter(methode, params, rid, agent)` (L134–L160).
  - `tools/forge_a2a_card.py` : déclaration de la compétence `token_efficient_digests`.
* **Contenu :**
  - Permettre à `message/send` de demander et recevoir des artefacts de digest compressés (`kind="application/vnd.nokido.digest+json"`).
  - Normalisation de l'argument `contextId` pour servir d'identifiant de session de lecture dans les sous-tâches A2A.
* **Vérification :** Non-régression prouvée via `tests/nr/test_a2a_digests_nr.py`.

---

## 8. Synthèse Finale & Recommandations

L'approche retenue répond exactement à la prescription de l'owner :
1. **Zéro token LLM gaspillé sur les fichiers invariants :** Réduction de 99,9 % du coût de re-lecture par le marqueur `[INCHANGÉ]`.
2. **Transferts minimaux sur les fichiers édités :** Réduction de 98 % du coût par le diff unifié contextuel `[DIFFÉRENTIEL]`.
3. **Mutualisation inter-agents des squelettes et fonctions ciblées :** Les digest AST partagés suppriment les lectures intégrales exploratoires.
4. **Sécurité et souveraineté :** Cloisonnement étanche par racine de worktree et persistance locale sous `sandbox/token_cache.db`.
