# P0 — Plus aucun jeton hub en clair dans une config client (ÉTUDE, phase 1)

Item : `P0_jetons_clients_coffre_seul_rfc_20261024`. Date : 2026-10-25. Aucun code, aucune écriture hors ce fichier.

## 0. Méthode et limites

- Aucun fichier de profil ni config client n'a été ouvert. Les cibles viennent du **code** de
  `tools/forge_hub_token_rotation.py` (`CONFIG_FILES`, L66-110). La base RAG n'a pas été interrogée.
  Aucune valeur de secret n'est citée.
- Étiquettes : **SOURCÉ** (code ou doc du dépôt, fichier cité) · **INCONNU** (pas de source ingérée :
  à mesurer avant tout geste). Je n'ai pas consulté d'URL de doc officielle : ce qui n'a pas de source
  dans le dépôt est INCONNU, même si je crois le connaître.
- `OpenCode` **n'est pas** dans `CONFIG_FILES` : il n'est pas inventorié. Écart à corriger (§5).
- La doc ingérée de Claude Code est citée par le commentaire de `tools/forge_mcp_json_sync.py` L99-105
  (« Doc Claude Code (mcp.md, ingérée le 24/09) »). Le texte même de cette doc n'a pas été relu ici.

## 1. Briques Nokido déjà là (réutiliser, ne rien recréer)

| Brique | Rôle | Source |
|---|---|---|
| `forge_secrets.get_secret` | coffre DPAPI. L'ordre inclut une source `wcm` (Credential Manager) via `_sonder` | `app/forge_secrets.py` ~L843-902 |
| `forge_secrets.injecter_env_depuis_coffre` | noms dans `Nokido.env`, valeurs au coffre, jamais la valeur du fichier | idem L843 |
| `forge_cli_harness.jeton_mcp(agent)` | `{variable: valeur}` lu au coffre à chaque lancement, pour le seul enfant | `app/forge_cli_harness.py` L315 |
| `tools/nokido_vibe.py` | lanceur owner Vibe : jeton `FORGE_TOKEN_VIBE_CLI` posé dans l'env du seul process `vibe`, config avec `api_key_env` | `tools/nokido_vibe.py` L1-39 |
| `forge_mcp_json_sync.py --emit-headers AGENT` | `headersHelper` Claude Code : en-têtes JSON sur stdout à chaque connexion, jeton propre, jamais le maître, rien si absent | `tools/forge_mcp_json_sync.py` L99-130 |
| `tools/forge_jeton_lanceur.py` | jeton **court** (preuve TPM, repli secret statique DIT) pour le superviseur | `tools/forge_jeton_lanceur.py` L1-27 |
| `app/forge_agent_credential.py` | `jeton_pour` / `jeton_hub` : credential statique → jeton court 30 min, repli nommé | `app/forge_agent_credential.py` |
| `forge_auth_tokens.renouveler` | échange de jeton RFC 8693 (`/api/login/renouveler`) | `app/forge_auth_tokens.py` L7, L315 |
| `forge_dpop.py` | preuve DPoP RFC 9449 (14 contrôles), états LIEE/REFUSEE/INVERIFIABLE, `CleTpm`, `creer_preuve_tpm` | `app/forge_dpop.py` |
| `tools/forge_provision_clients.py --apply` | **anti-modèle** : pose les jetons en variables HKCU, donc lisibles par tout process de l'utilisateur | `tools/forge_provision_clients.py` L16-21 |

## 2. Par client : comment référencer le jeton sans le contenir

