# EVENT_SPEC.md — Nokido Event Bus Multi-Agent

> **Status:** Draft v1.0 — 2026-04-24 23:12  
> **Auteurs:** Claude Desktop (spec) + Gemini CLI (implementation)  
> **Scope:** Contrat d'interface pour le streaming de dialogue entre agents, tools, skills, silos de Nokido.  
> **Related:** commit 304312d (StateManager filelock), MCPHandlerRegistry Gemini (en cours de commit), protocol:claude_auto_poll RAG chunk.

---

## 1. Intention

Le bridge actuel (`bridge_state.json.pending_notifications` + `gemini_poll_daemon` 15s) est une **boîte aux lettres** : asynchrone, polled, pas de typage, pas de correlation, pas de persistance par topic.

L'Event Bus vise à fournir un **dialogue live typé** entre :
- **Agents** (Claude Desktop STDIO, Gemini CLI HTTP, VS Code Copilot HTTP, futurs agents)
- **Tools** MCP (via `forge_mcp_registry`)
- **Skills** (via `AgenticEngine`)
- **Silos** de raisonnement (via `SiloEngine`)
- **Système** (mode switches, alerts)

Objectifs :
- **Pas d'écritures concurrentes destructrices** : réutilise le `FileLock` de `StateManager` pour la persistance de snapshot
- **Streaming live** pour les consommateurs capables (Gemini CLI via wrapper, web_hub dashboard, TUI)
- **Polled fallback** pour les consommateurs non-capables (Claude Desktop qui ne peut pas garder une connexion SSE ouverte entre tours)
- **Filtrage par topic** : chaque consommateur n'écoute que ce qui l'intéresse (évite la pollution contextuelle)
- **Corrélation via `corr_id`** : un thread de dialogue ("refacto X") se suit d'un bout à l'autre

## 2. Non-goals (v1)

- Pas de persistance SQL durable des events (juste buffer circulaire mémoire + replay jsonl disque)
- Pas de garantie de delivery cross-restart (un event émis avant crash peut être perdu si pas encore snapshot-é)
- Pas de fan-out cross-machine (localhost uniquement dans cette itération)
- Pas de retry automatique côté consommateur : si tu rates une fenêtre, tu as l'historique via `/events/history`

## 3. Schéma d'un Event

```json
{
  "id": "evt_20260424T231205_a3f1",
  "topic": "agent.claude.reply",
  "ts": "2026-04-24T23:12:05.123456",
  "ttl_s": 3600,
  "agent": "CLAUDE",
  "kind": "msg",
  "data": { "text": "...", "length": 234 },
  "corr_id": "thread_refacto_event_bus_a3f1",
  "parent_id": "evt_20260424T231130_b7c2",
  "sig": "hmac_sha256_hex"
}
```

### 3.1 Champs obligatoires

| Champ | Type | Description |
|---|---|---|
| `id` | string | Identifiant unique de l'event : `evt_{YYYYMMDDTHHMMSS}_{hex4}`. Monotone croissant. |
| `topic` | string | Topic hiérarchique pointé (voir section 4). |
| `ts` | string ISO8601 | Timestamp de publication. Le bus accepte uniquement `now ± 5min` pour éviter la réinjection de vieux events. |
| `agent` | string enum | `CLAUDE \| GEMINI \| VSCODE_COPILOT \| HUB \| SYSTEM \| TOOL \| SKILL \| SILO`. Qui émet. |
| `kind` | string enum | `msg \| reply \| tool_call \| tool_result \| skill_match \| skill_score \| silo_progress \| mode_switch \| alert \| error`. Signal court. |
| `data` | object | Payload libre mais **taille max 4 KB**. Au-delà = erreur 413. |

### 3.2 Champs optionnels

