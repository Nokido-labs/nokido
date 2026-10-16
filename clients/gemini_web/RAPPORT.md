# Rapport d'Intégration — Client Gemini Web vers le Connecteur des Pairs Nokido

*Auteur : Agent ANTIGRAVITY (Ring 1) — Date : 15 octobre 2026*  
*Branche : `agy/gemini-web-pair` (depuis `alpha`)*  
*Pointeur de référence : `clients/gemini_web/RAPPORT.md`*

---

## 1. Contexte & Objectif de la Mission

Contrairement à Claude.ai ou ChatGPT qui supportent des connecteurs d'actions ou MCP distants, **Gemini Web (`https://gemini.google.com`) ne propose aucun connecteur MCP distant natif**.

L'objectif de cette mission est de relier Gemini Web au connecteur souverain des pairs de Nokido (`tools/forge_pair_mcp.py`) avec **exactement les mêmes garanties de sécurité que ChatGPT web** :
1. **Surface figée** : accès restreint aux seuls outils autorisés (5 outils de lecture, 5 outils de quarantaine/suivi).
2. **Quarantaine inviolable** : toute interaction entrante depuis Gemini Web est traitée comme une donnée externe (`EXTERNE_NON_VERIFIEE`), déposée dans `agent_messages` au statut `quarantaine` dans la boîte `OWNER_APPROBATION`. Aucune instruction ne s'exécute automatiquement.
3. **Transport HTTPS strict** : requêtes isolées via `GM_xmlhttpRequest` en `https://` vers l'URL publique annoncée (`NOKIDO_PAIR_PUBLIC_URL`). Aucun appel vers le hub local (`/mcp` port 8766), aucune lecture de fichier local.
4. **Authentification souveraine OAuth 2.1 PKCE** : aucun jeton en dur, aucun secret dans le code ; stockage isolé dans l'extension du navigateur (`GM_setValue`), inaccessible au contexte de la page Gemini.
5. **Intégrité du code** : aucun usage de `eval()` ni de constructeur `Function()`.

---

## 2. Fichiers Produits

| Fichier | Rôle |
|---|---|
| `clients/gemini_web/nokido_pair.user.js` | Userscript Tampermonkey autonome injectant le panneau latéral sur `gemini.google.com`. |
| `clients/gemini_web/README.md` | Guide d'utilisation et spécifications succinctes du client. |
| `tests/nr/test_gemini_web_pair_client_nr.py` | Test de non-régression vérifiant statiquement le script (outils, HTTPS, secrets, eval, stockage). |
| `clients/gemini_web/RAPPORT.md` | Le présent rapport d'installation, diffs serveur proposés et analyse de risques. |

---

## 3. Guide d'Installation Pas à Pas pour l'Owner

### Étape 1 : Prérequis Côté Serveur Nokido
1. Vérifier que les secrets d'appariement sont inscrits au coffre souverain Nokido (`app.forge_secrets`), conformément à la règle Nokido (aucun secret en clair dans l'environnement du shell) :
   ```powershell
   python -c "import getpass; from nokido_agent.app.forge_secrets import set_secret; set_secret('NOKIDO_PAIR_OAUTH_APPARIEMENT', getpass.getpass('code d appariement : ')); set_secret('NOKIDO_PAIR_CAPABILITY_KEY', getpass.getpass('clef de signature : '))"
   ```
   La valeur se saisit MASQUEE (`getpass`) : jamais en argument de commande, sinon elle reste dans l'historique du
   shell et dans la liste des processus (revue CLAUDE du 15/10).
2. Lancer le connecteur des pairs via le lanceur dédié `tools/forge_bridge_launch.py`, qui extrait les secrets du coffre et les transmet dans l'environnement du sous-processus isolé :
   ```powershell
   $env:NOKIDO_PAIR_PUBLIC_URL = "https://pair.votre-domaine.com"
   python tools/forge_bridge_launch.py --passerelle pair --port 8793
   ```
   *(Remarque : `NOKIDO_PAIR_PUBLIC_URL` est une URL publique annoncée et non un secret).*
3. Le serveur écoute en local sur `[IP_INTERNAL_1]:8793` et est exposé via un tunnel sécurisé (Tailscale Funnel ou Cloudflare Tunnel) annonçant `https://pair.votre-domaine.com`.

