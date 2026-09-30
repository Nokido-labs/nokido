# Etat d'authentification des routes du hub — 2026-09-22

Mesure sur `tools/nokido_hub.py`, **83 routes**. Produit par
`tools/forge_route_authz_audit.py` (statique) et **croise avec des sondes
runtime** sur le hub reellement charge (pid demarre 04:44).

> **Ce document distingue trois choses que le mot « protege » confond :**
> une garde **declaree** · une garde qui **mord depuis ici** · une route
> **nue**. Compter les trois ensemble surestime la protection.

---

## 1. Ce qui REFUSE vraiment — 25 routes

Une seule forme de garde rend un refus depuis le loopback : **`_admin_tok_ok`**.

Sondes runtime du jour, sans porteur, toutes **401** :

| route | code |
|---|---|
| `GET /api/ring_buffer/stats` | **401** |
| `GET /admin/heap` | **401** |
| `GET /admin/job/{job_id}` | **401** |
| `GET /api/services/logs/{name}` | **401** |

Les 25 routes portant cette garde : `/admin/heap`, `/admin/ingest_repo`,
`/admin/job/{job_id}`, `/admin/job/{job_id}/stop`, `/admin/run_job`,
`/api/audit/recent`, `/api/audit/trace/{trace_id}`, `/api/hormones/release`,
`/api/maintenance/gc`, `/api/mcp/toggle`, `/api/ring_buffer/stats`,
`/api/sandbox/spawn`, `/api/services/boot_all`, `/api/services/logs/{name}`,
`/api/services/restart/{name}`, `/api/services/shutdown_all`,
`/api/services/start/{name}`, `/api/services/stop/{name}`, `/api/swarm/run`,
`/ingest/bulk`, `/ingest/qualify`, `/ingest/url`, `/mcp/batch`, `/mpc/plan`,
`/orchestrate/loop`.

Depuis le 2026-09-21 ces refus sont **journalises avec leur cause**
(`admin_tok_refuse:<cause>`, quatre causes distinctes), verifie en runtime :
`by_tool["_admin_tok_ok"]` et `by_decision["DENY"]` bougent a chaque refus.

## 2. Gardes DECLAREES qui ne mordent pas depuis le loopback — 10 routes

**`HUB_TOKEN` — 5 routes.** La condition exempte `127.0.0.1` / `::1` /
`localhost` / `""`. Sondes du jour :

| route | code |
|---|---|
| `GET /forge/debate` | **200** |
| `GET /forge/recon` | **200** |

Les trois autres : `POST /api/ctf/run`, `POST /api/recon/run`,
`GET /forge/graph`. Leurs POST **ne sont pas sondes** : un appel accepte
declencherait un fan-out LLM. Classe `NON_MESURABLE_SANS_EFFET_DE_BORD` —
et la borne est structurelle, aucune adresse non-loopback n'atteint le hub
depuis cette machine (mesure du 2026-09-21).

**`_resolve_ring` — 5 routes.** Ce point de controle repond « qui es-tu »,
pas « as-tu le droit » : il resout une identite et un ring, il ne refuse
qu'aux seuils extremes.

| route | code | seuil reel |
|---|---|---|
| `GET /forge/rings` | **200** | aucun refus |
| `GET /mcp` | — | `ring < 0` → 401 |
| `POST /admin/restart` | — | `ring < 0 or ring > 1` → 403 |
| `POST /api/rings/set`, `POST /mcp` | — | non sonde (mutant) |

`POST /admin/restart` est la seule de ce groupe a porter une **vraie borne
d'autorite**. Mesure du journal : sur 318 643 observations, `_resolve_ring`
produit 93,7 % du total et **aucune decision** — le ring est resolu partout,
consomme pour decider a de tres rares endroits.

**`_AGENT_TOKENS` — 1 route** : `POST /api/login`. Non sondee (POST).

## 3. Routes NUES — 47

### ADMIN sans garde — 2, et elles repondent 200 anonymement

| route | code mesure |
|---|---|
| `GET /api/sandbox/runtimes` | **200** |
| `GET /api/services/list` | **200** |

### MUTANTE sans garde — 8

`POST /api/ingest` · `POST /api/mcp/flags` · `POST /api/push` ·
`POST /api/rag/tokenize` · `GET /api/resource/should_spawn` ·
`POST /api/watch/create` · `POST /nervous_system/emit` · `POST /ui/generate`

