# Inventaire outils externes alignés Nokido

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


**Date** : 2026-05-02
**Statut** : Documenté, **PAS installé** (review sécu requise par
`feedback_marketplace_install_review.md` post-incident trailofbits).

---

## 🧠 Mémoire / RAG (extension hippocampe)

### mem0ai/mem0 (⭐ universel)
- Universal memory layer pour AI agents
- API simple add/search/update/delete
- Backends : Qdrant, Pinecone, ChromaDB
- **Nokido fit** : alternative à `forge_self_correction` + `lessons_learned.md`
- **Risque** : duplication avec stack RAG existant (FAISS + bge-m3 + BM25
  + RRF fusion + SIGReg). Nokido a déjà mieux.
- **Verdict** : SKIP (duplicate, on a déjà cette couche)

### coleam00/mcp-mem0
- MCP server wrapping mem0
- Template Python pour build MCP servers
- **Verdict** : utile comme **template** pour Phase G Tool Smithing
  Python templates, pas pour usage prod direct

### mhalder/qdrant-mcp-server
- MCP semantic search Qdrant local + OpenAI embeddings
- **Nokido fit** : alternative à `brain_worker` ZMQ :5557
- **Risque** : OpenAI embeddings = pas local, brain_worker NPU est mieux
- **Verdict** : SKIP (NPU XDNA + bge-m3 local supérieur)

### thedotmack/claude-mem
- Claude Code plugin auto-capture sessions + replay context
- **Nokido fit** : ressemble à anchor_solution + auto memory existant
- **Verdict** : SKIP (déjà couvert)

---

## 🐳 Sandbox / exécution code (Phase G.5 référence)

### Recherches : "ephemeral docker sandbox exec"
- Pas de hit pertinent direct GitHub
- Pattern Phase G.5 (cf docs/roadmap_singularite_technique.md) custom
  est suffisant : `docker run --rm --network none --memory 256m`
- **Verdict** : implémenter custom Phase G.5, pas de dep externe

### docker mcp gateway (Anthropic native)
- Déjà installé dans Claude Desktop config
- Catalogue MCP servers Docker Hub (Prisma, Stripe, Sentry, etc.)
- **Verdict** : **DÉJÀ ACTIF**, exploiter dispatch via existing gateway

---

## 📊 Observability / metrics

### Recherches : "mcp observability prometheus"
- 0 hit pertinent direct
- Stack actuel : `forge_anatomy_state` + `/api/anatomy/state` =
  observability custom suffisante
- **Verdict** : pas besoin tool externe

---

## 🔍 Code analysis / linting (renfort code_critic)

### tree-sitter (npm, déjà mentionné Phase G)
- Parser incremental multi-langages
- **Nokido fit** : utilisé dans `code_critic.ts` futur pour validation
  syntax avant LLM audit (économie tokens)
- **Verdict** : INSTALL en TS (npm:tree-sitter + tree-sitter-typescript +
  tree-sitter-python) — Phase G.6 amélioration code_critic

### semgrep (CLI Python/binary)
- Pattern-based static analysis multi-langages
- **Nokido fit** : pré-scan code généré avant audit LLM
- **Verdict** : à évaluer Phase G.6 (alternative ou complément
  code_critic local OPSEC scan)

---

## 🎯 Top 2 candidats install (post-review sécu)

| Tool | Install Phase | Bénéfice |
|---|---|---|
| **tree-sitter** (Deno npm) | G.6 | Syntax validation pré-LLM = économie tokens code_critic |
| **semgrep** (CLI Python) | G.6 | Pattern security scan complément OPSEC local |

**Pas avant** : Phase G MVP stable + 5+ tools forgés sans Docker layer.

---

## ❌ NE PAS installer

- mem0 (duplicate FAISS+BM25+RRF stack existant)
- qdrant-mcp (NPU XDNA + bge-m3 local supérieur)
- claude-mem (anchor_solution déjà couvre)
- trailofbits/skills-curated (purgé incident 2026-05-02)
- android-mcp (purgé)
- searxng MCP wrapper (Docker container suffit)

---

## 📝 Process review obligatoire avant install

Cf `feedback_marketplace_install_review.md` :
1. Lister plugins/tools du repo
2. Lire `plugin.json` + `SKILL.md` + `hooks.json` + scripts shell
3. Vérifier patterns suspects : `wooyun`, `*-yeet`, `*-legacy`,
   `references/(sql-injection|command-execution|file-upload)`
4. Présenter inventaire au user avec risques
5. Install seulement après validation explicite

---

## 🛡️ MCP_DOCKER catalogue à exploiter (déjà dispo)

Via `docker mcp catalog` (déjà active Claude Desktop). Servers
disponibles directement sans clone :
- Prisma DB ORM
- Stripe, Sentry, Snowflake, MongoDB, Redis, Neo4j
- Filesystem, fetch, time, sequential-thinking
- GitHub MCP, Linear MCP, Atlassian MCP

→ accessible TOUS CLI (Cline/Codex/Gemini configuré). Pas
d action immédiate, exploiter selon besoin runtime.