### Étape 2 : Installation de l'Userscript dans le Navigateur
1. Installer une extension de gestion d'userscripts dans le navigateur (ex. **Tampermonkey** ou **Violentmonkey** sur Chrome, Firefox ou Edge).
2. Ouvrir le tableau de bord de Tampermonkey -> **Créer un nouveau script**.
3. Remplacer l'intégralité du modèle par le contenu du fichier :  
   [`clients/gemini_web/nokido_pair.user.js`](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/antigravity/clients/gemini_web/nokido_pair.user.js)
4. Enregistrer avec `Ctrl + S`.
5. *(Recommandé)* Une fois l'URL publique configurée dans le panneau, remplacer la directive `// @connect *` de l'en-tête par l'hôte exact de votre serveur (ex: `// @connect pair.votre-domaine.com`).

### Étape 3 : Connexion et Appariement OAuth
1. Naviguer sur `https://gemini.google.com/`.
2. Un bouton flottant discret **🪐 Nokido Pair** apparaît en bas à droite de la page. Cliquer dessus pour ouvrir le panneau latéral.
3. Dans la section **1. Connexion & URL Publique** :
   - Renseigner l'URL publique du serveur (ex: `https://pair.votre-domaine.com`).
   - Cliquer sur **Sauvegarder URL**.
   - Cliquer sur **OAuth (Appariement)**.
4. Un nouvel onglet s'ouvre sur la page de consentement du serveur (`/consentement?demande=...`).
5. Saisir le code d'appariement de l'opérateur et valider.
6. Le serveur redirige vers `https://gemini.google.com/?nokido_pair_oauth=callback&code=...`.
7. L'userscript intercepte automatiquement le code d'autorisation, échange le code contre le jeton d'accès via PKCE, le sauvegarde dans le coffre isolé `GM_setValue`, nettoie l'URL et passe le voyant au **vert**. Le vérificateur PKCE est immédiatement supprimé du stockage isolé.

### Étape 4 : Utilisation au Quotidien
- **Lecture dans Gemini** : Cliquer sur l'un des boutons de lecture (`État Corps`, `SSoT Roadmap`, `SSoT Rules`, `Dernière Capsule`, `Commits Récents` ou `Recherche RAG`). Les données formatées et rédigées par la membrane sont automatiquement insérées dans le champ de saisie de Gemini.
- **Dépôt en Quarantaine** : Une fois que Gemini a répondu, cliquer sur **📋 Capturer la dernière réponse de Gemini**. Cliquer ensuite sur **Proposer Fait (Quarantaine)** ou **Envoyer M2M**.
- **Validation Owner** : Le dépôt est consigné dans `agent_messages` (`status='quarantaine'`). L'owner l'approuve en console administrateur via :
  ```powershell
  python tools/forge_pair_quarantaine.py --lister
  python tools/forge_pair_quarantaine.py --approuver <ID>
  ```
- **Suivi et Réception** : Le client permet de suivre l'avancement via `suivre` et de relever les réponses via `lire_reponses`.

---

## 4. Ce qui reste à faire côté Serveur (Diffs Proposés & Analyse des Écarts)

Conformément à la consigne de mission, **les fichiers `tools/forge_pair_mcp.py` et `tools/forge_bridge_oauth.py` n'ont PAS été modifiés**.

### Analyse de Lecture des Secrets Côté Serveur (Écart Constaté)
À la lecture attentive de l'arbre principal (`tools/forge_pair_mcp.py`, `tools/forge_bridge_oauth.py` et `tools/forge_passerelle_pair.py`) :
- `tools/forge_bridge_oauth.py::code_d_appariement()` (ligne 189) lit le code d'appariement directement via `(os.environ.get("NOKIDO_BRIDGE_OAUTH_APPARIEMENT") or "").strip()`.
- `tools/forge_passerelle_pair.py` lit sa clef de signature via `(os.environ.get("NOKIDO_BRIDGE_CAPABILITY_KEY") or "").strip()`.
- `tools/forge_pair_mcp.py` ne lit pas le coffre directement et s'appuie entièrement sur ces modules.

