# Rapport du Pilote Formel Lean 4 — Arbitre d'Invariants de la Boucle Agentique

**Date :** 15 octobre 2026  
**Auteur :** Agent `ANTIGRAVITY`  
**Branche Git :** `agy/lean-pilote` (créée depuis `alpha`)  
**Mission :** Pilote Lean 4 borné (décision owner 15/10) : *Lean comme ARBITRE d'invariants de la boucle agentique, pas comme moteur d'exécution.*

---

## 1. Environnement & Accès Lean 4

Lean 4 et son gestionnaire Lake sont accessibles via le chemin absolu de l'installation `elan` de l'hôte :
- **Binaire Lean :** `%USERPROFILE%\.elan\bin\lean.exe`
- **Binaire Lake :** `%USERPROFILE%\.elan\bin\lake.exe`

### Versions exactes
```text
Lean (version 4.35.0, x86_64-w64-windows-gnu, commit eb6cafb7290e8bd5f2937522d8d804f58f02bafc, Release)
Lake version 5.0.0-src+eb6cafb (Lean version 4.35.0)
```

---

## 2. Projet Lake Minimal `formel/` (Lean 4 cœur, SANS Mathlib)

Le projet est configuré dans le sous-dossier `formel/` avec zéro dépendance externe lourde (pas de Mathlib) :
```
formel/
├── lakefile.toml
├── lean-toolchain
├── Formel.lean
└── Formel/
    ├── HarnessContract.lean
    └── DurableWorkflow.lean
```

### Configuration (`lakefile.toml`)
```toml
name = "formel"
version = "0.1.0"
defaultTargets = ["Formel"]

[[lean_lib]]
name = "Formel"
```

### Commande de compilation
```powershell
cd formel
& "%USERPROFILE%\.elan\bin\lake.exe" build
```

### Sortie verbatim du build
```text
✔ [2/5] Built Formel.DurableWorkflow (1.1s)
✔ [3/5] Built Formel.HarnessContract (1.1s)
ℹ [4/5] Built Formel (792ms)
info: Formel.lean:13:0: 'Formel.HarnessContract.thm1_pas_de_faux_succes' depends on axioms: [propext]
info: Formel.lean:14:0: 'Formel.HarnessContract.thm1_succes_si_prouve' depends on axioms: [propext]
info: Formel.lean:15:0: 'Formel.HarnessContract.thm1_equivalence_liste_blanche' depends on axioms: [propext]
info: Formel.lean:16:0: 'Formel.HarnessContract.thm1_corollaire_refus' depends on axioms: [propext]
info: Formel.lean:17:0: 'Formel.HarnessContract.thm1_corollaire_echec' depends on axioms: [propext]
info: Formel.lean:18:0: 'Formel.HarnessContract.thm1_corollaire_incertain' depends on axioms: [propext]
info: Formel.lean:19:0: 'Formel.HarnessContract.thm1_corollaire_non_verifie' depends on axioms: [propext]
info: Formel.lean:21:0: 'Formel.DurableWorkflow.thm2_reprise_memes_entrees' depends on axioms: [propext]
info: Formel.lean:22:0: 'Formel.DurableWorkflow.thm2_divergence_si_autre_entree' depends on axioms: [propext]
info: Formel.lean:23:0: 'Formel.DurableWorkflow.thm2_divergence_ni_replay_ni_reexec' does not depend on any axioms
info: Formel.lean:24:0: 'Formel.DurableWorkflow.thm2_equivalence_replay' depends on axioms: [propext]
Build completed successfully (5 jobs).
```

---

## 3. Modèles & Théorèmes Formels

### Théorème 1 : « Pas de faux succès » (`Formel/HarnessContract.lean`)
Modèle formel des états et transitions de `app/forge_harness_contract.py`.
- **Verdict par liste blanche :** Une étape n'atteint le statut `ACHIEVED` si et seulement si tous ses 6 piliers sont simultanément prouvés :
  $$\text{action\_emise} \land \text{autorisation} = \text{allow} \land \text{observation} = \text{ok} \land \text{effet\_observe} = \text{observed} \land \text{preuve} = \text{accept} \land \text{effet\_attendu} = \text{declared}$$
