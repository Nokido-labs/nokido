# ACP ingress — exposer Nokido comme agent ACP

`tools/forge_acp_server.py` expose le hub Nokido comme **agent** Agent Client
Protocol (ACP, Zed) sur stdio (NDJSON JSON-RPC). Pendant inverse de
`tools/forge_acp_client.py` (qui PILOTE des agents ACP externes). N'importe quel
**client** ACP (Zed, ou le `forge_acp_client` en loopback) s'y connecte :
`initialize` -> `session/new` -> `session/prompt`, le tour est répondu par le
brain Nokido.

## Pourquoi (stabilisation, veille ACP 2026-06-21)
- **#1 streaming** : `session/prompt` émet des notifications `session/update`
  `agent_message_chunk` -> fin de l'ingress qui aplatissait en text-only/no-stream.
- **#2 cancel** : `session/cancel` + timeout borné -> le tour renvoie TOUJOURS un
  `StopReason` (jamais de wedge du caller).
- **#3 permission** : `session/request_permission` in-band -> garde portée par le
  protocole, donc effective MÊME pour les clients sans hooks.
- **#4 capabilities** : `initialize` négocie `protocolVersion` + capacités.

## Modèle d'exécution
Un agent ACP est **spawné par le client** en sous-processus stdio (pas un daemon
qui écoute un port). Donc pas une entrée `services.toml`. Le transport *remote*
(HTTP/WS) du spec ACP est WIP — un daemon-port serait un follow-up.

## Lancement
```
~/miniforge3/python.exe \
  "~/Script python IA/Nokido/tools/forge_acp_server.py" --brain hub
```
- `--brain hub` : route chaque tour via le pipeline gouverné `forge_agent_proxy.ask`
  (firewall pre/post + thread + tracked usage). Provider par défaut `ollama` ;
  override `ACP_BRAIN_PROVIDER` (ex `router_local`, `router_cascade`, `groq`).
- défaut (sans `--brain hub`) : `EchoBrain` (no-hub, sert le selftest).
- le serveur bootstrap `app/` dans `sys.path` lui-même (pas besoin de PYTHONPATH).

## Brancher Zed (external agent)
Dans le `settings.json` de Zed :
```json
{
  "agent_servers": {
    "Nokido": {
      "command": "~/miniforge3/python.exe",
      "args": [
        "~/Script python IA/Nokido/tools/forge_acp_server.py",
        "--brain", "hub"
      ]
    }
  }
}
```
Tout éditeur/agent ACP-conforme (Zed et la communauté `agentclientprotocol`)
devient ainsi un client natif de Nokido.

## Test loopback (sans Zed)
Le `forge_acp_client` existant pilote ce serveur :
`C:/tmp/acp_loopback_test.py` (echo + permission) — exécuter via `run_job`.

## Brains
- `--brain hub` : `forge_agent_proxy.ask` (réponse post_flight-scannée) chunkée par phrase.
- `--brain stream` : idem gouverné mais émission **mot-par-mot** (delivery progressif).
- défaut : `EchoBrain` (no-hub).

## Transport remote WebSocket (expérimental)
```
~/miniforge3/python.exe \
  "~/Script python IA/Nokido/tools/forge_acp_server.py" --ws
```
- endpoint `ws://127.0.0.1:7782/acp` (frames NDJSON ; `ACP_WS_HOST`/`ACP_WS_PORT`).
  8770 est réservé par `NokidoExegolMCP` -> ACP sur 7782.
- une `ACPServer` par connexion ; writes des threads-de-tour marshalés sur l'event
  loop via `run_coroutine_threadsafe`. Testé : initialize→session→prompt→chunks→end_turn.
- **supervisé** : entrée `NokidoAcpWs` dans `proxy_deno/core/services.toml`
  (disabled/on-demand, comme Exegol/SearXNG). Activation = reload superviseur
  (restart coordonné), puis wake `tools/forge_supervisor_ctl.py ensure NokidoAcpWs`.
  Brain via `ACP_BRAIN` (echo défaut | hub | stream).

## tool_call lifecycle (#2)
`session/update` `tool_call`(pending) → `session/request_permission` →
`tool_call_update`(in_progress→completed/cancelled). Helpers `TurnContext.tool_call()`
/ `tool_update()` ; un vrai brain exécute l'action via une route gouvernée (run/edit)
entre in_progress et completed. Démo : EchoBrain sur prompt `!<action>`.

## CONTRAINTE : pas de vraie SSE token-par-token
Le streaming token natif (`stream=True` vers le client) est **interdit par la
gouvernance** : la doctrine firewall `post_flight` scanne la réponse COMPLÈTE
(DLP/canary/SSRF) avant egress — un flux token bypasse ce scan. Le tripwire
`governed_edit` bloque d'ailleurs le flag de streaming. Donc le « streaming » ACP
ici = chunker une réponse déjà scannée (ce que fait aussi l'ingress anthropic/gemini
existant). Vraie SSE exigerait un `post_flight` incrémental par-delta = changement
d'architecture firewall, pas un tweak d'adaptateur.

## Follow-ups restants
- `post_flight` incrémental (débloquerait la vraie SSE dans les clous) ;
- brain agentique multi-tours réel (boucle tool-call LLM, pas la démo Echo) ;
- brancher `--ws` en service supervisor si le spec remote se stabilise.
