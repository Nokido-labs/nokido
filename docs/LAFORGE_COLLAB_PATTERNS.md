# Patterns de collaboration multi-agent Nokido

Document de reference pour les differents mecanismes de communication
inter-agent dans l'ecosysteme Nokido, avec leurs cas d'usage, limitations
et recommandations d'implementation.

Date : 2026-04-24
Base : session Claude + Gemini (patterns A, B, C, D en prod) + proposition
D2 (autonomous polling) implementee dans cette session.

## Vue d'ensemble

Nokido supporte **7 patterns de collaboration** distincts entre agents LLM.
Chacun a son niveau de maturite, ses pre-requis et ses contraintes.

| Pattern | Nom | Maturite | Asynchrone | Pre-requis |
|---------|-----|----------|------------|------------|
| A       | Claude STDIO local | PROD | non | Claude Desktop |
| B       | Gemini HTTP Bearer | PROD | non | Gemini CLI + token |
| C       | Nokido auto-pilote | PROD | oui | Hub local + Ollama |
| D       | Collab notify/poll human-triggered | PROD | semi | 2 agents actifs |
| D2      | Autonomous polling daemon | PROD | oui | daemon tourne en background |
| E       | Webhook/SSE push | FUTUR | oui | endpoint HTTP cote agent |
| F       | P2P agents (slm-mesh style) | FUTUR | oui | broker P2P + MCP |

## Pattern A : Claude STDIO local

Claude Desktop charge `tools/nokido_mcp_server.py` comme sous-processus Python.
Communication JSON-RPC via stdin/stdout, latence intra-process <10ms.

```
Claude Desktop ──spawn subprocess──> nokido_mcp_server.py
   │                                        │
   └─────── stdin/stdout JSON-RPC ──────────┘
```

**Usage** : edition de code, refactor, debug, tache courte interactive.

**Limitation** : un seul agent par instance, pas de partage entre sessions.

## Pattern B : Gemini HTTP Bearer

Gemini CLI configure dans `~/.gemini/settings.json` avec `url` pointant sur
`http://127.0.0.1:8766/mcp` + header `Authorization: Bearer <FORGE_MCP_TOKEN>`.

```
Gemini CLI ──POST /mcp + Bearer──> Hub Nokido :8766
                                         │
                                    13 tools
```

**Usage** : tache longue exploratoire, generation de doc massive, analyse
complexe. Gemini a 1M tokens de contexte.

**Limitation** : Gemini est reactif - il n'agit que sur prompt humain.
Resolu par Pattern D2.

## Pattern C : Nokido auto-pilote (fire-and-forget)

Un LLM appelle `trigger_autonomous_evolution(intention, domains, max_silos)`.
Le silo engine decompose en domaines (parmi 7 SiloDomain), assigne chacun au
meilleur modele via MODEL_MAP, execute en parallele dans process detache,
retour immediat avec `task_id`. Le LLM poll ensuite via `task_status(tid)`.

```
LLM ──trigger_auto──> forge_runner.spawn(runner_code, env=base64)
                              │
                              ├── mmap live_bridge allocation
                              ├── Popen DETACHED
                              └── watchdog thread 600s timeout

LLM ──task_status(tid)──> live_bridge.task_get(tid)
                              │
                              └── sandbox/orch_<tid>.json si OK
```

**Usage** : tache complexe multi-angle (doc + audit + reco), tache longue
(>30s) ou l'agent ne veut pas bloquer, pipeline reproductible.

**Limitation** : timeout fixe 600s par silo, Ollama serialise les prompts
sur meme modele.

## Pattern D : Collab Claude <-> Gemini (notify/poll)

Les deux agents partagent :
- RAG SQLite `RAG/embeddings.db` (lecture/ecriture via `query`, `index_result`)
- Notifications via `notify` (push) + `poll` (pull consommation one-shot)
- Mode de collaboration dans `bridge_state.json` (AUTO/DEBAT/CHEF/CLINE/PING)

```
CLAUDE ──notify("hey Gemini, tache X")──> bridge_state.json::pending_notifications
                                                   │
GEMINI ──poll──> recupere et VIDE la file ─────────┘
       ──effectue la tache──>
       ──notify("reponse: Y")──> bridge_state.json
CLAUDE ──poll──> recupere
```

**Usage** : delegation de tache, review croise (pattern Reviewer Checker),
brainstorming entre 2 agents, division du travail.

**Regle d'or** : toute doc produite par un agent sans lecture prealable du
code doit etre reviewee factuellement par un autre agent avec acces au code.
Les LLMs hallucer plausiblement sans contexte precis.

**Limitation** : les agents sont reactifs. Sans trigger humain pour `poll`,
les notifs restent en attente indefiniment. Resolu par D2.

## Pattern D2 : Autonomous polling daemon (NOUVEAU)

Resout la limite de D. Un daemon Python independant poll le Hub pour le compte
d'un agent LLM, et a 2 modes de traitement :

**Mode PASSIVE** (defaut) :
```
tools/gemini_poll_daemon.py (background process)
       │
       ├── every N seconds : poll Hub
       ├── append notifs to ~/.gemini/inbox.md
       └── heartbeat sandbox/gemini_poll_daemon.heartbeat
```

L'humain peut :
- consulter `inbox.md` visuellement (texte markdown)
- prompter Gemini CLI "lis mon inbox.md et traite"

**Mode ACTIVE** :
```
Meme boucle, mais au lieu d'append :
       │
       ├── invoke API Gemini (generateContent)
       ├── parser la reponse
       ├── notify retour vers CLAUDE via Hub
       └── index_result dans RAG partagee
```

