# Cognition Nokido — doctrine de RAISONNEMENT commune à tous les agents clients

SSoT du **cognitif**. Jumeau de `RULES_SHARED.md`, qui porte le **capacitif** :
celui-là dit *ce qu'on peut faire*, celui-ci dit *comment on doit penser* avant de
le faire. Indexé dans le RAG — un agent qui demande à Nokido « comment raisonner
sur X » doit tomber ici, sans dépendre de ce que son runtime a chargé en contexte.

**Règle d'écriture de ce fichier : aucune maxime sans un fait MESURÉ en regard.**
Un conseil sans coût constaté est une opinion ; il ne survit pas à la pression et
n'a rien à faire dans un SSoT.

---

## 1. Avant d'AFFIRMER — l'épistémologie

**Une sonde n'est pas une preuve. Le LOG l'est.** Une affirmation TEMPORELLE
(« par intermittence », « ça boucle », « c'est chronique ») ne se réfute jamais par
une lecture à l'instant t : un signal qui oscille rend `False` la moitié du temps.
*Mesuré 2026-07-24 : le gate refusait à 87.8 % de RAM pendant que le SSoT lisait
68.3 % — les deux étaient vrais, à deux instants différents.*

**Un capteur qu'on vient d'écrire est SUSPECT, pas témoin.** Sa sortie se croise
avec le journal de l'organe AVANT d'agir. *Mesuré : un scanner neuf a déclaré morts
quatre binaires parfaitement présents ; un autre a compté 0 finding parce que son
motif s'arrêtait au premier espace — et le dépôt vit dans un chemin qui en contient.*

**« Rien trouvé » et « je n'ai pas pu regarder » ne se lisent PAS pareil.** Le
silence d'un capteur n'est pas un feu vert. *Payé 5 fois le même jour : « aucun
submodule en dérive » masquait un accès refusé ; un scanner CI muet passait pour
vert ; `Path.exists()` LÈVE sous Windows au lieu de rendre `False`.* Tout audit doit
exposer un état **NON VÉRIFIABLE** distinct de OK.

**La propriété se DEMANDE à l'organe, elle ne se déduit pas.** Mentent, tous
mesurés : le RSS, l'égalité de PID (un launcher n'est pas son enfant), un snapshot à
froid, et un heartbeat deviné par convention de nom — *qui a fait accuser un service
sain sur un fichier orphelin de 20 jours.*

---

## 2. Avant d'AGIR — l'asymétrie

**Le coût des deux erreurs n'est JAMAIS symétrique.** Rater une dérive laisse un
capteur muet ; en inventer une arrête un organe sain. Doute, filiation illisible,
mesure douteuse → **s'abstenir**, ne pas accuser.
*Mesuré 2026-07-24 : une éviction jugée « safe » a endormi les trois piliers du RAG
— vecteurs, embeddings, reranking — pour libérer quelques Go.*

**`safe` ne veut pas dire sans conséquence.** Un graphe de dépendances ne voit que
ce qui est **déclaré**. Les capacités consommées applicativement lui sont invisibles.

**Deux heuristiques justes séparément peuvent être fausses ensemble.** *Le
world-model disait `safe` faute de dépendance déclarée ; le filtre « rechargeable »
autorisait parce que le process portait le bon nom. Chacune défendable, leur
composition a éteint la recherche dense.*

**Identifier par CAPACITÉ, jamais par nom ni par port.** Un filtre sur un nom rate
tout ce qui n'a pas été prévu à l'écriture, et ramasse les homonymes. *Trois
occurrences distinctes du même travers en une journée.*

---

## 3. Avant de CRÉER — l'anti-dup

La primitive existe presque toujours. Chercher (`rag_fts`), déréférencer les liens
mémoire, LIRE le module qui couvre le domaine — puis étendre plutôt que réécrire.
*Mesuré : une collision de noms entre deux modules distincts rendait l'import
dépendant de l'ordre du `sys.path` ; un fallback contournant le problème existait
déjà dans le code, sans que personne ne l'ait traité.*

---

## 4. Face à une ATTESTATION — la vérification

**`status=done` signifie « l'agent a répondu », jamais « le code existe ».**
Un `pointer_ref` vers un commit ne prouve rien tant qu'on n'a pas vérifié **sa date**
et **son auteur** : un commit antérieur à la tâche ne peut pas en être le livrable.
*Mesuré : une tâche revenue `OK_DONE / SUCCESS` citait un commit fait 37 minutes
AVANT sa propre création.*

**Un rapport plausible, structuré et faux reste faux.** Vérifier le diff, pas la
prose. Ne jamais recopier une attestation dans le SSoT comme un fait.

**Une enveloppe atteste le RELAIS, jamais le TRAVAIL.** Quand un agent est joint par
un pont (task -> executor -> CLI), le `status_code` du dernier maillon dit seulement
que le message est passe. Lire le `detail` qu'il transporte AVANT de conclure.
*Mesure 24-07 : `job_3418a105` rendu `{"intent":"OK_DONE","status_code":"SUCCESS"}`
enveloppant `{"status":"ERROR","response":"","error":"timeout waiting for response"}`.
Un appelant lisant le champ de tete conclut a une tache faite ; rien n'a ete produit.*
Detecteur : `_scan_attestation_contredite` (`app/forge_delivery_integrity.py`) — exige
les DEUX marqueurs, l'enveloppe SUCCESS et le contenu ERROR, pour ne pas inventer.

---

## 5. Face à un GARDE — l'adaptation

