# Base documentaire — Unification & déportation locale des 3 CLI agentiques

> Objectif (user 2026-06-10) : intercepter les appels LLM-API **natifs** des 3 CLI
> (Claude Code, Gemini CLI, GitHub Copilot CLI) derrière le hub local Nokido :8766 →
> **préserver les quotas Ultra/Max** (Claude/Gemini OAuth) + le free-tier Copilot (Haiku 4.5),
> **déporter les micro-tâches** sur workers locaux, zéro fuite de contexte.
>
> ⚠ Levers `env` ci-dessous = documentés mais **à confirmer/enrichir via veille profonde**
> (crawl docs officielles) une fois le hub relancé. Les modules Nokido = **vérifiés au code**
> (Explore 2026-06-10, file:line). Distinguer les deux.

## Principe : Ingress Adapter + Switchboard

```
Claude Code   --ANTHROPIC_BASE_URL-->  /v1/messages         (:7776  À BUILD)
Copilot CLI   --BYOK OpenAI-------->   /v1/chat/completions (:7777  EXISTE: forge_openai_proxy)
Gemini CLI    --GOOGLE_*_BASE+proxy->  /v1/.../generateContent (:7778 À BUILD)
        │
        ├─ SemanticFirewall.pre_flight (DLP/injection/ring)  [forge_semantic_firewall]
        ├─ forge_cache_aligner + forge_prompt_cache (cache Anthropic)
        ↓
   hub :8766  ask  ─→  SWITCHBOARD  [forge_llm_router.call_cascade + forge_cognitive_router.route_task]
        │
        ├─ PASSTHROUGH cloud : tâche lourde → injecte OAuth Max/Ultra, relaie (proxy pur)
        └─ DÉPORT local      : micro-tâche (docstring/typecheck/relecture) → ollama/llama/run_job
```

## 1. Claude Code CLI — interception `ANTHROPIC_BASE_URL`

- **Lever** : `ANTHROPIC_BASE_URL=http://localhost:7776` (+ `ANTHROPIC_AUTH_TOKEN` / passthrough OAuth).
  Force le binaire `claude` à POSTer ses payloads Messages API sur Nokido.
- **Format ingress** : Anthropic Messages API — `{model, max_tokens, system, messages:[{role,content}], stream}`,
  header `anthropic-version` ; réponse `{content:[{type:"text",text}], usage, stop_reason}`.
- **Docs officielles** : `code.claude.com/docs` (settings/env, LLM gateway, Bedrock/Vertex = preuve base_url surchargeable).
- **OSS de référence (fournis user, À INGÉRER+VÉRIFIER via veille)** :
  `FlorianBruniaux/cc-copilot-bridge`, `voidsteed/copilot-proxy-api` (réécriture en-têtes auth à la volée).
- **Nokido** : ❌ MANQUE → BUILD `tools/forge_anthropic_ingress.py` (fork `forge_openai_proxy.py`,
  convertit Anthropic→`ask`, applique `forge_prompt_cache.build_cached_system`).

## 2. Gemini CLI — paradoxe OAuth + proxy local

- **Lever** : `GOOGLE_GEMINI_BASE_URL`/`GOOGLE_API_BASE` + `HTTPS_PROXY=http://localhost:7778`
  + gestion cert local (`NODE_EXTRA_CA_CERTS` / `CURL_CA_BUNDLE`). L'OAuth Gemini dialogue avec
  Google → le proxy doit coexister sans casser le flux d'auth initial (le "paradoxe").
- **Format ingress** : Gemini Dev API / Vertex — `generateContent` (`contents[]`, `generationConfig`).
- **Docs** : `google-gemini.github.io` (config gemini-cli) ; repo `google-gemini/gemini-cli` (**OSS, DÉJÀ dans
  le RAG = 1075 chunks, veille 2026-06-10** → `rag search` dessus pour l'impl exacte endpoint/SDK google-genai).
- **Nokido** : ❌ MANQUE → BUILD `tools/forge_gemini_ingress.py` (même base).

## 3. GitHub Copilot CLI — BYOK (OpenAI-compatible)

- **Lever** : BYOK → endpoint OpenAI `/v1/chat/completions`. Config agent Copilot pointe sur le port local.
  Quota faible (Haiku 4.5) → faire croire que le modèle local Nokido est le modèle distant.
- **Docs** : `docs.github.com` — "Using your own LLM models in GitHub Copilot CLI".
- **OSS** : `caozhiyuan/copilot-api` (impl inverse protocole Codex `/responses`).
- **Nokido** : ✅ **DÉJÀ COUVERT** — `tools/forge_openai_proxy.py` (:7777) sert `/v1/chat/completions`
  (firewall pre/post + hub_call + cascade). **Pointer Copilot dessus = 0 build.** (+ `.github/mcp.json` déjà câblé.)

## 4. Nokido — ce qui existe (RÉUTILISER, anti-dup §3)

| Brique | Fichier | Rôle |
|---|---|---|
| Base ingress OpenAI | `tools/forge_openai_proxy.py` :7777 | `/v1/chat/completions` + `/v1/models` + firewall + hub_call. **= base à forker.** |
| **Switchboard** | `app/forge_llm_router.py::call_cascade` (~774-946) | use-case→provider, gating quota/host/ring. |
| Routeur cognitif | `app/forge_cognitive_router.py::route_task` (~347-489) | complexité→backend (onnx_local/ollama/cloud), ring-0 force local = règle déport. |
| Gate cloud/local | `app/forge_semantic_firewall.py::pre_flight` (~369-460) | DLP+injection+ring avant routage. |
| Cache Anthropic | `app/forge_prompt_cache.py::build_cached_system` | `cache_control ephemeral` + keepalive. |
| Stabilisation préfixe | `app/forge_cache_aligner.py` | nettoie tokens volatils → hit cache. |
| Déport exécution | hub `run` action=`run_job` | micro-tâche détachée sur worker local. |

## 5. À construire (3 pièces, reuse-first)

1. `tools/forge_anthropic_ingress.py` (:7776) — `/v1/messages`, fork openai_proxy.
2. `tools/forge_gemini_ingress.py` (:7778) — `generateContent`, idem.
3. `app/forge_llm_format_bridge.py` — convertisseurs Anthropic↔OpenAI↔Gemini + Message/Response unifiés.
   (Le switchboard = réutilisé via `ask`, PAS réécrit.)

## 6. À enrichir via veille profonde (post-reload hub)

Requêtes deep-veille / veille-rapide (ingest → RAG `domain=biblio_cli`) :
- `ANTHROPIC_BASE_URL claude code custom endpoint proxy gateway`
- `gemini-cli GOOGLE_GEMINI_BASE_URL HTTPS_PROXY oauth local proxy`
- `github copilot cli BYOK custom model openai endpoint /v1/chat/completions`
- URLs directes à crawler : les 5 docs/OSS ci-dessus (cc-copilot-bridge, copilot-proxy-api, copilot-api,
  code.claude.com/docs, docs.github.com copilot-cli BYOK).

> Anti-dup : `forge_openai_proxy` couvre l'OpenAI-format ; ne PAS le dupliquer — les 2 nouveaux
> ingress le FORKENT pour Anthropic/Gemini, et délèguent la décision au switchboard existant.
