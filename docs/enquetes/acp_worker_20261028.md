# Worker ACP : authentification des jobs par EdDSA (2026-10-28)

## Reprise de session ACP après la mort de l'agent (2026-10-28, ajout)

| Affirmation | Preuve | État |
|---|---|---|
| `claude-agent-acp` 0.99.0 sort rc=1 dès qu'aucun tour n'est actif ; le worker ouvrait et envoyait en jobs séparés | Mesure owner (console, `forge_acp_client.py --raw`), journal « [fin] flux stdout de l'agent ferme, rc=1 » | Mesuré par l'owner, non rejoué ici |
| `envoyer` relance l'agent (même cwd), appelle `session/load` (si `agentCapabilities.loadSession`) sinon `session/resume` (si `sessionCapabilities.resume`), puis envoie ; « reprise » journalisée | RED : 6 échecs (`RuntimeError: agent ACP mort ... rc=1`, `TypeError prompt_initial`). GREEN : `tests/nr/test_acp_reprise_session_nr.py` 6 passed ; 265 passed / 4 skipped sur `-k acp` | Fait |
| Échec de reprise = erreur dite (rc + stderr), jamais un faux succès | `test_reprise_impossible_est_une_erreur_dite...` ; journal `reprise_echec` | Fait |
| Mode : seul `MODES_SURS` est rejoué à la reprise ; le worker refuse toujours un mode non sûr | `test_aucun_mode_non_sur_a_la_reprise`, `test_le_worker_ouvrir_accepte_prompt...` (refus `bypassPermissions`) | Fait |
| `ouvrir(prompt_initial=...)` envoie le prompt aussitôt après `session/new` ; op worker `ouvrir` accepte `prompt` -> `{session, reponse}` | `test_ouvrir_avec_prompt_initial...`, `test_le_worker_ouvrir_accepte_prompt...` | Fait |
| Limite : si l'agent meurt PENDANT un tour, le prompt n'est pas rejoué (risque de double exécution) ; seule une mort détectée avant l'envoi ou à l'écriture déclenche la reprise | Code `ACPRouter.envoyer` | Choix assumé |
| Vrai agent : reprise réelle non rejouée ici (NR avec faux agent seulement, aucun état vivant) | — | À confirmer en recette owner |

### Profil allégé : option trouvée ou NON

Source lue : `%APPDATA%\npm\node_modules\@agentclientprotocol\claude-agent-acp\dist\acp-agent.d.ts` (0.99.0).

- **Mécanisme trouvé** : `NewSessionMeta` (l. ~895-913) accepte `_meta.claudeCode.options: Options`, « options forwarded to Claude Code when starting a new session » (le type `Options` vient de `@anthropic-ai/claude-agent-sdk` 0.3.312). `computeSessionFingerprint` cite aussi `systemPrompt` et `_meta` comme paramètres de `NewSessionRequest`.
- **Non vérifié** : les champs précis de `Options` (`settingSources`, `appendSystemPrompt`...) n'ont pas été lus dans les types du SDK (lecture/recherche dans `node_modules` du SDK non effectuée faute d'outil de recherche). Aucun gain de tokens n'a été mesuré (référence : tour « BONJOUR » = 44 138 tokens, 0,22 $).
- **Décision** : RIEN d'implémenté pour le profil allégé : passer des options non lues serait inventer. Prochaine étape : lire `@anthropic-ai/claude-agent-sdk/sdk.d.ts` (type `Options`), puis mesurer avec `forge_acp_client.py --raw` avant d'ajouter `_meta.claudeCode.options` à `session/new`. **État : NON implémenté.**

## Constat
La clé HMAC partagée `FORGE_ACP_JOB_KEY` ne pouvait être lue à la fois par le hub (SYSTEM) et le worker (compte OWNER) :
le guichet tait les noms réservés hors SYSTEM, et le coffre machine est lisible par les bacs à sable.