`/api/mcp/flags` est nue **volontairement** : une garde y a ete posee puis
**retiree** le 2026-09-21 apres mesure — son appelant est `resetFlags()`, une
fonction JS **inline dans `nokido_hub.py`**, qui n'envoie aucun porteur. La
garde cassait un bouton de l'interface.

### LECTURE sans garde — 37

Quatre sont **publiques par destination** : `/health`, `/health/liveness`,
`/health/readiness`, `/static/{fname}`, plus `/.well-known/{wk_path:path}`.

Les **33 autres exposent de l'etat interne sans porteur**. Sonde du jour :
`GET /debug/stacks` → **200**. Y figurent notamment `/api/agents`,
`/api/organs`, `/api/graph/proprioception`, `/api/rag/stats`,
`/api/hormones/*`, `/inbox/{agent_id}`, `/forge/*`.

---

## 4. Le compte honnete

| categorie | routes | statut |
|---|---|---|
| refusent depuis le loopback (`_admin_tok_ok`) | **25** | **PROUVE** sur 4 sondes |
| garde declaree, **200** depuis le loopback | **10** | PROUVE sur 3 sondes, deduit pour 7 |
| nues | **47** | PROUVE sur 3 sondes, statique pour 44 |
| non mesurees (POST a effet) | — | `NON_MESURABLE_SANS_EFFET_DE_BORD` |

**25 routes sur 83 refusent un appel anonyme depuis cette machine.** Les 58
autres repondent, soit parce qu'elles n'ont aucune garde, soit parce que leur
garde exempte le loopback.

> **`LOCAL_ONLY` n'est pas `TRUSTED`** (directive owner, 2026-09-18). Le compte
> sandbox atteint le loopback, et cela n'authentifie personne.

## 5. Les 8 routes MUTANTE nues — matrice de decision

Mesure du 2026-09-22. **EFFET** lu dans le handler, **APPELANTS** par
`forge_route_authz_audit._appelants` (corrige le meme jour pour voir le JS
inline), **CREDENTIAL** mesure au site d'appel.

| route | effet REEL | appelants | credential | plus petit durcissement |
|---|---|---|---|---|
| `/api/ingest` | base RAG + journal | `forge_clawhub_bridge` (**anonyme**), `forge_dsl` (porteur), `sidebar.html` | **MIXTE** | faire porter un credential a `clawhub_bridge`, **puis** garder |
| `/api/mcp/flags` | ecrit fichier + reseau | **JS inline du hub** (`resetFlags`) | **ANONYME** | corriger l'appelant d'abord — une garde ici a deja casse l'UI le 21/09 |
| `/api/push` | **AUCUN** — stub qui rend `{"ok": true}` | `_batch11_send.py` | anonyme | **aucun** : reclasser, la route ne mute rien |
| `/api/rag/tokenize` | **AUCUN** — fonction pure (tiktoken, borne 50 000 car.) | `rag_dashboard.html`, `wired_routes.py` | **UNKNOWN** | reclasser en LECTURE ; le cout est CPU, pas une mutation |
| `/api/resource/should_spawn` | lecture d'etat de spawn | `proxy_deno/core/supervisor.ts` | **porteur present** | **meilleur candidat** — l'appelant porte deja un credential |
| `/api/watch/create` | **mutation** (`forge_watch_agent.create_job`) | `ci_local`, `watch_agent_worker`, **JS inline du hub** | **ANONYME** (JS) | corriger l'appelant d'abord, comme `/api/mcp/flags` |
| `/nervous_system/emit` | forward vers Deno `:8000/event` | `_batch10_send`, `_batch11_send` | **ANONYME** (les deux) | faire porter un credential aux emetteurs, **puis** garder |
| `/ui/generate` | ecrit fichier + appel LLM | `web_hub/app.py`, `web_hub/ui_generate.py` | **ANONYME** (les deux) | l'interface possede `_hub_token()` et ne s'en sert pas ici — le cabler, puis garder |

**Deux routes ne meritent aucun durcissement** : `/api/push` ne mute rien et
`/api/rag/tokenize` est une fonction pure. Les classer MUTANTE venait de leur
methode POST, pas de leur effet.

    METHODE != EFFET

**Cinq routes sont bloquees par leur appelant**, pas par une politique
manquante : poser la garde avant de donner un credential a l'appelant
casserait le consommateur. L'ordre est donc : *appelant d'abord, garde
ensuite*.

