# Roadmap — Accès llama.cpp local **EXCLUSIF + SÉCURISÉ** (Master fallback)

**Date** : 2026-04-30
**Auteur** : CLAUDE (Nokido)
**Cible LLMs exécutants** : Gemini CLI déporté, llama.cpp (`:8080`), LM Studio (`:1234`), Ollama (`:11434`), brain_worker ZMQ (`:5557`).
**Audience humaine** : user (ring 0, owner).

---

## 0. Objectif unique

Construire un canal LLM **local-first, master-only, audité** vers `llama.cpp :8080` qui :

1. **Reste vivant** quand tous les providers cloud (groq, gemini, mistral, openrouter, github_models, sambanova) répondent 429 / quota épuisé.
2. **Élève automatiquement le ring du caller** vers `MASTER` (-1) quand `LAFORGE_ADMIN_TOKEN` est présenté **et** que `caller_ip ∈ {127.0.0.1, ::1}`.
3. **N'invente jamais** de fallback cloud silencieux (échec dur si llama.cpp DOWN, plutôt que retomber sur OpenRouter par accident).
4. **Audite chaque appel** dans `agent_messages` + `network_log` avec `method=master.llamacpp.call`, `ring=-1`, et un canary HMAC.
5. **Reste utilisable en CLI humain** sans transiter par le bridge MCP (zero dépendance à `gemini_poll_daemon` ou `mcp_stdio_bridge`).

**Non-objectifs** : remplacer le routeur cloud, mocker llama.cpp, ajouter un nouveau provider.

---

## 1. Contraintes de sécurité (immuables)

| # | Règle | Vérification |
|---|---|---|
| C1 | `LAFORGE_ADMIN_TOKEN` présenté **+** `client.host ∈ local` → ring=-1 MASTER, TTL session 5 min auto-renew tant que token valide | unit test `_resolve_ring` |
| C2 | Token admin **+** caller remote → **rejet HTTP 403** (jamais ring=-1 hors localhost) | unit test |
| C3 | Aucun fallback cloud dans le chemin master ; si llama.cpp DOWN → HTTP 503 explicite | E2E test (kill llama.cpp, expect 503) |
| C4 | Chaque appel master-llamacpp : INSERT `agent_messages` (`from_agent=usr_naarob`, `to_agent=wrk_llamacpp`, `method=master.llamacpp.call`) **+** `network_log` (channel=`MASTER_LOCAL`, ring=-1) | grep DB après E2E |
| C5 | SemanticFirewall.pre_flight = canary-only (pas de DLP redact, on est local-master ; on garde la canary leak detection au post_flight) | code review + test |
| C6 | Pas de log du prompt complet en clair (max 200 chars preview, hash sha256 du full prompt en audit) | grep `mcp_audit.log` après E2E |
| C7 | Endpoint refuse les `tool_calls` (master = chat-only, pas de pivot tool→cloud) | test : payload avec `tools` → 400 |

---

## 2. État actuel (audit 2026-04-30)

| Composant | État | Référence code |
|---|---|---|
| `LAFORGE_ADMIN_TOKEN` reconnu break-glass | ✅ | `app/forge_rbac.py:21,38` |
| `_resolve_ring` ring promotion MASTER | ❌ | `tools/nokido_hub.py:299` — donne ring=0 SYSTEM, jamais -1 |
| Endpoint `/master/llamacpp/chat` | ❌ absent | — |
| Slot `llamacpp_local` dans LLMRouter | ⚠ port défaut **1234** (LM Studio) | `app/forge_llm_router.py:191` |
| `LAFORGE_LLAMACPP_PORT=8080` dans `Nokido.env` | ❌ non défini | grep `Nokido.env` |
| Audit `MASTER_LOCAL` channel | ❌ absent | — |
| CLI wrapper humain `tools/nokido_master_chat.py` | ❌ absent | — |
| `IntegrityManager.emit_master_token` | ✅ | `app/forge_integrity.py:456` (TTL 5min forcé) |

---

## 3. Phases d'exécution

### Phase 0 — Pré-requis (15 min, blocant)

1. Ajouter dans `Nokido.env` :
   ```
   LAFORGE_LLAMACPP_PORT=8080
   LAFORGE_LLAMACPP_HOST=127.0.0.1
   LAFORGE_LLAMACPP_MODEL=qwen2.5-coder:7b-instruct-q4_K_M
   ```
2. Vérifier `curl http://127.0.0.1:8080/v1/models` → 200 + JSON listant le modèle chargé.
3. Si llama.cpp pas UP : `LAFORGE_PYTHON tools/forge_services_launcher.py --only llamacpp_native`.