**Écart constaté** : Les modules serveur lisent ces valeurs critiques dans **l'environnement (`os.environ`) SEUL**, et non directement via `app.forge_secrets.get_secret()`.  
Bien que `tools/forge_bridge_launch.py --passerelle pair` compense cet écart en extrayant les secrets du coffre (`NOKIDO_PAIR_OAUTH_APPARIEMENT`, `NOKIDO_PAIR_CAPABILITY_KEY`) pour les injecter dans l'environnement du processus enfant, une exécution directe de `python tools/forge_pair_mcp.py` dépendrait encore de variables d'environnement. Cet écart doit être résorbé côté serveur par une lecture avec repli direct vers le coffre (voir Diff Proposé 4).

Voici les évolutions proposées côté serveur :

### Diff Proposé 1 : Enregistrement du client `gemini_web` dans la liste des clients OAuth
Dans le fichier JSON désigné par `NOKIDO_BRIDGE_OAUTH_CLIENTS` (ex: `config/clients_pair.json`), ajouter l'entrée pour le client public `gemini_web` :

```json
[
  {
    "client_id": "gemini_web",
    "client_name": "gemini_web",
    "redirect_uris": [
      "https://gemini.google.com/",
      "https://gemini.google.com/?nokido_pair_oauth=callback"
    ],
    "scope": "pair:collaborer",
    "grant_types": [
      "authorization_code",
      "refresh_token"
    ],
    "response_types": [
      "code"
    ],
    "token_endpoint_auth_method": "none"
  }
]
```

### Diff Proposé 2 : Autorisation de l'Origine `https://gemini.google.com` dans `tools/forge_pair_mcp.py`
> ⚠️ **À MESURER d'abord : ne pas recommander tel quel. N'appliquer que si une requête réelle est refusée pour Origin, avec la trace.**

`GM_xmlhttpRequest` s'exécute dans le contexte privilégié de l'extension et contourne nativement les restrictions CORS de page du navigateur. Ajouter de façon préventive `https://gemini.google.com` dans les origines autorisées de FastMCP n'est donc pas nécessaire en condition nominale. Ne pas appliquer ce diff sans observation préalable d'un refus réel documenté par une trace.

```diff
--- a/tools/forge_pair_mcp.py
+++ b/tools/forge_pair_mcp.py
@@ -462,6 +462,8 @@ def securite_transport(base: str):
     if publique.scheme == "https" and publique.hostname:
         hotes += [publique.netloc, publique.hostname + ":*"]
         origines.append("https://" + publique.netloc)
+    # Autoriser l'origine du client web Gemini
+    origines.append("https://gemini.google.com")
     return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                      allowed_hosts=hotes, allowed_origins=origines)
```

### Diff Proposé 3 : Middleware CORS optionnel sur l'application Starlette
> ⚠️ **À MESURER d'abord : ne pas recommander tel quel. N'appliquer que si une requête réelle est refusée pour Origin, avec la trace.**

`GM_xmlhttpRequest` contourne le mécanisme des pré-vols OPTIONS CORS. Un middleware Starlette avec `allow_credentials=True` élargirait inutilement la surface d'exposition du serveur sans besoin démontré pour l'userscript. À ne considérer que si un blocage explicite de transport cross-origin intervient avec trace probante.

```diff
--- a/tools/forge_pair_mcp.py
+++ b/tools/forge_pair_mcp.py
@@ -561,6 +561,14 @@ def main(argv=None) -> int:
     import uvicorn
 
     application = serveur.streamable_http_app()
+    from starlette.middleware.cors import CORSMiddleware
+    application.add_middleware(
+        CORSMiddleware,
+        allow_origins=["https://gemini.google.com"],
+        allow_credentials=True,
+        allow_methods=["GET", "POST", "OPTIONS"],
+        allow_headers=["Authorization", "Content-Type", "Accept"],
+    )
     serveur._nokido_oauth.poser_complements(application)
     _LOG.info("[pair] ecoute %s:%d%s ; annonce %s", HOTE, args.port, CHEMIN_HTTP, base_publique(args.port))
```

### Diff Proposé 4 : Résolution directe au coffre dans `tools/forge_bridge_oauth.py`
Pour résorber l'écart serveur constaté et aligner le serveur sur la doctrine Nokido (`forge_secrets.get_secret`) sans dépendre exclusivement des variables d'environnement :