- **Corollaires formels d'exclusion prouvés :**
  - Refus (`autorisation = deny`) $\implies \text{verdict} \neq \text{ACHIEVED}$ (résout en `REFUSED` ou `CONTRADICTION`).
  - Échec (`observation = failed`) $\implies \text{verdict} \neq \text{ACHIEVED}$ (résout en `FAILED`).
  - Incertain / illisible (`observation = incertain`) $\implies \text{verdict} \neq \text{ACHIEVED}$ (résout en `INCERTAIN`).
  - Non vérifié (`observation = unknown`) $\implies \text{verdict} \neq \text{ACHIEVED}$ (résout en `REQUESTED`).
  - Effet attendu non déclaré ou preuve non acceptée $\implies \text{verdict} \neq \text{ACHIEVED}$ (résout en `ACCEPTED`).

### Théorème 2 : « Reprise = Mêmes Entrées » (`Formel/DurableWorkflow.lean`)
Modèle formel du journal d'exécution durable et de la détection de divergence de `tools/forge_durable_workflow.py` (issu du correctif suite à l'audit ChatGPT web du 15/10).
- **Invariants prouvés :**
  - **Reprise nominale :** Pour une activité complétée avec un hash enregistré, un replay ne rend une sortie que si $h_{\text{courant}} = h_{\text{enregistre}}$ ; l'effet de bord $f$ n'est pas ré-exécuté.
  - **Détection de divergence :** Si $h_{\text{courant}} \neq h_{\text{enregistre}}$, l'arbitre produit une `ActivityOutcome.divergence`.
  - **Exclusion stricte :** La divergence n'est ni un replay (`divergence ≠ replayed out`), ni une ré-exécution (`divergence ≠ executed out`). Le workflow s'arrête net sans silencier le changement d'entrées.

---

## 4. Vérification des Axiomes (`#print axioms`)

Conformément à la consigne : **AUCUN `sorry`, AUCUN axiome ad-hoc ajouté.**

| Théorème / Lemme | Axiomes Déclarés | Statut |
|---|---|---|
| `Formel.HarnessContract.thm1_pas_de_faux_succes` | `[propext]` | Standard Lean 4 core |
| `Formel.HarnessContract.thm1_succes_si_prouve` | `[propext]` | Standard Lean 4 core |
| `Formel.HarnessContract.thm1_equivalence_liste_blanche` | `[propext]` | Standard Lean 4 core |
| `Formel.HarnessContract.thm1_corollaire_refus` | `[propext]` | Standard Lean 4 core |
| `Formel.HarnessContract.thm1_corollaire_echec` | `[propext]` | Standard Lean 4 core |
| `Formel.HarnessContract.thm1_corollaire_incertain` | `[propext]` | Standard Lean 4 core |
| `Formel.HarnessContract.thm1_corollaire_non_verifie` | `[propext]` | Standard Lean 4 core |
| `Formel.DurableWorkflow.thm2_reprise_memes_entrees` | `[propext]` | Standard Lean 4 core |
| `Formel.DurableWorkflow.thm2_divergence_si_autre_entree` | `[propext]` | Standard Lean 4 core |
| `Formel.DurableWorkflow.thm2_divergence_ni_replay_ni_reexec` | *(aucun)* | **0 axiome** |
| `Formel.DurableWorkflow.thm2_equivalence_replay` | `[propext]` | Standard Lean 4 core |

