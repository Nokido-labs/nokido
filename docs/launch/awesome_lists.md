# 📜 Awesome-lists PR templates

3 listes prioritaires. Visibility durable (indexées Google) > viralité
courte. Faire les PRs **+45 min après launch HN** (laisse les modérateurs
voir le buzz).

## 1. awesome-mcp

Repo : `punkpeye/awesome-mcp-servers` ou `appcypher/awesome-mcp-servers`

### Where to add

Section : **Servers** → sous-section selon contenu. Nokido fit dans
plusieurs catégories — choisir une (la plus naturelle = "Knowledge & Memory"
ou "Multi-Agent Orchestration"). Voir le README de la liste pour l'ordre.

### Entry line (Markdown)

```markdown
- [Nokido](https://github.com/user/Nokido) - 🐍 🏠 Autonomous local-first AI OS exposing 25 MCP tools (RAG, vault-backed provider routing, neuro-symbolic governance). Multi-client (Claude/Gemini/Codex/Cline), Docker compose, AGPLv3.
```

Emojis legend (vérifier la convention de la liste en cours) :
- 🐍 = Python
- 🏠 = self-hosted

### PR title

```
Add Nokido — autonomous local-first AI OS with 25 MCP tools
```

### PR body

```markdown
Adding Nokido to the list. Solo-dev project, alpha branch but
publicly usable (Docker compose quick-start works).

What it brings :
- 25 MCP tools exposed via HTTP + STDIO
- Vault-backed API key management (DPAPI / Keychain / libsecret)
- Multi-client tested : Claude Desktop, Claude Code, Gemini CLI, Codex CLI, Cline
- Cross-OS (Ubuntu / macOS / Windows CI matrix)
- 8-language README (EN/FR/ES/ZH/PT-BR/JA/DE/AR)

Repo : github.com/user/Nokido
Manifesto : github.com/user/Nokido/blob/main/MANIFESTO.md
Wiki : 18 pages bilingual (EN+FR)

License : AGPLv3.

Let me know if any of the placement / emoji conventions need adjustment.
```

## 2. awesome-ai-agents

Repo : `e2b-dev/awesome-ai-agents` ou `kyrolabs/awesome-langchain` (selon
ce qui est le plus actif au moment du launch).

### Where to add

Section : **Frameworks** ou **Orchestration**.

### Entry line

```markdown
- [Nokido](https://github.com/user/Nokido) – Hub-as-orchestrator pattern (5-15× fewer client-side tokens than LLM-as-orchestrator). Local-first, 29 LLM providers, persistent RAG memory, neuro-symbolic governance. Python · AGPLv3.
```

### PR body — même structure que awesome-mcp, adapter scope.

## 3. awesome-selfhosted

Repo : `awesome-selfhosted/awesome-selfhosted`

### Where to add

Section : **AI - Models** ou **AI - Tools** (la liste évolue souvent).

### Entry line

```markdown
- [Nokido](https://github.com/user/Nokido) - Autonomous local-first AI Operating System with MCP hub, persistent RAG memory, 29 LLM providers cascade (3 local + 26 cloud opt-in), DPAPI/Keychain/libsecret vault, Docker compose. ([Source Code](https://github.com/user/Nokido)) `AGPL-3.0` `Python`
```

(Note : awesome-selfhosted veut le format strict avec `(...Source Code...)` et tags backticks pour licence + langage. Suivre le pattern existant à la lettre.)

## 4. autres listes optionnelles

| Liste | URL | Quand l'attaquer |
|---|---|---|
| `awesome-llm` | `Hannibal046/Awesome-LLM` | semaine 1 post-launch |
| `awesome-python` | `vinta/awesome-python` | semaine 2 (très selectif) |
| `awesome-machine-learning` | `josephmisiti/awesome-machine-learning` | semaine 3 |
| `awesome-claude` | divers | jour 1 même que awesome-mcp |
| `awesome-rust` (si tu pitch brain_worker) | `rust-unofficial/awesome-rust` | semaine 4 |
| `awesome-rag` | divers | jour 1 |

## 📋 Convention awesome-lists générale

- **1 line per project** — pas de gros paragraphes.
- **Description sous 100 caractères** — extra info dans le repo.
- **Liens vers source code obligatoires** sur awesome-selfhosted.
- **Tag licence obligatoire** sur awesome-selfhosted, awesome-python.
- **Emojis legend** sur certaines listes — vérifier le README.
- **Ordre alphabétique** dans la section.
- **PR description courte** — les mainteneurs veulent juste savoir si
  le projet match les critères de la liste.

## ⏱️ Timing

J+0 launch :
- 15:15 Paris : awesome-mcp + awesome-ai-agents + awesome-claude
- 15:30 Paris : awesome-selfhosted + awesome-rag

J+1 :
- awesome-llm + awesome-python

J+7 :
- awesome-machine-learning + awesome-rust (si traction sur brain_worker
  est notable, sinon skip)

## 🆘 Si la PR est rejetée

Common reasons :
- "Project too new" — re-soumets dans 3 mois.
- "Not enough stars" — accumule traction d'abord (target 100+ stars).
- "License doesn't match list policy" — certaines listes refusent AGPL.
  Pas de discussion, skip cette liste.
- "Description too marketing-y" — réécris en plus neutre.

Toujours **remercie le mainteneur** et propose les ajustements si feedback
constructif. Les mainteneurs voient passer 50+ PRs/mois, ils apprécient le
ton respectueux.