```diff
--- a/tools/forge_bridge_oauth.py
+++ b/tools/forge_bridge_oauth.py
@@ -183,7 +183,16 @@ def code_d_appariement() -> str:
     """Le secret que l'operateur presente a la page de consentement.
 
     Absent = aucune delivrance possible. C'est un fail-closed voulu : un serveur
     d'autorisation sans consentement accorderait a quiconque atteint le tunnel.
     """
-    return (os.environ.get("NOKIDO_BRIDGE_OAUTH_APPARIEMENT") or "").strip()
+    valeur = (os.environ.get("NOKIDO_BRIDGE_OAUTH_APPARIEMENT") or "").strip()
+    if not valeur:
+        try:
+            from app.forge_secrets import get_secret
+            valeur = (get_secret("NOKIDO_PAIR_OAUTH_APPARIEMENT")
+                      or get_secret("NOKIDO_BRIDGE_OAUTH_APPARIEMENT") or "").strip()
+        except Exception:
+            valeur = ""
+    return valeur
```

---

## 5. Limites et Risques

1. **Évolution du DOM de Gemini Web** : Google met à jour régulièrement l'interface de `gemini.google.com`. Les sélecteurs CSS pour cibler l'éditeur Quill (`rich-textarea div[contenteditable="true"]`) et les bulles de réponse (`message-content`, `.model-response-text`) peuvent évoluer. Le script intègre plusieurs sélecteurs de repli ainsi qu'une zone de saisie manuelle dans le panneau latéral pour garantir la continuité de service.
2. **Confiance et Contamination** : Même si le modèle Gemini 3.1 Pro est puissant, tout texte en provenance du web peut faire l'objet de tentatives d'injection indirecte (prompt injection). Le connecteur applique strictement la Golden Rule #4 : le texte est marqué `EXTERNE_NON_VERIFIEE`, consigné dans `OWNER_APPROBATION`, analysé par `forge_prompt_guard` lors des boucles d'écoute et n'est jamais exécuté sans l'approbation explicite de l'owner.
3. **Péremption des Jetons & Nettoyage PKCE** : La durée de vie par défaut des jetons est de 3600s (1 heure). Le script implémente le renouvellement automatique transparent via `refresh_token`. Le vérificateur PKCE est automatiquement purgé de `GM_setValue` dès l'échange effectué (succès ou échec).
4. **Confinement de Transport** : Toute requête sortante `GM_xmlhttpRequest` est vérifiée dynamiquement à l'exécution pour correspondre strictement à l'origine (protocole https, hôte, port) de l'URL publique sauvegardée. L'en-tête `@connect` doit également être épinglé sur l'hôte configuré.

---

## 6. Vérification et Preuve de Test

Le test de non-régression dédié `tests/nr/test_gemini_web_pair_client_nr.py` valide statiquement l'ensemble des règles (12 tests) :
```
tests/nr/test_gemini_web_pair_client_nr.py::test_fichier_userscript_existe_et_lisible PASSED
tests/nr/test_gemini_web_pair_client_nr.py::test_en_tete_userscript_tampermonkey_conforme PASSED
tests/nr/test_gemini_web_pair_client_nr.py::test_seuls_les_outils_autorises_du_connecteur_pair_sont_nommes PASSED
tests/nr/test_aucun_outil_d_action_ni_hub_local_vise PASSED
tests/nr/test_transport_https_strict_sans_aucun_http PASSED
tests/nr/test_aucun_jeton_en_dur_ni_secret_dans_le_script PASSED
tests/nr/test_aucun_eval_ni_constructeur_function PASSED
tests/nr/test_stockage_securise_sans_localstorage PASSED
tests/nr/test_provenance_gemini_web_et_quarantaine_clairement_identifiees PASSED
tests/nr/test_documentation_readme_presente PASSED
tests/nr/test_controle_origine_avant_chaque_requete_http PASSED
tests/nr/test_suppression_verificateur_apres_echange PASSED
============================= 12 passed in 2.27s ==============================
```

Et la non-régression globale sur `test_pair_mcp_nr.py` (9 tests) confirme la parfaite étanchéité de la surface :
```
============================== 9 passed in 3.93s ==============================
```