| Champ | Type | Description |
|---|---|---|
| `ttl_s` | int | Durée de validité. Defaults selon `kind` (voir section 6). Event expiré n'apparaît plus dans `/events/history`. |
| `corr_id` | string | Identifiant du fil de dialogue. Créé par l'émetteur du premier message. Format libre mais court (max 64 chars). Si absent : tool/skill/silo events n'ont pas besoin, mais agent msg/reply **doivent** en avoir un. |
| `parent_id` | string | `evt_...` de l'event parent (utile pour reconstituer un arbre de replies sans relire tout le thread). |
| `sig` | string | HMAC-SHA256 signature (voir section 7). Requis si l'émetteur n'est pas sur le même process que le bus. |

## 4. Topics hiérarchiques

Convention : **segments minuscules séparés par `.`**, du plus générique au plus spécifique.

### 4.1 Topics agent

| Topic | Qui publie | `kind` typique |
|---|---|---|
| `agent.claude.msg` | Claude Desktop | `msg` — notification simple |
| `agent.claude.reply` | Claude Desktop | `reply` — réponse à un `corr_id` |
| `agent.gemini.msg` | Gemini CLI | `msg` |
| `agent.gemini.reply` | Gemini CLI | `reply` |
| `agent.vscode_copilot.msg` | VS Code Copilot | `msg` |
| `agent.vscode_copilot.reply` | VS Code Copilot | `reply` |

### 4.2 Topics tools

| Topic | Qui publie | `kind` typique |
|---|---|---|
| `tool.{name}.start` | `forge_mcp_registry._tool_call` | `tool_call` — args, agent caller, ring |
| `tool.{name}.end` | idem | `tool_result` — success/error, latency_ms, result_summary |

Exemples : `tool.auto_test.start`, `tool.query.end`, `tool.trigger_autonomous_evolution.start`.

### 4.3 Topics skills

| Topic | Qui publie | `kind` typique |
|---|---|---|
| `skill.{name}.matched` | `AgenticEngine.prepare_rag_context` | `skill_match` — score, context_size |
| `skill.{name}.score` | idem | `skill_score` — update vitality/fail_streak/verified |

### 4.4 Topics silos

| Topic | Qui publie | `kind` typique |
|---|---|---|
| `silo.{domain}.progress` | `SiloEngine.evolve` | `silo_progress` — domain, step, pct |
| `silo.{domain}.result` | idem | `msg` — synthesis chunk |

Domains : `code, security, strategy, synthesis, recon, exploit, doc` (cf `SiloDomain` enum).

### 4.5 Topics système

| Topic | Qui publie | `kind` typique |
|---|---|---|
| `system.mode.switch` | `set_mode` handler | `mode_switch` — from, to, reason |
| `system.alert.{level}` | n'importe | `alert` — level=info/warn/error/critical |
| `system.heartbeat` | bus lui-même | `msg` — émis toutes les 60s pour keep-alive SSE |

### 4.6 Wildcards supportés dans les subscriptions

- `*` match un segment : `tool.*.end` match tous les `tool.X.end` mais pas `tool.X.Y.end`
- `**` match plusieurs segments (suffix uniquement) : `agent.**` match `agent.claude.msg`, `agent.gemini.reply`, etc.
- `#` (exact) : `tool.auto_test.start` match uniquement ça

Un consommateur SSE peut s'abonner à plusieurs topics via liste séparée par virgules : `?topics=agent.**,tool.*.end,system.alert.critical`.

## 5. API HTTP (exposée par `nokido_hub.py`)

### 5.1 POST `/events/publish`

JSON-RPC compatible MCP :

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "event_publish",
    "arguments": {
      "topic": "agent.claude.msg",
      "kind": "msg",
      "data": {"text": "je commence le refacto X"},
      "corr_id": "thread_refacto_x_a3f1"
    }
  }
}
```

Headers requis :
- `Authorization: Bearer <FORGE_MCP_TOKEN>`
- `X-Agent-Name: CLAUDE | GEMINI | VSCODE_COPILOT | ...`

**Réponse success :**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{
      "type": "text",
      "text": "published evt_20260424T231205_a3f1"
    }]
  }
}
```

**Erreurs :**
- `400` — topic invalide, kind invalide, data trop grand, ts hors fenêtre
- `401` — token invalide
- `413` — data > 4 KB
- `429` — rate limit (voir section 8)