**Une seule est prete** : `/api/resource/should_spawn`, dont l'appelant
(`supervisor.ts`) porte deja un porteur. C'est aussi un **controle negatif de
la campagne** — son 200 anonyme sert de temoin — donc la garder demande de
choisir un autre temoin d'abord.

## 5.bis Onze routes sont appelees par le JS inline du hub

Rendu visible par la correction de `_appelants` (2026-09-22). Neuf n'ont
**aucune garde** :

| classe | routes |
|---|---|
| MUTANTE nues | `/api/mcp/flags`, `/api/watch/create` |
| LECTURE nues | `/api/mcp/servers`, `/api/network/history`, `/api/network/stream`, `/api/organs`, `/api/watch/jobs`, `/api/watch/stream`, `/health` |
| gardees | `/mcp` (GET et POST, `_resolve_ring`) |

Leur nudite n'est pas un oubli : **c'est la contrepartie d'un consommateur qui
n'envoie aucun porteur**. Jusqu'a ce correctif, l'audit les declarait « aucun
appelant trouve » — et une garde posee sur ce verdict a deja casse un bouton
de l'interface le 2026-09-21.

## 5.ter Les 2 routes ADMIN nues — instruites

### `/api/sandbox/runtimes` — rester nue, et c'est documente

Huit lignes. Rend `list_allowed_runtimes()` : la **liste blanche** des runtimes
autorises. Son docstring porte la decision : *« GET liste runtimes whitelistes
(pas d'auth, read-only) »*.

| propriete | valeur |
|---|---|
| appelants (audit corrige, JS inline inclus) | **AUCUN** |
| expose | des noms de runtimes autorises |
| effet | aucun |
| pourquoi ADMIN | prefixe `/api/sandbox/`, **decide**, parce que `/api/sandbox/spawn` y vit |

**Correction d'une affirmation que j'ai faite trop vite** : j'avais ecrit que sa
classe ADMIN etait « un artefact de l'heuristique sur le mot sandbox ». C'est
FAUX -- la regle est `chemin.startswith(prefixe)` sur une table EXPLICITE. La
classe est juste ; c'est la ROUTE qui est une exception assumee dans un espace
administratif.

**Decision : nue, justifiee.** Connaitre la liste blanche des runtimes ne donne
aucun pouvoir ; c'est meme ce qu'un appelant doit lire avant de demander un
spawn -- lequel est garde (`/api/sandbox/spawn`, `_admin_tok_ok`).

Reserve : « aucun appelant » reste **UNKNOWN**, pas « morte ». Un client hors
depot n'apparait dans aucun scan.

### `/api/services/list` — bloquee par son appelant, et CONFUSED DEPUTY

Trois lignes : `_sup_call("GET", "/supervisor/status")`. Un **relais**.

| propriete | valeur |
|---|---|
| appelant REEL | `app/laforge_tui/laforge_tui.py:111` — **ANONYME** |
| mentions sans verbe d'appel | `agent_sre_observabilit/agent_core.py`, `forge_jwt_issue.py` → **UNKNOWN**, pas des appels |
| expose (mesure sur 20 984 o) | **59 services · 91 pid · 24 port · 4 chemins** |
| n'expose pas | **0 jeton, 0 commande, 0 compte** — verifie par comptage |
| effet | lecture seule |

**J'AI D'ABORD CONCLU A UN CONFUSED DEPUTY. C'ETAIT FAUX, ET LA MESURE L'A DIT.**

`_sup_call_sync` porte bien un credential vers le superviseur :

    _sup_tok = LAFORGE_SUPERVISOR_TOKEN or FORGE_MCP_TOKEN or ""
    if _sup_tok: headers["Authorization"] = f"Bearer {_sup_tok}"

J'en ai deduit que le hub pretait son autorite a un appelant anonyme. La
contre-epreuve qui manquait -- **le superviseur exige-t-il seulement ce
jeton ?** -- refute la deduction :

| sonde (GET, sans porteur) | code |
|---|---|
| `:8765/supervisor/status` | **200** (31 153 o) |
| `:8765/supervisor/circadian/status` | **200** |
| `:8765/supervisor/zzz_inexistant` | **401** |

Le superviseur applique une **liste BLANCHE** (`supervisor.ts` L2150-2153) :
quatre GET nommes sont publics, tout le reste de `/supervisor/` passe par
`_supervisor_auth_ok`, et les non-GET ont un filtre supplementaire. Le 401 sur
un chemin hors liste le PROUVE.

    LE HUB NE PRETE RIEN : il relaie une route PUBLIQUE PAR DECISION,
    et l'appelant anonyme obtiendrait plus en interrogeant :8765 directement.

**Consequence pratique : garder `/api/services/list` ne protegerait RIEN.**
Ce serait une garde cosmetique, devant une porte voisine ouverte par choix --
*un garde ne vaut que par le nombre de portes qu'il tient*.

**Verification incidente, et c'est la vraie bonne nouvelle** : les CINQ autres
routes qui appellent `_sup_call` (`boot_all`, `restart/{name}`, `shutdown_all`,
`start/{name}`, `stop/{name}`) sont gardees `_admin_tok_ok` cote hub ET
couvertes par `_supervisor_auth_ok` cote superviseur. L'asymetrie est donc
voulue : **mutations gardees des deux cotes, lecture publique des deux cotes.**

**Decision : nue, et coherente.** Si l'on veut reduire l'exposition, le geste
utile n'est pas cote hub mais cote superviseur -- retirer `/supervisor/status`
de la liste blanche, ou borner ce qu'il rend (91 pid et 24 port relevent de la
reconnaissance, pas d'un affichage d'etat). C'est une decision d'OWNER sur une
surface tierce, et elle est notee ici sans etre prise.

