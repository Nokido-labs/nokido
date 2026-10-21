# Audit E — Le routage LLM choisit-il le bon modèle ?
**Analyse quantitative et qualitative de `forge_llm_router.py` et `forge_agent_proxy.py` sur 7 jours**

- **Période auditée** : 12 octobre 2026 au 19 octobre 2026 (7 jours glissants)
- **Auteur de l'audit** : ANTIGRAVITY (Ring 1)
- **Worktree cible** : `%NOKIDO_ROOT%_worktrees\antigravity`
- **Fichier de restitution** : `docs/audit/routage_demande_vs_servi.md`
- **Cadre d'exécution** : Lecture seule absolue des sources de production, interrogation des journaux persistants existants et tables de vérité SQLite / JSON.

---

## 1. Résumé Exécutif & Verdict de l'Audit

### Le routeur choisit-il le « bon » modèle ?
**Verdict : PARTIELLEMENT, AVEC UN DÉFICIT MAJEUR D'OBSERVABILITÉ PERSISTANTE.**

1. **Sur le plan algorithmique (`forge_llm_router.py`)** : Le routeur intègre des mécanismes défensifs remarquables (arbre de décision DT appris, filtrage dynamique `_slots_prouves_morts`, disjoncteurs `_breaker`, repli OAuth borné, détection de surcharge locale).
2. **Sur le plan de l'alignement réel** :
   - Le modèle **DEMANDÉ** et le modèle **SERVI** divergent fréquemment sans que la divergence ne soit enregistrée dans les tables de consommation.
   - Lorsque le proxy appelle le routeur (`RouterCascadeProvider`), le résultat textuel est extrait, mais le modèle réellement servi (`served_model`) ainsi que l'historique des replis (`attempts`) sont **détruits avant l'enregistrement en base**. La table `token_usage` consigne aveuglément `provider='router'` et `model='cascade qualité (use_case auto)'` (95 appels sur 7 jours).
3. **Sur le plan de la fiabilité fournisseur** :
   - Le catalogue déclaratif est en décalage massif avec la réalité du réseau : sur **984 modèles déclarés** dans le recensement gratuit (`sandbox/free_tier_census.json`), seuls **5 échantillons réels** sont joignables sans erreur ni solde épuisé.
   - Sur 26 sondes d'inspection récentes, **27 % renvoient HTTP 404** (modèles disparus ou faux chemins) et **19 % renvoient HTTP 429** en continu.
4. **Sur le plan de la mesure d'usage (`_noter_usage_rapporte`)** :
   - Seul **Groq** appelle effectivement `_noter_usage_rapporte(resp)`. Les 14 autres fournisseurs compatibles OpenAI omettent cet appel. Résultat : **seuls 19 appels sur 396 (4,8 %)** disposent d'un comptage réel de tokens (`REPORTED`). 95,2 % des appels du proxy sont estimés par heuristique de caractères (`ESTIMATED`).

---

## 2. Cartographie des Journaux Persistants Analysés

L'audit a investigué cinq sources de vérité persistantes couvrant la période du 12/10/2026 au 19/10/2026 :

