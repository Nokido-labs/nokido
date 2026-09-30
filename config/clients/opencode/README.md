# Client `opencode` (sst/opencode) — gouvernance Nokido

opencode servi en **interface web** par le lanceur du portail :7400, branché sur le hub
souverain avec **sa propre identité**, outils natifs d'exécution et d'écriture refusés.
Décision owner du 2026-09-25 (choix A).

## Deux authentifications, deux portes

| porte | qui s'authentifie | comment |
|---|---|---|
| navigateur → opencode (`127.0.0.1:4096`) | l'owner | Basic, utilisateur `opencode`, mot de passe rangé dans **son** gestionnaire d'identification Windows (keyring, service `Nokido`, clé `OPENCODE_SERVER_PASSWORD`) |
| opencode → hub (`:8766/mcp`) | l'agent `OPENCODE` | jeton **dérivé** `FORGE_TOKEN_OPENCODE` (coffre), en-tête `X-Agent-Name: OPENCODE` |

Jamais le jeton maître `FORGE_MCP_TOKEN` : le hub lui accorde `via=master_token`, qui
conserve l'agent déclaré dans l'en-tête et son ring. Distribué à un client, il devient
un passe-partout d'identité (mesuré le 2026-09-02 sur vibe et mammouth).

## Mise en service

1. **Mot de passe de l'interface** — dans une console de l'owner (pas le `!` de Claude
   Code, dont la sortie entre dans la conversation) :

   ```
   python tools/nokido_opencode_web.py --definir-mot-de-passe
   ```

2. **Jeton de l'agent** — semé au coffre, jamais écrasé s'il existe, relu après écriture :

   ```
   LAFORGE_PYTHON tools/forge_vault_seed_agent_tokens.py --generate-missing --agents OPENCODE
   ```

   ⚠️ Le hub charge les jetons **à l'import** : il ne reconnaît `OPENCODE` qu'après son
   prochain redémarrage. D'ici là, un appel MCP d'opencode est refusé en `bad_token`.

3. **Contrôle sans rien démarrer** : `python tools/nokido_opencode_web.py --verifier`.

4. **Démarrer** depuis `/launcher` sur :7400, puis « Ouvrir ».

## Remonter en ring 2

Ring 3 **provisoire**, comme vibe et mammouth à leur arrivée. Trois preuves d'abord :

- le nombre d'outils vus côté client est celui que le RBAC réserve à `OPENCODE`, et non
  celui d'un agent par défaut — preuve d'IDENTITÉ, pas seulement de connexion ;
- une commande shell native est **refusée** ;
- une écriture de fichier native est **refusée**, l'écriture passant par `governed_edit`.

Élargir `write_paths` (au-delà de `sandbox/`, `docs/`, `tests/`) aux interfaces que
l'owner veut lui confier est une décision owner, prise après ces trois preuves.
