# Plan de Migration : Renommer LaForge & Forge vers Nokido

Ce document est un plan de migration détaillé destiné à guider la transition complète du projet **LaForge** vers le nouveau nom **Nokido**. L'objectif est de s'assurer qu'aucun service, script, tâche planifiée, ou import de code ne soit cassé lors de la migration.

---

## 📋 Résumé Global du Renommage
* **Dossier racine** : `%NOKIDO_ROOT%` ➔ `%NOKIDO_ROOT%` (ou `nokido`)
* **Préfixe des fichiers et modules** : `laforge_` ou `forge_` ➔ `nokido_` (ou restructuration propre des packages)
* **Services Windows (NSSM)** : `LaForgeMCP` ➔ `NokidoHub`
* **Configuration MCP** : `laforge-sovereign-hub` ➔ `nokido-sovereign-hub`
* **Variables d'environnement** : `LAFORGE_*` / `FORGE_*` ➔ `NOKIDO_*`
* **Compétences (Skills) Gemini** : `laforge-*` et `forge-*` ➔ `nokido-*`
* **Tâches planifiées Windows** : Dossier de tâches `LaForge` ➔ `Nokido`

---

## 🛠 Phase 0 : Sauvegarde & Préparation (Sécurité Avant Tout)

Avant de lancer le moindre script de modification, il convient d'exécuter ces étapes :

1. **Arrêter tous les services actifs** :
   ```powershell
   # Depuis la console administrateur
   nssm stop LaForgeMCP
   nssm stop NokidoWebHub
   nssm stop NokidoGraph
   nssm stop NokidoHebbian
   nssm stop NokidoLlamaNative
   nssm stop NokidoLlamaRouter
   nssm stop NokidoRSSWatcher
   nssm stop NokidoGeminiDaemon
   ```
2. **Faire une sauvegarde Git complète** :
   ```bash
   git add .
   git commit -m "pre-migration backup"
   git branch migration-nokido
   git checkout migration-nokido
   ```
3. **Backup physique de la base de données et des configs** :
   Créer une archive compressée du dossier `LaForge/RAG/` (`embeddings.db`, `quota_state.json`) et du fichier `.forge_brain.db`.

---

## 📁 Phase 1 : Renommage des Fichiers & Dossiers Système

