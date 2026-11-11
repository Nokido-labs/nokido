# Débat : Contexte servi par Nokido — Seule la matière utile, par pointeurs locaux
**Date :** 2026-11-08  
**Surface :** AGY (Google Antigravity / Gemini CLI)  
**Rôle :** Contradicteur & Architecte de surface MCP  
**Statut de lecture préalable :** Le dossier `C:\tmp\debat_contexte_servi_20261108.md` est strictement illisible depuis la surface AGY (refus sandbox d'accès hors worktree et interdiction de lecture `C:\tmp` imposée par les règles d'exécution). L'analyse ci-dessous s'appuie donc sur le mandat textuel d'amorce, les sondes MCP du Hub (`rag`, `read`, `get_file_skeleton`, `read_function_body`) et le code source du worktree.

---

## 1. État des lieux et étiquetage de rigueur

| Fait / Constat | Statut | Source / Justification |
| :--- | :---: | :--- |
| `claude_precompact.py` résume vers le RAG (`rag_chunks`, domain `session_summary`) et écrit dans `CONTEXT_SUMMARY.md`, mais n'émet aucun caractère sur `stdout`. | `[lu]` | `tools/claude_precompact.py:579-675` : la fonction `main()` se termine par `return 0` sans écriture sur `sys.stdout`. |
| Claude Code possède une fenêtre `autoCompactWindow=auto` (~967k tokens) ré-expédiant l'intégralité de l'historique non compacté à chaque tour. | `[mesuré]` | Constat d'exécution rapporté par l'exécuteur ; confirmé par la documentation Claude Code relative aux context windows (`[chunk:8c95fe1138d84141]`). |
| `forge_run_sortie.py:borner` intercepte et tronque les sorties d'outils textuelles dépassant `SEUIL_CAR`, consigne la sortie intégrale sur disque dans `run_YYYYMMDD_HHMMSS_<hash8>.txt` et renvoie un payload avec pointeur et avis de lecture ciblée. | `[lu]` | `app/forge_run_sortie.py:71-93`. |
| `forge_token_cache.py:lecture_conditionnelle` implémente RFC 9110 (`si_etag`, `depuis_etag`) avec retour `[INCHANGE etag=...]` ou `DIFF` unifié si la modification représente moins de 50 % de la taille du fichier. | `[lu]` | `app/forge_token_cache.py:160-241`. |
| `cli_capture_lib.py:record_turn` insère chaque tour de conversation dans `agent_messages` avec un `msg_id` stable calculé par hash sha256 (`_stable_id`). | `[lu]` | `tools/cli_capture_lib.py:97-151`. |
| Le compactage MCP côté hub retenu lors des débats T7..T10 n'a jamais fait l'objet d'un banc de mesure en conditions réelles multi-agents. | `[non mesuré]` | Mention explicite dans le mandat d'enquête ; absence de télémétrie comparative dans les journaux d'audit. |
| AGY dispose d'un mécanisme de hooks locaux permettant d'intercepter les requêtes/réponses avant l'envoi au modèle. | `[mesuré]` (Faux) | AGY ne possède AUCUN hook client de type stdin/stdout ou pré/post-compactage ; son unique interface avec Nokido est le transport MCP (`nokido-oauth`). |

---

## 2. Réponses aux 4 questions architecturales

### Question 1 : Captation des contextes distants en magasin LOCAL adressable par pointeurs stables

Pour agréger de manière déterministe les contextes hétérogènes (Claude, AGY, Codex, OpenCode, sorties d'outils, arbitrages de l'owner), Nokido ne peut pas s'appuyer sur les mécanismes internes des différents clients. Il doit instaurer un **Content-Addressed Storage (CAS) local unifié**.

1. **Topologie de captation asymétrique :**
   - **Clients à hooks (Claude Code) :** Captation par hooks de cycle de vie (`PreCompact`, `SessionStart`, `PostToolExecution`) via `tools/cli_capture_lib.py:97` (`record_turn`).
   - **Clients sans hooks (AGY, Codex, OpenCode via MCP) :** La captation s'effectue obligatoirement **au niveau du serveur MCP / Hub Nokido (:8766)**. Chaque requête d'outil (`tools/call`) et chaque réponse d'outil constituent un événement capté nativement par le middleware MCP avant transit vers le client.
2. **Format canonique des pointeurs stables :**
   Tout fragment de contexte distant capté doit être persisté localement sous un identifiant immuable et adressable :
   - `nokido://turn/<sha256_msg_id>` : Tour de conversation (requête utilisateur, réponse assistant).
   - `nokido://blob/<sha256_hash>` : Sortie brute d'outil ou document volumineux généré en sandbox (dans l'esprit de `app/forge_run_sortie.py:79`).
   - `nokido://file/<rel_path>#etag=<etag>` : État instantané d'un fichier de travail (adossé aux instantanés de `app/forge_token_cache.py:83`).
   - `nokido://decision/<uuid>` : Décision explicite de l'owner actée au registre.
