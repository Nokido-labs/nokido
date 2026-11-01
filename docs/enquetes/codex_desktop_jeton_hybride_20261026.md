# Enquête : Mécanismes d'authentification MCP de Codex Desktop

**Date** : 26/10/2026  
**Auteur** : OPENCODE_GLM  
**Objectif** : Analyser les mécanismes d'authentification HTTP disponibles pour Codex desktop (CLI et application) dans le contexte de l'implémentation d'un jeton hybride depuis le coffre Nokido.

## Contexte

Décision owner du 26/10/2026 : Codex desktop doit recevoir son jeton du hub en mode « hybride » :
- (a) Injection par un lanceur depuis le coffre
- (b) Jeton court lu par un petit helper / trousseau Windows quand le client est lancé à la main

**Question** : Quels mécanismes Codex offre-t-il réellement pour l'en-tête d'authentification d'un serveur MCP HTTP ?

## Mécanismes d'Authentification MCP Découverts

### 1. `bearer_token_env_var`

**Champ exact** : `bearer_token_env_var`  
**Fichier de configuration** : `config.toml` section `[mcp_servers.<nom>]`  
**Fonctionnement** : Lit un jeton depuis une variable d'environnement spécifiée  
**Support desktop** : ✅ Oui (testé dans les unit tests)  
**Source** : `codex/codex-rs/core/src/config/config_tests.rs:5a30154883f97e06`

```toml
[mcp_servers.docs]
url = "https://example.com/mcp"
bearer_token_env_var = "MCP_TOKEN"
startup_timeout_sec = 2.0
```

### 2. `http_headers`

**Champ exact** : `http_headers`  
**Fichier de configuration** : `config.toml` section `[mcp_servers.<nom>.http_headers]`  
**Fonctionnement** : Définit des headers HTTP statiques en clair  
**Support desktop** : ✅ Oui (testé dans les unit tests)  
**Source** : `codex/codex-rs/core/src/config/config_tests.rs:545b920721431197`

```toml
[mcp_servers.docs.http_headers]
X-Doc = "42"
Authorization = "Bearer static_token"
```

### 3. `env_http_headers`

**Champ exact** : `env_http_headers`  
**Fichier de configuration** : `config.toml` section `[mcp_servers.<nom>.env_http_headers]`  
**Fonctionnement** : Définit des headers HTTP depuis des variables d'environnement  
**Support desktop** : ✅ Oui (testé dans les unit tests)  
**Source** : `codex/codex-rs/core/src/config/config_tests.rs:545b920721431197`

```toml
[mcp_servers.docs.env_http_headers]
Authorization = "AUTH_TOKEN_VAR"
X-Custom-Header = "CUSTOM_VAR"
```

### 4. `http_headers_helper`

**Champ exact** : `http_headers_helper`  
**Fichier de configuration** : `config.toml` section `[mcp_servers.<nom>]`  
**Fonctionnement** : Exécute un helper externe pour générer dynamiquement les headers  
**Support desktop** : ✅ Oui (mentionné dans les tests)  
**Source** : `codex/codex-rs/cli/tests/mcp_list.rs:04de5f7550e60158`

```toml
[mcp_servers.docs]
url = "https://example.com/mcp"
http_headers_helper = {helper}
```

### 5. Commande CLI `codex mcp add`

**Mécanisme** : Interface en ligne de commande pour ajouter des serveurs MCP  
**Support desktop** : ✅ Oui  
**Source** : `codex/codex-rs/cli/tests/mcp_add_remove.rs:0f95c4eda418d01e`

```bash
codex mcp add github --url "https://example.com/mcp" --bearer-token-env-var "GITHUB_TOKEN"
```

## Note de l'intégrateur (Claude, 26/10 22 h 50) — conclusion RECTIFIÉE

La recommandation ci-dessous (`bearer_token_env_var` + un helper qui *lance* Codex) est la **voie (a)**, celle du
lanceur. Elle ne couvre pas la voie (b) : Codex desktop ouvert depuis Windows ne passe par aucun lanceur, et la
variable devrait alors vivre dans HKCU, ce que la décision owner veut supprimer.

