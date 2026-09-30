---
name: forge-connectors
description: >
  Connecteurs cloud Claude (claude.ai) accessibles UNIQUEMENT par agt_claude :
  Gmail (10 tools), Google Calendar (auth), Google Drive (auth), Notion (13 tools).
  Déclencher quand l utilisateur demande : "envoie mail", "créé draft Gmail",
  "cherche dans Gmail", "créé page Notion", "mets à jour Notion", "ajoute event
  calendar", "fichier Drive". Si la demande vient d un autre CLI (Gemini/Cline/
  Codex), router vers agt_claude via TUI ou agent_messages — eux n'ont PAS
  accès direct.
---

# claude-connectors — Connecteurs cloud Claude.ai

## Rôle

Catalogue des outils MCP **exclusivement** disponibles depuis Claude (Sonnet/
Opus) sur claude.ai et Claude Code natif. Ces outils sont injectés via le
système deferred tools de l'agent Anthropic — invisibles pour Gemini CLI,
Cline, Codex, llama.cpp local, et tous les agents non-Claude.

Pourquoi ce skill : faire savoir aux autres CLIs (qui lisent le RAG Nokido)
que ces capacités existent et **par qui** elles passent (toujours
`agt_claude`).

---

## Catalogue des connecteurs

### Gmail (10 outils)

| Tool | Action |
|---|---|
| `mcp__claude_ai_Gmail__create_draft` | Créé brouillon email (recipients, subject, body) |
| `mcp__claude_ai_Gmail__create_label` | Créé nouveau label dans Gmail |
| `mcp__claude_ai_Gmail__get_thread` | Récupère thread complet (messages + headers) |
| `mcp__claude_ai_Gmail__label_message` | Applique label à message individuel |
| `mcp__claude_ai_Gmail__label_thread` | Applique label à thread complet |
| `mcp__claude_ai_Gmail__list_drafts` | Liste brouillons (filtres possibles) |
| `mcp__claude_ai_Gmail__list_labels` | Liste tous labels (system + user) |
| `mcp__claude_ai_Gmail__search_threads` | Cherche threads (Gmail query syntax) |
| `mcp__claude_ai_Gmail__unlabel_message` | Retire label d'un message |
| `mcp__claude_ai_Gmail__unlabel_thread` | Retire label d'un thread |

**Pas d'envoi direct** — créer brouillon + signaler à l'utilisateur pour
review/envoi manuel.

### Google Calendar (2 outils auth)

| Tool | Action |
|---|---|
| `mcp__claude_ai_Google_Calendar__authenticate` | Démarre OAuth Calendar |
| `mcp__claude_ai_Google_Calendar__complete_authentication` | Complète flow OAuth |

⚠ Outils d'auth seulement visibles. Outils opérationnels (create_event, list_events,
etc.) apparaîtront seulement après authentification active.

### Google Drive (2 outils auth)

| Tool | Action |
|---|---|
| `mcp__claude_ai_Google_Drive__authenticate` | Démarre OAuth Drive |
| `mcp__claude_ai_Google_Drive__complete_authentication` | Complète flow OAuth |

Idem Calendar — outils file ops disponibles après auth.

### Notion (13 outils + 8 sources connectées)

**Notion AI Search est un connecteur racine** : `notion-search` avec
`query_type=internal` cherche aussi dans les sources externes connectées
au workspace Notion :

| Source connectée | Accès |
|---|---|
| Slack | messages, threads, fichiers partagés |
| Google Drive | docs, sheets, slides indexés |
| GitHub | issues, PRs, commits, README |
| Jira | tickets, projets, sprints |
| Microsoft Teams | chats, channels |
| SharePoint | documents, pages |
| OneDrive | fichiers personnels |
| Linear | issues, projects, cycles |

→ Requête unique multi-source : `notion-search query="bug login" filters={}`
retourne résultats fusionnés Notion + Slack + GitHub + Jira + Linear.



