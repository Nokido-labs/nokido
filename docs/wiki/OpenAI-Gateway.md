---
type: guide
title: OpenAI Gateway souverain
status: draft
resource: repo://docs/wiki/OpenAI-Gateway.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# OpenAI Gateway souverain

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

`tools/forge_openai_proxy.py` — service `NokidoOpenAIProxy`, port **7777**. Expose
`/v1/chat/completions` + `/v1/models` OpenAI-compatibles, en façade du hub Nokido.

## Chaîne (depuis 2026-05-29)

```
client CLI → POST /v1/chat/completions
  → SemanticFirewall.pre_flight (ring 3)
        DLP redact → safe_task ; injection / ring → HTTP 403 firewall_blocked
  → hub ask (routeur LLM local/cloud)
  → SemanticFirewall.post_flight
        SSRF / canary leak / hallucination → HTTP 502 firewall_post_blocked
  → restore (placeholders DLP → originaux)
  → réponse OpenAI ChatCompletion
```

Non-stream **et** pseudo-stream (le « stream » récupère la réponse complète puis la
découpe → `post_flight` possible). Best-effort : si le module firewall est indisponible,
le gateway logue + dégrade (ne brick pas). Budget/quota cloud : géré en aval (routeur).

## Frontends CLI (Nokido = backend, eux = frontends)

Ne PAS intégrer shell_gpt / simonw-llm / aichat comme backends (dupliquerait
routeur/RAG/providers/firewall). Les brancher sur `http://127.0.0.1:7777/v1` :

**shell_gpt** — `~/.config/shell_gpt/.sgptrc`
```
API_BASE_URL=http://127.0.0.1:7777/v1
OPENAI_API_KEY=laforge-local
DEFAULT_MODEL=laforge-cascade
```

**simonw/llm** — `extra-openai-models.yaml`
```yaml
- model_id: nokido
  model_name: laforge-cascade
  api_base: http://127.0.0.1:7777/v1
```

**aichat** — `~/.config/aichat/config.yaml`
```yaml
clients:
  - type: openai-compatible
    name: nokido
    api_base: http://127.0.0.1:7777/v1
    api_key: laforge-local
    models: [{ name: laforge-cascade }]
```

Détails : [`docs/llm_cli_frontends.md`](../llm_cli_frontends.md).

## À porter plus tard (pas wrapper)

- simonw/llm : modèle de plugins + log SQLite prompt/réponse.
- shell_gpt : UX NL→shell côté terminal user.
- aichat : rien (serveur OpenAI-compat redondant avec ce gateway).

## Tests

`tests/test_forge_openai_proxy_firewall.py` — pre 403 / post 502 / restore / stream block.

## Connu

`/v1/models` : timeout observé (endpoint lent côté hub) — à investiguer si utilisé.