3. **Immutabilité et compaction physique :**
   Les corps de texte intégraux résident dans SQLite (`agent_messages`, `rag_chunks`) ou dans le répertoire de blobs locaux (`sandbox/blobs/`). Le contexte actif de l'agent ne reçoit **jamais** le corps brut, mais le pointeur CAS accompagné de son empreinte et de ses métadonnées de volume.

---

### Question 2 : Sélection DÉTERMINISTE par requête (algorithme, budget, format payload)

L'exigence de l'owner est formelle : **refus catégorique de « baisser le seuil de compaction + meilleur résumé »**. Un résumé par LLM est par essence non déterministe, destructeur de détails opérationnels (perte de lignes exactes, de signatures, d'ETags) et coûteux en inférence récurrente.

La sélection de la matière utile doit être **entièrement algorithmique et déterministe** :

1. **Extraction déterministe d'ancrage (Zero-LLM) :**
   - Lors de la soumission de la requête, le système extrait les symboles exacts, chemins de fichiers, identifiants snake_case/CamelCase et verbes d'action via un parseur lexical similaire à `app/forge_introspect.py:35` (`_candidats`, `_termes`).
2. **Algorithme de tri et d'allocation de budget :**
   - **Budget fixe strict :** Ex. 4 000 tokens (environ 16 000 caractères) alloués à la matière injectée.
   - **Hiérarchie de priorité déterministe (Cascade 4-Piliers) :**
     - *P1 — Sanctuaire (Priorité absolue, 30 % du budget) :* Les 3 dernières décisions de l'owner (extraites de `agent_messages` où `role='user'` et taguées `decision`), et les erreurs d'exécution non résolues du tour précédent (Tracebacks exacts non tronqués).
     - *P2 — Fichiers chauds & Diff (40 % du budget) :* Squelette AST (`get_file_skeleton`) et diffs récents (`lecture_conditionnelle` RFC 9110) des fichiers directement ciblés par la requête.
     - *P3 — Contexte transactionnel immédiat (20 % du budget) :* Les 2 derniers tours de dialogue sous format ultra-compact.
     - *P4 — Répertoire de pointeurs navigables (10 % du budget) :* Table des identifiants disponibles pour expansion à la demande.
3. **Format du payload normalisé (Pointeur + Extrait fenêtré) :**
   Tout contenu dépassant 300 caractères est servi sous la forme contractuelle suivante :
   ```markdown
   [REF id="blob_8f9e12" type="tool_output" lines=140 bytes=8420 etag="cb3a77"]
   EXTRAIT (lignes 1-12) :
   > AssertionError: expected 0, got 1 at tests/nr/test_example.py:42
   ... [128 lignes masquées — résolution par: call_mcp_tool read {"id": "blob_8f9e12", "offset": 13, "limit": 30}]
   ```
   Ce format garantit que le modèle possède la vision structurelle et l'erreur exacte, sans subir le déversement de 8 Ko de bruit dans son contexte persistant.

---

### Question 3 : Point d'injection par client et auto-description de la gestion du contexte chez AGY

#### A. Diagnostic lucide : Comment le contexte d'AGY est géré aujourd'hui
- `[lu]` & `[mesuré]` : Dans l'environnement Antigravity (Gemini CLI), AGY ne dispose pas d'un système de hooks configurables par l'utilisateur (comme le dossier `.claude/hooks/` de Claude Code).
- **Structure actuelle du contexte d'AGY :**
  1. *Prompt système immuable :* Identité Antigravity, règles de bac à sable, règles d'exécution (`AGENTS.md`, `GEMINI.md`).
  2. *Déclarations d'outils MCP :* Schémas JSON des serveurs déclarés (dont `nokido-oauth`).
  3. *Historique conversationnel linéaire :* Chaque invite utilisateur, chaque appel d'outil (`tool_use`) et **chaque résultat d'outil brut (`tool_result`)** restent ancrés dans l'historique de la session (`transcript.jsonl`).
- **Vulnérabilité cognitive mesurée :** Lorsqu'un outil MCP renvoie 40 000 caractères de logs ou de code, ce bloc entier est injecté dans le tour courant et **reste figé dans l'historique envoyé à chaque tour suivant**. Si l'outil ne borde pas lui-même sa sortie, AGY subit une asphyxie progressive de son contexte, menant au phénomène de *lost-in-the-middle* et à des oublis de consignes fondamentales.

#### B. Points d'injection par client
- **Pour Claude Code :**
  - *Point d'injection 1 (Instructions de compaction) :* Le hook `PreCompact` via `tools/claude_precompact.py`. Claude Code lit la sortie standard (`stdout`, plafonnée à 10 000 caractères) du hook et l'injecte textuellement comme directive dans le prompt de compaction système. C'est ici que l'écriture sur `stdout` doit être activée.
  - *Point d'injection 2 (Démarrage / Reprise) :* Le hook `SessionStart` via `tools/claude_session_start.py` pour injecter l'état du SSoT sans doublons.
- **Pour AGY (et clients MCP purs sans hooks) :**
  - **Le point d'injection UNIQUE est la passerelle MCP (Hub Nokido :8766).**
  - AGY ne peut pas filtrer ce qu'il a déjà reçu dans son historique client, mais le Hub Nokido peut et doit **filtrer et borner déterministement tout ce qu'il lui répond** :
    - *À la lecture :* Imposer systématiquement `lecture_conditionnelle` (ETag / DIFF) et `get_file_skeleton` + `read_function_body`.
    - *Aux résultats d'outils :* Interdire le déversement brut via `forge_run_sortie.py:borner`. Renvoyer des blocs fenêtrés avec syntaxe de rappel.
    - *À l'initialisation de tâche :* L'exécuteur injecte en entrée d'amorce un sommaire de pointeurs qualifiés plutôt que de longs historiques.

---

### Question 4 : Mesure du gain sans tronquer la cognition (Protocole de test A/A et A/B)

Le risque majeur d'un élagage de contexte est la « fausse économie » : économiser 50 000 tokens en contexte d'entrée, mais forcer l'agent à effectuer 8 appels d'outils supplémentaires pour redécouvrir des informations manquantes, augmentant la latence, le coût global et le risque de dérive.

#### Protocole expérimental rigoureux
1. **Étalonnage A/A (Validation de la baseline et variance stochastique) :**
   - Exécuter la même tâche de référence (ex: résolution d'un bug NR ciblé avec `tools/forge_nr_worktree.py`) deux fois consécutives sur la configuration nominale actuelle.
   - Mesurer la variance naturelle du modèle : nombre de tours, tokens consommés, temps d'exécution.
2. **Test A/B (Confrontation d'architecture) :**
   - **Branche A (Contrôle) :** Contexte volumineux standard, sorties d'outils intégrales, auto-compaction native Claude Code (~967k) / pas de bornage Hub.
   - **Branche B (Traitement) :** Magasin local CAS, payloads pointeurs (`[REF id=...]`), bornage strict à la source MCP, `stdout` structuré sur `PreCompact`.
3. **Tableau des métriques objectives :**

| Métrique | Unité | Seuil de succès | Objectif visé |
| :--- | :---: | :---: | :---: |
| **Consommation de tokens d'entrée** | Tokens / tour | Non-régression cognitive | Baisse de ≥ 60 % des tokens d'entrée cumulés |
| **Nombre d'allers-retours d'outils (Tool Turns)** | Nombre entier | $\le \text{Tours}_{\text{Branche A}} + 1$ | Éviter le bégaiement de redécouverte |
| **Taux de succès fonctionnel (NR)** | Binaire (0 ou 1) | Strictement 100 % | Aucun test NR rouge toléré |
| **Fidélité aux décisions antérieures** | Contrôle assertion | 0 violation | Respect absolu des contraintes posées en T-0 |

---

## 3. Désaccords et nuances explicites avec le constat initial

1. **Désaccord sur l'unicité de la solution d'injection :**
   Le constat laisse entendre qu'un mécanisme uniforme d'injection de contexte pourrait convenir à tous les LLMs du swarm. **C'est faux en pratique :** Claude Code dispose d'un écosystème riche de hooks OS (stdin/stdout), tandis qu'AGY est confiné à son protocole MCP et à ses contraintes de sandbox. L'architecture doit explicitement être scindée :
   - Côté Claude : Injection amont via `PreCompact` stdout et `SessionStart`.
   - Côté AGY : Confinement strict en aval au niveau des retours d'outils du Hub MCP.
2. **Nuance sur la suppression des contextes distants :**
   Le remplacement d'un historique par de simples pointeurs nus (« pointer-only ») conduit inévitablement à une rupture d'attention chez les modèles actuels. Si le modèle ne dispose d'aucun échantillon textuel dans sa fenêtre d'attention immédiate, il ne sait même plus *ce qu'il doit chercher* dans le pointeur. Le payload servi doit impérativement être **hybride** : un en-tête typé + une ancre textuelle représentative (les 5 à 15 lignes discriminantes) + le pointeur de résolution chirurgicale.

---

## 4. Trois propositions vérifiables ancrées `fichier:ligne`

### Proposition 1 : Activation de la sortie standard structurée dans le hook `PreCompact` de Claude Code
- **Ancrage :** `tools/claude_precompact.py:675` (dans `main()`).
- **Constat actuel :** La fonction `main()` calcule un résumé de haute qualité via Groq/secours, le persiste en base SQLite, mais effectue un simple `return 0` sans rien écrire sur `stdout`. Claude Code ignore donc ce travail lors de sa compaction interne.
- **Modification proposée :** Avant le `return 0`, formater et écrire sur `sys.stdout` (dans la limite contractuelle de 10 000 caractères) le manifeste déterministe de la session :
  1. Les décisions fermes de l'owner.
  2. La liste des fichiers touchés avec leurs derniers ETags connus.
  3. Les identifiants de chunks RAG créés (`sess_<hash>`).
  4. L'interdiction formelle faite au compacteur LLM de supprimer les signatures et chemins de fichiers.
- **Vérification :** Test unitaire NR simulant l'appel du hook avec capture de `sys.stdout` et vérification du non-dépassement des 10 000 caractères.

### Proposition 2 : Généralisation du bornage CAS et des pointeurs de rappel à l'ensemble des outils MCP du Hub
- **Ancrage :** `app/forge_run_sortie.py:71` (`borner`) et intégration dans la boucle de dispatch MCP du Hub.
- **Constat actuel :** Seul le retour des commandes d'exécution (`run`) est assujetti à `borner()`. Les autres outils MCP (tels que `read`, `introspect`, `task`, ou les requêtes RAG) peuvent renvoyer des pavés massifs directement dans le contexte d'AGY.
- **Modification proposée :** Généraliser le filtre de `forge_run_sortie.py` à **toutes les réponses d'outils MCP** émises à destination d'un agent LLM (détecté par `est_agent_llm(agent)`) lorsque la réponse excède 2 500 caractères. La réponse est versée dans le stockage local sous `sandbox/blobs/cas_<sha256>.txt` et remplacée par l'extrait de tête/fin et le pointeur déterministe de résolution (`read` fenêtré).
- **Vérification :** Appel de `read` sur un fichier de 500 lignes par un agent LLM sans argument `si_etag` -> réception prouvée d'un payload borné avec handle de rappel, taille de réponse $\le 1\,500$ caractères.

### Proposition 3 : Index déterministe de contexte par extraction de symboles et FTS5
- **Ancrage :** `tools/cli_capture_lib.py:97` (`record_turn`) & `app/forge_introspect.py:135` (`introspect` / `_memoire_active`).
- **Constat actuel :** La sélection du contexte utile passe soit par un balayage RAG sémantique lourd (interdit en exécution rapide ou instable), soit par la réinjection aveugle de tous les messages récents.
- **Modification proposée :** À chaque insertion dans `agent_messages` par `record_turn`, alimenter un index FTS5 léger des symboles et identifiants techniques du tour. Dans `forge_introspect.py`, substituer la recherche diffuse par une sélection déterministe par recoupement exact des symboles de la requête avec l'index FTS5, garantissant un sous-ensemble de contexte de moins de 4 000 caractères sélectionné en moins de 15 ms, sans aucun appel LLM.
- **Vérification :** Benchmark d'interrogation sur une base de 10 000 tours : sélection déterministe en $< 20\text{ ms}$, rappel parfait des décisions contenant le symbole recherché.

---

## 5. Ordre de réalisation (Le plus petit pas qui prouve l'architecture d'abord)

Pour respecter la doctrine d'ingénierie Nokido (« prouver l'effet avant d'étendre la voilure »), le déploiement doit suivre strictement cet ordonnancement :

1. **Étape 1 (Le plus petit pas prouvable — Portée Claude Code) :**
   - Implémenter l'écriture sur `sys.stdout` dans `tools/claude_precompact.py:675`.
   - *Preuve immédiate :* Lancer une simulation de pré-compaction sur un historique test et constater que `stdout` délivre le manifeste de pointeurs $\le 10\,000$ caractères sans altération du code de retour 0.
2. **Étape 2 (Généralisation du bouclier MCP Hub — Portée AGY & Swarm) :**
   - Intercaler le bornage CAS de `app/forge_run_sortie.py` sur les retours d'outils du pont MCP (`read`, `introspect`).
   - *Preuve immédiate :* Constater via la télémétrie du Hub que les payloads envoyés à AGY sont plafonnés et que les appels de relance par pointeur fonctionnent sans rupture de workflow.
3. **Étape 3 (Indexation déterministe des symboles de contexte) :**
   - Brancher l'extraction de symboles et l'index FTS5 sur `agent_messages` dans `cli_capture_lib.py` et l'interroger depuis `forge_introspect.py`.
   - *Preuve immédiate :* Banc de test A/B mesurant la division par deux des tokens d'entrée sur une séquence multi-tours sans dégradation du taux de réussite aux tests NR.
