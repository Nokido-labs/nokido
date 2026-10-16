import Formel.HarnessContract
import Formel.DurableWorkflow

/-
  Racine de la bibliothèque Formel (Lean 4 coeur).
  Pilote d'arbitrage d'invariants de la boucle agentique Nokido :
  - HarnessContract : modèle des états, verdict par liste blanche, théorème 1 « pas de faux succès ».
  - DurableWorkflow : modèle du journal d'activités, replay conditionné au hash, théorème 2 « reprise = mêmes entrées ».

  Exigence stricte : AUCUN `sorry`, AUCUN `axiom` ajouté.
-/

#print axioms Formel.HarnessContract.thm1_pas_de_faux_succes
#print axioms Formel.HarnessContract.thm1_succes_si_prouve
#print axioms Formel.HarnessContract.thm1_equivalence_liste_blanche
#print axioms Formel.HarnessContract.thm1_corollaire_refus
#print axioms Formel.HarnessContract.thm1_corollaire_echec
#print axioms Formel.HarnessContract.thm1_corollaire_incertain
#print axioms Formel.HarnessContract.thm1_corollaire_non_verifie

#print axioms Formel.DurableWorkflow.thm2_reprise_memes_entrees
#print axioms Formel.DurableWorkflow.thm2_divergence_si_autre_entree
#print axioms Formel.DurableWorkflow.thm2_divergence_ni_replay_ni_reexec
#print axioms Formel.DurableWorkflow.thm2_equivalence_replay
