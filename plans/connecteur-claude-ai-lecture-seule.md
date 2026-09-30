# Connecteur claude.ai → Nokido, en lecture seule — plan

**Statut : PROPOSÉ** (owner, 28/09 : « oui »). **Rien n'est exposé.** Chaque étape est un geste
sortant ou de sécurité : aucune ne s'exécute sans go owner explicite.
Tâche **locale** — elle touche aux secrets et au réseau : jamais déléguée à une session cloud.

## Objectif

claude.ai (web / app) interroge l'état **vivant** de Nokido — santé, SSoT, roadmap, RAG — sans
pouvoir agir. L'impossibilité d'agir vient de la **construction** (aucun outil d'action n'existe
sur cette surface), pas d'un refus au moment de l'appel.

## Contraintes mesurées (28/09)

- Le hub écoute en loopback (`127.0.0.1:8766/mcp`) et son `/mcp` porte `run`, `governed_edit`,
  `run_job`… → **le hub n'est jamais exposé**, ni directement ni derrière un tunnel.
- claude.ai appelle depuis l'infrastructure d'Anthropic → il faut une **URL publique HTTPS**.
  Différence avec ChatGPT : le Secure MCP Tunnel d'OpenAI est un objet d'organisation **sans URL
  publique** ; ce chemin ne sert pas ici.
- Le coffre machine DPAPI est lisible par les comptes bac à sable, jeton maître compris
  (mesuré le 28/09) → **prérequis bloquant** (étape 0).
- **Existant à réutiliser, pas à refaire** :
  - `NokidoGithubBridgeMCP` — `tools/forge_github_bridge_mcp.py` (`construire_serveur`,
    `base_publique`, streamable HTTP, port 8791) ;
  - `tools/forge_bridge_oauth.py` — autorité OAuth locale : DCR avec clients persistés
    (`NOKIDO_BRIDGE_OAUTH_CLIENTS`), consentement par **code d'appariement owner**, renouvellement
    **tournant**, habilitation relue à **chaque** requête (`_lire_capacite`) ;
  - pièges déjà payés (fiche mémoire `chatgpt_github_oauth_wired_2026-09-14`) : annonce
    `token_endpoint_auth_methods_supported` sans `none` alors que `none` est accepté ;
    `/.well-known/oauth-protected-resource` à la racine en 404 ; `https` exigé pour la base
    publique.

## Étapes

### 0. Prérequis — le coffre (plan séparé, go owner)

`FORGE_MCP_TOKEN` est à la fois porteur admin, repli du secret JWT, matériau de chiffrement
(`forge_encrypt`, `forge_env_crypt`, `forge_db_conn`), clé HMAC (`forge_state_manager`) et base
de dérivation des jetons d'agent (`forge_auth_tokens`). Il faut :

