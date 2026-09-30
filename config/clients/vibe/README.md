# Client `vibe` (mistral-vibe) — gouvernance Nokido

Le CLI de Mistral (`vibe`, dépôt `mistralai/mistral-vibe`) branché sur le hub souverain,
avec ses outils natifs coupés. Config **versionnée ici** plutôt que dans `~/.vibe`, pour
qu'elle soit relue et vue par la CI.

## Pourquoi ce client est gouvernable

`RULES_SHARED.md` distingue les clients selon ce qui peut les contraindre : un hook natif,
une règle émanée, ou un contrôle côté hub. Antigravity n'a **pas** de hooks et tient par la
seule discipline. `vibe`, lui, expose deux mécanismes réels :

- `permission = "always" | "ask" | "never"` par outil, dans `config.toml` ;
- des hooks `pre_tool` / `post_tool` capables de **refuser** un appel (`{"decision":"deny"}`).

On emploie le premier ici. Le second reste disponible en défense en profondeur (voir plus bas).

## Lancement RECOMMANDÉ — aucun secret sur disque

```
LAFORGE_PYTHON tools/forge_cli_route.py launch vibe
```

Le routeur de CLI existant (`forge_cli_route`, déjà utilisé pour claude / gemini / cline /
copilot) pose `VIBE_HOME` **et résout les secrets depuis le coffre DPAPI au lancement** :
`MISTRAL_API_KEY` et `FORGE_MCP_TOKEN` ne vivent alors que dans la mémoire du process —
ni `.env`, ni fichier de configuration, ni registre.

C'est la réponse à la limite de vibe : `ProviderConfig.api_key_env_var` ne porte qu'un
**nom** de variable, jamais la valeur, et il n'existe aucun mécanisme de commande. La clé
doit donc venir de l'environnement — autant que ce soit l'appelant qui l'y mette, depuis
la source unique, plutôt qu'un fichier recopié qui devient une seconde vérité.

Conséquences :

- **Le `.env` de ce dossier devient inutile** — supprime-le. Il reste gitignoré au cas où
  `vibe --setup` le recrée.
- Une variable **déjà présente** dans l'environnement n'est jamais écrasée : l'appelant
  reste souverain.
- Coffre illisible ou clé absente → on n'injecte rien et le CLI le signale lui-même. Un
  message du CLI vaut mieux qu'un échec opaque dans le lanceur.

`vibe` est déclaré `(None, None, {})` dans `INGRESS` : il n'existe pas d'ingress Mistral,
donc le routeur le **reconnaît** et lui donne son environnement, mais ne route rien — le
garde `var is None` du module bascule en lancement natif.

## Installation