| Client (cible de `CONFIG_FILES`) | Mécanisme | Statut | Source |
|---|---|---|---|
| **Codex** (`.codex/config.toml`) | `bearer_token_env_var = "<NOM>"` : le fichier porte le **nom** de la variable. | SOURCÉ | `docs/CODEX_MCP_CONFIG.md` L14, `docs/wiki/04-MCP-Clients-Setup.md` L242, `forge_provision_clients.py` L18 |
| | Piège mesuré : la variable doit exister et être à jour. Aujourd'hui elle vit en HKCU (`--apply`), donc **le secret reste en clair au registre** (relève de (b), pas de (a)). | SOURCÉ | `forge_hub_token_rotation.py` L352-365 |
| **Claude Code** (`.claude.json`, `.claude/.mcp.json`, `.mcp.json`, `settings.local.json`) | `headersHelper` : commande lancée à chaque connexion, relancée sur 401/403, remplace les en-têtes statiques. | SOURCÉ | `forge_mcp_json_sync.py` L99-105 |
| | Reste à régler : `settings.local.json` porte des **littéraux Bearer** dans l'allowlist de permissions. Les remplacer par un motif sans jeton (`mcp__<serveur>__*`) : forme exacte **INCONNU**. | INCONNU | rotation L24-26 |
| **Claude Desktop** (`claude_desktop_config.json`, `laforge_bridge.bat`, copie MSIX) | Pont STDIO : le bearer vit dans l'`env` du lanceur. Piste : que le pont lise lui-même le coffre (`get_secret`) au démarrage, config sans `env`. La doc officielle de Claude Desktop n'est pas ingérée. | pont SOURCÉ ; piste = INCONNU | `forge_hub_token_rotation.py` L87-93 ; `tools/mcp_stdio_bridge.py` (nommé dans `forge_provision_clients.py` L40, contenu non relu) |
| **Copilot CLI** (`.copilot/mcp-config.json`) | Interpolation d'env, helper ou en-tête depuis l'env : **INCONNU**. Piste sans doc : remplacer l'entrée HTTP par un pont stdio local qui lit le coffre. | INCONNU | `docs/gouvernance/PROFILS_CLI_CODEX_COPILOT_CLINE_20261024.md` L36-42 (serveur `laforge-sovereign-hub`, clé du coffre INCONNUE : `rotation` L82-83) |
| **Cline** (`mcp_settings.json`, `cline_mcp_settings.json`) | Ponts stdio (`LaForge_Plan/Act`, `Nokido_*`) : même piste que Desktop. L'entrée HTTP `laforge` : référence à une variable ou à un helper **INCONNU**. | INCONNU (ponts SOURCÉ) | PROFILS… L44-50 |
| **AGY** (Antigravity) | Gouvernance `AGY_MCP_ONLY` (`_govern_agy`) existe. Mécanisme de référence au jeton : **INCONNU**. Clé du coffre : `FORGE_TOKEN_ANTIGRAVITY`. | INCONNU | `tools/forge_connect_clients.py` L68 ; rotation L62 |
| **Gemini CLI** (`.gemini/settings.json`, hors liste de l'énoncé mais dans `CONFIG_FILES`) | Bearer **littéral** constaté par la doc interne. Mécanisme de remplacement : **INCONNU**. | INCONNU | `docs/transient_surface_matrix.md` L56-60 |
| **Vibe** (`config.toml` sous `VIBE_HOME`) | `api_key_env` : nom de variable dans la config, valeur posée par le lanceur depuis le coffre dans l'env du seul process. **Modèle de référence.** | SOURCÉ | `tools/nokido_vibe.py` L6-9 ; `forge_cli_route.py` L83 |
| **OpenCode** | Hors `CONFIG_FILES`. Tout est **INCONNU** : chemin de config, mécanisme, clé du coffre. | INCONNU | — |

Constat transversal : seuls Codex, Claude Code et Vibe ont un mécanisme SOURCÉ. Les quatre autres
(Copilot, Cline-HTTP, AGY, Gemini) n'en ont aucun source, et OpenCode n'est même pas recensé.

## 3. Schéma hybride cible

- **(a) Injection par le lanceur / l'exécuteur** : le lanceur lit le coffre (`jeton_mcp`,
  `injecter_env_depuis_coffre`) à chaque lancement et pose la variable dans l'env du **seul** process
  enfant. Rien n'est écrit au disque ni en HKCU. Modèle : `nokido_vibe.py`. Pour Claude Code, `headersHelper`
  est l'équivalent (aucune variable héritée par les hooks).
- **(b) Trousseau Windows** pour un CLI lancé à la main : le jeton court (jamais le maître) est déposé dans
  Credential Manager. Un petit helper (commande d'aide ou pont stdio) le lit au démarrage. Le coffre
  connaît déjà `wcm` comme source de lecture ; il n'existe **pas encore** de chemin d'écriture ni de helper
  par client, à vérifier avant tout dev.
- **Jamais casser l'usage direct** : la config ne contient que des noms (variable, helper, cible
  trousseau). Si le helper échoue, il sort en code non nul **en le disant**, sans rien inventer
  (contrat AUTH-2/4 de `forge_mcp_json_sync`). Pas de repli sur le jeton maître.