### 1.1 Dossiers et Fichiers à la Racine du Projet
Renommer les éléments suivants dans `%NOKIDO_ROOT%\` :
* `dist_laforge/` ➔ `dist_nokido/`
* `laforge_persist/` ➔ `nokido_persist/`
* `transcripts_laforge/` ➔ `transcripts_nokido/`
* `laforge_boot.ps1` ➔ `nokido_boot.ps1`
* `laforge.lock` ➔ `nokido.lock`
* `.laforge.agent` ➔ `.nokido.agent`
* `.laforge_pids.json` ➔ `.nokido_pids.json`
* `LaForge.py.filehandler.bak` ➔ `Nokido.py.filehandler.bak`
* `LAFORGE_ATLAS.md` ➔ `NOKIDO_ATLAS.md`
* `LAFORGE_SKILLS.md` ➔ `NOKIDO_SKILLS.md`
* `interface_laforge_synthese.md` ➔ `interface_nokido_synthese.md`
* `laforge-lats-cerebras.lats_smoke_3.json` ➔ `nokido-lats-cerebras.lats_smoke_3.json`

### 1.2 Renommage ou Restructuration des Modules Python
Il y a deux approches possibles pour les centaines de fichiers `forge_*` dans `app/` :

* **Option A (Recommandée - Restructuration propre par sous-packages)** :
  Suivre la table de correspondance déjà définie dans [app/MIGRATION_PLAN.md](../app/MIGRATION_PLAN.md) pour déplacer les fichiers vers leurs dossiers respectifs (`core/`, `llm/`, `ui/`, `orchestration/`, `security/`, `hardware/`, `ctf/`) en supprimant le préfixe `forge_` ou en le remplaçant par `nokido_` (ex: `forge_rag_engine.py` ➔ `core/rag_engine.py`).
  
* **Option B (Directe - Simple remplacement de préfixe)** :
  Renommer tous les fichiers de `app/` commençant par `forge_` par le préfixe `nokido_` (ex: `forge_rag_engine.py` ➔ `nokido_rag_engine.py`).

---

## 💻 Phase 2 : Renommage du Code Source & Configuration

### 2.1 Remplacement des Chaînes de Caractères
Parcourir tous les fichiers `.py`, `.ts`, `.js`, `.json`, `.toml`, `.env`, `.bat`, et `.ps1` pour remplacer :
* `"LaForge"` (sensible à la casse) ➔ `"Nokido"`
* `"laforge"` ➔ `"nokido"`
* `"forge"` ➔ `"nokido"` (attention aux faux positifs dans le code général, ex. `forgex` ou mots contenant "forge", cibler précisément les termes liés à l'architecture).

### 2.2 Mise à jour des Variables d'Environnement
Dans `Nokido.env`, `Nokido.env.example`, `Nokido.env.secrets` et les scripts de chargement, renommer les préfixes de variables d'environnement :
* `LAFORGE_ENABLE_MULTI_LLM` ➔ `NOKIDO_ENABLE_MULTI_LLM`
* `LAFORGE_BRAIN_PYTHON` ➔ `NOKIDO_BRAIN_PYTHON`
* `LAFORGE_BRAIN_PORT` ➔ `NOKIDO_BRAIN_PORT`
* `LAFORGE_LLAMACPP_PORT` ➔ `NOKIDO_LLAMACPP_PORT`
* `LAFORGE_LLAMACPP_NATIVE_PORT` ➔ `NOKIDO_LLAMACPP_NATIVE_PORT`
* `LAFORGE_LLAMACPP_NATIVE_MODEL` ➔ `NOKIDO_LLAMACPP_NATIVE_MODEL`
* `LAFORGE_LLAMACPP_NATIVE_CTX` ➔ `NOKIDO_LLAMACPP_NATIVE_CTX`
* `LAFORGE_LLAMACPP_NATIVE_GPU` ➔ `NOKIDO_LLAMACPP_NATIVE_GPU`
* `LAFORGE_LLAMACPP_NATIVE_CHAT` ➔ `NOKIDO_LLAMACPP_NATIVE_CHAT`
* `LAFORGE_LMSTUDIO_BIN` ➔ `NOKIDO_LMSTUDIO_BIN`
* `LAFORGE_SKIP_LMSTUDIO` ➔ `NOKIDO_SKIP_LMSTUDIO`
* `LAFORGE_SKIP_LLAMACPP_NATIVE` ➔ `NOKIDO_SKIP_LLAMACPP_NATIVE`
* `LAFORGE_ENABLE_GEMINI_POLL` ➔ `NOKIDO_ENABLE_GEMINI_POLL`
* `FORGE_MCP_TOKEN` ➔ `NOKIDO_MCP_TOKEN`
* `FORGE_TOKEN_SERVICES` ➔ `NOKIDO_TOKEN_SERVICES`
* `FORGE_TOKEN_ANTIGRAVITY` ➔ `NOKIDO_TOKEN_ANTIGRAVITY`
* Le header HTTP `LaForge-Agent-Name` ➔ `Nokido-Agent-Name` (ou `X-Agent-Name`)

---

## 🖥 Phase 3 : Services Système & NSSM

### 3.1 Renommage du Service Core dans NSSM
Le service core qui fait tourner le hub s'appelle actuellement `LaForgeMCP` (sur le port 8766).
1. Supprimer l'ancien service :
   ```powershell
   nssm remove LaForgeMCP confirm
   ```
2. Créer le nouveau service `NokidoHub` :
   ```powershell
   nssm install NokidoHub "%USERPROFILE%\miniforge3\python.exe" "%NOKIDO_ROOT%\tools\nokido_hub.py"
   nssm set NokidoHub AppDirectory "%NOKIDO_ROOT%"
   nssm set NokidoHub DisplayName "Nokido Hub MCP"
   nssm set NokidoHub Start SERVICE_AUTO_START
   ```

---

## ⚙ Phase 4 : Configuration des Clients CLI & MCP

### 4.1 Mise à jour des `.mcp.json`
Modifier le nom du serveur dans les fichiers de configuration MCP pour qu'il s'appelle `nokido-sovereign-hub` :
1. Dans `%NOKIDO_WORKSPACE%\.mcp.json`
2. Dans `%NOKIDO_ROOT%\.mcp.json`
3. Dans la configuration globale de Claude Desktop / VSCode (ex: `AppData\Roaming\Claude\claude_desktop_config.json`) :
   ```diff
   - "laforge-sovereign-hub": {
   + "nokido-sovereign-hub": {
       "type": "http",
       "url": "http://127.0.0.1:8766/mcp",
       "headers": {
         "Authorization": "Bearer ...",
         "X-Agent-Name": "CLAUDE"
       }
     }
   ```

### 4.2 Dossier d'intégration MCP local
Renommer le dossier de configuration local de l'agent :
* `%USERPROFILE%\.gemini\antigravity-cli\mcp\laforge-sovereign-hub\` ➔ `%USERPROFILE%\.gemini\antigravity-cli\mcp\nokido-sovereign-hub\`

### 4.3 Planificateur de Tâches Windows
Renommer le dossier de tâches dans le Task Scheduler de Windows :
* Dossier `LaForge` ➔ `Nokido`
* Tâche `LaForge\WslPortProxyRefresh` ➔ `Nokido\WslPortProxyRefresh` (mettre également à jour le script PowerShell ou batch lié pour cibler la nouvelle racine `Nokido`).

---

## 🧠 Phase 5 : Compétences (Skills) de l'Agent

Renommer tous les dossiers de skills situés dans `%USERPROFILE%\.gemini\skills\` :
* `forge-anatomy` ➔ `nokido-anatomy`
* `forge-models` ➔ `nokido-models`
* `forge-security-scan` ➔ `nokido-security-scan`
* `forge-systematic-debugging` ➔ `nokido-systematic-debugging`
* `forge-tdd` ➔ `nokido-tdd`
* `forge-veille` ➔ `nokido-veille`
* `forge-veille-approfondie` ➔ `nokido-veille-approfondie`
* `forge-veille-rapide` ➔ `nokido-veille-rapide`
* `laforge` ➔ `nokido`
* `laforge-autonomie` ➔ `nokido-autonomie`
* `laforge-capability` ➔ `nokido-capability`
* `laforge-env` ➔ `nokido-env`
* `laforge-hub` ➔ `nokido-hub`
* `laforge-models` ➔ `nokido-models`
* `laforge-pipeline` ➔ `nokido-pipeline`
* `laforge-quota` ➔ `nokido-quota`
* `laforge-rag-sovereign` ➔ `nokido-rag-sovereign`
* `laforge-route` ➔ `nokido-route`

> [!IMPORTANT]
> Pour chaque dossier renommé, modifier le fichier `SKILL.md` à l'intérieur pour changer la clé `name:` dans le frontmatter YAML (ex: `name: laforge-env` ➔ `name: nokido-env`).

---

## 🧪 Phase 6 : Validation & Démarrage

1. **Vérification de la syntaxe Python** :
   ```powershell
   %USERPROFILE%\miniforge3\python.exe -m py_compile app/*.py
   ```
2. **Démarrer les services** :
   ```powershell
   nssm start NokidoHub
   # Attendre quelques secondes
   .\nokido_boot.ps1
   ```
3. **Lancer les tests de non-régression s'ils existent** :
   ```powershell
   %USERPROFILE%\miniforge3\python.exe -m pytest tests/
   ```
4. **Vérifier l'alignement inter-agents via le hub** :
   Exécuter les requêtes `hub action=whoami` et `hub action=poll` pour s'assurer que la communication HTTP MCP est opérationnelle sous la nouvelle configuration.
