# Frontends CLI LLM → gateway souverain Nokido

Nokido n'intègre PAS shell_gpt / llm / aichat comme backends (ce serait dupliquer
router + RAG + providers + firewall déjà présents). Inversion correcte : **Nokido
est le backend, ces CLI sont des frontends optionnels.**

## Le gateway

`tools/forge_openai_proxy.py` (service `NokidoOpenAIProxy`, port **7777**) expose
`/v1/chat/completions` + `/v1/models` OpenAI-compatibles. Depuis 2026-05-29 le
gateway passe **SemanticFirewall** en chemin :

- `pre_flight` (ring 3) : DLP redact (PII → placeholders avant upstream), blocage
  injection / ring → **HTTP 403** `firewall_blocked` AVANT tout appel LLM.
- `post_flight` : SSRF / canary leak / hallucination → **HTTP 502** `firewall_post_blocked`.
- `restore` : replace les placeholders DLP par les originaux dans la réponse.

Quotas/budget cloud : gérés en aval (router + `forge_provider_quota`).

→ Brancher n'importe quel CLI sur `http://127.0.0.1:7777/v1` = routing souverain
+ firewall + log, gratuitement. API key = dummy (`laforge-local`).

## Configs (points de départ — vérifier selon version de l'outil)

### shell_gpt (sgpt)
`~/.config/shell_gpt/.sgptrc` :
```
API_BASE_URL=http://127.0.0.1:7777/v1
OPENAI_API_KEY=laforge-local
DEFAULT_MODEL=laforge-cascade
OPENAI_USE_FUNCTIONS=false
```

### simonw/llm
`~/.config/io.datasette.llm/extra-openai-models.yaml` :
```yaml
- model_id: nokido
  model_name: laforge-cascade
  api_base: http://127.0.0.1:7777/v1
```
Puis `llm keys set nokido` (valeur bidon) et `llm -m nokido "..."`.

### aichat
`~/.config/aichat/config.yaml` :
```yaml
clients:
  - type: openai-compatible
    name: nokido
    api_base: http://127.0.0.1:7777/v1
    api_key: laforge-local
    models:
      - name: laforge-cascade
```
Puis `aichat -m nokido:laforge-cascade "..."`.

## À porter (pas wrapper) si besoin futur

- **simonw/llm** : modèle de **plugins** (largeur providers/tools via pip) + son
  schéma de **log SQLite** prompt/réponse → inspirer l'extensibilité Nokido.
- **shell_gpt** : UX NL→shell sur le terminal **user** (Nokido `run` = côté agent).
- **aichat** : rien — son serveur OpenAI-compat = redondant avec ce gateway.

Le reste de leur cœur (routing/RAG/embeddings/sessions) = déjà couvert par Nokido.