| Tool | Action |
|---|---|
| `mcp__claude_ai_Notion__notion-fetch` | Récupère page/database par URL ou ID |
| `mcp__claude_ai_Notion__notion-search` | Recherche workspace (queries naturelles) |
| `mcp__claude_ai_Notion__notion-create-pages` | Créé pages (parent + content) |
| `mcp__claude_ai_Notion__notion-update-page` | MAJ propriétés ou content existant |
| `mcp__claude_ai_Notion__notion-create-database` | Créé database avec schema |
| `mcp__claude_ai_Notion__notion-update-data-source` | MAJ schema database |
| `mcp__claude_ai_Notion__notion-duplicate-page` | Clone page (avec content) |
| `mcp__claude_ai_Notion__notion-move-pages` | Déplace pages vers nouveau parent |
| `mcp__claude_ai_Notion__notion-create-view` | Créé view filtrée database |
| `mcp__claude_ai_Notion__notion-update-view` | MAJ filtres/tri view |
| `mcp__claude_ai_Notion__notion-get-comments` | Récupère commentaires page |
| `mcp__claude_ai_Notion__notion-create-comment` | Ajoute commentaire |
| `mcp__claude_ai_Notion__notion-get-teams` | Liste teams workspace |
| `mcp__claude_ai_Notion__notion-get-users` | Liste users workspace |

---

## Quand se déclencher (intent triggers)

Activer ce skill quand l'utilisateur demande :

**Mail** :
- "envoie un mail à X", "créé brouillon Gmail"
- "cherche les emails de X", "trouve thread sujet Y"
- "ajoute label Z à ces emails"

**Calendar** :
- "ajoute un événement", "vérifie mon agenda"
- "créé meeting avec X demain"

**Drive** :
- "récupère fichier Y du Drive", "partage doc Z"

**Notion** :
- "créé page Notion sur sujet X"
- "mets à jour la database tasks"
- "trouve dans Notion les notes sur Y"
- "duplique cette page", "ajoute commentaire"

---

## Routing depuis autres CLIs

Si la demande arrive depuis Gemini CLI / Cline / Codex / llama.cpp :

1. Ces agents **n'ont pas accès direct** aux connecteurs.
2. Router via `agent_messages` ou TUI : `@claude <demande>`
3. `agt_claude` exécute l'outil cloud, retourne résultat dans mailbox.
4. Agent demandeur récupère résultat et continue son flow.

Pattern :
```
[GEMINI] @claude créé brouillon Gmail à user@example.com sujet "rapport"
[CLAUDE] Brouillon créé id=draft_xxx visible dans Gmail Drafts
[GEMINI] OK reprise flow
```

---

## Sécurité (OPSEC + Centaure)

⚠ Ces outils accèdent à du contenu **personnel sensible** (mails, agenda,
docs, notes Notion). Toujours :

1. Vérifier `forge_opsec.get_opsec_level()` avant action :
   - **CTF** : refuser (mode lab, pas prod)
   - **STANDARD/PARANOID** : autorisé après confirmation user
2. Pour actions destructives (suppression, modification massive) :
   - Vérifier `forge_opsec.is_human_locked()` → si lock actif, demander confirmation explicite
   - Préférer `create_draft` à envoi direct, `create_pages` à overwrite
3. Logger via `anchor_solution(domain="connectors")` pour audit trail.

---

## Limites

- **Calendar/Drive** : seulement outils auth visibles tant que pas authentifié.
  Si user demande feature non disponible → suggérer auth.
- **Pas de Slack/Discord/Teams** côté Claude pour l'instant.
- **Pas de GitHub natif** — utiliser `gh` CLI via Bash ou `MCP_DOCKER` gateway.
- **Pas de retry automatique** : OAuth peut expirer, refait flow auth si erreur 401.

---

## Anchor RAG après usage

```python
from forge_self_correction import anchor_solution
anchor_solution(
    problem="<demande user>",
    solution=f"Used connector mcp__claude_ai_<X>__<tool> | result: <id ou ref>",
    domain="connectors",
)
```

---

## Voir aussi

- `laforge-skills` — passerelle skills locales Nokido
- `claude-skills-marketplace` — 18+ skills Anthropic + caveman alt market
- `forge-anatomy` — cartographie biomimétique modules
- `MCP_DOCKER` — gateway Docker MCP (catalogue Docker Hub : **Prisma**, Stripe,
  Sentry, Snowflake, MongoDB, Redis, Neo4j, etc.) accessible depuis tous CLI
