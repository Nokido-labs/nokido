# Surface d'interception multi-LLM — GEN-0 du Transient Spine

**Mesuré le 2026-09-17.** Livrable de GEN-0 : savoir quels agents peuvent alimenter
le même Transient Spine, et **par quel transport**. Aucun code fonctionnel n'a été
écrit pour produire ce document — observation seule.

> **Règle de lecture : `UNKNOWN`, jamais `NO` sans expérience.** Une case vide dit
> qu'on n'a pas regardé, pas que la capacité est absente. Trois états partout :
> vrai · faux · illisible.

## Le résultat qui oriente le chantier

**Le transport dominant est déjà HTTP, pas `stdio`.** Trois clients sur quatre
adressent le hub par `http://127.0.0.1:8766/mcp`. Concevoir le Spine autour d'une
hypothèse `stdio` aurait décrit un parc qui n'existe pas.

L'endpoint a été sondé directement :

| chemin | réponse | lecture |
|---|---|---|
| `/health` | `200 OK`, `application/json` | vivant |
| `/mcp` | **`401 Unauthorized`** | **existe**, authentification requise |
| `/sse` | `404` | pas de transport SSE |
| `/messages` | `404` | idem |
| `/api/mcp` | `404` | idem |

`401` n'est pas `404` : l'endpoint est là. Un `POST /mcp` portant un `initialize`
JSON-RPC rend le même `401` — le transport répond, c'est le jeton qui manque à la
sonde. **Ne jamais lire un `401` comme une absence de capacité.**

## Matrice des surfaces