**Acceptance** : `curl -s http://127.0.0.1:8080/v1/chat/completions -d '{"model":"qwen2.5-coder","messages":[{"role":"user","content":"ping"}],"max_tokens":4}'` renvoie un JSON OpenAI-compat avec `choices[0].message.content` non vide.

---

### Phase 1 — Ring promotion MASTER (1h)

**Cible** : `tools/nokido_hub.py:_resolve_ring`.

**Ajout** (après le check break-glass actuel) :
```python
# Promotion MASTER : break-glass + caller local → ring=-1 (MASTER)
if local and is_breakglass(token):
    # TTL implicite : enforced upstream par IntegrityManager.emit_master_token
    logger.warning(f"[ring] MASTER promotion: {agent_hdr or 'admin'} @ {client}")
    return -1, agent_hdr or "MASTER_LOCAL"
```

**Tests à écrire** (`tests/test_ring_master_promotion.py`) :
- Token admin + 127.0.0.1 → ring = -1, agent="MASTER_LOCAL"
- Token admin + 192.168.x.x → ring = 3 ou rejet (cf. C2) — **ne doit jamais retourner -1**
- Token agent normal (ex: claude_cli) + 127.0.0.1 → ring = 0 (inchangé)
- Pas de token + 127.0.0.1 → comportement inchangé (`HUB_TOKEN` check)

**Acceptance** : 4/4 tests verts. Pas de régression sur les tests existants du hub.

---

### Phase 2 — Endpoint `/master/llamacpp/chat` (2h)

**Cible** : `tools/nokido_hub.py` — ajouter une route Starlette dédiée, pas un nouveau tool MCP.

**Squelette** :
```python
from forge_semantic_firewall import get_firewall

async def master_llamacpp_chat(request):
    # 1. Auth — strict
    ring, agent = _resolve_ring(request)
    if ring != -1:
        return JSONResponse({"error": "MASTER ring required"}, status_code=403)

    body = await request.json()
    if body.get("tools"):
        return JSONResponse({"error": "tool_calls forbidden in master mode"}, status_code=400)

    prompt = body.get("messages", [])
    if not prompt:
        return JSONResponse({"error": "messages required"}, status_code=400)

    # 2. Pre-flight (canary only, no redact)
    fw = get_firewall()
    last_user = next((m["content"] for m in reversed(prompt) if m.get("role")=="user"), "")
    pf = fw.pre_flight(last_user, ring=-1, provider="llamacpp_local",
                       redact=False, canary=True)
    if not pf.ok:
        return JSONResponse({"error": pf.reason}, status_code=403)

    # 3. Forward direct llama.cpp (pas via LLMRouter)
    port = int(os.environ.get("LAFORGE_LLAMACPP_PORT", "8080"))
    try:
        resp = await httpx_post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            json={"model": os.environ.get("LAFORGE_LLAMACPP_MODEL", "qwen2.5-coder"),
                  "messages": prompt,
                  "max_tokens": int(body.get("max_tokens", 1024)),
                  "temperature": float(body.get("temperature", 0.7))},
            timeout=120.0)
    except (httpx.ConnectError, httpx.ReadTimeout) as e:
        # C3 — pas de fallback cloud
        return JSONResponse({"error": f"llamacpp DOWN: {e}", "retry": False},
                            status_code=503)

    out = resp.json()
    answer = out["choices"][0]["message"]["content"]

    # 4. Post-flight (canary leak + SSRF)
    pfr = fw.post_flight(answer, task=last_user, session_id=request.headers.get("X-Session-Id",""))
    if not pfr.ok:
        # log + return drift instead of dropping
        logger.warning(f"[master.llamacpp] post-flight drift: {pfr.reason}")

    # 5. Audit (C4 + C6)
    _audit_master_call(agent, last_user, answer, out.get("usage", {}))

    return JSONResponse({"content": answer, "model": out.get("model"),
                         "usage": out.get("usage"), "ring": -1})

# routes
Route("/master/llamacpp/chat", master_llamacpp_chat, methods=["POST"]),
```

**Helper audit** :
```python
def _audit_master_call(agent: str, prompt: str, answer: str, usage: dict):
    import hashlib, sqlite3
    p_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    a_hash = hashlib.sha256(answer.encode()).hexdigest()[:16]
    conn = sqlite3.connect(_db_path()); conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT INTO agent_messages(id,from_agent,to_agent,method,payload,status,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (f"master_{int(time.time()*1000)}", f"agt_{agent.lower()}", "wrk_llamacpp",
         "master.llamacpp.call",
         json.dumps({"prompt_hash": p_hash, "prompt_preview": prompt[:200],
                     "answer_hash": a_hash, "answer_preview": answer[:200],
                     "usage": usage}),
         "audit", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.execute(
        "INSERT INTO network_log(ts,direction,method,tool,agent,status,channel,meta) "
        "VALUES (datetime('now'),'OUT','master.llamacpp.call','llamacpp',?,?,?,?)",
        (agent, "OK", "MASTER_LOCAL",
         f"p={p_hash[:8]} a={a_hash[:8]} tok={usage.get('total_tokens',0)}"))
    conn.commit(); conn.close()
```