### 5.2 GET `/events/stream?topics=...`

Server-Sent Events. Content-Type: `text/event-stream`.

**Query params :**
- `topics` (requis) — liste topics comma-separated, wildcards supportés
- `since` (optionnel) — `evt_id` ou `ts` ISO8601. Si présent, replay des events matchants du buffer circulaire depuis ce point avant de streamer le live.
- `agent` (optionnel) — filtre sur le champ `agent` après filtrage topic

**Format SSE :**
```
event: agent.claude.msg
id: evt_20260424T231205_a3f1
data: {"topic":"agent.claude.msg","ts":"...","agent":"CLAUDE","kind":"msg","data":{...},"corr_id":"..."}

event: system.heartbeat
id: hb_20260424T231305
data: {"topic":"system.heartbeat","ts":"...","agent":"HUB","kind":"msg","data":{}}
```

Le `id` SSE permet au client de se reconnecter avec `Last-Event-ID` header — le bus reprend depuis cet id dans le buffer circulaire.

### 5.3 GET `/events/history?topics=...&limit=50`

Pour les consommateurs non-SSE (Claude Desktop) :

```json
{
  "events": [ { ... }, { ... } ],
  "oldest_id": "evt_20260424T230500_...",
  "newest_id": "evt_20260424T231205_...",
  "has_more": false
}
```

**Query params :**
- `topics` (requis) — mêmes règles wildcards
- `limit` — défaut 50, max 200
- `since` — `evt_id` ou ISO8601
- `agent` — filtre post-topic

## 6. TTL par kind (defaults)

| `kind` | TTL | Rationale |
|---|---|---|
| `msg`, `reply` | 3600s (1h) | Dialogue agent : on veut pouvoir reconstituer un thread récent |
| `tool_call`, `tool_result` | 600s (10min) | Observability courte, pas besoin de garder longtemps |
| `skill_match`, `skill_score` | 300s (5min) | Volumineux (potentiellement 1/prompt), usage débug surtout |
| `silo_progress` | 1800s (30min) | Durée d'un silo = qques minutes, on garde un peu après |
| `mode_switch` | 86400s (24h) | Changement rare, utile pour audit |
| `alert` critical | 604800s (7 jours) | On ne perd pas un critical |
| `alert` warn/info | 3600s | Comme msg |

TTL peut être override par l'émetteur via `ttl_s` explicite.

## 7. Sécurité

### 7.1 Authentification

Bearer token `FORGE_MCP_TOKEN` (existant). Sur localhost uniquement. Pas de CORS externe.

### 7.2 Anti-spoofing agent

Le champ `agent` seul n'est pas fiable (Gemini a soulevé le risque). Solution :
- Le bus compute `sig = HMAC-SHA256(FORGE_MCP_TOKEN, f"{id}|{ts}|{topic}|{agent}|{kind}")` à la publication
- Si l'emetteur fournit déjà un `sig` (requis pour les clients externes), le bus le vérifie et rejette si mismatch
- Les clients internes (même process que le Hub) peuvent skip la signature via flag `trusted=True`

### 7.3 Rate limit (anti-flood)

Par agent, sur `/events/publish` :
- **100 events / minute** pour les agents `CLAUDE, GEMINI, VSCODE_COPILOT`
- **300 events / minute** pour `HUB, TOOL, SKILL, SILO` (ils peuvent être verbeux en observability)
- Token bucket avec burst de 20 events

Dépassement → `429 Too Many Requests` + `Retry-After: N` header.

### 7.4 Cap taille buffer

Buffer circulaire en mémoire par topic : **100 events max par topic**. Plus vieux évincé. Limite mémoire totale ≈ `N_topics × 100 × 4 KB = 40 MB` dans le pire cas (peu probable, on est plutôt à 2-3 MB).

### 7.5 Sanitization des `data`

Rejeter si :
- Contient `<script>`, `javascript:`, `on*=` (anti-XSS pour le dashboard)
- Contient des nulls (`\0`) ou caractères de contrôle non-ASCII hors tab/newline
- Encodage non-UTF-8 après serialization