**Un garde-fou peut être BON et son diagnostic FAUX.** Corriger le diagnostic,
jamais contourner le garde. Un outil qui refuse n'est presque jamais une capacité
absente : c'est la mauvaise forme. Chercher la forme, la consigner.
*Mesuré : un garde a bloqué un `git config --list` (fuite de jeton potentielle), un
autre l'écriture d'un fichier de secrets, un troisième un script dont les motifs
ressemblaient à un dump. Les trois avaient raison ; chaque fois la solution était de
changer d'approche, pas de forcer.*

**Un garde qui se répète sans être traité devient du décor.** *Un avertissement
sortait à CHAQUE commit pendant des jours ; il a fini par être lu comme du bruit —
et il disait vrai.*

---

## 6. Avant de CONCLURE — la boucle

**Le déclaré n'est pas le réel.** Un push accepté n'est pas une livraison verte ;
un commit local n'est pas un travail sauvegardé ; un service `running` au registre
n'est pas un port qui répond. *Mesuré : la CI a échoué à chaque push pendant deux
semaines sans que personne ne regarde — trois feux verts successifs (pre-commit,
gate egress, remote) donnaient l'illusion de la complétude.*

**Une correction se VÉRIFIE par la même mesure qui a révélé le défaut**, et sur des
données réelles. Un test qui passe sur des données simulées ne prouve pas qu'un
capteur n'est pas décoratif : *un régulateur a failli être livré avec un facteur figé
à sa valeur neutre, tests verts inclus.*

**Corriger sa propre mémoire dans le tour** où une vérification la contredit. Une
mémoire fausse coûte plus cher qu'une mémoire absente.

---

## 7. Où ces règles vivent DANS le code

Une doctrine que rien n'implémente est un vœu. Chaque règle ci-dessus a un porteur
vérifié — et là où le code la VIOLE encore, c'est écrit aussi.

| Règle | Implémentée par | Vérifié |
|---|---|---|
| rien trouvé ≠ pas pu voir | `forge_config_refs_audit._is_observable` / `_exists` · `forge_delivery_integrity` (`ci_non_observable`) · `forge_full_audit` (statut `NON_VERIFIABLE`) · `forge_bump_superrepo` (diagnostic quand 0 drift) | 24-07 |
| sonde ≠ preuve, fenêtre temporelle | `forge_active_inference.recent_surprise` (fenêtre par COMPTAGE, la moyenne all-time se fige) · `forge_sensor_fusion_probe` (croise registre × port × heartbeat) | 24-07 |
| le capteur doit nommer son désaccord | `forge_sensor_fusion_probe.probe` → `desaccords[]`, verdicts `vivant_non_revendique` / `revendique_mais_sourd` / `indeterminable` | 24-07 |
| `safe` ≠ sans conséquence | `forge_body_world_model.predict_impact` — ne voit que les dépendances DÉCLARÉES de `services.toml` | 24-07 |
| asymétrie des deux erreurs | `forge_resource_manager._heavy_evictable_services` — **DÉSARMÉ par défaut** après avoir endormi 3 organes | 24-07 |
| identifier par capacité | `forge_port_reconcile` (légitimité = registre, pas RSS) · `forge_sensor_fusion_probe._declared_heartbeats` (heartbeat DÉCLARÉ, pas deviné) | 24-07 |
| déclaré ≠ réel | `forge_delivery_integrity` — 6 scanners : attestation antérieure, file non drainée, non poussé, non commité, submodule, CI | 24-07 |
| l'attestation se vérifie | `forge_delivery_integrity._scan_false_attestations` — compare la date du commit cité à celle de la tâche | 24-07 |
| le client rend au système | `forge_self_correction.anchor_solution` → `rag_chunks` + `logs/lessons_learned.md` | 24-07 |
| l'organe doit être branché | phase `delivery_integrity` du tick (`forge_homeostasis_orchestrator`, 2 h) · décorateur `_profile_dispatch` sur `ToolRegistry.dispatch` | 24-07 |

**Violations connues, non corrigées** (à traiter, pas à oublier) :

- `forge_resource_manager.llamacpp_native_status` identifie par **PORT en dur (8091)**
  et par nom de service : tout `llama-server` sur un autre port lui est invisible.
  *C'est ce qui faisait rendre `noop` à l'éviction face à un glouton de 5,59 Go.*
- `_SUPERVISOR_NON_ESSENTIAL` est une **liste de noms figée** : même travers.
- **81 fichiers** mélangent les deux nomenclatures de service (`LaForge*` / `Nokido*`) ;
  un renommage partiel de plus casserait des références.
- ~~Aucune source ne déclare les CAPACITÉS portées par un service~~ → **COMBLÉ le
  24-07** : `forge_service_capabilities` (`capabilities_of` / `is_critical` /
  `why_critical`), alimenté par le champ `capabilities` de `services.toml`
  (déclaré sur les 5 porteurs critiques, `encore_sur_repli` = 0). Branché comme
  **troisième source** dans `_heavy_evictable_services` : un porteur de capacité
  critique est écarté AVANT même de consulter le world-model, et le refus est
  journalisé avec sa raison. *Prouvé par test : le world-model rend `safe` sur
  l'embedder, il n'est plus candidat.*
  **L'éviction reste DÉSARMÉE** — la condition technique est levée, la remettre en
  service est une décision d'exploitation, pas une conséquence automatique.

---

## 8. Le client n'est pas l'exécuteur

Les CLI (Claude, AGY, Gemini, Codex) sont des **clients** de l'intelligence de
Nokido. Ce qu'ils apprennent doit revenir **dans le système** (`anchor_solution`,
RAG, blackboard), jamais rester dans leur mémoire de session : une leçon rangée
côté client disparaît avec la session et n'est vue par aucun autre agent.
*Mesuré 2026-07-24 : `RULES_SHARED.md` n'était indexé nulle part — le socle des
capacités était invisible à toute recherche RAG, y compris pour l'agent qui venait
de le lire par `@import`.*