| Source | Signal observable | Transport vers Nokido | Capture | Blocage | Réinjection | Statut |
|---|---|---|---|---|---|---|
| **Claude Code** | `Task`, `Agent` (+ `dispatch_agent`, `explore`) | hooks locaux **et** MCP HTTP | `forge_tool_gate` sur `PreToolUse`, matcher `Read\|Grep\|Glob\|WebSearch\|WebFetch\|Task\|Agent\|Write\|Edit` | **OUI, mesuré** — le gate refuse les sous-agents quel que soit le `subagent_type` | **UNKNOWN** — le schéma utilisé expose `permissionDecision` et `additionalContext` ; aucune réécriture d'appel observée | MESURÉ |
| **Gemini CLI** | hooks `SessionStart`, **`AfterModel`** | **MCP HTTP** `/mcp`, en-tête d'agent `GEMINI` | deux hooks `AfterModel` déclarés (`after_model_hook`, `hook_gate_orchestrator`) | UNKNOWN | UNKNOWN | MESURÉ |
| **Codex** | appels d'outils MCP | **MCP HTTP** `/mcp`, jeton par **variable d'environnement** | `approval_mode = "approve"` déclaré sur 10 outils (`task`, `run`, `rag`, `forge_deep_explore`, `read`, `governed_edit`, `bundle`, `hub`, `event`, `read_function_body`) | **approbation par outil**, granularité déjà présente | UNKNOWN | MESURÉ |
| **Cursor** | — | — | `mcpServers` **vide** : non branché | — | — | MESURÉ (non branché) |
| **Antigravity** | outils / sous-agents | MCP (canal `github` authentifié déclaré par l'agent) | UNKNOWN | UNKNOWN | UNKNOWN | **UNKNOWN** |
| **MCP générique** | appel d'outil | Streamable HTTP | via le même `/mcp` | UNKNOWN | UNKNOWN | générique |
| **Agent maison** | événement | HTTP / JSONL | adaptateur à écrire | — | — | conditionnel |

### Événements de hook réellement câblés côté Claude

`PreToolUse` · `PostToolUse` · `PostToolUseFailure` · `UserPromptSubmit` ·
`PreCompact` · `SessionStart` · `Stop`.

**Ni `SubagentStart`, ni `SubagentStop`, ni `TaskCreated`, ni `TaskCompleted`.**
Ce n'est pas une preuve qu'ils n'existent pas dans cette version du client : c'est
un `UNKNOWN`. Tant qu'il n'est pas levé, **le Spine ne doit pas être bâti sur ces
événements** — ce serait un garde branché sur un signal que personne n'émet, motif
déjà payé (cf. `RULES_SHARED`, « Un garde branché sur un signal que PERSONNE n'émet »).

## Deux constats à traiter, hors périmètre du Spine

1. **Asymétrie de secret entre clients.** Codex référence son jeton par
   `bearer_token_env_var` ; la configuration Gemini porte un Bearer **littéral en
   clair** dans un fichier du profil. La doctrine est explicite : authentifier un
   agent passe par un bail court, et **aucun Bearer statique ne se distribue**.
   Décision owner — la valeur n'est pas reproduite ici.
2. **Un hook déclaré dormant ne l'était pas.** `hook_gate_orchestrator.py` est
   rapporté « PRESENT mais NON câblé » par le contrôle d'intégrité côté Claude,
   alors qu'il est câblé en `AfterModel` **chez Gemini**. Le contrôle ne ment pas :
   il dit ce qu'il voit dans SON périmètre. C'est la lecture qui doit être prudente
   — « non câblé ici » n'est pas « dormant ».

## Les surfaces M2M — une seconde voie d'entrée, distincte des hooks

Un transient ne naît pas seulement d'un appel d'outil intercepté : il peut naître
d'un **message inter-agents**. Cette voie a son propre contrat, ses propres bases
et ses propres défauts — elle ne se déduit pas de la table ci-dessus.

### Le contrat existe déjà, et il est versionné

`config/m2m_intents.json` est en **v1.3.0**, porte **25 intents** et déclare des
champs requis **par canal** :

| canal M2M | champs requis |
|---|---|
| `notify` | `intent`, `pointer_ref` |
| `postal` | `intent`, `pointer_ref`, `confidence` |
| `task_assign` | `intent`, `pointer_ref` |
| `task_result` | `intent`, `status_code`, `pointer_ref` |

**Conséquence directe pour le Spine :** `nokido.transient.v1` ne doit pas être un
second schéma posé à côté. Il **étend celui-ci**. Créer un dictionnaire parallèle
reproduirait la faute que le dépôt s'interdit déjà pour ACP et A2A — « ne pas créer
un 3ᵉ protocole ». Le validateur de ce contrat vit dans `app/forge_m2m_protocol.py`
et mord réellement : il refuse les intents hors dictionnaire, signale les champs
requis manquants, et limite la prose aux seuls **champs de prose** (liste positive),
précisément pour ne pas frapper les champs de données.

### Ce que les canaux livrent vraiment — et une mesure RETIRÉE

**Le canal M2M autonome fonctionne.** Sur la fenêtre de septembre (la base actuelle
est postérieure à la bascule de l'interrupteur M2M) : **1 962 `read`, 7 196
`archived`**, activité soutenue, débats effectivement tenus entre agents.

> **Mesure retirée le 2026-09-17, le jour même où elle a été écrite.** Une première
> version de cette section annonçait « 73 % des `task.assign` et 78 % des
> `task.result` jamais lus ». **C'était un artefact**, et il a fallu que l'owner
> conteste le chiffre pour qu'il soit vérifié. Deux défauts cumulés :
>
> 1. **`status` n'est pas un capteur de lecture.** `status='read'` avec `read_at`
>    NULL : **7 036 sur 8 371, soit 84 %**. Le champ n'est pas tenu par tous les
>    consommateurs, donc `unread` ne prouve pas qu'un message n'a pas été lu.
> 2. **93 % des `unread` ne visent aucun lecteur** : 2 507 sur 2 683 sont adressés
>    à `EVENTBUS_ARCHIVE`, une destination d'**archivage**. Les `unread` réellement
>    adressés à des agents sont **176**, pas 2 683.
>
> Faute de méthode, déjà écrite dans `RULES_SHARED` : « la moyenne all-time MENT sur
> les rafales », et un dénominateur doit être inspecté avant d'être publié. Le
> corollaire vaut dans les deux sens : **un chiffre défavorable ne se rapporte pas
> plus sans vérification qu'un chiffre flatteur** — un mauvais instrument ne sert
> personne. Ici l'observateur indépendant était le témoignage de l'owner, contre une
> sonde unique.

Ce qui **reste** mesuré et vrai :

| constat | mesure |
|---|---|
| adresse à double préfixe | **24** messages vers `agt_agt_gemini`, 1 vers `agt_agt_antigravity` — perdus |
| famille `agent.*` (`delegate`, `result`, `pingpong`, `proposal`, `reflection`, `reminder`, `reply`, `review`, `update`) | **11** messages, tous `pending`, aucun drain |
| `unread` réels vers des agents | 176, dont 87 vers `agt_claude` (reçus par ailleurs via l'inbox) |

**Ce que le Spine doit en retenir**, sans exagérer le défaut : un accusé de
livraison ne vaut pas un accusé de lecture **tant que `read_at` n'est pas tenu**.
La correction est petite — horodater la lecture — et elle rendrait ce canal
mesurable. Pour un livrable, l'accusé de **dépôt relu à la clé** reste exigé : le
2026-09-17, deux dépôts annoncés étaient absents en base, et une seule phrase de
consigne exigeant la relecture a suffi à corriger un exécuteur et à en démasquer
un autre.

### Adressage : deux pièges mesurés

- **Le canal autonome et la surface interactive ne portent pas la même adresse.**
  Le guide M2M transmis par ANTIGRAVITY lui-même dit : `hub action=notify to=gemini`
  pour le canal M2M **autonome**, et `hub action=poll` à chaque début de tour pour
  dépiler sa boîte. Écrire à la surface MCP/CLI est un **autre** destinataire.
- **Le double préfixe perd les messages** : `agt_agt_gemini` a reçu 23 messages,
  `agt_agt_antigravity` 1. L'adresse correcte porte **un seul** préfixe.

### Bases concernées

L'état M2M est réparti, et l'interrupteur global compte : `forge_db_path.m2m_path()`
résout `sandbox/m2m.db` (table `agent_messages` + `locks_state`), tandis que la
grosse base porte encore l'historique antérieur à la bascule. Le blackboard vit à
part (`swarm_blackboard`), et les tâches dans `sandbox/tasks.db`. **Lire la mauvaise
base fait conclure à un silence qui n'existe pas** : une lecture des messages
antérieure à la bascule rend des échanges vieux de deux semaines et donne
l'impression que le pair ne répond plus.

### Statut par CLI sur la voie M2M

| CLI | émet en M2M | reçoit en M2M | drain vérifié |
|---|---|---|---|
| Claude | oui (mesuré) | oui (inbox + poll) | oui |
| Antigravity / AGY | oui (mesuré ce jour) | oui | **partiel** — surface interactive vue ; le service autonome n'a pas pu être confirmé |
| Gemini | oui | oui | UNKNOWN |
| Codex | déclaré au dictionnaire | UNKNOWN | UNKNOWN |
| autres destinataires historiques (`CLINE`, `ROO_PLAN`, `SIXTH`, `COPILOT`) | trace en base | UNKNOWN | UNKNOWN |

## Ce que GEN-0 établit pour la suite

- Le transport est une **dimension mesurée**, pas une hypothèse : HTTP d'abord,
  `stdio` en compatibilité.
- Après l'adaptateur, **Nokido ne doit plus savoir** si l'événement venait de HTTP,
  de `stdio`, d'un hook ou de MCP. C'est le rôle de `nokido.transient.v1`.
- La granularité par outil existe déjà chez Codex : elle donne un précédent pour
  l'admission, au lieu d'inventer une politique neuve.

## Ce qui reste `UNKNOWN`, nommément

- la réinjection d'un résultat dans l'agent appelant, pour **toutes** les surfaces ;
- la surface Antigravity en entier ;
- l'existence des événements de sous-agent côté Claude.

Aucune de ces trois cases ne doit être comblée par déduction.
