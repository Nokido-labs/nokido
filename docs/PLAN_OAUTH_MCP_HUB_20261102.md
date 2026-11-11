# Plan — OAuth MCP émis par Nokido (hub :8766), clients interchangeables

Owner 2/11 (23 h 45 puis minuit) : « le 3 me semble plus durable, et aura des applications pour d'autres ponts
distants » ; « ça doit émaner de Nokido ; le OAuth doit venir de Nokido ; les clients sont interchangeables ; dans sa
version distribuable un utilisateur n'utilisera pas forcément Claude ».

## Principes (critères de rejet du chantier)

1. **Tout émane de Nokido.** L'autorité, l'identité, le ring, la révocation, l'émission des configs clients. Aucun
   mécanisme propre à un client (`headersHelper` de Claude Code, `inputs` de VS Code, `bearer_token_env_var` de Codex)
   n'est la voie principale.
2. **Clients interchangeables.** Un client MCP qui sait faire OAuth n'a besoin QUE de l'URL du hub. Son identité est
   attribuée par Nokido à l'inscription (consentement owner), pas codée en dur dans sa config.
3. **Aucun jeton fixe chez un client.** Jetons d'accès courts, renouvellement révocable, empreinte seule sur disque.
4. **Repli universel : le pont stdio de Nokido** (`tools/mcp_stdio_bridge.py`) pour les clients sans OAuth.
5. **Distribuable.** Aucun chemin, compte ou nom d'agent propre à l'owner dans le mécanisme.

## Conformité RFC — critère de rejet (owner 2/11 : « reste conforme RFC, attention »)

Chaque étape cite la RFC qu'elle applique et sa NR vérifie le comportement NORMATIF (MUST), pas seulement le chemin
heureux. Référence d'ensemble : spécification d'autorisation MCP (révision en vigueur, à relire en E0 dans la doc
ingérée) + OAuth 2.1 (draft-ietf-oauth-v2-1) + BCP sécurité OAuth (RFC 9700).

