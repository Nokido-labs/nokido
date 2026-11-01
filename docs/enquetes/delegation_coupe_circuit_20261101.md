# Enquête Délégation Sans Ping-Pong : Coupe-Circuit 3 États & Avertissement Assignation
Date : 2026-11-01
Auteur : ANTIGRAVITY (agt_antigravity)
Référence : Patron OmniRoute (Plan S3 de `docs/enquetes/omniroute_free_tier_quota_effort_20261030.md` §4-5)

## 1. Contexte & Problématique
Le 01/11 entre 10h27 et 10h35 (observé dans `sandbox/tasks.db`), 6 tâches assignées à `OPENCODE_NEMOTRON`, `OPENCODE_GPTOSS`, `OPENCODE_DEFAUT2/3` sont passées `running` puis ont été réaffectées en cascade toutes les ~30 secondes, parfois vers un exécuteur lui-même épuisé (NEMOTRON -> GPTOSS -> GLM), finissant toutes sérialisées sur `OPENCODE_GLM`.

Deux défauts conjoints ont causé ce comportement :
1. **Assignation aveugle (`task assign`)** : Le système acceptait en silence une tâche pour un agent en repos ou dont le modèle principal et le repli étaient déjà déclarés hors quota (`_opencode_hors_quota`).
2. **Coupe-circuit incomplet** : L'ancien coupe-circuit ne traitait que les pannes fournisseur par mise en repos brute, sans état intermédiaire `HALF_OPEN` permettant un essai contrôlé après un cooldown de 15 minutes, et ne filtrait pas systématiquement les cibles `OPEN` lors des réaffectations.

---

## 2. Architecture & Modifications Apportées

### A. Coupe-circuit 3 États (`tools/forge_task_executor.py`)
- **États** :
  - `CLOSED` : Fonctionnement normal.
  - `OPEN` : Enclenché après $N=2$ échecs consécutifs (sorties « vide », réaffectations ou pannes fournisseur). Durée de cooldown : 15 minutes (900 s, configurable via `LAFORGE_COUPE_CIRCUIT_COOLDOWN_S`).
  - `HALF_OPEN` : Transition automatique dès que le cooldown est écoulé. Une seule tâche d'essai en vol est autorisée (`autoriser_essai_half_open`). Si l'essai réussit (`enregistrer_succes_executeur`), retour à `CLOSED` et remise à zéro des compteurs. Si l'essai échoue (`enregistrer_echec_executeur`), réouverture immédiate en `OPEN`.
- **Statut en lecture pure** : `statut_coupe_circuit` calcule dynamiquement la transition `HALF_OPEN` sans écrire sur disque lors des lectures, évitant les effets de bord d'état passifs. L'écriture de transition et le verrouillage sont garantis par `autoriser_essai_half_open` ou `enregistrer_*`.
- **Propagation du paramètre temporel** : `_executeur_suspendu(agent, maintenant=None)` propage le paramètre temporel vers `executeur_en_repos(agent, maintenant=maintenant)`.
- **Persistance inter-processus** : Stocké sous `sandbox/opencode_coupe_circuit.json` (ou variable d'environnement `LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE`), écrit de manière atomique (`tmp -> replace`).
- **Garde de réaffectation et d'exécution** : `_reaffecter` et la boucle de délégation avant lancement excluent formellement toute cible `OPEN` et intègrent le verrou `autoriser_essai_half_open` pour ne pas saturer un exécuteur en convalescence.

### B. Avertissement & Proposition à l'Assignation (`app/forge_mcp_registry.py`)
- Extension de `_avertissement_agent(self, ag_raw)` :
  - Détecte si l'agent est non servi dans `services.toml`.
  - Détecte si l'exécuteur est en coupe-circuit `OPEN` (`statut_coupe_circuit`).
  - Détecte si l'exécuteur est hors quota (`_opencode_hors_quota`).
  - Propose les exécuteurs proches éligibles dans l'avertissement JSON de réponse au lieu d'accepter en silence.
  - Règle de résilience : un état illisible ou corrompu ne bloque pas et n'émet pas de faux refus (`UNKNOWN != NO`).

---

## 3. Matrice de Preuve (Affirmation | Preuve | État)

| Affirmation | Preuve & Mécanisme de Test | État |
| :--- | :--- | :--- |
| **(a) Refus / Avertissement à l'assignation sur agent OPEN ou hors quota** | `test_nr_a_assignation_executeur_open_ou_hors_quota_avertit_et_propose` dans `tests/nr/test_delegation_coupe_circuit_3_etats_nr.py` : assigne à un agent OPEN ou hors quota, vérifie la présence du motif explicite et des propositions d'agents éligibles de la même famille. | **VERT** (implémenté dans `app/forge_mcp_registry.py`) |
| **(b) 2 échecs consécutifs mènent à OPEN, 4e appel sauté** | `test_nr_b_deux_echecs_menent_a_open_et_quatrieme_appel_saute` : après 2 échecs successifs enregistrés (`enregistrer_echec_executeur`), statut passe à OPEN, `_executeur_suspendu` et `_peut_lancer_opencode` le bloquent. | **VERT** (implémenté dans `tools/forge_task_executor.py`) |
| **(c) Cooldown 15 min écoulé -> HALF_OPEN -> essai unique -> succès -> CLOSED** | `test_nr_c_cooldown_ecoule_half_open_essai_succes_closed` : simule le passage du temps (T0 + 901s), transition vers `HALF_OPEN`. Une 1ère tâche d'essai passe (`autoriser_essai_half_open`), une 2e concurrente est refusée. Après succès, l'état redevient `CLOSED`. | **VERT** (implémenté dans `tools/forge_task_executor.py`) |
| **(d) Réaffectation ne vise pas un agent OPEN** | `test_nr_d_reaffectation_ne_vise_pas_un_open` : quand le premier agent de repli est OPEN, `_reaffecter` saute vers le suivant éligible, et refuse si tous sont indisponibles. | **VERT** (implémenté dans `tools/forge_task_executor.py`) |
| **(e) Résilience aux états illisibles** | `test_nr_e_etat_illisible_ne_refuse_pas` : fichier coupe-circuit corrompu ou `services.toml` manquant ne lève aucune exception et retombe sur CLOSED/aucun avertissement (`UNKNOWN != NO`). | **VERT** (implémenté dans les deux modules) |
| **(f) Lecture pure de statut_coupe_circuit** | `test_statut_coupe_circuit_lecture_pure` : la transition OPEN -> HALF_OPEN après cooldown se calcule sans écriture fichier tant que `autoriser_essai_half_open` n'est pas appelé. | **VERT** (implémenté dans `tools/forge_task_executor.py`) |
| **(g) Non-régression exécuteur et chemin réel** | `test_executeur_coupe_circuit_opencode_nr.py`, `test_coupe_circuit_chemin_reel_nr.py`, `test_executeur_reaffecte_nr.py` : compatibilité ascendante avec les mécanismes de repos OpenCode existants. | **VERT** |