## 5.quater Limite de l'instrument, a ne pas oublier en lisant ce document

Les classes de l'audit sont **syntaxiques** :

    ADMIN    = prefixe de chemin  ("/admin/", "/api/services/", "/api/sandbox/", ...)
    MUTANTE  = nom du handler/chemin ("push", "create", "emit", "set", ...)
               OU methode POST/PUT/DELETE/PATCH

    METHODE != EFFET, et NOM != EFFET

Mesure du 2026-09-22 : `/api/push` est un **stub** qui rend `{"ok": true}` sans
rien ecrire, et `/api/rag/tokenize` est une **fonction pure**. Toutes deux sont
classees MUTANTE -- l'une par son nom, l'autre par sa methode. Lire la classe
comme un verdict d'effet surestime le travail restant.

## 5.quinquies Les 37 lectures nues — et la question qui les gouverne toutes

### « Interne » est vrai par CONFINEMENT RESEAU, pas par politique de route

Mesure du 2026-09-22, reprise de celle du 21/09 : **12 adresses locales
non-loopback, 0 joignable sur `:8766`**. Le hub ne repond qu'en loopback.

C'est la reponse a la question posee : aucune de ces 37 routes n'est « interne »
par decision. Elles le sont parce qu'un CONFINEMENT tient.

    LOCAL_ONLY != TRUSTED (directive owner, 2026-09-18)
    et un confinement n'est PAS une politique de route

Consequence a garder en tete pour toute decision future : si le confinement
tombe -- binding `0.0.0.0`, reverse proxy, port forward -- **46 routes
deviennent publiques d'un seul coup**, sans qu'aucune ligne de code ait change.

### Mesure runtime, sans jeton

| categorie | nombre |
|---|---|
| routes sondees (GET, sans parametre) | **43 / 83** |
| NON sondees (POST/PUT/DELETE ou chemin parametre) | **40** — `NON_MESURABLE_SANS_EFFET_DE_BORD`, assume |
| **200 sans jeton** | **33** |
| refus (401) | dont `/mcp` |
| redirections (302) | 3 — `/forge/postal`, `/forge/rag`, `/forge/swarm` |
| indeterminees | 2 — `/api/rag/stream` (400), `/health/readiness` (503) |

**Ouvertes ET sensibles : 3**, et toutes trois sont deja instruites plus haut --
`/api/resource/should_spawn`, `/api/sandbox/runtimes`, `/api/services/list`.

Les 30 autres 200 sont des LECTURES. Un 200 en lecture **n'est pas une faille
en soi** : il le devient s'il expose de l'information operationnelle. C'est une
decision route par route, pas une regle.

### La route la plus grave n'a PAS pu etre sondee

`GET /inbox/{agent_id}` est **parametree**, donc hors du probe (on n'invente pas
de valeur). Sa lecture de code tranche :

    frame = await _INBOX.pop(agent_id, timeout=25.0)

**`pop` RETIRE le message de la file.** Ce n'est pas une lecture : c'est une
CONSOMMATION DESTRUCTIVE. Un appelant qui connait un `agent_id` peut donc
intercepter les messages destines a cet agent -- qui ne les recevra jamais.

    CLASSEE LECTURE, C'EST UNE MUTATION