0. **Installer `vibe` dans un environnement ISOLÉ — jamais dans celui de Nokido.**

   ```
   "%USERPROFILE%/miniforge3/python.exe" -m venv "C:/tools/vibe-env"
   "C:/tools/vibe-env/Scripts/python.exe" -m pip install mistral-vibe
   ```

   Le binaire est alors `C:/tools/vibe-env/Scripts/vibe.exe` (+ `vibe-acp.exe` pour le
   mode Agent Client Protocol). Mesuré le 2026-07-29 : `vibe 2.23.1`, démarrage propre.

   **Pourquoi c'est une règle et pas un conseil.** Le premier essai avait installé vibe
   dans `%USERPROFILE%\miniforge3`, qui est `LAFORGE_PYTHON` — l'interpréteur de Nokido
   lui-même. Résultat : `ImportError: cannot import name 'inject' from
   'opentelemetry.propagate' (unknown location)`, et le CLI ne démarrait pas du tout.
   Cause mesurée : vibe exige `opentelemetry-api>=1.39.1` et l'a posé **par-dessus** une
   1.37.0 préexistante sans la désinstaller — six paquets `opentelemetry-*` se sont
   retrouvés en DOUBLE (`api`, `sdk`, `proto`, deux `exporter-otlp-*`,
   `semantic-conventions`), deux distributions revendiquant les mêmes fichiers. Le fichier
   `propagate/__init__.py` était pourtant intact : ce n'est pas un module manquant, c'est
   une résolution rendue incohérente par la superposition.
   Un CLI tiers ne partage pas l'environnement du système qu'il pilote ; la doc de vibe
   recommande d'ailleurs `uv tool install` en premier, c'est-à-dire un env dédié.

   **Env Nokido : nettoyé, RIEN D'AUTRE À FAIRE** (mesuré 2026-07-29). `pip uninstall -y
   mistral-vibe` a suffi — il a restauré les *fichiers* en 1.37.0. Vérifié avec
   l'interpréteur de Nokido : `propagate.inject` OK, `sdk` / `semconv` /
   `exporter.otlp.proto.http` / `instrumentation` OK, `importlib.metadata` rend `1.37.0`,
   et `tools/forge_otel_export.py` — seul consommateur — s'importe.

   **Ne PAS « réparer » les doublons de `.dist-info` restants.** Le disque porte encore
   `opentelemetry_api-1.41.1.dist-info` à côté de `1.37.0` (idem sdk, proto, les deux
   `exporter-otlp-*`, `semantic-conventions` en `0.62b1`). Ce sont des **métadonnées
   orphelines**, pas du code : la résolution rend bien la 1.37.0 et tout importe. Un
   `pip uninstall`/`install` sur `LAFORGE_PYTHON` pour du cosmétique risquerait de casser
   un système qui marche — le coût des deux erreurs n'est pas symétrique.

   **Piège de mesure à retenir** : `pip list` affichait *une seule* version par paquet
   alors que le disque en portait deux. Le registre ment, le disque dit vrai — même
   famille que `/supervisor/status` annonçant `running` pour un process mort.

1. **Pointer `VIBE_HOME` sur ce dossier** — c'est ce qui rend la config versionnée effective :

   ```
   setx VIBE_HOME "%NOKIDO_ROOT%\config\clients\vibe"
   ```

2. **Exposer le token du hub dans l'environnement** (jamais dans un fichier) :
   `FORGE_MCP_TOKEN` doit être lisible par le process qui lance `vibe`. C'est
   `auth.api_key_env` qui le NOMME ; vibe lit la variable au lancement et l'envoie en
   `Authorization: Bearer …`. Sans elle : 401, donc **aucun outil** — état voulu.
   `vibe` a aussi besoin de `MISTRAL_API_KEY` dans son propre environnement : le coffre
   DPAPI de Nokido ne le nourrit pas. Sinon il s'arrête sur
   `Missing MISTRAL_API_KEY environment variable`.

2 bis. **Neutraliser une éventuelle ancienne config utilisateur.** Si `~/.vibe/config.toml`
   existe, il est lu comme couche « user » et peut faire échouer le démarrage (voir plus
   bas). Le mettre de côté : `mv ~/.vibe/config.toml ~/.vibe/config.toml.bak`.

3. **Instructions projet** : copier ou lier `AGENTS.md` en `<dépôt>/.vibe/AGENTS.md`
   (vibe lit ce chemin, pas `VIBE_HOME`, pour les instructions de projet).

4. **Vérifier** — les trois points qui conditionnent la remontée en ring 2 :
   - demander à vibe de lancer une commande shell → doit être **refusé** ;
   - demander une écriture de fichier → doit être **refusée** (passer par `governed_edit`) ;
   - vérifier côté hub que les appels arrivent bien sous l'identité `VIBE` et non `BRIDGE`
     (`logs/` du hub, ou `blackboard_read_zone zone_name=tree_locks` après un claim).

## Le piège de format qui empêchait le démarrage

Symptôme, sans nom de champ :
`TypeError: UNION requires list operands, got list and dict`.

`mcp_servers` est déclaré `list[MCPServer]` avec une fusion **UNION** : il faut
`[[mcp_servers]]`, un TABLEAU de tables. Un `[mcp_servers.<nom>]` produit un **dict** et
casse la fusion. L'ancienne config d'avril employait cette forme (avec `type =
"streamable_http"`, l'ancien nom du champ `transport`, dont la valeur est aujourd'hui
`streamable-http`), et la migration automatique de vibe ne la convertit pas.

Attribué par bissection : quatre `VIBE_HOME` de test (vide / `[tools.*]` seuls /
`[[mcp_servers]]` seul / config complète) franchissent tous la fusion et s'arrêtent au
même endroit — donc la config de ce dossier était hors de cause, et le fautif était la
couche utilisateur.

## Vibe RÉÉCRIT son `config.toml` — ne rien y mettre de précieux

Mesuré le 2026-07-29 : au premier lancement avec `VIBE_HOME` sur ce dossier, vibe a
**réécrit `config.toml`** — tous les commentaires supprimés, `[tools.read]` normalisé en
`[tools.read_file]` (il a corrigé un nom d'outil erroné), `headers = { … }` inline converti
en section `[mcp_servers.auth.headers]`. Attribution certaine : `trusted_folders.toml` et
`vibehistory` portent le même horodatage que le lancement.

Trois conséquences :

1. **Les explications vivent DANS CE README**, pas dans `config.toml`. Ce fichier-ci n'est
   jamais réécrit par vibe ; l'autre lui appartient.
2. **Un diff git après un lancement est normal**, et même utile : il montre exactement ce
   que vibe a changé sous nos pieds. Le relire avant de committer plutôt que le subir.
3. **Aucun secret dans `config.toml`, jamais.** Le token passe par `auth.api_key_env` ;
   `vibe --setup`, lui, écrit dans `$VIBE_HOME/.env`, qui est gitignoré. Si un jour vibe
   venait à écrire une valeur sensible dans `config.toml`, le scan secret du pre-commit
   l'attraperait — mais mieux vaut ne pas dépendre d'un garde.

## Profil d'agent `laforge`

`agents/laforge.toml` est **versionné** (contrairement à `prompts/`) : un profil décide de
la `safety` et peut relâcher les permissions d'outils par `overrides` — c'est de la
configuration gouvernée. Il est actif par `default_agent = "laforge"`.

Il coupe les mêmes outils que `config.toml`, mais **par nom** (`disabled_tools`) plutôt que
par permission : deux mécanismes indépendants, et `disabled_tools` d'un profil est UNIONNÉ
avec celui de la config (`AgentProfile.apply_to_config`), jamais substitué — un profil ne
peut donc pas rouvrir en silence ce que la configuration a fermé. `safety = "neutral"`
(approbation requise), volontairement ni `accept-edits` ni `yolo`.

## Correctif annexe au bridge stdio

En cherchant à brancher vibe sans secret, on a trouvé que `tools/mcp_stdio_bridge.py`
codait `_AGENT = "BRIDGE"` en dur, alors que son propre commentaire annonçait
`LAFORGE_AGENT` depuis toujours : tout client stdio perdait son identité — donc son ring,
sa traçabilité et ses claims. La variable est désormais honorée, **défaut inchangé** (sans
elle, `BRIDGE`). vibe n'en dépend plus (il passe en HTTP), mais le défaut était réel et
concerne tout futur client stdio.

## Provider Mistral (distinct du CLI)

`tools/forge_broker_mistral.py` existait déjà (`agt_mistral` : mistral-large, mistral-small,
codestral, open-mistral-nemo), clé lue au coffre via `forge_secrets`. Mesuré le 2026-07-29 :
l'API répond **HTTP 200** sur `mistral-small-latest` et `open-mistral-nemo`. Le CLI et le
provider sont deux choses séparées — gouverner l'un ne configure pas l'autre.

## Défense en profondeur (non posée)

Un `hooks.toml` avec un `pre_tool` refusant `bash`/`write_file` doublerait la coupure par
`permission`. Non livré : le protocole d'entrée/sortie des hooks (format exact du JSON reçu
sur stdin) n'a pas été vérifié sur la machine, et un guard écrit sur un protocole supposé
serait pire qu'absent — il rassurerait sans protéger.
