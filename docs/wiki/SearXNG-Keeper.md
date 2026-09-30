---
type: guide
title: SearXNG Keeper
status: draft
resource: repo://docs/wiki/SearXNG-Keeper.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# SearXNG Keeper

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

`tools/forge_searxng_keeper.py` — service `NokidoSearxng` (wave 5, tourne **SYSTEM**).
Wrapper superviseur d'un conteneur Docker SearXNG (`:8080`), alimente la veille.
Pattern réutilisable pour tout conteneur Docker intégré à Nokido.

> **Au 2026-09-29, le service `NokidoSearxng` est coupé** (`disabled = true` dans
> `proxy_deno/core/services.toml`) : Docker est dynamique (il s'éteint quand personne ne le
> réclame). SearXNG se réveille à la demande par la route gouvernée
> `nokido_ensure_service{service: "searxng", desired_state: "running"}` ; un `web_search`
> qui revient vide signifie d'abord « SearXNG éteint », pas « aucun résultat ».

## Cycle

1. Probe daemon Docker (`docker version`). Down → exit 2, le superviseur relance.
2. `_ensure_running()` :
   - `running` + sonde json OK → laisser
   - `running` + json KO (container nu, 403) → `rm -f` + run frais avec config
   - `exited`/`created`/`dead`/`paused` → `docker start` ; échec → `rm -f` + run frais
   - `absent` → run frais
3. Boucle foreground : probe `:8080` toutes 30 s, heartbeat ; 3 échecs → `docker restart`.
4. SIGTERM → `docker stop`.

Mode one-shot : `--recover` (applique `_ensure_running` une fois puis sort ; le flag
`--restart unless-stopped` garde le conteneur vivant — pas besoin du daemon foreground).

## Pièges résolus (2026-05-29)

- **`docker .State.Status` = `"exited"`, jamais `"stopped"`.** Tester `== "stopped"`
  rate → fall-through vers `docker run --name` → **Conflict: name already in use**.
- **API json 403.** SearXNG défaut : `limiter: on` + JSON désactivé. Il faut un
  `settings.yml` (`formats:[html,json]`, `server.limiter:false`, `secret_key`).
- **Mount dir↔fichier.** Si le fichier hôte n'existe pas avant `docker run -v`, docker
  crée un **dossier** côté hôte → bind sur un fichier conteneur échoue (OCI mount error).
  → Garantir le fichier (`_write_settings`) **avant** le run.

`settings.yml` généré sous `sandbox/searxng/` (secret persisté, jamais commité).

## Tests

`tests/test_forge_searxng_keeper.py` — branches `_ensure_running` + `-v` mount +
`_write_settings` (contenu + idempotence).
