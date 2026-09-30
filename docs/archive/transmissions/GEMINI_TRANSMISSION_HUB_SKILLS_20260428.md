# Fiche Technique Gemini CLI - Hub & Skills Interopérabilité
Date : 2026-04-28 (transmise via user depuis session Gemini CLI)
Statut : fiche reconstituée depuis rapport oral

## Pourquoi passer par le Sovereign Hub

Gemini CLI pourrait appeler les LLM et outils directement (Node.js local).
Il passe par le hub parce que :

1. **Gouvernance centralisée** : le hub est le point de contrôle unique (RBAC, rate limiting, audit)
2. **Partage de contexte** : EventBus partagé avec Claude, INSPECTOR, et futurs agents
3. **Accès aux outils Nokido** : run, read, write, query, rag, task, biblio
4. **Traçabilité** : network_log avec canal GEMINI_OAUTH, ring 0, agent_id
5. **Délégation LLM** : ask(provider=mistral|groq|claude_cli|...) pour déléguer des sous-tâches

## Canaux de communication (post-patch 2026-04-28)

| Canal | Description | Logging |
|-------|-------------|---------|
| GEMINI_OAUTH | Gemini CLI via OAuth Google | channel_meta.oauth_account, auth_type=oauth2_personal |
| GEMINI_API | Appels sortants vers Gemini API | channel_meta.auth_type=api_key |

## Limitation connue : EventBus PULL

L'EventBus Nokido est en mode **PULL** (publish + history, pas subscribe).
Gemini CLI doit **poller** periodiquement pour recevoir les messages entrants :

```
# Gemini CLI polling pattern
Nokido:hub action=poll  (ou) Nokido:event action=history limit=10
```

Pas de push server-sent-events nativement vers Gemini CLI.
(Refactor PUSH = sprint futur beta)

## Règles d'usage des Skills

Les skills Nokido sont des SKILL.md dans /mnt/skills/.
Gemini CLI n'a PAS accès à ce filesystem (c'est le filesystem Docker de Claude).
Gemini CLI utilise les Skills via le RAG Nokido (vectorisé) :

```
Nokido:rag action=search topic="biblio worker sanitization"
```

## Messages perdus du matin

- 10:07 : [ARCH] Fiche technique - **perdu** (archivage patch non encore actif)
- 10:11 : [ARCH] Complement Hub - **perdu** (idem)
- Reconstruction via cette fiche + fiche identité

## Backlog signalé

- Refactor EventBus PUSH (reçoit les messages en temps réel sans polling)
- TUI @biblio commands (TUI Textual)
- NSSM packaging worker biblio
