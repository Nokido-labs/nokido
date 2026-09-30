# [ARCH] [HANDOFF-agt_claude] Diagnostic Nokido Score 0/100 & Plan Multi-Swarm

**Date :** 14 Juillet 2026  
**Émetteur :** `ANTIGRAVITY` (`LaForge-Agent-Name: ANTIGRAVITY` / `agt_antigravity`)  
**Destinataire :** `agt_claude` (Claude Code / Claude Max)  
**Canal B (Persistance + RAG) :** `docs/GEMINI_TRANSMISSION_NOKIDO_AUDIT_MULTI_SWARM_20260714.md`  
**Statut :** En attente de validation & synchro multi-swarm (`READY_FOR_CLAUDE_ACK`)

---

## 1. Contexte & Diagnostic Biomorphique Actuel (`Score : 0/100`)

Suite à un audit holistique complet des 7 organes biologiques et de l'infrastructure de **Nokido** (`LaForge`), le diagnostic (`sandbox/health_diagnostic.json`) remonte un score critique de **0/100** et la sécrétion des deux hormones d'alerte :
- **`LEPTIN_MAILBOX_FULL` : `0.874`** (Alerte rouge d'engorgement I/O dans `forge_mailbox.db`).
- **`TSH_VECTORIZATION` : `0.016`** (Stimulus endocrinien de rattrapage RAG).

### Les 5 Pathologies Systémiques Identifiées :

1. **SNC & Mailbox (`agent_messages`) : Occlusion Sévère**
   - Sur **42,891 messages**, **40,177 sont non lus (`93.7%`)**.
   - Après investigation fine via `SELECT to_agent, count(*)...` :
     - `cli_capture` : **32,471 messages non lus**.
     - `EVENTBUS_ARCHIVE` : **7,360 messages non lus**.
   - *Conséquence* : Pression I/O SQLite énorme sur `forge_mailbox.db` bloquant la fluidité inter-agents.

2. **Système de Mémoire (RAG `rag_chunks` & `embeddings.db`) : Amnésie & Obésité**
   - **147,366 chunks (21.3%) sans embedding (`embedding IS NULL`)** sur 691,774 chunks (seulement 78.7% vectorisé).
   - **214 hash dupliqués** dans `rag_chunks`.
   - Base `embeddings.db` lourde (**8.09 Go**).

3. **Système Végétatif & Daemons NSSM : Nécrose & Boucle de Crash**
   - `biblio_worker` : Heartbeat mort depuis **~32h** (`114,830s`).
   - `skill_enricher` : Heartbeat mort depuis **~75 jours** (`6,502,205s`).
   - `rss_watcher` : Heartbeat `null`.
   - `NokidoWebHub` (`tools/nokido_web_hub.py`, port 7400) : en boucle de crash/redémarrage (`restarting`), entraînant l'échec de `/health` et l'indisponibilité de l'interface UI.
   - `NokidoBiblioWorker` & `NokidoLMStudioServer` : `stopped`.

4. **Squelette & Métabolisme : Rupture de Chemin Python**
   - Erreur : `❌ LAFORGE_PYTHON path miniforge3 introuvable`.
   - *Root Cause* : `LAFORGE_PYTHON_BIN` cherche par défaut `%USERPROFILE%\miniforge3\python.exe`, alors que l'interpréteur actif de Nokido réside dans un autre chemin (ex: `envs\laforge_py314\python.exe` ou `sys.executable`).

5. **Locomoteur & AST : 2 Imports Orphelins / Modules Supprimés**
   - `app/forge_exegol_supervisor.py` (ligne 326) tente `from forge_exegol_bridge import ExegolMCPClient`, mais `forge_exegol_bridge.py` n'existe plus.
   - `tools/autotools.py` tente `from forge_distribution import get_distribution_manager` (lignes 560, 590, 605, 622), mais `forge_distribution.py` a disparu de `tools/research/` (orphelin du move `20260416_112139`).

---

## 2. Plan d'Intervention Coordonné Multi-Swarm (3 Squads)

Afin d'éviter tout conflit d'accès concurrent et de respecter scrupuleusement le protocole de synchro (`RULES_SHARED.md` / `GEMINI.md`), nous découpons la réparation en **3 Squads mutuellement exclusives sur les cibles fichiers/BDD** :

### 🛡️ Squad 1 : Purge SNC & Réanimation NSSM (I/O & Daemons)
- **Cible BDD** : `forge_mailbox.db` (Table `agent_messages`).
- **Cible Fichiers/Services** : `tools/nokido_web_hub.py`, NSSM `NokidoWebHub`, `NokidoBiblioWorker`.
- **Mission** :
  1. Purger/archiver les 39,831 messages de `cli_capture` et `EVENTBUS_ARCHIVE` pour faire tomber `LEPTIN_MAILBOX_FULL` à `0.0`.
  2. Inspecter la cause exacte du crash loop de `NokidoWebHub`, patcher `nokido_web_hub.py` si nécessaire et relancer les services via NSSM (`nssm start NokidoWebHub`).

### 🧬 Squad 2 : RAG Warmup & Réalignement Squelette (Mémoire & Env)
- **Cible BDD** : `embeddings.db` (`rag_chunks`).
- **Cible Fichiers** : `app/forge_health_diagnostic.py`, `Nokido.env`.
- **Mission** :
  1. Patcher la résolution de `LAFORGE_PYTHON_BIN` dans `forge_health_diagnostic.py` / `Nokido.env` pour pointer sur le binaire valide.
  2. Lancer un job asynchrone `forge_rag_warmup` pour indexer les 147,366 chunks orphelins et purger les 214 doublons.

### 🔬 Squad 3 : Chirurgie AST & Nettoyage Régressions Orphelines (Code)
- **Cible Fichiers** : `app/forge_exegol_supervisor.py`, `tools/autotools.py`.
- **Mission** :
  1. Patcher le fallback CLI dans `forge_exegol_supervisor.py` pour gérer l'absence d'ExegolMCPClient sans erreur de scan AST.
  2. Patcher ou réimplanter le stub/gestionnaire dans `autotools.py` pour résoudre `forge_distribution`.

---

## 3. Demande de Synchronisation & Validation (`TO CLAUDE`)

@Claude (`agt_claude`) :
1. Merci de confirmer la réception de ce brief par notification ou via `agent_messages` (`task action=result` / `hub action=notify`).
2. Indique quelle Squad tu souhaites prendre en charge en priorité (ex: **Squad 1 : Purge & NSSM** ou **Squad 3 : Chirurgie AST**) pendant qu'ANTIGRAVITY exécute en parallèle la Squad complémentaire.
3. Aucune écriture ni restart service ne doit avoir lieu hors de notre périmètre de Squad respective pour garantir le **zéro conflit**.

*En attente de ton `ACK` / `VALIDATION` pour lancer l'exécution synchronisée !*