1. découpler ces usages en secrets distincts ;
2. sceller chacun pour les seuls comptes qui en ont besoin (DPAPI en portée utilisateur du
   compte de service, ou coffre dont l'ACL exclut les comptes Sbx) ;
3. re-chiffrer les données avant de retirer l'ancienne clé ;
4. faire la rotation des porteurs (admin, superviseur, jetons d'agent) ;
5. poser un NR : aucun compte Sbx ne lit un secret de ring ≤ 3.

**Sans l'étape 0, pas d'étape 3.**

### 1. Serveur MCP en lecture seule — extension du pont, pas un serveur de plus

- Même cadre que le pont : `construire_serveur` + `forge_bridge_oauth` (**une seule autorité**),
  avec une habilitation distincte `vitrine:lecture`.
- **Liste blanche FIGÉE** d'outils, tous en lecture, sorties bornées en taille et passées par
  `redact_tool_output` :
  - `etat_corps` — dernier snapshot consolidé de santé (lecture de fichier, pas de sonde) ;
  - `point_ssot(domaine)` — `forge_ssot.point` ;
  - `roadmap` — faits `CURRENT` / `NEXT` / `BLOCKER` du SSoT ;
  - `recherche_rag(q, limite ≤ 10)` — FTS en lecture, **restreint à une liste blanche de
    sources exposables** (le RAG contient mémoires et notes : tout n'est pas publiable) ;
  - `journal_commits(n ≤ 20)` — messages de commits publiés.
- **Aucun** outil qui exécute, écrit, lance un job, lit un fichier arbitraire ou un secret.
- Processus sous le compte `LaForgeSbxOffline` (qui, après l'étape 0, ne lit plus rien de
  privilégié), port loopback dédié (proposé : 8793), déclaré dans
  `proxy_deno/core/services.toml` avec **`enabled = false` par défaut** et un heartbeat.
- NR :
  - les outils exposés sont **exactement** ceux de la liste blanche ;
  - aucun outil n'atteint `run` / `governed_edit` / `run_job` (graphe d'import) ;
  - les sorties sont rédigées et bornées ;
  - sans habilitation : 401 + `WWW-Authenticate` avec `resource_metadata` (RFC 9728) ;
  - une source RAG hors liste blanche n'est jamais rendue.

### 2. OAuth pour claude.ai — la même autorité

- Métadonnées RFC 8414 et RFC 9728 (à la racine **et** sous le chemin), DCR RFC 7591 en client
  public (`none`) avec PKCE S256 (OAuth 2.1), indicateur de ressource RFC 8707 lié à l'URL
  publique.
- `redirect_uri` en liste blanche = l'URL de rappel de claude.ai. **À vérifier dans la doc
  Anthropic au moment de le faire** (non vérifiée ici : RAG indisponible, WebFetch proscrit).
- Consentement par code d'appariement owner (jamais généré par l'agent), jetons d'accès courts
  (≤ 1 h), renouvellement tournant, scope unique `vitrine:lecture`.

### 3. Entrée publique HTTPS (go owner, identifiants owner)

- **Option A — Cloudflare Tunnel nommé** : `cloudflared` en service **sortant**, aucun port
  entrant ouvert ; exige un domaine géré par Cloudflare.
- **Option B — Tailscale Funnel** : URL `https://<machine>.<tailnet>.ts.net`, sans domaine.
- Dans les deux cas :
  - chemins autorisés seulement (`/mcp`, `/.well-known/*`, `/authorize`, `/token`, `/register`) ;
  - limitation de débit et de taille de corps ;
  - en option, liste blanche des plages IP sortantes publiées par Anthropic (**à vérifier**) ;
  - TLS terminé par le fournisseur, le service reste en loopback derrière.
- **URL finale = `https://<hôte>/mcp`**. C'est elle qu'on ajoute dans claude.ai (Paramètres →
  Connecteurs → connecteur personnalisé ; libellés **à vérifier**).

### 4. Observer avant d'ouvrir durablement

- Période d'essai (proposé : 48 h) : journal de chaque appel (videur), alerte sur les refus
  répétés.
- **Coupure en un geste** : arrêter le service tunnel, et l'URL meurt aussitôt.
- Décision owner à l'issue : maintenir, restreindre ou fermer.

## Retour arrière

Arrêter le service tunnel (URL morte immédiatement) · révoquer les clients DCR (fichier des
clients) · repasser le service vitrine à `enabled = false`. Aucune donnée n'est modifiée par
construction.

## Risques résiduels

- **Fuite par lecture** : le RAG porte des notes internes → liste blanche de sources et
  rédaction, relues par l'owner avant l'étape 3.
- **Injection de contenu** : un texte du RAG lu par claude.ai peut l'influencer. Sans outil
  d'action, l'effet reste borné à la conversation côté claude.ai.
- **Disponibilité** : PC éteint = connecteur indisponible (à l'inverse des sessions cloud).

## Gestes owner

Go sur l'étape 0 · choix A ou B, et le domaine pour A · création du tunnel avec ses identifiants ·
code d'appariement · ajout du connecteur dans claude.ai.

## Critères de fin

- claude.ai liste **exactement** les outils de la liste blanche ;
- `recherche_rag` rend un résultat rédigé, limité aux sources exposables ;
- sans jeton → 401 conforme (RFC 6750 / RFC 9728) ;
- tunnel coupé → URL injoignable ;
- NR verts, et NR de l'étape 0 vert.