La vraie voie (b) est le mécanisme 4 trouvé par cette enquête, **`http_headers_helper`**, vérifié au RAG le 26/10 :
- `codex/codex-rs/core/config.schema.json` : `"http_headers_helper": {"type": "string"}` dans la config d'un serveur MCP ;
- `codex/codex-rs/cli/src/mcp_cmd.rs` : `apply_http_headers_helper(http_client, server, config.cwd)` enveloppe le
  client HTTP du serveur MCP ;
- `codex/codex-rs/cli/tests/mcp_list.rs` (`list_and_get_redact_http_headers_helper`) : la valeur est une COMMANDE
  shell (`echo invoked > ...`) ; `codex mcp list/get` l'affichent `<redacted>` et ne l'exécutent PAS.

Donc : `http_headers_helper = "<commande qui lit le coffre et rend l'en-tête>"` dans `config.toml`, commande exécutée par
Codex lui-même au moment de l'appel → aucun jeton en clair dans la config ni dans HKCU, pour le CLI comme pour le
desktop. **Reste à MESURER en bac à sable** (sans toucher le profil owner) : le FORMAT de sortie attendu de la commande
(JSON d'en-têtes ? ligne `Nom: valeur` ?) et le moment d'exécution (au démarrage, à chaque requête, au renouvellement) —
la définition de `apply_http_headers_helper` (crate `codex_mcp`) n'est pas au RAG.

## Analyse de la Voie (b) - Jeton Court depuis Helper

### Scénario proposé

1. **Lancement manuel** de Codex desktop
2. **Exécution d'un petit helper** Windows (trousseau/coffre)
3. **Lecture du jeton court** depuis une variable d'environnement temporaire
4. **Transmission à Codex** via `bearer_token_env_var` ou `env_http_headers`

### Évaluation de la faisabilité

**Avantages** :
- ✅ **Pas de stockage en clair dans HKCU** (registre Windows)
- ✅ **Utilisation de variables d'environnement temporaires**
- ✅ **Support natif par Codex** via `bearer_token_env_var`
- ✅ **Jetons courts** (limité dans le temps si implémenté)

**Risques identifiés** :
- ⚠️ **Variable d'environnement visible** pendant l'exécution de Codex
- ⚠️ **Pas de chiffrement natif** de la variable d'environnement
- ⚠️ **Nécessite un processus séparé** pour injecter le jeton

### Implémentation recommandée

```toml
[mcp_servers.nokido_hub]
url = "http://localhost:8766"
bearer_token_env_var = "NOKIDO_MCP_TOKEN"
startup_timeout_sec = 5.0
```

Avec un helper Windows qui :
1. Récupère le jeton depuis le coffre Nokido
2. Définit la variable `NOKIDO_MCP_TOKEN`
3. Lance Codex desktop

## Conclusions

### Réponse à la question principale

**OUI, la voie (b) est techniquement réalisable sans laisser de jeton en clair dans HKCU**, sous réserve des conditions suivantes :

1. **Utilisation de `bearer_token_env_var`** pour la lecture du jeton depuis l'environnement
2. **Processus helper temporaire** pour injecter le jeton sans persistance
3. **Variables d'environnement temporaires** (non persistées après l'exécution)

### Recommandations

1. **Privilégier `bearer_token_env_var`** plutôt que `http_headers` pour éviter le stockage en clair
2. **Implémenter un helper Windows sécurisé** qui nettoie les variables après usage
3. **Utiliser des jetons à courte durée de vie** pour minimiser les risques
4. **Éviter tout stockage persistant** du jeton sur le disque ou dans le registre

### Sources principales

- `codex/codex-rs/core/src/config/config_tests.rs` - Tests unitaires de configuration
- `codex/codex-rs/cli/tests/mcp_add_remove.rs` - Tests CLI d'ajout de serveurs
- `codex/codex-rs/cli/tests/mcp_list.rs` - Tests de listing et configuration helper

---

*Ce rapport a été généré par OPENCODE_GLM le 26/10/2026 dans le cadre de l'enquête sur l'authentification hybride de Codex desktop.*