- **Préférer le jeton court** (RFC 8693, `forge_jeton_lanceur` / `forge_agent_credential`) à la clé
  statique `FORGE_TOKEN_<AGENT>` : un jeton lisible par un process du même compte expire en 30 min.

## 4. Plan de migration par client

Ordre : du moins risqué (mécanisme SOURCÉ) au plus incertain. Chaque étape est un geste **owner**,
l'agent ne touche à aucun fichier du profil.

1. **Claude Code** : `headersHelper` est déjà le mécanisme. Rester sur `--emit-headers` dans `.claude.json` et
   `.mcp.json`. Retirer ensuite les littéraux de `settings.local.json`. Retour arrière : sauvegarde du
   fichier par l'owner avant édition, l'ancienne valeur étant invalidée par la rotation.
2. **Vibe** : déjà conforme. Seul le test NR est à ajouter.
3. **Codex** : garder `bearer_token_env_var`. Remplacer `--apply` (HKCU persistant) par un lanceur
   `nokido_codex.py` calqué sur `nokido_vibe.py`, puis supprimer la variable HKCU. Retour arrière : relancer
   `forge_provision_clients.py --apply`. Risque : Codex desktop partage `config.toml` mais n'est pas lancé
   par le lanceur, donc INCONNU : mesurer avant de supprimer HKCU.
4. **Claude Desktop** : si le pont stdio lit le coffre lui-même, retirer `env` du config et du `.bat`.
   Retour arrière : réécrire `env` (la rotation sait déjà patcher ces fichiers). La copie MSIX est la seule
   vraie : patcher l'homonyme de `AppData\Roaming` est inerte (rotation L96-102).
5. **Cline, Copilot, AGY, Gemini, OpenCode** : **ne pas migrer avant mesure**. Chacun a d'abord besoin d'une
   étape « mesurer le mécanisme dans un sandbox, sans toucher au profil réel ». Pour Cline et Copilot,
   repli probable : pont stdio local. Pour OpenCode : l'inventorier d'abord (§5).
6. **Clôture** : relancer l'inventaire `forge_hub_token_rotation.py` (défaut, sans écriture) et exiger
   0 occurrence « trouvé » dans les fichiers clients ET dans HKCU/HKLM (`_env_registry`).

Retour arrière général : tant que le coffre est la source, remettre un jeton en clair n'est qu'un geste
owner. Il faut alors **rotater** la valeur ensuite, car la précédente a été exposée.

### Test NR proposé (prouve l'absence de clair sans lire la valeur)

`tests/nr/test_jetons_clients_sans_clair_nr.py` :
- Le test importe `CONFIG_FILES` et `TOKEN_RE` de `forge_hub_token_rotation` et charge les valeurs du coffre.
- Il scanne chaque fichier de **fixtures** (jamais le profil réel) par `_scan_text`. Il n'imprime que des
  empreintes `fp()`.
- Il vérifie que, pour chaque config générée par le provisionneur, aucune des valeurs du coffre n'apparaît
  (comparaison de `fp`) et que `TOKEN_RE` ne donne aucun 64-hex.
- Il vérifie aussi qu'aucun littéral `Bearer <hex>` ne subsiste, et que chaque entrée MCP référence un nom
  (`bearer_token_env_var`, `api_key_env`, `headersHelper`).
- **Piège** : un test qui lit le profil réel serait lui-même un incident. Le test réel sur le profil est
  l'inventaire exécuté par l'owner, trois états (trouvé · absent · ILLISIBLE) : un fichier illisible fait
  échouer le test, il ne passe pas pour sain.
- Contrôle négatif obligatoire : une fixture contenant un 64-hex fabriqué doit être détectée, sinon la sonde
  est aveugle.

## 5. Écarts

### RFC 6750 (Bearer) et 9700 (OAuth BCP)
- Le hub répond 401 avec `WWW-Authenticate: Bearer realm="nokido-hub"` (`nokido_hub.py` L1149, L5630). L'erreur
  `error="invalid_token"` n'a pas été vérifiée (INCONNU).