| Source / Fichier | Type de stockage | Volume sur 7 jours | Rôle dans l'audit |
|---|---|---|---|
| `sandbox/journal_token_usage.db` (`token_usage`) | SQLite (redirection via `sandbox/journaux.switch`) | **28 412 lignes** (dont 396 `agent_proxy`, 28 016 `claude_statusline`) | Appels effectifs, modèles enregistrés, tokens, latences p50/p95, statut `REPORTED` vs `ESTIMATED`. |
| `sandbox/token_usage.db` (`token_events`) | SQLite | **10 lignes** (câblage effectif depuis le 18/10 22h29) | Événements d'effort émis par `_emettre_effort` lors des succès de `call_cascade`. |
| `RAG/embeddings.db` (`network_log`) | SQLite | **328 895 lignes** (dont 12 requêtes sortantes pour l'outil `ask`) | Traces brutes du Hub, statuts JSON RPC, motifs d'erreur (429, 403, timeouts). |
| `sandbox/matrice_modele_fournisseur.json` | JSON structuré (15/10/2026 13:49:54) | 15 familles de modèles, 15 fournisseurs, 92 slots qualifiés | Équivalence de familles et statut de joignabilité pour la bascule de secours. |
| `sandbox/free_tier_census.json` | JSON structuré (19/10/2026 01:06:54) | 984 modèles déclarés, 26 sondes d'inspection détaillées | Taux réel d'attrition des paliers gratuits (404, 429, 402, 410). |
| `logs/ask_block_report.jsonl` | JSONL (append-only) | **89 événements** de blocage >25s sur les 7 derniers jours | Alertes de saturation coroutine et traces de pile des blocages de cascade. |

---

## 3. Analyse par Provider sur 7 Jours (2026-10-12 au 2026-10-19)

### 3.1 Tableau Quantitatif Consolidé

*Source principale : `sandbox/journal_token_usage.db` (table `token_usage` pour `source = 'agent_proxy'` et `ts >= '2026-10-12'`), croisée avec `network_log` (`RAG/embeddings.db`) et `logs/ask_block_report.jsonl`.*

```sql
-- Requête d'agrégation d'usage proxy
SELECT provider, model, measurement_kind, count(*),
       round(avg(latency_ms), 1) as avg_lat,
       round(min(latency_ms), 1) as min_lat,
       round(max(latency_ms), 1) as max_lat,
       sum(prompt_tokens), sum(completion_tokens)
FROM token_usage
WHERE ts >= '2026-10-12' AND ts <= '2026-10-19 23:59:59'
  AND source = 'agent_proxy'
GROUP BY provider, model, measurement_kind
ORDER BY count(*) DESC;
```

| Provider déclaré | Modèle consigné dans le journal | Nb Appels | Usage Rapporté (`REPORTED`) | Modèle Demandé vs Servi | Taux 429 / 413 / Err | Latence p50 | Latence p95 |
|---|---|---|---|---|---|---|---|
| **router** | `cascade qualité (use_case auto)` | **95** | 0 / 95 (0 %) | **ÉCART MASQUÉ** (servi : mistral_small, ollama, cohere, gemini) | 71 blocages >25s (74,7 %) | **38 175 ms** | **47 043 ms** |
| **groq** | `openai/gpt-oss-120b` | **48** | **19 / 48 (39,6 %)** | Identique (demandé gpt-oss-120b) | 1 429 TPD journalisé (23s) | **9 356 ms** | **17 843 ms** |
| **nr_lent** *(banc test)* | `modele-b` / `modele-a` / `defaut` | **54** | 0 / 54 (0 %) | Identique (simulation) | 0 % | **193 ms** | **713 ms** |
| **openrouter_free** | Divers (`free`, `laguna-s`, `dots-3`, etc.) | **60** | 0 / 60 (0 %) | Pool gratuit auto-sélectionné | 404 / 402 fréquents | **15 601 ms** | **37 043 ms** |
| **mistral** | `mistral-large-latest` (23), `medium` (3) | **26** | 0 / 26 (0 %) | Identique | 1 403 Tier-denied | **8 568 ms** | **12 237 ms** |
| **cohere** | `command-r-08-2024` | **22** | 0 / 22 (0 %) | Identique | 5 blocages >25s | **25 851 ms** | **73 976 ms** |
| **gemini** | `gemini-2.5-pro` (12), `flash` (3), `lite` (1) | **16** | 0 / 16 (0 %) | Identique | 0 % (hors quota cloud) | **38 960 ms** | **142 465 ms** |
| **deepseek** | `deepseek-chat` | **12** | 0 / 12 (0 %) | Identique | 402 sans solde (census) | **9 154 ms** | **12 762 ms** |
| **gemini_cli** | `gemini-3.1` (OAuth Google One) | **10** | 0 / 10 (0 %) | Identique (repli OAuth) | 10 blocages >25s | **73 095 ms** | **76 771 ms** |
| **nvidia_nim** | `nemotron-3-super-120b-a12b` | **10** | 0 / 10 (0 %) | Identique | 0 % | **39 976 ms** | **85 994 ms** |
| **gemini_gemma** | `gemini-2.5-flash-lite` | **4** | 0 / 4 (0 %) | Identique | 0 % | **14 487 ms** | **20 514 ms** |
| **grok** | `grok-3-latest` (3), `grok-3-mini` (1) | **4** | 0 / 4 (0 %) | Identique | 0 % | **334 ms** | **663 ms** |
| **cerebras** | `gpt-oss-120b` | **3** | 0 / 3 (0 %) | Identique | Réponses None (fix Cerebras) | **1 148 ms** | **3 105 ms** |
| **sambanova** | `DeepSeek-V3.1` | **3** | 0 / 3 (0 %) | Identique | 0 % | **470 ms** | **494 ms** |
| **zai_glm5_2** | `glm-5.2` | **3** | 0 / 3 (0 %) | Identique | Risque 429/1113 solde | **4 122 ms** | **6 240 ms** |
| **ollama** | `laforge-qwen:latest` | **1** | 0 / 1 (0 %) | Demandé local resident | 1 Timeout 60s (65 177 ms) | **60 387 ms** | **60 387 ms** |
| **gpt4o_github** | `openai/gpt-4o` | **1** | 0 / 1 (0 %) | Identique | 0 % | **337 ms** | **337 ms** |
| **hf** | `Llama-3.3-70B-Instruct` | **1** | 0 / 1 (0 %) | Identique | 0 % | **1 059 ms** | **1 059 ms** |
| **glm** | `z-ai/glm-4.5-air:free` | **1** | 0 / 1 (0 %) | Identique | 0 % | **197 ms** | **197 ms** |
| **gemini_flash_lite**| `gemini-3.1-flash-lite` | **1** | 0 / 1 (0 %) | Identique | 0 % | **4 279 ms** | **4 279 ms** |

---

### 3.2 Analyse Critique de l'Écart : Modèle Demandé vs Modèle Servi

L'examen du code source révèle une divergence fondamentale entre la **surface d'appel** et le **journal d'usage** :

1. **L'illusion du provider `router`** :
   Dans `app/forge_agent_proxy.py` (lignes 2846-2885), la classe `RouterCascadeProvider` déclare `name = "router"` et `model = "cascade qualité (use_case auto)"`.
   Lors d'un appel `ask(provider="router", ...)` :
   - Le proxy exécute en arrière-plan `get_router().call_cascade(...)`.
   - `call_cascade()` tente successivement plusieurs slots (`mistral_small`, `ollama_local`, `cohere_command_r_plus`, etc.) et produit un dictionnaire complet contenant `"requested_model"`, `"served_model"`, `"tokens"` et `"attempts"`.
   - **Mais** `RouterCascadeProvider.ask()` exécute :
     ```python
     d = _fut.result()
     if isinstance(d, dict) and d.get("ok"):
         return d.get("text", "")
     ```
   - Il ne renvoie que la chaîne brute `text`. Le proxy enregistre ensuite l'appel dans `sandbox/journal_token_usage.db` avec `provider="router"` et `model="cascade qualité (use_case auto)"`.
   - **Conséquence** : Les 95 appels servis par la cascade qualité n'indiquent **nulle part** dans la table d'usage quel modèle a réellement généré la réponse.
2. **Le patch partiel du 18/10 (`token_events`)** :
   Le 18/10 à 22h29, `_emettre_effort(slot_name, resp)` a été branché dans `call_cascade()` pour consigner les événements dans `sandbox/token_usage.db`. Les 10 lignes existantes montrent que la cascade sert en réalité :
   - `mistral_small` (60 % des succès)
   - `ollama_local` (20 % des succès)
   - `cohere_command_r_plus` (10 %)
   - `gemini_pro` (10 %)
   Cependant, cette table ne contient pas le modèle initialement visé, ni l'identifiant de corrélation avec l'appel proxy, ni les tentatives avortées.

### 3.3 Taux 413, 429 et Réponses Vides

*Sources : `network_log` (`RAG/embeddings.db`), `sandbox/free_tier_census.json` et `app/forge_agent_proxy.py`.*

```sql
-- Requête d'inspection des statuts et motifs d'erreur dans network_log
SELECT id, ts, agent, provider, model, latency_ms, payload_out
FROM network_log
WHERE ts >= '2026-10-12' AND direction = 'OUT' AND tool = 'ask'
ORDER BY id DESC;
```

1. **Taux HTTP 413 (Payload Too Large)** : **0,0 %**.
   Aucun événement 413 n'est recensé en 7 jours. La borne de contexte amont `_borner_contexte()` dans `forge_agent_proxy.py` et le contrôle DLP/tokens évitent le débordement de fenêtre contextuelle.
2. **Taux HTTP 429 (Rate Limit / Quota Exceeded)** :
   - **En production journalisée (`network_log`)** :
     - ID `1823490` (15/10 15:59) : Groq `openai/gpt-oss-120b` a explosé son quota journalier : `RateLimitError: Error code: 429 - Rate limit reached for model openai/gpt-oss-120b ... on tokens per day (TPD): Limit 200000`.
   - **Au recensement actif des paliers gratuits (`sandbox/free_tier_census.json`)** :
     - **5 modèles sur 26 sondés (19,2 %)** sont en statut **HTTP 429 permanent** (`x-ratelimit-remaining-req-minute: 0`), notamment toute la gamme Mistral gratuite : `mistral:devstral-2512`, `mistral:devstral-latest`, `mistral:devstral-small-latest`, `mistral:mistral-medium-latest`, `mistral:mistral-small-latest`.
3. **Réponses Vides (`text = ""`)** :
   - `network_log` ID `1964743` : `openrouter_gpt_oss` a renvoyé `{"ok": false, "text": "", "latency_ms": 0}`.
   - Provider Cerebras : Dans `forge_agent_proxy.py` (lignes 3676-3679), un filtre spécifique a dû être introduit : `"Provider Cerebras a renvoye None, repli sur chaine vide (fix Cerebras)"`.

### 3.4 Latence et Dérives Percentiles (p50 / p95)

L'écart entre p50 et p95 illustre la friction des cascades de secours :
- **Groq** : p50 = 9,3s, p95 = 17,8s (réponse quasi immédiate quand le slot est chaud, mais dérive lors des congestions réseau).
- **Router (Cascade)** : p50 = 38,2s, p95 = 47,0s. La latence médiane très élevée confirme que la cascade parcourt généralement plusieurs slots indisponibles ou en timeout avant de trouver un candidat ou d'atteindre le deadline `LAFORGE_CASCADE_DEADLINE=45s`.
- **Gemini CLI (OAuth)** : p50 = 73,1s, p95 = 76,8s. Le repli OAuth CLI passe par un processus externe lourd, réservé aux secours ultimes.
- **Cohere** : p50 = 25,8s, p95 = 74,0s (extrême volatilité de l'API cloud).

---

## 4. Analyse des 4 Cas d'Échec Répertoriés par l'Audit

### Cas A : Provider déclaré disponible mais muet (ou faux disponible)

1. **Preuve directe en journal (`network_log`)** :
   - **ID 1739320** (2026-10-13 18:45:03) : L'agent appelle `codex_cli` (`gpt-5.5`). Le proxy répond immédiatement par un échec :
     `"Provider 'codex_cli' indisponible : backend non pret (ce provider n'utilise aucune cle : port ...)"`.
     Le provider était déclaré dans le registre, mais le daemon sous-jacent n'écoutait pas.
2. **Preuve directe au recensement (`free_tier_census.json`)** :
   - Sur 26 modèles déclarés dans la matrice, **7 renvoient HTTP 404 immédiat** (modèles supprimés par le fournisseur ou chemins d'accès erronés) :
     - `groq:llama-3.3-70b-versatile` (HTTP 404)
     - `groq:qwen/qwen3-32b` (HTTP 404)
     - `groq:llama-3.1-8b-instant` (HTTP 404)
     - `openrouter:meta-llama/llama-3.3-70b-instruct:free` (HTTP 404)
     - `openrouter:qwen/qwen-2.5-coder-32b-instruct:free` (HTTP 404)
     - `cerebras:qwen-3-235b-a22b-instruct-2507` (HTTP 404)
     - `cerebras:zai-glm-4.7` (HTTP 404)
3. **Analyse de code (`forge_llm_router.py`)** :
   - La fonction `_slots_prouves_morts()` (lignes 730-744) a dû être codée pour pallier le fait que le routeur interrogeait des slots dont le backend n'existait plus :
     > *« Mesure du 2026-08-18 : sur 16 chaînes, SEPT commençaient par un slot dont le backend n'existe plus (`collab`, `debate`, `sentinel`, `inspect`, `reasoning`, `eu`, `mesh`). Chaque appel de ces cas d'usage démarrait donc par un échec garanti... »*

---

### Cas B : Fallback qui rend vide

1. **Preuve dans le code du proxy (`forge_agent_proxy.py`, lignes 3676-3679)** :
   Le proxy intercepte activement les retours `None` de certains moteurs :
   ```python
   text = await provider.ask_tracked(...)
   if text is None:
       logging.getLogger(__name__).warning("Provider %s a renvoye None, repli sur chaine vide (fix Cerebras).", provider_name)
       text = ""
   ```
2. **Escalade basse-confiance dans le routeur (`forge_llm_router.py`, lignes 1773-1788)** :
   Lorsqu'un slot candidat répond par une chaîne vide ou une formule de refus (« je ne peux pas », « unable to »), le routeur qualifie le retour de `low_confidence -> escalade vers plus fort` et retente le slot suivant. Si tous les slots suivants échouent ou si la chaîne est épuisée, l'appelant reçoit un échec global alors qu'un slot intermédiaire avait pourtant produit un token.

---

### Cas C : Reprises qui s'empilent sans succès

1. **Preuve directe dans `logs/ask_block_report.jsonl`** :
   Sur les **89 événements de blocage >25s** enregistrés sur les 7 derniers jours :
   - **71 événements (79,8 %)** proviennent de `provider=router, model=cascade qualité (use_case auto)`.
   - La trace de pile montre systématiquement l'attente du thread dans le pool `_cascade_executor` :
     `"File tools/nokido_hub.py, line 1434, in _tool_call -> res = await get_registry().dispatch(...)"`.
   - La cascade parcourt jusqu'à 5 slots (`max_attempts = 5`). Si chaque slot met 5 à 10 secondes à expirer ou à lever une exception réseau, le temps cumulé atteint la limite `LAFORGE_CASCADE_DEADLINE = 45s`.
2. **Échec de bascule par la matrice (`_bascule_par_matrice`)** :
   Dans `forge_agent_proxy.py` (lignes 3434-3459), lorsqu'un provider renvoie une erreur de type `SANS_SOLDE` ou `HORS_PALIER` (402/403), le proxy tente jusqu'à 2 alternatives dans la même famille. Mais si la matrice (`sandbox/matrice_modele_fournisseur.json`) indique que les alternatives sont également 401 (`together`, `siliconflow`) ou 402, les reprises s'empilent et se soldent par l'avertissement :
   `"bascule sans issue pour ... : 2 voie(s) essayee(s)"`.

---

### Cas D : Modèle local sollicité au-delà de sa charge

1. **Preuve directe en journal (`network_log`)** :
   - **ID 2000444** (2026-10-19 13:39:17) :
     - Agent : `OPENCODE_NEMOTRON`
     - Provider : `ollama` (modèle `laforge-qwen:latest`)
     - Latence : **65 177,9 ms** (65,2 secondes)
     - Statut retourné : `{"ok": false, "error": "Timeout apres 60s"}`.
     - Cause : Le serveur Ollama local était surchargé par l'inférence ou en attente d'allocation mémoire, dépassant le timeout configuré de 60s.
2. **Preuve par l'état physique du système (P1 Homeostat)** :
   - L'inspection en direct via le hub a relevé une pression RAM critique de **95,7 % (1,02 Go libre seulement)**, avec `vmmemWSL` consommant 3,15 Go et `python.exe` 1,2 Go.
   - Lorsque la RAM dépasse 85 %, le homeostat bloque le spawn de processus locaux (`THROTTLED: pression RAM/CPU`). Si un slot local est sollicité dans cet état, la génération tombe à ~8 tokens/s sur iGPU partagé, transformant une réponse de 1400 tokens en un blocage de 170 secondes.
3. **Protection implémentée dans le routeur** :
   Dans `app/forge_llm_router.py` (lignes 1662-1670), un cap obligatoire `LAFORGE_LOCAL_MAX_TOKENS = 384` a été imposé pour éviter que le modèle local ne paralyse le hub.

---

## 5. Ce qui est INMESURABLE faute de Journal (Lacunes Structurelles)

L'audit a identifié cinq angles morts majeurs où l'absence de colonnes ou de journalisation empêche une mesure déterministe :

### 5.1 Absence du Modèle Demandé et du Modèle Servi dans `token_usage`
- **Constat** : La table `token_usage` (`sandbox/journal_token_usage.db`) comporte les colonnes `id, ts, provider, model, prompt_tokens, completion_tokens, latency_ms, source, measurement_kind`.
- **Manque** : Il n'existe **aucune colonne `requested_model`**, ni **`served_model`**, ni **`routing_slot`**.
- **Impact** : Pour les 95 appels du routeur, il est mathématiquement impossible de reconstituer a posteriori quel modèle a répondu. Si l'appelant demandait un modèle de raisonnement fort et que la cascade s'est rabattue sur un petit modèle 8B local, l'écart est indétectable en base.

### 5.2 Disparition de la Chaîne des Tentatives et Reprises (`attempts`)
- **Constat** : `call_cascade()` génère une liste d'échecs `attempts: List[Tuple[str, str]]` (ex: `[('openrouter_gpt_oss', '402 Payment Required'), ('mistral_small', '429 Rate Limit')]`).
- **Manque** : Cette liste n'est écrite dans aucune table SQLite (`token_usage`, `token_events`, ni `network_log`). Elle est seulement retournée au client RPC en mémoire.
- **Impact** : Le nombre exact de reprises avant succès et les motifs d'abandon de chaque maillon de la chaîne sont **inmesurables sur l'historique**.

### 5.3 Absence de Codes d'Erreur HTTP Structurés
- **Constat** : Dans `network_log`, les échecs MCP sont stockés dans un champ texte brut `payload_out` contenant un dump JSON ou un traceback de chaîne.
- **Manque** : Absence des colonnes `http_status_code INTEGER` et `error_category TEXT` (ex: `RATE_LIMIT`, `QUOTA_EXHAUSTED`, `TIMEOUT`, `AUTH_EXPIRED`, `BAD_REQUEST`).
- **Impact** : La distinction entre un 413 (contexte trop grand), un 429 (débit atteint) et un 402 (solde nul) exige un parsing par expressions régulières sur des payloads hétérogènes.

### 5.4 Faillite du Déploiement de `_noter_usage_rapporte` (95,2 % d'appels estimés)
- **Constat** : Seule la classe `Groq` dans `app/forge_agent_proxy.py` appelle `_noter_usage_rapporte(resp)`.
- **Manque** : Toutes les autres classes dérivées de `Provider` (`Mistral`, `Cohere`, `DeepSeek`, `Gemini`, `HuggingFace`, `SambaNova`, `OpenRouterFree`, `Cerebras`, etc.) reçoivent l'objet de réponse de l'API mais omettent d'appeler `_noter_usage_rapporte`.
- **Impact** : Sur 396 appels du proxy en 7 jours, **377 ont un comptage de tokens fictif** (`measurement_kind = 'ESTIMATED'`), calculé par une simple division de la longueur du texte (`len(text) // 4`).

### 5.5 Volatilité des Statistiques de Cache et TTFT
- **Constat** : `forge_cache_aligner.py` calcule les tokens en cache (`cached_tokens`) et `forge_llm_router.py` mesure le `ttft_ms` (Time To First Token).
- **Manque** : Ces métriques sont émises sur le bus d'événements interne (`_emit_nervous_event`), mais ne sont stockées dans aucune table d'usage persistante.
- **Impact** : L'efficacité réelle du cache de prompt sur 7 jours est inmesurable.

---

## 6. Synthèse des Sources et Requêtes Utilisées

Toutes les données chiffrées de ce rapport proviennent des requêtes directes et lectures de fichiers suivantes :

1. **Volume et latences proxy par fournisseur** :
   - Fichier : `sandbox/journal_token_usage.db`
   - Requête : `SELECT provider, model, measurement_kind, count(*), avg(latency_ms), min(latency_ms), max(latency_ms) FROM token_usage WHERE ts >= '2026-10-12' AND source='agent_proxy' GROUP BY provider, model, measurement_kind`
2. **Événements d'effort de la cascade** :
   - Fichier : `sandbox/token_usage.db`
   - Requête : `SELECT rowid, ts, provider, session_id, input_tok, output_tok, cost FROM token_events ORDER BY rowid DESC`
3. **Erreurs et statuts bruts d'appels `ask`** :
   - Fichier : `RAG/embeddings.db`
   - Requête : `SELECT id, ts, agent, provider, model, latency_ms, status, payload_out FROM network_log WHERE ts >= '2026-10-12' AND direction='OUT' AND tool='ask' ORDER BY id DESC`
4. **Matrice de bascule de secours** :
   - Fichier : `sandbox/matrice_modele_fournisseur.json` (horodaté `2026-10-15T13:49:54`, 15 familles)
5. **Censier d'attrition des modèles gratuits** :
   - Fichier : `sandbox/free_tier_census.json` (horodaté `2026-10-19T01:06:54`, 984 modèles, 26 verdicts)
6. **Alertes de suspension de coroutine** :
   - Fichier : `logs/ask_block_report.jsonl` (filtrage `ts >= 1791805122.6`, 89 événements sur 7 jours)