*(Note : `propext` est l'extensionalité propositionnelle fondamentale du noyau de Lean 4, invoquée par les simplifications logiques booléennes.)*

---

## 5. Conformité au Code Python (`tests/nr/test_lean_conformite_harness_nr.py`)

La preuve formelle ne vaut que si elle est confrontée au code d'exécution réel.
Le test NR instancie le vrai code Python (`app/forge_harness_contract.py` et `tools/forge_durable_workflow.py`) et rejoue la table complète des cas modélisés en Lean.

### Exécution du test NR
```powershell
& "%USERPROFILE%\miniforge3\python.exe" -m pytest tests/nr/test_lean_conformite_harness_nr.py -v --basetemp=C:\tmp\pytest_nr
```

### Résultat
```text
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[nominale_achieved] PASSED [  6%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[action_unknown] PASSED [ 12%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[deny_contradiction] PASSED [ 18%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[deny_refused_blocked] PASSED [ 25%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[deny_refused_unknown_effect] PASSED [ 31%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[requested_rien_observe] PASSED [ 37%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[failed_echec_observe] PASSED [ 43%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[incertain_non_tranche] PASSED [ 50%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[incertain_illisible] PASSED [ 56%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[manque_autorisation] PASSED [ 62%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[manque_effet_observe] PASSED [ 68%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[manque_preuve_challenge] PASSED [ 75%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_table_cas[manque_effet_attendu] PASSED [ 81%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme1_pas_de_faux_succes_invariant PASSED [ 87%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme2_reprise_memes_entrees PASSED [ 93%]
tests/nr/test_lean_conformite_harness_nr.py::test_conformite_theoreme2_divergence_si_autres_entrees PASSED [100%]

============================= 16 passed in 2.37s ==============================
```

---

## 6. Ce que les Théorèmes NE couvrent PAS (Limites et Frontières)

Une preuve formelle dans un assistant de preuve porte strictement sur le **modèle mathématique** spécifié :
1. **Le code Python n'est pas extrait ni prouvé formellement :** Il n'y a pas d'extraction automatique de bytecode ou d'AST vérifié de Python vers Lean. La passerelle repose sur la validation empirique exhaustive de la table de vérité dans `tests/nr/test_lean_conformite_harness_nr.py`.
2. **Intégrité du calcul de hash en Python :** Le Théorème 2 prouve que si $h_1 \neq h_2$, il y a divergence. Il ne prouve pas que l'implémentation de `_hash` en Python est exempte de bugs de sérialisation JSON (ex: objets non sérialisables, ordre de clés non normalisé au-delà du 1er niveau).
3. **Effets physiques et concurrence :** Les théorèmes modélisent la décision séquentielle d'arbitrage. Ils ne couvrent pas les pannes de disque OS, les verrous SQLite inter-processus (`database is locked`), ni les corruptions de mémoire de l'interpréteur Python.
4. **Validité sémantique des organes en amont :** Si l'organe de preuve (`forge_swarm_evidence`) émet un faux verdict `accept`, le contrat de harness le déclarera `ACHIEVED` conformément à ses règles ; le modèle formel garantit l'intégrité de l'arbitrage, pas l'infaillibilité des oracles d'entrée.

---

## 7. Coûts & Métriques

| Métrique | Valeur Mesurée | Commentaire |
|---|---|---|
| **Temps de compilation Lean (cold build)** | ~3.04 s | 5 jobs (SANS Mathlib) |
| **Temps de compilation Lean (incrémental)** | ~0.84 s | Rebuild quasi-instantané |
| **Taille des sources Lean (`formel/`)** | 10.96 Ko | Empreinte minimale |
| **Taille totale avec build (`.lake`)** | 1.38 Mo | Zéro dépendance giga-octets |
| **Temps d'exécution du test de conformité** | 2.37 s | 16 tests pytest NR |

---

## 8. Conclusion

Le pilote démontre avec succès la pertinence de **Lean 4 comme arbitre d'invariants formels** :
- Il formalise sans ambiguïté les règles constitutionnelles de Nokido (`REQUESTED ≠ ACCEPTED ≠ ACHIEVED`).
- Il borne formellement le comportement du replay d'activités (interdiction stricte de rejouer ou ré-exécuter sur divergence).
- Son coût de build (3s, 1.4 Mo) reste parfaitement compatible avec un usage d'arbitrage en boucle de test ou de CI ciblée, sans la lourdeur d'une dépendance Mathlib.
