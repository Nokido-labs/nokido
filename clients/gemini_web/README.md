# Client Gemini Web — Connecteur des Pairs Nokido

Client navigateur sous forme d'userscript Tampermonkey (`nokido_pair.user.js`) permettant à **Gemini Web** (`https://gemini.google.com`) d'interagir avec le connecteur des pairs de Nokido (`tools/forge_pair_mcp.py`), avec les **mêmes garanties de sécurité que ChatGPT web**.

---

## 🛡️ Garanties & Posture de Sécurité

1. **Surface figée** : seuls les 10 outils du connecteur des pairs sont accessibles (5 de lecture, 5 de quarantaine/suivi).
2. **Quarantaine stricte** : tout texte déposé entre dans `agent_messages` au statut `quarantaine` dans la boîte `OWNER_APPROBATION`, sous la provenance `gemini_web` et le marquage `EXTERNE_NON_VERIFIEE`. Aucune instruction n'est exécutée directement.
3. **Transport HTTPS strict & Confinement d'Origine** : toutes les requêtes passent par `GM_xmlhttpRequest` en `https://` exclusif et font l'objet d'un contrôle d'exécution vérifiant l'origine exacte (même schéma `https:`, même hôte, même port) par rapport à l'URL publique sauvegardée. En cas de non-concordance, la requête est refusée et journalisée. Aucun appel vers un hôte divergent, aucun appel au hub local (`http://127.0.0.1:8766/mcp`), aucune lecture de fichier arbitraire.
4. **Authentification OAuth 2.1 PKCE** : aucun jeton en dur ni secret dans le code. Les jetons sont conservés dans le stockage isolé de l'extension (`GM_setValue`), inaccessibles au contexte JavaScript de la page. Le vérificateur PKCE est systématiquement supprimé du stockage dès l'échange effectué (succès ou échec).
5. **Aucun `eval` ni constructeur dynamique**.

---

## 🚀 Installation Rapide

1. **Installer un gestionnaire d'userscripts** : [Tampermonkey](https://www.tampermonkey.net/) ou Violentmonkey sur votre navigateur.
2. **Ajouter le script** :
   - Créer un nouveau script dans Tampermonkey.
   - Coller l'intégralité du fichier [`nokido_pair.user.js`](./nokido_pair.user.js).
   - Enregistrer (`Ctrl+S`).
3. **Ouvrir Gemini Web** :
   - Se rendre sur `https://gemini.google.com`.
   - Le bouton flottant **🪐 Nokido Pair** apparaît en bas à droite.
4. **Authentification** :
   - Renseigner l'URL publique de votre serveur de pairs (ex: `https://nokido-pair.votre-domaine.com`).
   - Cliquer sur **OAuth (Appariement)**.
   - Dans l'onglet ouvert, renseigner le code d'appariement de l'opérateur et valider.
   - De retour sur Gemini Web, le voyant passe au vert.
5. **Verrouillage de l'Hôte (`@connect`)** :
   - Dans l'en-tête du script Tampermonkey, la directive initiale `// @connect *` autorise la configuration initiale.
   - **Après avoir configuré votre URL publique**, remplacez `*` par l'hôte exact de votre serveur de pairs (ex: `// @connect pair.votre-domaine.com`). Cela garantit un double verrouillage : navigateur/extension via `@connect` et exécution applicative via le contrôle d'origine strict.

---

## 📖 Utilisation

- **Lecture** : cliquer sur un bouton de lecture (`État Corps`, `SSoT Roadmap`, `SSoT Rules`, `Dernière Capsule`, `Commits Récents` ou `Recherche RAG`) pour insérer directement les données rédigées dans le prompt de saisie de Gemini.
- **Quarantaine** : cliquer sur **📋 Capturer la dernière réponse de Gemini**, puis soumettre une proposition SSoT (`proposer_fait`) ou un message M2M (`envoyer_message`). Le dépôt attend l'approbation de l'owner (`tools/forge_pair_quarantaine.py --approuver <ID>`).
- **Suivi** : suivre l'avancement d'un dépôt (`suivre`) ou relever les messages et capsules adressés à `PAIR:gemini_web` (`lire_reponses`).
