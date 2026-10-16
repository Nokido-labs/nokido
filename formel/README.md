# Projet Formel — Pilote Lean 4 (Nokido)

Modèles formels et théorèmes d'invariants pour la boucle agentique Nokido :
- `Formel/HarnessContract.lean` : modèle du contrat de harness (`app/forge_harness_contract.py`) et Théorème 1 (« pas de faux succès »).
- `Formel/DurableWorkflow.lean` : modèle de reprise durable et détection de divergence (`tools/forge_durable_workflow.py`) et Théorème 2 (« reprise = mêmes entrées »).
- `Formel.lean` : racine de la bibliothèque et audit des axiomes (`#print axioms`).

Voir le rapport complet : [RAPPORT_PILOTE.md](file:///%USERPROFILE%/Script%20python%20IA/nokido_worktrees/antigravity/formel/RAPPORT_PILOTE.md).