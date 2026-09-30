## BOOT CONTEXT — 2026-09-08 17:39

**Modèle recommandé :** `gemini-3.1-pro-preview`
**Session ID :** `gemini_20260908_173944`

**État quota (reporté session précédente) :**
  Flash      : 0.0%
  Flash-Lite : 0.0%
  Pro 2.5    : 0.0%
  Pro 3.1    : 0.0%  ← pool séparé

**Messages en attente :**
```
GATE_DENIED: ring:ring 4 <= requis 3
```

**🔎 CONTEXTE NOKIDO (lazy-load) :**
  known_issues  → `query sql="SELECT id,SUBSTR(text,1,80) FROM rag_chunks WHERE domain='known_issues'"`
  policy_rules  → `query sql="SELECT id,SUBSTR(text,1,80) FROM rag_chunks WHERE domain='policy_rules'"`
  snapshot      → `query sql="SELECT text FROM rag_chunks WHERE id='snapshot_20260429'"`

**Actions OBLIGATOIRES au boot :**
1. `/model` → noter les % réels → `hub action=quota_report flash=X flash_lite=Y pro=Z preview_pro=W`
2. Appliquer le bon modèle selon les vrais %
3. Lire les messages en attente ci-dessus

---
# 🧠 CENTRE DE L'INTELLIGENCE — NOKIDO
*Protocole tools centralisé v3 — 2026-05-06*

---

@RULES_SHARED.md

---

## 🛡️ RÈGLE ABSOLUE — TOUT PASSE PAR LE HUB :8766

**Jamais d'appel direct** à Python, SQLite, fichiers, ou LLMs.
Le hub MCP `http://127.0.0.1:8766/mcp` est le **seul point d'entrée** pour toute action.

### Table des tools disponibles

| Besoin | Tool | Arguments clés |
|---|---|---|
| Lire fichier | `read` | `path=<chemin relatif>` |
| Écrire fichier | `write` | `path=<chemin> content=<contenu>` |
| Exécuter Python | `run` | `action=python code=<code>` |
| Exécuter shell | `run` | `action=shell command=<cmd>` |
| Query SQL directe | `query` | `sql=<requête>` |
| Chercher RAG (sémantique) | `rag` | `query=<texte> top_k=5 domain=<opt>` |
| Chercher RAG (FTS) | `query` | `sql="SELECT ... FROM rag_fts WHERE rag_fts MATCH '<mots>'"` |
| Appeler un LLM | `ask` | `provider=<name> message=<msg> max_tokens=<n>` |
| Assigner tâche agent | `task` | `action=assign agent=<name> description=<desc>` |
| Réclamer tâche | `task` | `action=claim agent=agt_gemini` |
| Poster résultat | `task` | `action=result task_id=<id> result=<texte>` |
| Statut tâche | `task` | `action=status task_id=<id>` |
| Notifier agent | `hub` | `action=notify topic=<topic> message=<msg>` |
| Lire inbox | `hub` | `action=poll` |
| Web search | `web_search` | `query=<query>` |
| Crawler URL | `crawl` | `url=<url>` |
| Ancrer solution RAG | `run` | `action=python code="from forge_self_correction import anchor_solution; anchor_solution(...)"` |

---

## ⚡ PROVIDERS LLM CONFIRMÉS (2026-05-06)

Tier-0 gratuits (pas de coût, utiliser en priorité):
```
ask provider=groq        message="..." max_tokens=1000   # ~109ms  Llama-3.3-70B — quota 1K req/jour reset minuit UTC
ask provider=sambanova   message="..." max_tokens=1000   # ~200ms  Llama-3.3-70B — cloud.sambanova.ai
ask provider=kimi        message="..." max_tokens=1000   # ~500ms  Llama-3.3-70B:free (OpenRouter)
ask provider=kimi_think  message="..." max_tokens=1000   # ~800ms  Hermes-3-405B:free (OpenRouter)
ask provider=glm         message="..." max_tokens=1000   # ~600ms  GLM-4.5-Air:free (OpenRouter/Zhipu)
ask provider=gemini_cli  message="..." max_tokens=4000   # OAuth Google One — illimité
ask provider=claude_cli  message="..." max_tokens=4000   # OAuth Max — illimité
ask provider=ollama      message="..." max_tokens=500    # local fallback
```