## 8. Persistance (à implémenter par Gemini)

### 8.1 Snapshot périodique

Toutes les 60s OU quand buffer grossit de +50 events depuis dernier snapshot :
```
sandbox/event_bus_buffer.jsonl.gz
```
Ecrit atomiquement via `StateManager.write_state` pattern (`.tmp` + `replace` sous FileLock). Contient le snapshot des buffers par topic sous forme jsonl compressé.

### 8.2 Replay log (append-only)

Chaque publish écrit une ligne dans :
```
sandbox/event_bus_replay.jsonl
```
Rotation : si > 10 MB → archive sous `event_bus_replay_YYYYMMDD_HHMMSS.jsonl.gz` et on repart à zéro. Garder 7 jours, purger au-delà.

### 8.3 Restart behavior

Au boot du Hub :
1. Charger le dernier snapshot dans le buffer en mémoire
2. Appliquer les events du replay log ajoutés après le snapshot (si `ts > snapshot.ts`)
3. Émettre `system.alert.info` "event_bus restored N events from snapshot"

## 9. Hooks d'intégration (à wire dans les modules existants)

### 9.1 forge_mcp_registry

Dans `_tool_call` (ou équivalent du Registry Gemini) :
```python
corr_id = f"tool_{name}_{uuid4().hex[:8]}"
event_bus.publish(
    topic=f"tool.{name}.start",
    agent=requester_agent,  # via X-Agent-Name
    kind="tool_call",
    data={"args": args, "ring": ring},
    corr_id=corr_id,
)
result = handler(args)
event_bus.publish(
    topic=f"tool.{name}.end",
    agent="HUB",
    kind="tool_result",
    data={"ok": not error, "latency_ms": elapsed, "result_summary": str(result)[:200]},
    corr_id=corr_id,
    parent_id=previous_evt_id,
)
```

### 9.2 AgenticEngine.prepare_rag_context

Après sélection des skills :
```python
for skill in matched_skills:
    event_bus.publish(
        topic=f"skill.{skill.name}.matched",
        agent="SKILL",
        kind="skill_match",
        data={"score": skill.score, "layer": skill.layer, "context_chunks": len(chunks)},
    )
```

### 9.3 SiloEngine.evolve

Dans la boucle des silos :
```python
event_bus.publish(
    topic=f"silo.{silo.domain.value}.progress",
    agent="SILO",
    kind="silo_progress",
    data={"pct": progress, "step": current_step, "silo_id": silo.id},
    corr_id=task.id,
)
```

### 9.4 Backward compat : `notify` / `poll`

L'ancien `Nokido:notify` et `Nokido:poll` restent fonctionnels. Leur handler dans le Registry doit **aussi** publier sur `agent.{name}.msg` pour que les nouveaux consommateurs SSE voient la notification en live. C'est une transition douce — les existants (Gemini daemon poll 15s) continuent de marcher, les nouveaux (dashboard temps réel) utilisent SSE.

## 10. Consommateurs typiques

### 10.1 Claude Desktop (polled)

Pas de SSE possible (pas de connexion persistante entre tours). À chaque début de tour :
```python
GET /events/history?topics=agent.claude.**,system.alert.**&since=<last_sync_ts>
```
Puis met à jour `sandbox/claude_last_sync.ts`. Déjà préparé dans `protocol:claude_auto_poll` (chunk RAG).

### 10.2 Gemini CLI (streamed)

Via `tools/gemini_with_inbox.ps1` étendu :
```powershell
# Nouveau mode : au lieu de polled inbox, fetch stream sur demande
$events = curl -N "http://127.0.0.1:8766/events/history?topics=agent.gemini.**,agent.**.reply&since=$lastTs&limit=20"
# Préinject dans le prompt comme actuellement
```

### 10.3 VS Code Copilot (streamed natif)

Via MCP `event_subscribe` tool (nouveau) qui retourne un stream. À spec ultérieurement.

### 10.4 TUI Nokido / Dashboard web_hub

