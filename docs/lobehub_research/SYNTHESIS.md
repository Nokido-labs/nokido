# LobeHub — Synthèse Capacités (recherche 2026-05-02)

## Vue d'ensemble

LobeHub = **agent harness next-gen** (post-chat tool). Pas un simple chat client, c'est un OS pour agents IA persistants.

Tagline officielle : "find, build, and collaborate with agent teammates that grow with you".

## Capacités MAJEURES

### 1. Agents persistants (Agent Builder)
- Description text → auto-config agent
- 10 000+ skills MCP-compatible
- Chaque agent = unité de travail (vs message one-off)

### 2. Agent Groups (collaboration parallèle)
- Multi-agents en parallèle dans 1 page
- Iterative improvement entre agents
- Shared context

### 3. Pages + Schedule + Project + Workspace
- **Pages** : write content multi-agents shared context
- **Schedule** : runs cron, agents bossent quand tu dors
- **Project** : organisation tâches structurées
- **Workspace** : team collab + ownership tracking

### 4. Memory (white-box)
- Personal Memory persistante structurée
- **Editable** par user (transparency)
- Continual learning depuis interactions
- Vs mémoire opaque OpenAI/ChatGPT

### 5. MCP Marketplace + Custom MCP
- **MCP Market** : 10 000+ skills ready-to-use
- **Custom MCP HTTP** (Streamable, web + desktop)
- **Custom MCP STDIO** (desktop seulement, CLI tools)
- JSON paste import config
- Settings → Skills → Skill Store → Custom

### 6. Online Search natif
- SearxNG/Tavily/Brave intégré dans agent
- `docs/self-hosting/advanced/online-search.mdx`
- → on a déjà SearxNG :8080 déployé !

### 7. Knowledge Base (RAG natif)
- PGVector + S3 + OpenAI Embeddings (text-embedding-3-small)
- File upload (PDF, Word via Unstructured.io)
- Per-agent KB possible

### 8. Multi-modal
- Vision (GPT-4V, Claude Vision, Gemini Vision)
- Image Generation (DALL-E, FLUX, ComfyUI)
- TTS/STT (text-to-speech / speech-to-text)
- Audio + video upload

### 9. Artifacts (rendu live HTML/SVG/Mermaid/code)
- Comme Claude.ai artifacts
- Chain-of-Thought visualization
- Sandbox d'exécution code

### 10. Channels (multi-platform)
- Discord, Slack, Telegram, Lark, Feishu, WeChat, QQ
- Agents accessibles depuis ces apps

### 11. Self-hosting full stack
- Docker Compose : Next.js + PostgreSQL + Redis + RustFS (S3) + SearxNG
- Vercel, Zeabur, Sealos, Dokploy, Coolify
- Desktop : Electron app standalone (140MB, ce qu'on a téléchargé)

### 12. Better Auth (SSO/OIDC)
- Email/password
- Magic links
- OAuth : Google, GitHub, Microsoft, AWS Cognito
- Generic OIDC

### 13. Provider env vars (50+ providers builtin)
- OpenAI, Anthropic, Google, Groq, DeepSeek, xAI, Mistral, OpenRouter
- Ollama, LMStudio, vLLM (locaux)
- Azure, Bedrock, VertexAI, Cloudflare AI
- ComfyUI, FAL, BFL (image gen)
- Custom OpenAI-compatible (base URL override)

### 14. Branching conversations (Forkable Chat)
- Topic = thread isolé
- Branche conversation à n'importe quel point
- Compare réponses agents différents

### 15. Agent Tasks (autonomous)
- Agent reçoit tâche, l'exécute en background
- Daily Brief : agent compile actu jour
- Triggered par événements (cron, webhook)

### 16. Gateway / Sidebar
- Vue gateway centralisée tous agents
- Sidebar workspace structuré
- Multi-tab parallèle

## Architecture Self-Hosted

```
┌──────────────────────┐
│  LobeHub Next.js     │  ← UI + API routes
└──────┬───────────────┘
       │
       ├─── PostgreSQL + PGVector (chats, agents, KB)
       ├─── Redis (sessions, cache)
       ├─── S3 / RustFS / MinIO (file storage)
       ├─── SearxNG (web search)
       └─── External LLMs (50+ providers)
```

## Intégration Nokido → LobeHub

### Stratégie Custom MCP (recommandée)

Dans LobeHub :
```
Settings → Skills → Skill Store → Custom → Add custom skill
↓ JSON Import
{
  "mcpServers": {
    "laforge": {
      "url": "http://127.0.0.1:8766/mcp",
      "type": "http"
    }
  }
}
↓ Auth : Bearer FORGE_TOKEN_CLAUDE
```

Tous les 16 tools Nokido exposés direct comme skills agent.

### Stratégie Provider OpenAI-compat (multi-CLI bridge)

Mon proxy `tools/forge_openai_proxy.py` :7777/v1 expose tous backends Nokido comme models OpenAI :
- `claude-cli`, `gemini-cli` (CLI bridges)
- `qwen3-8b`, `qwen2.5-coder-32b`, `deepseek-r1-14b`, `gemma4-e4b` (Ollama locaux)
- `llamacpp-local`, `lmstudio` (locaux OpenAI)
- `claude-sonnet-4.6`, `gemini-2.5-pro`, `groq-llama-70b`, `deepseek-v3`, etc. (cloud)
- `laforge-cascade` (auto-routing intelligent)

Configuration LobeHub :
- Settings → AI Service Provider → + Custom
- Type : OpenAI Compatible
- Base URL : `http://127.0.0.1:7777/v1`
- API Key : `laforge-local`
- Models : auto-fetch via `/v1/models`

### Stratégie SearxNG

LobeHub natif supporte SearxNG. Configurer pour pointer notre instance :
```env
SEARXNG_URL=http://127.0.0.1:8080
```

### Stratégie Knowledge Base

2 options :
- a) Utiliser KB native LobeHub (PGVector + S3) — installer LobeHub self-hosted full stack
- b) Wrapper RAG/embeddings.db en MCP `rag` tool exposé via custom MCP

## Multi-CLI single window

**Pas natif LobeHub**. Solutions :

### Option 1 — Pseudo-multi via OpenAI proxy (rapide)
Chaque CLI = model dans dropdown LobeHub. Switch instantané.
- Limite : 1 conversation à la fois.

### Option 2 — Custom plugin LobeHub
SDK plugin → iframe HTML/JS contenant N PTY widgets.
- Réutiliser `forge_pty.py` (Textual PTY existant).
- Effort : ~1 sprint dev.

### Option 3 — Externe (Wezterm/Zellij)
Splits terminaux Claude Code + Gemini CLI + Cline.
- Coordonné via Nokido `agent_messages` SQLite.
- Plus simple, hors LobeHub.

## Conclusion

LobeHub = **plateforme orchestration agents** complète. Beaucoup de chevauchement avec Nokido (RAG, MCP, agents, search).

Approche optimale : **Nokido backend + LobeHub frontend**.
- Nokido expose ses 16 tools via MCP HTTP custom
- LobeHub utilise comme skill provider universel
- Eviter duplication KB / Memory / Search

Pour multi-CLI vrai : custom plugin LobeHub OU externe (Wezterm splits).