| RFC | exigence appliquée | où |
|---|---|---|
| RFC 9728 | métadonnées de ressource protégée ; `401` + `WWW-Authenticate: Bearer resource_metadata="..."` | E2 |
| RFC 8414 | métadonnées du serveur d'autorisation (`issuer` exact, points annoncés = points servis) | E2 |
| RFC 7591 | inscription dynamique (champs validés, `redirect_uris` obligatoires) | E3 |
| RFC 7636 | PKCE, `S256` SEULEMENT (`plain` refusé) | E3 |
| RFC 8252 | client natif : redirection bouclage local (`127.0.0.1`/`[::1]`, port libre), jamais de schéma arbitraire | E3 |
| RFC 8707 | indicateur de ressource : `resource` exigé et lié au jeton (`aud`), jeton refusé hors de sa ressource | E3, E5 |
| RFC 6750 | usage du Bearer (en-tête seul, jamais en paramètre d'URL), codes d'erreur `invalid_token` / `insufficient_scope` | E5 |
| RFC 7009 | révocation (jeton d'accès et renouvellement) ; effet à l'appel suivant | E3, E4 |
| OAuth 2.1 §4.3.1 | renouvellement à ROTATION pour les clients publics (ancien renouvellement invalidé à l'usage) | E3 |
| RFC 9449 | DPoP : liaison du jeton quand le client la propose (direction owner du 30/10) | question ouverte |
| RFC 8693 | échange de jetons : reste interne (identité de service des jobs, décision du 30/10) | hors périmètre client |

Tout écart d'une brique existante à ces exigences (ex. renouvellement non tournant, `resource` non vérifié) est
corrigé AVANT de la monter sur le hub, avec sa NR.

## Ce qui existe déjà (à réutiliser, pas à réécrire)

| brique | rôle | limite actuelle |
|---|---|---|
| `tools/forge_bridge_oauth.py` `AutoriteLocale` | SDK MCP `OAuthAuthorizationServerProvider` : inscription dynamique, consentement owner (`demande`/`accorder`, code d'appariement), jetons courts (`_delivrer`), renouvellement par empreinte, révocation (`revoquer(jti)`), plafond d'échecs | attachée au pont des pairs (`PONT.AUDIENCE`, `PONT.SCOPE`, `depot_unique()`) ; montée sur un serveur du SDK, pas sur le hub |
| `app/forge_auth_tokens.py` | jetons de capacité courts (émission/vérification) | — |
| `tools/forge_pair_mcp.py`, `tools/forge_github_bridge_mcp.py` | deux montages réels de l'autorité (patron `reglages` / `poser_complements` / `poser_consentement`) | — |
| hub :8766 `/mcp` | Bearer par jeton d'agent (coffre), RBAC/ring | `/.well-known/oauth-*` → 404 « Bearer token auth only » (mesuré 2/11) |
| `tools/forge_provision_clients.py` | émet les blocs de config clients | émet des jetons en clair |
| `tools/forge_mcp_json_sync.py` | synchronise les jetons dans les configs | ÉCRIT des jetons en clair (`.claude.json` ×2, `.gemini` ×2, `.github/mcp.json`) |

## Étapes (une NR par étape, rien n'avance sans la précédente prouvée)

- **E0 — Reconnaissance.** Où le hub vérifie le Bearer (pile HTTP, middleware) ; comment l'autorité est montée sur le
  pont des pairs ; ce qui la lie au pont. Livrable : carte fichier:ligne.
- **E1 — Découpler l'autorité du pont.** Audience, portée et ressource paramétrées par serveur ; le pont des pairs
  garde son comportement (ses NR rejouées).
- **E2 — Le hub publie ses métadonnées.** RFC 9728 (ressource protégée) + RFC 8414 (serveur d'autorisation) ; `401`
  avec `WWW-Authenticate: Bearer resource_metadata=...`. NR : un client découvre l'autorité depuis l'URL seule.
- **E3 — Points d'inscription / autorisation / jeton / révocation sur le hub.** PKCE S256 obligatoire ; redirections
  limitées au bouclage local (RFC 8252) ; inscription dynamique bornée (plafond existant).
- **E4 — Consentement owner par le tray.** Un nouveau client = une demande au tray (nom déclaré, portée, ring proposé,
  le plus bas par défaut) ; refus par défaut à l'échéance. Registre des clients OAuth = identité Nokido
  (`OAUTH_<client>`) + ring. Révocation depuis le tray.
- **E5 — Le hub accepte les jetons OAuth.** Même chemin RBAC/ring/audit que les jetons d'agent ; le journal d'audit
  montre le principal OAuth. Les jetons d'agent restent pour les organes internes (exécuteurs, daemons).
- **E6 — Émission des configs par Nokido.** `forge_provision_clients` émet « URL seule » pour les clients OAuth et le
  pont stdio pour les autres ; `forge_mcp_json_sync` devient auditeur (jeton en clair = défaut signalé, jamais écrit).
- **E7 — Migration client par client.** Après preuve OAuth (connexion + `tools/list` + ring vérifié au journal),
  retrait de son jeton fixe et rotation. Le Lot 1 (recopie registre) se ferme quand Codex et Vibe ne lisent plus le
  registre.
- **E8 — Version distribuable.** Même mécanisme, sans chemin owner ; documentation d'installation « URL seule ».
- **E9 — Racine de confiance TPM (owner 2/11 : « pousser la chaîne d'authentification jusqu'au TPM »).** La clé qui
  SIGNE les jetons émis par Nokido est créée dans le TPM 2.0 (fournisseur CNG « Microsoft Platform Crypto Provider »,
  clé persistée NON exportable, ECDSA P-256), la vérification se fait par la clé publique (logiciel). Le jeton prouve
  alors qu'il vient de CETTE machine. Repli si TPM absent ou illisible (version distribuable) : clé logicielle au
  coffre, DIT au démarrage (ILLISIBLE ≠ ABSENT), jamais silencieux. Mesures exigées : latence d'une signature TPM
  (émission seulement : une par client et par heure), comportement après reboot et après mise à jour du TPM.
  **CORRIGÉ 2/11 ~0 h 30** : la première carte E0 disait « aucun code TPM » — FAUX, le motif `(?i)tpm` n'est pas
  compris par `git grep -E` (silence pris pour une absence). Existant à RÉUTILISER : `app/forge_persona_tpm.py`
  (clés ECDSA P-256 dans le TPM via le fournisseur CNG, `ensure_agent_key`, `sign_as`, `cle_publique_jwk`,
  `poser_ace_cle_tpm`, `tpm_available`) ; `app/forge_dpop.py` (preuves DPoP signées TPM, `CleTpm`,
  `creer_preuve_tpm`, conversion DER↔JWS ES256) ; `app/forge_oauth_route.py` (le hub sert DÉJÀ `/oauth/token`,
  échange RFC 8693 + DPoP pour les jobs) ; `cryptography` 50.0.0, `PyJWT` 2.15.0 ; fournisseur PCP ouvert (statut 0).
  Choix d'algorithme (owner : « HMAC → ECDSA, plus fort si possible, compat Linux/macOS ») : **ES256** (P-256),
  seul commun au TPM Windows, au TPM Linux et à la Secure Enclave de macOS ; agilité `alg`/`kid` pour ES384 là où la
  puce le permet ; format JWS compact (RFC 7515/7518) au lieu du `corps.sceau` HMAC maison.
  **Mesure 3/11 (compte owner, cle de test supprimee)** : source `tpm`, creation + export de la publique 155 ms,
  signature ES256 mediane **32 ms** (30-35) sur 20, verification logicielle 20/20. Compte bac a sable des jobs
  (`LaForgeSbxOffline`) : TPM INACCESSIBLE, refus DIT par le signataire (pas de repli silencieux quand `tpm=True`).
  Production : cle de NIVEAU MACHINE + ACE pour le compte du hub (`forge_persona_tpm.poser_ace_cle_tpm`). Signature
  a l'EMISSION seulement (un jeton par client et par heure) : 32 ms y est negligeable ; la verification ne touche
  jamais le TPM.
  **3/11 — clé machine CRÉÉE** (`forge_tpm_agent_keys.py --create HUB`, admin) : `laforge-agent-HUB-sign`, SDDL
  `D:P(A;;FA;;;CO)(A;;FA;;;SY)(A;;FA;;;BA)`. **Compte du hub PROUVÉ** (2 observateurs, GetOwner rc=0 +
  Get-Process) : pid 29724 NokidoMCP = `AUTORITE NT\Système` → SYSTEM a FA : AUCUNE ACE à poser. Reste pour
  l'allumage : le hub doit viser le magasin MACHINE (`FORGE_TPM_MACHINE=1` est GLOBAL au processus dans
  `forge_persona_tpm._key_flags`) — à passer sans effet de bord sur les autres clés du hub (mesurer qui d'autre
  lit cette variable dans le processus avant de la poser).
  **Conséquence sur E2-E5 : UNE autorité, le hub.** `forge_oauth_route` est étendue (code d'autorisation + PKCE +
  inscription dynamique) ; `forge_bridge_oauth` lui prête sa logique de consentement, jamais une seconde autorité.

## E7 — état au 3/11 ~13 h et chantier reporté « pont stdio client OAuth »

Migrés en OAuth et PROUVÉS au journal (ring 1, consentement tray) : Claude Code, Codex, AGY (interactif + headless),
LM Studio, VS Code/Copilot, Cline. Restent sur le pont stdio (AUCUN jeton en config, le pont lit FORGE_TOKEN_<AGENT>
au coffre) : Roo (pas d'OAuth MCP dans sa version), Sixth, Claude Desktop (OAuth local impossible ; mcp-remote écarté
par l'owner, dépendance tierce). Rotation des 5 jetons exposés faite (CLAUDE, COPILOT, ANTIGRAVITY, CODEX, GEMINI).

**Reporté par l'owner (3/11, « plus tard »)** — le pont stdio devient CLIENT OAuth : DCR + PKCE au 1er lancement,
consentement au tray, code récupéré SANS navigateur (le pont interroge `/oauth/authorize/etat` et lit la redirection),
jeton de renouvellement au coffre DPAPI ; repli DIT sur le jeton du coffre si OAuth indisponible. Gain : consentement,
ring et révocation par client, jetons qui expirent, pour Roo/Sixth/Claude Desktop sans toucher leur config. Réutiliser
la passerelle E1 (`tools/forge_passerelle_hub.py`), jamais un second client. Interrupteur + NR + essai réel Roo.

## Lot P — pairs cloud (claude.ai) sur l'autorité du hub (owner 3/11 ~4 h 40)

Décision owner (choix multiple) : « Pont + OAuth du hub » — le pont des pairs (8793) GARDE ses outils bornés (aucun
shell, jamais le `/mcp` du hub), mais son authentification passe à l'autorité du hub : consentement au tray comme
Claude Code, ring porté par le jeton, ring 1 = dépôts directs sans quarantaine. Exigences claude.ai (doc
connecteurs/authentication, lue le 3/11) : DCR ou CIMD, PKCE S256, `401` + `resource_metadata`, `resource` = URL
publique EXACTE, seul le 1er `authorization_servers` est lu, redirect `https://claude.ai/api/mcp/auth_callback`,
`/token` en `application/x-www-form-urlencoded`, `invalid_grant` à l'expiration, rotation du refresh, 10 s max
(30 s refresh), trafic depuis `160.79.104.0/21`. Mesuré 3/11 : `valider_inscription` REFUSE ce redirect (bouclage
seul), pas de CIMD, Funnel ne publie que `/` → 8793.

- **P1 — L'autorité admet des redirections HTTPS en liste BLANCHE EXACTE** (pas de motif) :
  `https://claude.ai/api/mcp/auth_callback` ; tout autre HTTPS refusé. Plusieurs ressources (RFC 8707) : le jeton
  porte l'`aud` de la ressource DEMANDÉE parmi celles déclarées (hub `/mcp`, pont public `/mcp`), jamais une autre.
- **P2 — Funnel publie l'autorité, pas le hub.** Chemins `/oauth/` et `/.well-known/oauth-authorization-server`
  → 8766 ; `/` reste → 8793. Le gardien du tray (7df545570) vérifie les TROIS handlers. Émetteur = base publique.
  Geste d'exposition = ordre `funnel-ouvrir` (session owner).
  **Mesuré 3/11 avant code (conception arrêtée)** :
  1. UN émetteur par autorité (RFC 8414 §3.3 : `issuer` = URL de découverte). Basculer `NOKIDO_HUB_EMETTEUR` sur la
     base publique casserait Claude Code local (découverte via 127.0.0.1). → **seconde instance**
     `AutoriteClientsHub(dossier_public, MEME signataire HUB, ressource = <base publique>/mcp du pont, emetteur =
     <base publique>)`, registre de clients SÉPARÉ (une inondation DCR publique ne touche pas les clients locaux).
  2. `forge_oauth_http` tient des SINGLETONS (`_AUTORITE[0]`, `_NOTIFIER[0]`, `_ATTENTE`, `decider()` lit
     `_AUTORITE[0]`) : une seconde instance écraserait celle de la connexion Claude Code EN SERVICE. → registre
     d'instances par préfixe ; `_ATTENTE[ident]` porte son instance ; `decider()` et le décideur du hub résolvent
     l'autorité par l'ident. NR : deux instances, une décision chacune, aucune fuite croisée.
  3. `/oauth/token` DÉLÈGUE les autres flots à l'échange RFC 8693 des jobs : exposé tel quel, il publierait
     l'échange interne. → instance publique : `authorization_code` et `refresh_token` SEULS, sinon
     `unsupported_grant_type` ; jamais `delegue_jeton`. NR dédié.
  4. Montage sous préfixe `/pairs` du hub ; Funnel : `/oauth` → `8766/pairs/oauth`,
     `/.well-known/oauth-authorization-server` et `/.well-known/jwks.json` → `8766/pairs/.well-known/...` ; `/` → 8793.
     Les points publiés gardent `https://<base>/oauth/...` (absolus, via Funnel). Fichier critique `nokido_hub.py`
     (allow_critical owner) + restart-hub (fenêtre tray).
- **P3 — Le pont accepte les jetons du hub** : JWS ES256 vérifié par la JWKS du hub (bouclage), `aud` = sa ressource,
  ring du jeton ; ses métadonnées RFC 9728 désignent l'autorité du hub en PREMIER. L'appariement reste en parallèle
  le temps de la preuve.
- **P4 — Ring 1 : dépôts directs ; ring 2 : quarantaine** (inchangé). Ring proposé au consentement du tray, le plus
  bas par défaut ; `config/pairs_rings.json` reste le plafond par nom de client.
- **P5 — Bascule** : après preuve claude.ai (connexion + `tools/list` + ring 1 au journal du pont), retrait de
  l'appariement (`forge_bridge_oauth.AutoriteLocale`) ; rotation.
- **P6 — CIMD** (`client_id_metadata_document_supported` + `none`) : préalable du dossier répertoire
  (`docs/DOSSIER_REPERTOIRE_ANTHROPIC.md`).

## Carte E0 (2/11, git grep sur le code suivi)

- Hub `/mcp` : `tools/nokido_hub.py` (routes Starlette ; `/.well-known/oauth-*` → 404 l. 5473 ; `_AGENT_TOKENS` l. 977) ;
  Bearer contrôlé par `tools/forge_mcp_http.py:114` `_check_bearer`.
- Autorité : `tools/forge_bridge_oauth.py` — `DUREE_JETON_S` 3600 (l. 100) ; `resource` stocké (l. 517) — vérification à
  prouver (RFC 8707) ; `load_refresh_token` / `exchange_refresh_token` l. 590-601 — rotation à prouver (OAuth 2.1).
- Couplage : `_chemin_pont` l. 76, `_charger_pont` l. 109, `depot_unique` l. 128 ; émission/vérification déléguées au
  pont chargé (`forger_capacite` / `_lire_capacite` : `forge_github_bridge`, `forge_passerelle_pair`, `forge_m2m_bridge`).
- Montages : `tools/forge_github_bridge_mcp.py` l. 253-430 ; `tools/forge_pair_mcp.py` l. 768.

## Questions ouvertes (à trancher en E0, avec mesure)

- DPoP (RFC 9449, direction owner du 30/10) : quels clients le gèrent ? Liaison optionnelle quand le client la propose.
- Durées : jeton d'accès (valeur actuelle `DUREE_JETON_S`) et renouvellement (`DUREE_RENOUVELLEMENT_S`) à relire.
- Clients cibles OAuth à vérifier dans leur doc ingérée avant E7 (VS Code : oui, `oauth.clientId` documenté ;
  Claude Code, Cursor, Gemini/AGY, Cline, Roo, LM Studio : à vérifier, sinon pont stdio).