Widget "Bus feed" qui connect directement `/events/stream?topics=**` pour voir tout en live.

## 11. Roadmap d'implémentation

| Phase | Qui | Contenu | Statut |
|---|---|---|---|
| 1 | Claude | Ce doc | ✅ draft |
| 2 | Gemini | `EventBus` classe dans `forge_state_manager.py` avec `publish/subscribe/history` | pending |
| 3 | Gemini | Endpoints `/events/publish`, `/events/stream`, `/events/history` dans `nokido_hub.py` | pending |
| 4 | Gemini | Persistance snapshot + replay log | pending |
| 5 | Claude | Hooks dans `forge_mcp_registry._tool_call` | pending |
| 6 | Claude | Hooks dans `AgenticEngine` + `SiloEngine` | pending |
| 7 | Claude | Adapter `gemini_with_inbox.ps1` pour consommer `/events/history` | pending |
| 8 | Both | Tests NR structurels event_bus (rate limit, ttl, wildcards, sig) | pending |
| 9 | Both | Dashboard widget feed live dans web_hub | pending |

## 12. Questions ouvertes à résoudre ensemble

### Q1 : Format `data` libre ou schema-validé ?
Option A : `data` complètement libre, juste cap 4KB.  
Option B : chaque `kind` a un schema JSON strict (ex: `tool_call` doit avoir `args`, `tool_result` doit avoir `ok`+`latency_ms`).  
**Ma préférence :** A pour v1 (pragmatique), migration vers B plus tard si besoin.

### Q2 : Ack / delivery confirmation ?
Gemini mentionne "Acknowledgement" dans sa réponse. Pour v1 je propose : **pas d'ack explicite** (les consommateurs SSE gèrent leur Last-Event-ID eux-mêmes). Si besoin futur, ajouter topic `system.ack.{evt_id}` émis par le consommateur.

### Q3 : ID de message unique
Format proposé : `evt_{YYYYMMDDTHHMMSS}_{hex4}`. Collision possible à 10ms près avec 2 émetteurs simultanés. Alternative : ULID (26 chars, strictement monotone). **Je vote ULID** si le coût est acceptable.

### Q4 : Stockage replay log jsonl vs SQLite ?
Gemini a mentionné `database is locked` dans ses réponses — il craint les deadlocks. Proposition : **jsonl append-only pour le replay log** (pas de lock), **SQLite pour une future indexation** queryable dans un chunk à part (hors du chemin critique).

### Q5 : Émission d'events depuis Claude Desktop
Claude Desktop ne peut pas facilement faire des POST HTTP. Solution : ajouter un tool MCP `event_publish` qui wrap le POST — comme ça je peux publier depuis mes tool calls. Gemini est d'accord ?

---

## 13. Exemple complet : un thread de refacto

Claude lance un refacto sur forge_collab_modes :

```
Claude →  publish agent.claude.msg
          { corr_id: "refacto_collab_modes_a3f1", data: {text: "je commence"} }

Claude →  publish tool.auto_test.start  
          { corr_id: "tool_auto_test_b7c2", parent_id: <claude_msg>, data: {args:{filepath:"..."}} }
Hub    →  publish tool.auto_test.end  
          { corr_id: "tool_auto_test_b7c2", data: {ok: true, latency_ms: 142} }

Claude →  publish tool.query.start ... (x plusieurs)

Gemini →  subscribes agent.claude.**, tool.*.end depuis son daemon étendu
Gemini →  voit les events, publish agent.gemini.reply 
          { corr_id: "refacto_collab_modes_a3f1", parent_id: <claude_msg>, data: {text:"LGTM"} }

user →  consulte dashboard web_hub :
          widget feed filtré topics=**, corr_id="refacto_collab_modes_a3f1"
          voit le thread complet en un coup d'œil
```

Voilà le dialogue streamé que tu cherchais.

---

**Prochaine étape :** Gemini valide ou conteste cette spec, puis commence le code de l'`EventBus` classe dans `forge_state_manager.py`. Je me tiens prêt à itérer.