**Pre-requis mode ACTIVE** : `GEMINI_API_KEY` valide, `GEMINI_MODEL`
(defaut `gemini-2.5-flash`).

**Usage** : collaboration autonome 24/7 entre agents, sans intervention
humaine pour declencher le poll.

**Limitation** :
- Mode active consomme le quota API de l'agent repondant
- Pas de garantie de traitement en moins de N secondes (depends du cycle)
- Les agents peuvent entrer en loop infinie si mal configures
  (CLAUDE notify -> GEMINI daemon notify retour -> CLAUDE qui notify encore)

**Configuration** :
```bash
LAFORGE_ENABLE_GEMINI_POLL=1      # opt-in
GEMINI_POLL_INTERVAL_S=30
GEMINI_POLL_MODE=passive          # ou active
```

Lancement :
```bash
python tools/forge_services_launcher.py
# ou directement :
python tools/gemini_poll_daemon.py
```

## Pattern E : Webhook / SSE push (FUTUR)

Au lieu que le Hub stocke les notifs et attende le poll, il **pousse** vers
un endpoint HTTP cote agent.

```
CLAUDE ──notify("X")──> Hub Nokido :8766
                               │
                               └── POST http://gemini-agent.local:3000/webhook
                                       │
                                       └── Gemini instance recoit et traite
```

**Pre-requis** : chaque agent doit exposer un endpoint HTTP stable.
Possible pour Gemini CLI via un hook custom, ou via MCP `resources/subscribe`.

**Avantage** : latence push <100ms vs polling cycle N secondes.

**Non-implement** actuellement, mais structure deja presente dans Hub via
le module `event_log` + table `tui_notifications`.

## Pattern F : P2P agents (slm-mesh inspiration, FUTUR)

Inspire `qualixar/slm-mesh` : chaque session IDE (VS Code, Cursor, Claude
Desktop) auto-decouvre les autres et partage state + locks + broadcasts via
un broker localhost avec authentification bearer.

```
Claude Desktop session A ──register──> broker :XXXX
Cursor session B         ──register──> broker :XXXX
VS Code session C        ──register──> broker :XXXX

Session A ──broadcast("db migration done")──> broker ──> B, C
Session B ──lock("file.py")──> broker ──> A, C bloques si ecriture concurrente
```

**Pre-requis** :
- Un broker P2P (Node.js ou Python) sur localhost port arbitraire
- Chaque agent lance un client MCP qui se register aupres du broker
- Protocole partage : BROADCAST, PEERS, LOCK, UNLOCK, SYNC

**Cas d'usage** :
- 3 sessions AI coding en parallele sur le meme repo
- Coordination des locks sur fichiers edites
- Partage de "session A vient de fixer bug X, session B peut continuer"

**Complexite** : XL. Non prioritaire car notre Hub central fait deja 80% du
boulot via la RAG partagee et notify/poll.

## Pattern G : Trigger humain manuel (baseline)

Le plus simple : l'humain copie un message d'un agent vers l'autre.

```
Claude produit X ──[copier-coller humain]──> Gemini prompt
Gemini produit Y ──[copier-coller humain]──> Claude prompt
```

**Usage** : fallback ultime quand tous les autres patterns echouent.
L'humain reste le message bus entre agents, ce qui ralentit enormement.

**Observation** : c'etait le mode operant actuellement avant Pattern D2.
Meme avec le Hub qui stocke tout, il fallait que tu copies manuellement le
prompt QUALIXAR dans Gemini CLI. D2 supprime cette friction.

## Matrice de decision

| Situation                                        | Pattern recommande |
|--------------------------------------------------|--------------------|
| Dev interactif, edition code                     | A (Claude STDIO)  |
| Analyse longue par agent distant                 | B (Gemini HTTP)   |
| Tache complexe multi-silos                       | C (auto-pilote)   |
| Review croise sur un document                    | D (notify/poll)   |
| Collaboration autonome 24/7                      | D2 (daemon)       |
| Push immediat bas-latence                        | E (webhook)       |
| 3+ sessions IDE sur meme repo                    | F (P2P mesh)      |

## Roadmap

- [x] Pattern A : Claude Desktop STDIO (commit historique)
- [x] Pattern B : Gemini CLI HTTP Bearer (commit 2026-04-24)
- [x] Pattern C : trigger_autonomous_evolution fire-forget (commit 8a8396f)
- [x] Pattern D : notify/poll via bridge_state.json (commit historique)
- [x] Pattern D2 : gemini_poll_daemon.py (commit f1f5e69, cette session)
- [ ] Pattern E : webhook push (S - 2 jours effort)
- [ ] Pattern F : broker P2P a la slm-mesh (XL - 2 semaines)

## References

- Implementation Pattern D2 : `tools/gemini_poll_daemon.py`
- Launcher integration : `tools/forge_services_launcher.py`
- State bridge : `sandbox/bridge_state.json::pending_notifications`
- Inspiration externe :
  - https://github.com/qualixar/slm-mesh (Pattern F)
  - https://github.com/qualixar/qualixar-os (patterns A-D)
  - https://github.com/qualixar/slm-mcp-hub (federation multi-MCP, futur)

---

Date : 2026-04-24
Auteur : Claude Desktop (Claude Opus 4.7) avec review attendue de Gemini CLI
Commits references : `f1f5e69`, `5cd4ad8`, `8a8396f`, `d96f611`, `d83f317`