**Tests E2E** (`tests/test_master_llamacpp_endpoint.py`) :
- POST avec `LAFORGE_ADMIN_TOKEN` + 127.0.0.1 → 200, content non vide, audit DB présent
- POST sans token → 403
- POST avec token admin mais via X-Forwarded-For non-local → 403
- POST avec `tools=[...]` → 400
- llama.cpp simulé DOWN (port wrong) → 503 sans fallback cloud
- Verify : `agent_messages` row avec `method=master.llamacpp.call` après chaque succès

**Acceptance** : 6/6 verts.

---

### Phase 3 — CLI humain `tools/nokido_master_chat.py` (45 min)

Wrapper interactif pour user : pas de bridge, pas de MCP, juste HTTP direct.

```python
#!/usr/bin/env python
"""Chat direct llama.cpp via /master/llamacpp/chat — utilisé quand cloud quota=0."""
import os, sys, json
from pathlib import Path
import httpx

ENV_FILE = Path(__file__).resolve().parent.parent / "Nokido.env"
def _load_admin_token() -> str:
    for line in ENV_FILE.read_text(errors="replace").splitlines():
        if line.startswith("LAFORGE_ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("LAFORGE_ADMIN_TOKEN absent de Nokido.env")

def main():
    tok = _load_admin_token()
    history = [{"role": "system", "content": "Tu es l assistant local Nokido en mode master fallback."}]
    print("=== Nokido Master Chat (llama.cpp local, ring=-1) — Ctrl+C pour quitter ===")
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user: continue
        history.append({"role": "user", "content": user})
        try:
            r = httpx.post("http://127.0.0.1:8766/master/llamacpp/chat",
                json={"messages": history, "max_tokens": 1024, "temperature": 0.7},
                headers={"Authorization": f"Bearer {tok}", "X-Agent-Name": "MASTER"},
                timeout=180.0)
            if r.status_code == 503:
                print(f"\n!! llama.cpp DOWN. Fix : LAFORGE_PYTHON tools/forge_services_launcher.py --only llamacpp_native")
                continue
            r.raise_for_status()
            ans = r.json()["content"]
            history.append({"role": "assistant", "content": ans})
            print(f"\nllama> {ans}")
        except httpx.HTTPStatusError as e:
            print(f"\n!! HTTP {e.response.status_code}: {e.response.text[:200]}")

if __name__ == "__main__":
    main()
```

**Acceptance** : `LAFORGE_PYTHON tools/nokido_master_chat.py` ouvre une boucle, accepte une question, répond depuis llama.cpp en moins de 30s sur RTX/CPU.

---

### Phase 4 — Quota detector + auto-promotion (1h)

**Cible** : `app/forge_llm_router.py:call_cascade` — quand toutes les chaînes cloud échouent (HTTP 429 ou quota=0).

**Comportement** : appel automatique de `/master/llamacpp/chat` au lieu de retourner "ERR: tous les modeles en quota".

**Logique** :
```python
async def call_cascade(self, prompt, use_case="general", caller_token=None):
    # ... cascade existante ...

    # NEW: tous les cloud épuisés
    if self._all_cloud_429() and caller_token and is_breakglass(caller_token):
        logger.warning("[router] cloud all-429 → master.llamacpp fallback")
        return await self._call_master_llamacpp(prompt, caller_token)

    return "ERR: tous les modeles en quota."
```

**Acceptance** :
- Mock tous les providers cloud à 429 + caller_token=admin → la cascade route vers llamacpp et retourne contenu non vide
- Idem sans token admin → comportement inchangé (renvoie "ERR")

---

### Phase 5 — Anchor RAG + docs (15 min)

```python
from forge_self_correction import anchor_solution
anchor_solution(
    problem="Quotas cloud épuisés cassent toute interaction LLM ; pas de canal master local sécurisé.",
    solution="Endpoint /master/llamacpp/chat ring=-1 avec promotion auto via LAFORGE_ADMIN_TOKEN+local. Audit DB + canary. CLI nokido_master_chat.py.",
    example="curl http://127.0.0.1:8766/master/llamacpp/chat -H 'Authorization: Bearer $LAFORGE_ADMIN_TOKEN' -d '{\"messages\":[...]}'",
    domain="llm",
)
```