Elle est classee LECTURE parce que la methode est GET et que le nom ne contient
aucun verbe de `MUTANT`. C'est la limite de la classification syntaxique,
mesuree une troisieme fois.

**Non corrige ici** : une garde casserait les daemons qui depilent leur inbox
(`forge_message_frame`, `dispatch_migration_tasks`), et le remede juste n'est
pas une garde d'origine mais une **preuve que l'appelant EST l'agent nomme** --
c'est une decision d'autorite. Consigne pour ne pas se perdre.

### Deux correctifs de la session, prouves par l'instrument lui-meme

| mesure | avant | apres |
|---|---|---|
| routes avec garde detectee | 36 | **37** (borne loopback de `/debug/stacks`) |
| routes sans garde | 47 | **46** |
| routes sans appelant trouve | 12 | **9** (3 ont retrouve leur appelant JS inline) |
| appelant de `/api/mcp/flags` | « AUCUN » | **`tools/nokido_hub.py`** |

## 5.sexies Les 10 routes qui acceptent le loopback — classees

| route | condition REELLE | classe |
|---|---|---|
| `POST /api/ctf/run` | `valid = tok in {...HUB_TOKEN}` ; si `not valid` **et** hors loopback → 401 | **A** — preuve d'origine seule, depuis ici |
| `POST /api/recon/run` | idem | **A** |
| `GET /forge/rings` | `client.host not in (locaux)` → 403 | **A** — borne d'origine explicite |
| `POST /api/rings/set` | `client.host not in (locaux)` → 403, puis ring de l'appelant | **A + B** |
| `POST /admin/restart` | `ring < 0 or ring > 1` → **403** | **B** — veritable autorite, pas une origine |
| `GET /mcp` | `ring < 0` → 401 | **B**, seuil tres bas |
| `POST /mcp` | `Origin` non autorise → 403, `ring < 0` → 401, puis `qualify_session` | **A + B** |
| `GET /forge/debate` | **aucune** — injecte le porteur dans la page | **D** + **EMISSION** |
| `GET /forge/graph` | **aucune** | **D** + **EMISSION** |
| `GET /forge/recon` | **aucune** | **D** + **EMISSION** |

**Aucune route de classe C** n'a ete identifiee : les exemptions rencontrees
sont documentees et assumees, pas des restes de compatibilite.

### Les trois routes de classe D distribuent un porteur — DECISION OWNER

    tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""
    html = html.replace("__LAFORGE_BEARER__", tok)

Mesure du 2026-09-22, **sans jamais lire la valeur** : les trois rendent 200
sans jeton ; sur la page servie, le placeholder a disparu et il reste une
chaine de 64 caracteres. Dans le template, le placeholder vit APRES `</html>`.

Le fichier temporaire de la mesure a ete supprime, absence verifiee.

**Pourquoi ce n'est pas corrige ici** : le porteur est injecte pour que le JS
de la page puisse appeler le hub. Le retirer casse les trois interfaces ;
garder la page derriere une authentification change leur mode d'acces (on
accede a ces pages au navigateur, precisement sans porteur).

**Les trois options, avec leur cout** :
1. garder la page (`_admin_tok_ok`) — l'acces navigateur direct cesse ;
2. servir un jeton de PORTEE REDUITE, a duree courte, au lieu du maitre ou du
   jeton `CLAUDE` — le mecanisme existe (`login_agent`, bail 30 min) ;
3. laisser en l'etat et l'ecrire ici — le confinement loopback tient
   aujourd'hui (0/12 adresses joignables), mais **LOCAL_ONLY != TRUSTED**.

L'option 2 est la seule qui garde la fonction sans distribuer une autorite
durable. Elle n'est pas prise ici.

## 5.septies Classer l'exposition — avec le vocabulaire DU CORPS, pas le mien

`config/share_policy.json` definit deja quatre classes de donnees. On les
reprend telles quelles : inventer un vocabulaire parallele (« interne »,
« diagnostique », « sensible ») aurait cree une seconde verite a maintenir.

| classe | definition (citee) |
|---|---|
| `PUBLIC` | « deja publique ou publiable en l'etat » |
| `INTERNAL` | « interne au systeme, non secrete : code Nokido, mesures, journaux non sensibles » |
| `CONFIDENTIAL` | « sensible : **configuration, topologie**, contenu d'enquete, memoire owner » |
| `SECRET` | « secrets, cles, **jetons**, certificats prives, journal DPAPI. **Ne sort JAMAIS** » |