Clés manquantes (providers ajoutés mais à activer dans Nokido.env):
```
ask provider=cerebras    # CEREBRAS_API_KEY — signup: cloud.cerebras.ai/platform (1M tok/day)
ask provider=nvidia_nim  # NVIDIA_NIM_API_KEY — signup: build.nvidia.com (40 RPM, 70+ modèles)
```

Tier payant (utiliser avec parcimonie):
```
ask provider=hf          # HF_TOKEN
ask provider=mistral     # MISTRAL_API_KEY
ask provider=gpt4o_github # GITHUB_MODELS_TOKEN
ask provider=gemini      # GEMINI_API_KEY — quota daily
```

KO: `deepseek` (pas d'API directe), `grok` (modèle obsolète), `pollinations` (API legacy dépréciée).

---

## 🔄 CYCLE TÂCHES — job_id + JWT signing

```python
# 1. Attendre une tâche
task action=claim agent=agt_gemini
# retourne: {ok, task_id, job_id, description, from_agent}

# 2. Livrer résultat (corrélé par job_id)
task action=result task_id=<task_id> result=<contenu complet>

# 3. Vérifier statut
task action=status task_id=<task_id>
```

Chaque échange est signé JWT HS256. Le `job_id` = corrélateur universel entre agents.

---

## 📬 CANAL INTER-AGENTS (agent_messages)

```sql
-- Lire messages entrants (rowid = ordre fiable, indépendant timezone)
SELECT from_agent, method, payload, created_at
FROM agent_messages
WHERE to_agent='agt_gemini' AND status='unread'
ORDER BY rowid DESC LIMIT 5

-- Marquer lus
UPDATE agent_messages SET status='read'
WHERE to_agent='agt_gemini' AND status='unread'
```

---

## 🔍 RAG AVANT TOUTE CRÉATION

Avant tout nouveau fichier `app/forge_*.py` :
```
rag query="<domaine>" top_k=8
```
Match sémantique >50% → ÉTENDRE l'existant, pas créer.
Règle absolue: `INSERT INTO rag_chunks` toujours avec `id TEXT` explicite = `sha256(source+text)[:16]`.

---

## 📡 COMMUNICATION GRANDES LIVRAISONS (>500 chars)

DOUBLE canal obligatoire pour briefs techniques:
```
# Canal A — signal temps réel
hub action=notify topic=architecture_liaison message=[ARCH] voir docs/GEMINI_TRANSMISSION_<sujet>.md

# Canal B — persistance + RAG
write path=docs/GEMINI_TRANSMISSION_<SUJET>_<DATE>.md content=<contenu complet>
```

Topics standards: `architecture_liaison`, `sprint_briefing`, `risk_alert`, `handoff`, `audit`
Préfixes: `[ARCH]` `[BRIEF]` `[RISK-HIGH]` `[AUDIT-<provider>]` `[HANDOFF-<agent>]`

---

## ⚠️ WINDOWS — PIÈGES SHELL

**`curl` n'existe PAS sur Windows PowerShell** — c'est un alias de `Invoke-WebRequest` (interactif, demande Uri).
JAMAIS faire `Shell curl -s http://...` → bloque en attente de saisie.

À la place:
```
# Health check hub
run action=shell commands=["Invoke-WebRequest -Uri 'http://127.0.0.1:8766/health' -UseBasicParsing | Select-Object -Expand Content"]

# Ou utiliser curl.exe (binaire natif Windows)
run action=shell commands=["curl.exe -s http://127.0.0.1:8766/health"]
```

**Hub DOWN** → le relancer (sans admin):
```
run action=shell commands=["Start-Process -FilePath '~/miniforge3/python.exe' -ArgumentList 'tools/nokido_hub.py' -WorkingDirectory '~/Script python IA/Nokido' -NoNewWindow -RedirectStandardOutput 'sandbox/hub_restart.log' -RedirectStandardError 'sandbox/hub_restart.err'"]
```
Attendre 8s puis vérifier `/health`.

---

## 🏗️ RÈGLES D'OR SESSION

1. `run action=python` → jamais Shell pour Python (LAFORGE_PYTHON = miniforge3)
2. Jamais `Shell curl ...` → utiliser `curl.exe` ou `Invoke-WebRequest` (voir section WINDOWS ci-dessus)
3. Pas de tâche → `hub action=poll`, attendre. PAS codebase_investigator
4. `[CLAUDE]` ou `[ROADMAP]` dans message → exécuter immédiatement
5. Jamais SQL LIKE primitif → `rag query=` ou `rag_fts MATCH`
6. Jamais INSERT sans id explicite
7. Jamais envoi cloud sans SemanticFirewall pre_flight + post_flight
8. Chaque décision architecturale → `anchor_solution()` via `run action=python`

---

## ⚡ BOOT + TICK SEQUENCE OBLIGATOIRE

**Au démarrage ET à chaque tick autonome :**
```
hub action=whoami          ← mailbox persistante (survit aux restarts hub)
hub action=poll            ← volatile temps réel
hub action=quota_model quality=high apply=true     ← boot seulement
```

**Règle tick :** `whoami` AVANT `poll`. La mailbox est la source fiable.
Le poll volatile peut être effacé par un restart hub (inspector NSSM).
Si whoami retourne des messages non lus → exécuter avant de continuer.

---

## 📊 QUOTA — REPORTER APRÈS /model
```
hub action=quota_report flash=X flash_lite=Y pro=Z preview_pro=W
```
Pools séparés : Flash+Lite partagent un pool. Pro = pool propre. Ne pas assumer disponible.

---

## 🛟 GESTION SOUVERAINE
1. Worker le moins coûteux d'abord (local/Ollama avant cloud)
2. **Reliability (Sémantique) vs Grille (Déterministe)** : Le routeur sémantique (RRF threshold 0.85) définit l'**INTENTION**. Le pipeline de validation du Hub définit la **CAPACITÉ** (censure binaire). Ne jamais mélanger les deux.
3. **Ingress Adapter & Confinement** : Le Hub injecte un Ring de Session dynamique : `[CLI] + [Destination] + [Tâche]`.
   - **Cloud (Zero-Trust)** : Inférence cloud → Ring 4 (Confinement / Read-Only).
   - **Local (Souverain)** : Inférence locale → Ring 2 (Write / Exec).
   - Toute mutation (`write`, `run`) via un flux Cloud est bloquée au niveau de l'Ingress.
4. Barre progression ASCII pour actions longues
5. Code : blocs Copy-Paste Ready, sans numéros de ligne, sans caractères parasites

---

## 🔌 SI CLAUDE EST COUPÉ
```
query sql="SELECT text FROM rag_chunks WHERE id='snapshot_20260429'"
```

---

## 🗿 CAVEMAN MODE (défaut actif)
Drop articles/filler/pleasantries/hedging. Fragments OK.
Code/commits/PRs/warnings sécurité: écrire normal complet.

---

## 💸 ÉCONOMIE TOKENS — TACTIQUES (Gemini CLI)

Socle (historique re-facturé, client pas exécuteur, deport multi-étapes) :
voir `RULES_SHARED.md` importé en tête de fichier.

1. LECTURE — `read_function_body` pour une fonction précise ; `read` fenêtré
   (`lines`) pour une zone. Jamais lire un gros fichier entier (>150 lignes).
2. RECHERCHE — `rag` / `query` semantic : l'index EST le moteur de recherche.
   Pas de scan de fichiers bruts.
3. ÉCRITURE — `edit` chirurgical. Buffer MCP <4000 chars : pas de gros `write`.
4. VALIDATION — après tout write/edit Python → AST via `run python`. Gemini
   n'a PAS les hooks Claude Code (`.claude/` ne s'applique qu'à Claude Code).
5. MULTI-ÉTAPES — `orchestrate`/`task`, jamais une boucle d'appels manuels.

---

## 🛡️ RÈGLES DE RECHERCHE SÉCURISÉE (ANTI-BLOCAGE UI)

Pour éviter de figer l'interface CLI et de saturer le contexte :

1.  **Filtrage Strict** : Interdiction de `Get-ChildItem -Recurse` sans filtre. Toujours exclure les dossiers lourds/binaires :
    `Get-ChildItem -Recurse -Exclude .git,node_modules,.venv,*.db,*.exe,*.pyc`
2.  **Limitation de Sortie** : Toujours limiter le nombre de résultats affichés :
    `... | Select-String "motif" | Select-Object -First 30`
3.  **Déport de Données** : Si > 50 lignes attendues, rediriger vers un fichier :
    `Get-ChildItem ... > temp_search.txt` puis analyser le fichier de manière ciblée.
4.  **Sémantique d'abord** : Utiliser `rag query="..."` au lieu d'un scan brut de fichiers pour les recherches de code larges.


<!-- LAFORGE_HARMONIZATION -->
# Nokido regles communes (emanation) — voir aussi hub `point rules` / `point roadmap`
@~/Script python IA/Nokido/RULES_SHARED.md