## Décision (owner) : signature asymétrique, aucun secret partagé
- **Hub** (`forge_acp_hub.deposer`) : le job est un JWS compact (RFC 7515), `alg=EdDSA` (RFC 8037), en-tête `{alg, kid}`,
  charge utile canonique `{id, op, params, ts, nonce}`. Clé privée = celle, existante, des JWT du hub
  (`forge_auth_jwt._cle_ed25519`, lue par le hub sous SYSTEM). Aucune nouvelle clé, aucune clé écrite ni affichée.
  Codage base64url = `forge_auth_jwt._b64url_*` (repli identique si l'espace de noms est absent).
- **Worker** : vérifie avec la clé PUBLIQUE épinglée `{kid, x}` lue au coffre PERSONNEL du compte courant
  (keyring WCM, `forge_env_crypt._keyring_get`, nom `FORGE_ACP_JOB_PUB`). Aucun appel au guichet de secrets.
  Refus : kid inconnu, alg ≠ EdDSA (`none`, `HS*` inclus : l'alg n'est jamais un choix de l'émetteur), signature fausse,
  âge > 120 s, nonce déjà vu (registre persisté, survit au redémarrage), id ≠ nom de fichier. Sans épingle : tout refusé.
- **Épinglage** : `tools/forge_acp_epingler.py` (owner). `--dry-run` par défaut, affiche kid + empreinte
  `sha256(clé publique brute)`, `--ecrire` écrit au coffre personnel. Loopback seulement.

## Le hub expose-t-il déjà sa clé publique ? Non.
Recherche : `app/web_hub/auth.py`, `tools/nokido_hub.py` : seules existent `/.well-known/oauth-*` (découverte OAuth MCP,
`oauth_discovery`, nokido_hub.py ~l.6749) ; aucun JWKS. Le commentaire de `forge_auth_jwt` dit que la publique est dérivée
en mémoire, sans fichier. Je n'ai pas touché `app/forge_mcp_registry.py` ni le web hub.

### Route minimale à câbler par l'intégrateur (port :8766, hub)
`GET /.well-known/acp-jwks.json`, sans authentification, lecture seule :
```python
r = forge_auth_jwt._cle_ed25519()          # (priv, pub, kid) ; ne jamais sérialiser priv
x = b64url(r[1].public_bytes(Raw, Raw))
return {"keys": [{"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig", "kid": r[2], "x": x}]}
```
`forge_acp_epingler` s'y attend (URL par défaut `http://127.0.0.1:8766/.well-known/acp-jwks.json`, `--url` pour changer).
Garde-fou : l'owner COMPARE l'empreinte affichée à celle du hub (hors bande) avant `--ecrire`.

## Résultats : plus de HMAC
Le worker n'a plus de secret : `.result.json` n'est plus signé ; `resultat()` ne vérifie que la forme.
**L'ACL de `sandbox/acp_jobs` couvre** : qui peut déposer/poser des fichiers (si elle limite l'écriture au hub, et la lecture/écriture
des résultats au worker + hub, un bac à sable ne peut ni injecter un job — déjà couvert par la signature — ni fabriquer
ou remplacer un résultat).
**Elle ne couvre pas** : un compte autorisé en écriture (ex. OWNER lui-même, ou tout code tournant sous ce compte) ;
l'altération hors ACL (admin/SYSTEM) ; la preuve d'origine d'un résultat (pas de non-répudiation, un résultat copié est
indiscernable) ; le temps entre `.done` et lecture si l'ACL est trop large. Tant que l'ACL n'est pas posée et vérifiée,
un résultat est à considérer comme non authentifié (régression assumée : ancien test « résultat forgé illisible » remplacé).
Option future : persona TPM pour signer les résultats.

## Tests
`tests/nr/test_acp_worker_auth_nr.py`, `tests/nr/test_acp_epingler_nr.py` (clé Ed25519 générée, faux keyring, tmp_path),
`tests/nr/test_acp_worker_sessions_nr.py` (adapté : cas « résultat forgé » → « résultat mal formé »).
Non couvert (hors portée) : vrai CLI, vrai keyring, services.toml/registre/web hub.

## Décisions de permission signées (faille sandbox/acp_permissions, 28/10)
| Affirmation | Preuve | État |
|---|---|---|
| Une décision non signée / autre clé / autre pid / périmée / rejouée est refusée (cancelled, journalisée) | `tests/nr/test_acp_decision_signee_nr.py` (6 cas, clé Ed25519 générée en tmp_path) : ROUGE puis VERT ; 235 NR ACP verts | Fait |
| Seule la charge SIGNÉE fait foi (le champ `decision` du fichier est ignoré) | `politique_owner._decision_signee` | Fait |
| Vérification par clé publique épinglée (`forge_acp_worker.epingle_coffre`), réutilise `forge_acp_hub.sceller/verifier` | `forge_acp_router.verifier_decision` | Fait |
| Anti-rejeu : nonce en mémoire du processus agent ACP (+ pid aléatoire par demande) | `_NONCES_VUS` | Fait (non persisté : un redémarrage purge, mais le pid est à usage unique) |
| Signature à la décision : `acp_views.api_decider` appelle `R.signer_hub` ; clé illisible -> 503, décision NON écrite | `acp_views.py` | Fait |
| Compte réel du web hub (peut-il lire la clé privée ?) | non mesuré : services.toml absent de ce worktree, clé privée jamais lue ni affichée | À MESURER |

Route minimale proposée si le web hub ne tourne pas sous SYSTEM : `POST :8766/acp/sign` (jeton admin hub), corps
`{pid, option, refuser, sub}`, rend `{jws}` via `forge_acp_hub.sceller("acp_decision", ...)` ; `signer_hub` appellerait
cette route. Non implémentée (app/forge_mcp_registry.py et tools/nokido_hub.py interdits).
Effet de bord : les NR ACP historiques reçoivent une clé de test via `tests/nr/conftest.py` (fixture ciblée).
