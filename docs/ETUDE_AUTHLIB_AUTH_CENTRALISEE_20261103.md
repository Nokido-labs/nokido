# Étude — Authlib comme interface d'authentification centralisée de Nokido (3/11/2026)

Demande owner : « lance une veille sur https://github.com/authlib/authlib et entrevois d'en faire notre interface
d'authentification centralisée dans Nokido ».

Veille : dépôt ingéré en entier au RAG (`job_419e64a17ac6`, 2 775 chunks, sources `github:authlib/authlib/...`,
vérifié en FTS). Matrice mesurée sur le paquet **Authlib 1.7.2** déjà installé dans `miniforge3` (base) ;
**absent** de l'environnement du hub et de `nokido_services`. Licence **BSD-3-Clause** (compatible distribution PyPI).

## 1. Ce qu'Authlib couvre, face à ce que Nokido exige

| Exigence Nokido | Authlib 1.7.2 | Nokido aujourd'hui |
|---|---|---|
| Code d'autorisation + PKCE (6749, 7636) | ✅ `oauth2/rfc6749`, `rfc7636` | ✅ `forge_oauth_route.valider_autorisation` |
| DCR (7591) + gestion du client (7592) | ✅ `rfc7591`, `rfc7592.ClientConfigurationEndpoint` | 7591 ✅ ; 7592 non trouvé |
| Métadonnées serveur (8414) + `iss` (9207) | ✅ `rfc8414`, `rfc9207` | 8414 ✅ `metadonnees_autorite` ; 9207 non trouvé |
| Jeton d'accès JWT (9068) | ✅ `rfc9068` (validateur + émetteur) | ✅ at+jwt ES256 signé clé TPM |
| Introspection (7662) / révocation (7009) | ✅ `IntrospectionEndpoint`, `RevocationEndpoint` | révocation via ordre tray `oauth-revoquer` ; points HTTP standard non trouvés (ILLISIBLE : recherche par nom seulement) |
| Device flow (8628) | ✅ `rfc8628` | ❌ — utile aux CLI sans navigateur |
| JWT bearer client/assertion (7521, 7523) | ✅ | ❌ |
| **Indicateurs de ressource (8707)** | ⚠️ seulement `aud` dans `rfc9068/token.py:157` | ✅ `_table_ressources`, `resource` validé |
| **Métadonnées de ressource protégée (9728)** | ❌ absent | ✅ `metadonnees_ressource` |
| **Échange de jeton (8693)** | ❌ `rfc8693/__init__.py` = docstring seule, aucune classe | ✅ option B (identité de service des jobs) |
| **DPoP (9449)** | ❌ absent | ✅ `forge_dpop.py` (+ TPM) |
| **Signature par clé TPM non exportable** | ⚠️ possible : `JWSAlgorithm` + `register_algorithm` (rfc7515/jws.py:47) | ✅ ES256 TPM |
| Serveur sur **Starlette** (le hub) | ❌ intégrations serveur Flask/Django seules ; Starlette = client | ✅ `forge_oauth_http.py` |
| Consentement owner au tray, rings, quarantaine | ❌ (métier Nokido) | ✅ |
| Client OAuth (code + PKCE + rafraîchissement) | ✅ `httpx_client`, `requests_client` | ❌ — chantier reporté « pont stdio client OAuth » |

`authlib.jose` est en dépréciation au profit de **joserfc** (même auteur) : tout code neuf JOSE vise joserfc.

## 2. Lecture

Authlib n'est pas un serveur clé en main pour Nokido : les 4 briques qui font notre spécificité (DPoP, 8693,
9728, TPM) et l'intégration Starlette sont **à notre charge** dans tous les cas. Ce qu'il apporte de réel :
- des **endpoints standard éprouvés** (validation, erreurs conformes RFC) : 7662, 7009, 7592, 9207, 8628 ;
- un **client OAuth** complet — exactement la pièce qui manque au pont stdio pour passer Roo, Claude Desktop,
  Vibe, Copilot CLI en OAuth (chantier reporté au plan, `docs/PLAN_OAUTH_MCP_HUB_20261102.md`) ;
- un **oracle de conformité** : rejouer nos réponses contre ses validateurs dans des NR.

Remplacer d'un bloc notre serveur (prouvé sur 6 clients en ring 1) par Authlib = réécrire un chemin critique
de sécurité qui marche, pour y regreffer DPoP/8693/9728/TPM/tray. Coût élevé, gain faible.

## 3. Options

- **A — Hybride, client d'abord (recommandée).** (1) Authlib côté CLIENT dans le pont stdio (`httpx_client`,
  code + PKCE + jeton au coffre, rafraîchissement) : solde le chantier reporté. (2) Côté serveur, adopter
  ses endpoints manquants derrière notre façade Starlette (adaptateur `create_oauth2_request` /
  `handle_response`) : 7662 + 7009 d'abord, puis 8628 et 9207. Notre noyau (route, DPoP, 8693, 9728, TPM,
  tray) reste. (3) Authlib comme oracle de conformité dans les NR.
- **B — Migration serveur complète** sur `AuthorizationServer` d'Authlib + extensions maison. Gros chantier,
  risque de régression sur la voie d'accès de tous les clients.
- **C — Référence seule** : pas de dépendance d'exécution ; Authlib sert d'oracle de conformité en test.

Dépendance à ajouter (A ou B) : `authlib` (+ `joserfc`) dans l'env du hub, `nokido_services` et les
dépendances de la distribution ; montée d'env de services EN MARCHE = lister avant, relire
`/supervisor/status` après (gotcha 1/11).

## 4. Première étape proposée (A1)

Pont stdio client OAuth : `mcp_stdio_bridge.py` obtient son jeton par Authlib (inscription DCR une fois,
consentement owner au tray, jetons au coffre DPAPI, rafraîchissement), repli sur le jeton d'agent tant que
le consentement manque. NR : le pont présente un at+jwt au hub (journal d'audit `via=oauth_rfc9068`), aucun
jeton dans la config cliente ni dans l'environnement.
