# Enquête : Consigne coupée en silence à ~30 000 caractères sur le chemin OpenCode et AGY

- **Date** : 2026-11-09
- **Contexte** : Détection sur la tâche `job_e871edd7_1794245408_oauth_nkc_nb_cvt_task_assign` (OPENCODE_DEFAUT3) d'une consigne de 35 209 caractères (40 branches) tronquée à ~30 000 caractères (35 branches complètes), avec repli par défaut OpenCode et cause DELAI. Symptôme analogue sur AGY (lots 5, 12, 14 livrés 29/40).
- **Statut** : Concluante — Cause racine identifiée, prouvée en base et verrouillée par un test NR rouge.

---

## 1. Réponse à la question fermée

### Question
> Quelle ligne coupe la description entre `tasks.db` et le prompt reçu par l'agent (chemin OpenCode ACP vs chemin AGY) ? Ou bien la coupe est-elle côté OpenCode/modèle ?

### Réponse catégorique et prouvée

1. **Sur le chemin OpenCode (ACP)** :
   - **Ligne de coupure** : [`tools/forge_task_executor.py:316`](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/taches/antigravity_17caac47ce67/tools/forge_task_executor.py#L313-L316) dans la fonction `_extract_message`.
   - **Mécanisme** : Appelée par `_delegate_to_opencode` à la ligne [`tools/forge_task_executor.py:6444`](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/taches/antigravity_17caac47ce67/tools/forge_task_executor.py#L6444) :
     ```python
     desc = _avec_carte_attention(_resoudre_pointeurs_consigne(_extract_message(raw_desc) or raw_desc))
     ```
     Dans `_extract_message` :
     ```python
     if len(description) > 30000:
         log.warning("description de %d caracteres : agy n'en recevra que 30000 (borne argv)",
                     len(description))
     return description[:30000]
     ```
     Pour une consigne de 35 209 caractères, `_extract_message` coupe à 30 000 caractères exacts.
   - **La coupe vient-elle d'OpenCode ou du modèle ?**
     **NON.** OpenCode n'a rien tronqué. La preuve matérielle en base montre qu'OpenCode a reçu exactement la chaîne coupée par Python à 30 000 caractères (se terminant au milieu du mot `- b` du 36e bloc). OpenCode a traité avec succès les 35 branches reçues et a consigné dans son rapport d'exécution :
     > *« J’ai produit le livrable demandé pour les 35 branches visibles dans la consigne reçue [...] Blocage (conformité livrable) : la consigne annonce 40 branches, mais le texte reçu est tronqué après tache/opencode_glm/8c5... »*
   - **Anomalie de contexte** : Le logger interne superviseur émet `WARNING description de 35209 caracteres : agy n'en recevra que 30000 (borne argv)` alors même que l'agent affecté est `OPENCODE_DEFAUT3` et communique via les flux `stdio` (ACP JSON), sans aucune contrainte d'argv Windows.

2. **Sur le chemin ANTIGRAVITY (AGY)** :
   - **Première borne** : [`tools/forge_task_executor.py:316`](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/taches/antigravity_17caac47ce67/tools/forge_task_executor.py#L316) via `_extract_message` (coupe à 30 000 caractères).
   - **Deuxième borne (qui tranche réellement à 29 000)** : [`tools/forge_task_executor.py:4165`](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/taches/antigravity_17caac47ce67/tools/forge_task_executor.py#L4165) dans `_delegate_to_agy` :
     ```python
     cmd = [agy_bin, "--print", _consigne_agy(workdir) + "\n\n[Tache]\n" + desc[:29000], "--new-project", ...]
     ```
     La troncature `desc[:29000]` ramène la consigne à 29 000 caractères pour faire tenir la commande dans les ~32 767 octets de la limite `CreateProcess` de Windows.
   - **Effet constaté sur AGY** : Dans les lots de 40 branches (lots 5, 12, 14), chaque bloc fait environ 900 à 1 000 caractères. 29 000 caractères ne permettent de passer que 29 blocs. C'est la cause directe pour laquelle ces lots ont été livrés avec 29 branches sur 40 traitées.

3. **Sur le chemin CODEX** :
   - [`tools/forge_task_executor.py:5011`](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/taches/antigravity_17caac47ce67/tools/forge_task_executor.py#L5011) applique également un slice `desc[:29000]` muet.

4. **Violation doctrinale : règle « une borne dit combien »** :
   Dans tous ces cas, la coupure est **muette pour l'agent**. Le warning `log.warning` n'est visible que dans les logs du démon superviseur ; le texte remis à l'agent ne contient aucun en-tête ni mention du type `« N car. sur M servis, le reste n'est PAS servi »`. L'agent découvre un texte amputé en plein milieu d'une phrase.

---

## 2. Cartographie détaillée des maillons (Fichier:Ligne)

| Étape / Maillon | Fichier & Ligne | Effet sur une consigne longue (> 30 000 car.) | Coupe active ? |
| :--- | :--- | :--- | :--- |
| **Lecture base** | `sandbox/tasks.db` | `task["description"]` contient 35 209 caractères (40 blocs). | Non |
| **Assignation hub** | `tools/forge_task_executor.py:475` (`servir_consignes_a_l_assignation`) | Remplace les pointeurs de fichier `consigne:nom@sha`. Préserve l'intégralité du texte. | Non |
| **Pointeurs consigne** | `tools/forge_task_executor.py:477` (`_resoudre_pointeurs_consigne`) | Résout les pointeurs `tasks.db:id`. Ne tronque pas. | Non |
| **Extraction consigne** | **`tools/forge_task_executor.py:316`** (`_extract_message`) | **Tronque à 30 000 caractères** (`return description[:30000]`). Émet un warning superviseur mentionnant `agy` et `borne argv`. | **OUI (OpenCode, AGY, Claude, Vibe)** |
| **Conseiller souverain** | `tools/forge_task_executor.py:6330` (`_conseil_plan`) | Borne le contexte envoyé au conseiller (`_CONSEIL_CTX_MAX = 3000`) et son avis (`_CONSEIL_PLAN_MAX = 1500`), mais concatène `desc` sans la modifier (L6498). | Non |
| **Prechargement / Docs** | `tools/forge_task_executor.py:333`, `335` | Ajoutent du contexte sans tronquer `desc`. Si le plafond est atteint, ils l'annoncent explicitement. | Non |
| **Délégation OpenCode** | `tools/forge_task_executor.py:6444` (`_delegate_to_opencode`) | Utilise `_extract_message(raw_desc)`, recevant une consigne déjà coupée à 30 000 caractères. | **OUI (héritée de L316)** |
| **Veilleur OpenCode** | `tools/forge_opencode_journal.py:104` (`prompt_avec_veilleur`) | Transmet `text` intégralement à `client.prompt`. | Non |
| **Client ACP OpenCode** | `tools/forge_acp_client.py:441` (`ACPClient.prompt`) | Envoie le prompt via JSON line sur stdin (`self.proc.stdin.write(...)`). Aucune coupure. | Non |
| **Délégation AGY** | **`tools/forge_task_executor.py:4165`** (`_delegate_to_agy`) | **Tronque à 29 000 caractères** (`desc[:29000]`) dans la construction de la ligne de commande CLI. | **OUI (coupe AGY à 29k)** |
| **Délégation Codex** | **`tools/forge_task_executor.py:5011`** (`_delegate_to_codex`) | **Tronque à 29 000 caractères** (`desc[:29000]`) dans le job JSON. | **OUI (coupe Codex à 29k)** |

---

## 3. Preuves matérielles directes

### 3.1 Tâche OpenCode `job_e871edd7_1794245408_oauth_nkc_nb_cvt_task_assign`
- **Taille dans `sandbox/tasks.db`** : 35 209 caractères (40 blocs `- branche ...`).
- **Exécution de `_extract_message(description)`** :
  ```python
  len(desc) = 35209
  len(_extract_message(desc)) = 30000  # Exactement 5209 caractères amputés
  ```
- **Fin de la consigne reçue à 30 000 caractères** :
  ```text
  ... tests/nr/services.test.toml: args = ["x.py", "--agent", "OPENCODE_TEST"]\n- b
  ```
  La consigne se termine brutalement sur les lettres `"- b"`, coupant en deux l'en-tête de la 36e branche (`"- branche tache/opencode_glm/90bdf2cf5a48..."`).
- **Contenu du résultat produit par l'agent OpenCode DEFAUT3** (colonne `result` en base) :
  > `[effet observe] commits produits : 0 ; conseil: groq_gpt_oss_120b | [repli sur le modele par defaut d'OpenCode apres quota epuise ou delai depasse du modele principal] J’ai produit le livrable demandé pour les 35 branches visibles dans la consigne reçue : docs/reconciliation/lot6_tri_05.md. Blocage (conformité livrable) : la consigne annonce 40 branches, mais le texte reçu est tronqué après tache/opencode_glm/8c5...`

### 3.2 Tâches AGY (Lots 5, 12, 14)
- Dans `_delegate_to_agy`, `desc[:29000]` ampute la consigne à 29 000 caractères.
- 40 blocs de consigne requièrent ~35 000 à 40 000 caractères.
- À 29 000 caractères, seuls les 29 premiers blocs entrent dans l'argument CLI `--print`.
- Résultat constaté : l'agent AGY a fidèlement traité les 29 blocs qu'il a reçus, livrant des rapports de réconciliation à 29/40 branches.

---

## 4. Origine architecturale de la régression

1. **Monoculture historique d'AGY CLI** :
   À l'origine, l'exécuteur déléguait exclusivement à AGY sous Windows via la commande CLI `agy --print "<prompt>"`. Sous Windows, l'API système `CreateProcess` impose une taille maximale de ligne de commande de 32 767 caractères. La borne de 30 000 / 29 000 caractères avait été posée pour éviter un crash `OSError: [WinError 206] Le nom de fichier ou l'extension est trop long`.
2. **Placement inadapté dans `_extract_message`** :
   Cette borne spécifique à l'argv d'AGY a été codée en dur dans `_extract_message` (L316) :
   ```python
   if len(description) > 30000:
       log.warning("description de %d caracteres : agy n'en recevra que 30000 (borne argv)", len(description))
   return description[:30000]
   ```
3. **Contamination des exécuteurs modernes (OpenCode, Claude, etc.)** :
   Tous les exécuteurs (`_delegate_to_opencode`, `_delegate_to_claude`, `_delegate_to_vibe`) ont factorisé la lecture de consigne via `_extract_message`. OpenCode ACP fonctionne par flux JSON sur `stdin`, sans aucune contrainte de longueur de commande système. Il s'est pourtant retrouvé bridé arbitrairement à 30 000 caractères par cette fonction héritée.
4. **Absence d'annonce à l'agent** :
   Même lorsque la coupure est imposée par une contrainte de transport (comme l'argv pour AGY), elle n'est jamais notifiée à l'agent dans le corps du texte. L'agent reçoit une consigne coupée net, sans en-tête ni pied d'avertissement, violant la règle « une borne dit combien ».

---

## 5. Non-Régression (NR Rouge)

Un test de non-régression a été créé :
[`tests/nr/test_consigne_longue_jamais_coupee_en_silence_nr.py`](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/taches/antigravity_17caac47ce67/tests/nr/test_consigne_longue_jamais_coupee_en_silence_nr.py).

Il vérifie trois propriétés fondamentales :
1. `test_extract_message_consigne_longue_entiere_ou_coupe_dite` : Face à une consigne de 40 000 car., si une coupe a lieu, elle doit être explicitement DITE dans le texte remis à l'agent (« N car. sur M servis, le reste n'est PAS servi »). Actuellement, L316 coupe silencieusement. *(Statut : FAILED / ROUGE)*
2. `test_opencode_consigne_longue_non_amputee_a_30000` : Sur le chemin OpenCode (ACP stdin), aucune contrainte argv ne justifie une coupe à 30 000 car. La consigne doit arriver entière ou être explicitement déclarée tronquée. Actuellement amputée à 30 000 car. *(Statut : FAILED / ROUGE)*
3. `test_agy_consigne_longue_borne_argv_dite_a_l_agent` : Sur le chemin AGY, si la consigne est bornée à 29 000 car. (`desc[:29000]`), la coupure doit obligatoirement porter une mention explicite dans le prompt de l'agent. Actuellement muet. *(Statut : FAILED / ROUGE)*

---

## 6. Recommandations pour le correctif (pour la phase ultérieure)

1. **Dans `_extract_message` ([`tools/forge_task_executor.py:316`](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/taches/antigravity_17caac47ce67/tools/forge_task_executor.py#L316))** :
   - Supprimer la troncature globale `description[:30000]`. `_extract_message` doit uniquement extraire le texte sans appliquer de politique de transport propre à un agent CLI particulier.
2. **Pour OpenCode ACP / Claude / Vibe (transport stdio / fichier / API)** :
   - Transmettre la consigne dans son intégralité (aucun plafonnement artificiel à 30 000 caractères).
3. **Pour AGY / CLI (transport argv Windows limité à ~32k)** :
   - Si la consigne dépasse le budget disponible pour argv (ex: 29 000 caractères), appliquer strictement la règle **« une borne dit combien »** :
     Insérer en tête de la consigne servie à l'agent :
     ```text
     [ATTENTION - CONSIGNE TRONQUÉE : 29000 car. sur {total} servis (limite ligne de commande OS), le reste n'est PAS servi]
     ```
     afin que l'agent sache exactement ce qu'il a reçu et puisse adapter son travail ou réclamer la suite sans se retrouver piégé par une rupture silencieuse.