- Le jeton est présenté dans l'en-tête (méthode §2.1) : bon. Aucun jeton dans l'URL n'a été constaté,
  mais je n'ai pas cherché.
- BCP 9700 : le jeton statique long qui vit en HKCU contredit le principe « courte durée + liaison à
  l'émetteur ». Corrigé par §3 (jeton court) et par DPoP (ci-dessous).

### RFC 8693
Livré : `/api/login/renouveler` (`forge_auth_tokens.renouveler`). Un jeton lié exige la preuve de possession.
Manque : l'échange n'est pas branché pour les clients tiers (Codex, Cline…). Seul le `headersHelper` Claude Code
et le superviseur le peuvent. Un client qui ne sait que lire une variable obtient au mieux un jeton court posé
au lancement, sans renouvellement en cours de session.

### RFC 9449 (DPoP) côté hub : ce qui manque
Existe : module `forge_dpop` complet, `/api/login` accepte `dpop_jwk` et émet `cnf.jkt`
(`nokido_hub.py` L2861-2881), clé TPM (`CleTpm`).
Manque, vérifié dans le code lu :
1. **Aucune vérification de preuve sur `/mcp`.** La seule porte qui vérifie DPoP est le chemin admin
   (`decision_admin_tpm`, L5776), en **observation** par défaut, appliquée seulement avec
   `LAFORGE_ADMIN_TPM_ENFORCE=1`. La porte `/mcp` utilisée par les clients n'en a pas (à confirmer par audit
   complet : je n'ai lu que des extraits de `nokido_hub.py`).
2. **Le hub répond `Bearer`, pas `DPoP`** : pas de schéma `Authorization: DPoP`, pas de `WWW-Authenticate: DPoP
   algs=…`, pas de `DPoP-Nonce` serveur (§8), pas de `use_dpop_nonce`. `forge_dpop.verifier` sait contrôler un
   nonce, mais rien ne l'émet côté HTTP (INCONNU, non cherché en profondeur).
3. **Aucun client tiers ne produit de preuve.** Codex, Copilot, Cline, AGY n'ont aucun point d'accroche DPoP
   connu (INCONNU). Une preuve par requête exige un code côté client, hors de portée d'un simple
   `bearer_token_env_var`. Donc un jeton lié ne peut être exigé que d'un client qui passe par un pont Nokido
   (stdio ou `headersHelper` étendu). Un `headersHelper` ne voit pas la méthode ni l'URL de la requête, donc il
   **ne peut pas** fabriquer `htm`/`htu` : à vérifier dans la doc Claude Code.
4. **Anti-rejeu `jti`** : mémoire de process (non persistée, par conception `forge_dpop` L128). À prévoir si le hub
   redémarre ou passe en multi-process.
5. **Enrôlement** : `jkt_tpm_enregistre` existe pour les agents à clé TPM. Une clé par client tiers n'est pas
   provisionnée.

Conclusion : DPoP est **utilisable** pour les organes et les ponts Nokido, **pas pour les CLI tiers**. Pour
eux, l'anti-usurpation est : jeton court + coffre/trousseau + jamais en clair. Le mTLS `cnf.x5t#S256`
(RFC 8705, `forge_cert_binding`) est une alternative à étudier (INCONNU côté clients).

## 5 bis. Phase 2 — mécanismes natifs d'après la documentation (25/10, Claude Code)