Deux invariants de ce fichier gouvernent la suite :

    UNKNOWN = REFUSE. Classe absente, politique absente : on refuse et on NOMME
    ce qu'on ne savait pas. Ne pas savoir n'est pas une autorisation.

### Ce qui est MESURE

| route | ce qui a ete mesure | classe |
|---|---|---|
| `/forge/debate`, `/forge/graph`, `/forge/recon` | un porteur injecte dans la page servie, 200 sans jeton | **`SECRET`** |
| `/api/services/list` | 59 services, 91 pid, 24 port, 4 chemins — 0 jeton | **`CONFIDENTIAL`** (topologie) |
| `/debug/stacks` | piles asyncio + threads, chemins de code | **`CONFIDENTIAL`** |
| `/api/sandbox/runtimes` | liste blanche de runtimes autorises | `INTERNAL` |
| `/health`, `/health/liveness`, `/health/readiness` | statut de service | `PUBLIC` |
| `/static/{fname}`, `/.well-known/{wk_path}` | ressources servies, metadonnees de decouverte | `PUBLIC` |

### Mesure d'exposition, 43 routes sondees

`forge_route_authz_audit --exposition` classe ce que chaque reponse revele.
Il ne rend que des COMPTEURS et une raison : aucune valeur n'est lue, rendue
ni ecrite sur disque.

| classe | n | routes |
|---|---|---|
| **`SECRET`** | **3** | `/forge/debate`, `/forge/graph`, `/forge/recon` |
| **`CONFIDENTIAL`** | **5** | `/api/mcp/servers` (**commande + chemin**), `/api/services/list` (pid, port, chemin), `/api/resource/state` (pid), `/api/network/history` (chemin), `/debug/stacks` (chemin) |
| `INTERNAL` | 25 | dont `/api/watch/jobs` et `/inbox/status` (identites d'agents) |
| `PUBLIC` | **0** | aucune : le caractere publiable est une DECISION, pas un defaut |
| `NON_MESUREE` | **10** | la route a refuse ou redirige — voir ci-dessous |
| non sondees | 40 | POST ou chemin parametre |

**Decouverte de ce passage** : `/api/mcp/servers` expose **les commandes** des
serveurs MCP configures. Elle etait classee LECTURE nue, et elle est appelee
par le JS inline du hub.

### UN REFUS N'EST PAS UNE ABSENCE D'EXPOSITION

Premier passage de l'instrument : `/admin/heap`, `/api/audit/recent` et
`/api/ring_buffer/stats` ressortaient `INTERNAL — aucun marqueur sensible
detecte`. Ce sont trois routes **GARDEES** : elles rendent 401. L'instrument
classait le corps de leur refus, donc les rangeait du cote rassurant.

    elles n'ont rien montre parce qu'elles ont REFUSE,
    et ce qu'elles exposeraient reste INCONNU

Le statut se lit desormais AVANT le corps. Effet mesure : `INTERNAL` passe de
**31 a 25**, et dix routes rejoignent `NON_MESUREE` (quatre 401, trois 302, un
400, un 503). **Dix routes retirees du cote rassurant** par une seule
distinction.

### LA CONCLUSION QUI NE DEPEND PLUS D'UN JUGEMENT

Le corps ecrit que la classe `SECRET` **ne sort jamais**. Trois routes servent
un jeton a un appelant anonyme. Ce n'est donc pas « une fuite selon moi » :

    c'est un INVARIANT ECRIT DE NOKIDO que trois routes contredisent

La politique existe, elle est configuree, elle est lue par
`app/forge_share_policy.py` -- et elle gouverne l'egress vers les providers,
pas les reponses HTTP locales. **Aucun garde ne l'applique a une route.**
C'est le meme motif que la serrure du 2026-09-21 : la regle etait ecrite, et
aucune porte ne la consultait.

## 6. Ce que ce document ne dit pas

- Il ne classe **aucune route comme sure**. Une route sans garde n'est pas
  forcement un defaut : `/health` doit repondre. Le travail restant est de
  **decider** route par route, pas de tout fermer.
- Les POST a effet ne sont pas sondes, **volontairement**. Un « vert » obtenu
  en declenchant un fan-out ou une ecriture ne vaut pas la mesure.
- L'audit statique est **confirme** sur les 8 routes sondees (4 refus, 4 acces).
  Pour les 75 autres il reste un audit **statique**, et son accord avec le
  runtime est etabli sur un echantillon, pas sur la population.