Mettre à jour `CLAUDE.md §8` (stack services) avec la mention de `/master/llamacpp/chat`. Pas de nouveau fichier doc autonome.

---

## 4. Anatomie Nokido (CLAUDE.md §10)

| Question | Réponse |
|---|---|
| Quel organe ? | **Métabolisme énergétique de secours** (réserve glucose / corps cétoniques) — quand l'apport cloud (glucose) est coupé, on bascule sur la réserve locale (cétones = llama.cpp). Côté SNC : ce nouvel endpoint est une voie nerveuse haute-priorité court-circuitant le cortex routeur. |
| Vascularisation | Entrée : token admin + JSON messages. Dépendances : llama.cpp `:8080` (vital), `forge_semantic_firewall` (canary), `agent_messages` (audit). Ring requis : -1 MASTER. Aucun appel sortant cloud. |
| Scénario hémorragie | Si l'endpoint fuit (auth bypass) : un attaquant remote avec le token admin pourrait invoquer le LLM local. Mitigation C2 (refuse remote même avec admin token). Si llama.cpp compromis : impact limité au modèle local (pas de credentials cloud exposés ; canary leak côté post_flight). |

## 5. Anti-pièges spécifiques Nokido

1. **NE PAS** créer un nouveau module `app/forge_master_*.py` — l'endpoint vit dans `tools/nokido_hub.py` (anti-duplication §3).
2. **NE PAS** réutiliser `forge_llm_router` pour le master endpoint — la cascade router peut accidentellement réintroduire un fallback cloud (C3 violé).
3. **NE PAS** accepter `tool_calls` dans le master payload — un tool-use pourrait pivoter vers un browser/fetch et exfiltrer.
4. **NE PAS** redact PII dans le master mode — c'est le humain ring 0 qui parle à son LLM local, le redact est contre-productif. Garder canary anti-leak quand même.
5. **NE PAS** logger le prompt complet — hash + 200 chars preview, sinon bloat DB.
6. **TOUJOURS** appeler `anchor_solution()` après merge (§4 CLAUDE.md).

## 6. Tests d'acceptance globaux (E2E checklist)

- [ ] `curl http://127.0.0.1:8080/v1/models` → 200 (Phase 0)
- [ ] `pytest tests/test_ring_master_promotion.py` → 4/4 verts (Phase 1)
- [ ] `pytest tests/test_master_llamacpp_endpoint.py` → 6/6 verts (Phase 2)
- [ ] `LAFORGE_PYTHON tools/nokido_master_chat.py` → boucle interactive fonctionnelle (Phase 3)
- [ ] Mock cascade avec all-cloud-429 → llamacpp répond automatiquement (Phase 4)
- [ ] `SELECT count(*) FROM agent_messages WHERE method='master.llamacpp.call'` ≥ 1 après E2E (audit C4)
- [ ] `grep MASTER_LOCAL logs/mcp_audit.log` → entries présents
- [ ] `git diff --stat` ≤ 5 fichiers touchés (anti-bloat) : `tools/nokido_hub.py`, `tools/nokido_master_chat.py`, `Nokido.env`, `tests/test_ring_master_promotion.py`, `tests/test_master_llamacpp_endpoint.py`
- [ ] Aucun nouveau module `app/forge_*.py` (extension only)
- [ ] `anchor_solution()` exécuté → entry visible dans `rag_chunks`

## 7. Découpage exécution multi-LLM

| LLM exécutant | Phase prioritaire | Pourquoi |
|---|---|---|
| **Gemini CLI** (déporté, contexte 1M) | Phase 1+2 (code + tests) | meilleur contexte long, voit toute la stack |
| **llama.cpp local** (ce roadmap) | Phase 3 (CLI) | dogfooding — l'endpoint sert son propre wrapper |
| **LM Studio** | Phase 4 (router patch) | rapide pour itérer sur cascade logic |
| **Ollama qwen-coder:32b** | Phase 5 (docs + anchor) | autonome offline, idéal pour finir |

## 8. Ce qui n'est PAS dans cette roadmap (volontaire)

- Pas de support multi-modèles llama.cpp parallèles (un seul `LAFORGE_LLAMACPP_MODEL`).
- Pas d'authent multi-utilisateur — c'est un canal **mono-owner** (user ring 0).
- Pas de réplication/failover llama.cpp — si DOWN, on s'en aperçoit (C3).
- Pas d'intégration avec `gemini_poll_daemon` ni autre bridge MCP (volontairement standalone).
- Pas de chiffrement des audits — la DB est déjà locale, pas de PII cloud.

---

**FIN ROADMAP** — version 1.0, 2026-04-30. Modifier après merge en incrémentant la version, pas avant.