Décisions owner du 25/10 : suppression HKCU après mesure ; clients sans mécanisme documenté **au cas par
cas** (natif d'abord, pont stdio en repli) ; mesure faite par Claude Code en **profil jetable** ; TPM admin
pas maintenant. Première passe = documentation seule (aucun fichier du profil lu). Niveau de preuve indiqué :
une doc tierce ne vaut pas mesure, chaque ligne reste à confirmer en profil jetable avec un jeton factice.

| Client | Référence au jeton dans un en-tête HTTP | Source | Preuve |
|---|---|---|---|
| **OpenCode** | `"headers": {"Authorization": "Bearer {env:NOM}"}` ; `$NOM` n'est PAS développé. Bogue ouvert : substitution qui échoue sur certains serveurs distants (anomalyco/opencode#5299) | doc officielle v2.opencode.ai/docs/mcp-servers | DOC OFFICIELLE + bogue connu |
| **Gemini CLI** | `$NOM` ou `${NOM}` dans toute valeur de settings.json, en-têtes compris (transport `httpUrl`) ; en stdio, `env` explicite requis (masquage des `*TOKEN*`) | miroir de la référence settings (mintlify), guides fournisseurs | DOC TIERCE |
| **Copilot CLI** | `"headers": {"Authorization": "Bearer ${NOM}"}` (type `http`) ; `env` avec `${NOM}` pour stdio | guide d'installation du dépôt github/github-mcp-server | DOC TIERCE (dépôt GitHub, pas la référence CLI) |
| **Cline** | `${env:NOM}` dans `headers` (type `streamableHttp`) | une seule page fournisseur (DomainTools), non confirmée par docs.cline.bot | INDICE |
| **AGY** | non documenté publiquement | — | INCONNU |

**Mesure en profil jetable du 25/10** (`tools/forge_p0_mesure_entetes_clients.py` : CLI installés dans un
préfixe npm du bac à sable, HOME/APPDATA jetables, faux jeton dans `NOKIDO_P0_FAUX_JETON`, serveur MCP
d'écho sur 127.0.0.1 qui journalise l'en-tête reçu ; rapport `sandbox/workspace/p0_profil_jetable/rapport.json`) :

| Client | Verdict mesuré | Détail |
|---|---|---|
| **Gemini CLI** | **NATIF_OK** | `"Authorization": "Bearer $NOKIDO_P0_FAUX_JETON"` → reçu `Bearer <valeur>` (4 requêtes). Prérequis : dossier approuvé (`~/.gemini/trustedFolders.json`), sinon les serveurs MCP sont désactivés. |
| **Copilot CLI** | AUCUNE_REQUETE · AUTH_CLI_REQUISE | exige une authentification GitHub AVANT tout appel MCP ; pas de vrai jeton GitHub dans un profil jetable → forme non mesurée (ce n'est pas un refus). |
| **OpenCode** | AUCUNE_REQUETE · BINAIRE_ABSENT | le postinstall npm d'`opencode-ai` ne pose pas son binaire Windows (même avec `opencode-windows-x64[-baseline]`) ; le binaire des exécuteurs vit dans le profil owner, illisible du bac à sable (voulu). Forme non mesurée. |
| **Cline, AGY** | non mesurés | extension VS Code / client interne : pas de lancement sans interface. |

Conséquence : pour OpenCode, Gemini, Copilot et peut-être Cline, la forme native « en-tête depuis une
variable » existe ; le lanceur (schéma a) pose la variable depuis le coffre, le trousseau (schéma b) sert au
lancement manuel. Pont stdio seulement si la mesure en profil jetable réfute la doc (cas d'OpenCode #5299).
Prochaine étape : pour chaque client, profil jetable + jeton factice + serveur d'écho local qui journalise
l'en-tête reçu (jamais le hub réel, jamais un vrai jeton).

Sources : [OpenCode MCP](https://v2.opencode.ai/docs/mcp-servers) ·
[opencode#5299](https://github.com/anomalyco/opencode/issues/5299) ·
[Gemini CLI settings (miroir)](https://www.mintlify.com/google-gemini/gemini-cli/reference/settings) ·
[Copilot CLI (github-mcp-server)](https://glama.ai/mcp/servers/@github/github-mcp-server/blob/bf6467855c13d3b8f5cf72f8dfd9c86f8336b20b/docs/installation-guides/install-copilot-cli.md) ·
[DomainTools, Cline/Gemini](https://docs.domaintools.com/mcp/api-key-auth/) ·
[Cline MCP](https://docs.cline.bot/mcp/mcp-overview)

## 6. Questions à l'owner avant la phase 2
1. Autorise-t-on la suppression des variables HKCU `FORGE_TOKEN_*` une fois les lanceurs en place ?
2. Pour les clients sans mécanisme SOURCÉ, accepte-t-on le pont stdio local comme forme unique ?
3. Qui mesure Copilot, Cline, AGY, Gemini et OpenCode (sandbox, pas le profil réel) ?
4. Activer `LAFORGE_ADMIN_TPM_ENFORCE=1` : geste owner, hors périmètre de cette étude.
