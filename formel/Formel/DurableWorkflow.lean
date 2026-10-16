/-
  Formel.DurableWorkflow — Modèle formel de reprise durable et détection de divergence (Lean 4 coeur).
  Ref: tools/forge_durable_workflow.py (WorkflowContext.activity, WorkflowDivergence)
-/

namespace Formel.DurableWorkflow

/-- Hash des entrées d'une activité (ex: sha256)[:16] -/
def Hash := String
deriving DecidableEq, Repr

/-- Statut d'une étape dans le journal durable -/
inductive StepStatus where
  | completed
  | running
  | failed
deriving DecidableEq, Repr

/-- Étape persistée dans le cache du journal -/
structure CachedStep where
  status : StepStatus
  inputHash : Option Hash
  output : String
deriving DecidableEq, Repr

/-- Résultat de l'arbitrage d'exécution d'une activité :
    - replayed : sortie restaurée du cache, aucun effet de bord ré-exécuté
    - executed : exécution de l'activité (1re exécution ou étape non complétée)
    - divergence : activité déjà complétée mais rappelée avec d'AUTRES entrées
                   -> arrêt strict (ni replay ni ré-exécution) -/
inductive ActivityOutcome where
  | replayed (output : String)
  | executed (output : String)
  | divergence (attendu : Hash) (recu : Hash)
deriving DecidableEq, Repr

/-- Arbitre d'exécution d'activité conforme à WorkflowContext.activity -/
def stepActivity
    (cached : Option CachedStep)
    (currentHash : Hash)
    (fn : Unit → String) : ActivityOutcome :=
  match cached with
  | some step =>
    if step.status == StepStatus.completed then
      match step.inputHash with
      | some recordedHash =>
        if recordedHash == currentHash then
          ActivityOutcome.replayed step.output
        else
          ActivityOutcome.divergence recordedHash currentHash
      | none =>
        ActivityOutcome.replayed step.output
    else
      ActivityOutcome.executed (fn ())
  | none =>
    ActivityOutcome.executed (fn ())

/-- Théorème 2 (« reprise = mêmes entrées ») :
    Dans le modèle du journal durable, un replay ne rend une sortie que si le hash
    des entrées est égal au hash enregistré. -/
theorem thm2_reprise_memes_entrees
    (step : CachedStep)
    (h_completed : step.status = StepStatus.completed)
    (recordedHash : Hash)
    (h_hash : step.inputHash = some recordedHash)
    (currentHash : Hash)
    (fn : Unit → String)
    (out : String) :
    stepActivity (some step) currentHash fn = ActivityOutcome.replayed out →
    currentHash = recordedHash ∧ out = step.output := by
  intro h
  unfold stepActivity at h
  simp only [h_completed, beq_self_eq_true, ↓reduceIte, h_hash] at h
  split at h
  · rename_i h_eq
    have h_rec_eq : recordedHash = currentHash := of_decide_eq_true h_eq
    injection h with h_out
    exact ⟨h_rec_eq.symm, h_out.symm⟩
  · contradiction

/-- Théorème 2 (branche divergence) :
    Si les entrées diffèrent d'une étape déjà complétée, l'arbitre lève une divergence. -/
theorem thm2_divergence_si_autre_entree
    (step : CachedStep)
    (h_completed : step.status = StepStatus.completed)
    (recordedHash : Hash)
    (h_hash : step.inputHash = some recordedHash)
    (currentHash : Hash)
    (fn : Unit → String)
    (h_diff : currentHash ≠ recordedHash) :
    stepActivity (some step) currentHash fn = ActivityOutcome.divergence recordedHash currentHash := by
  unfold stepActivity
  simp only [h_completed, beq_self_eq_true, ↓reduceIte, h_hash]
  have h_bne : (recordedHash == currentHash) = false := by
    apply decide_eq_false
    intro h_eq
    exact h_diff h_eq.symm
  rw [h_bne]
  rfl

/-- Théorème 2 (exclusion stricte) :
    La divergence n'est ni un replay (la sortie n'est pas acceptée)
    ni une ré-exécution (l'effet de bord n'est pas rejoué). -/
theorem thm2_divergence_ni_replay_ni_reexec
    (attendu recu : Hash) (out : String) :
    ActivityOutcome.divergence attendu recu ≠ ActivityOutcome.replayed out ∧
    ActivityOutcome.divergence attendu recu ≠ ActivityOutcome.executed out := by
  constructor
  · intro h; contradiction
  · intro h; contradiction

/-- Équivalence replay pour une étape complétée avec hash enregistré -/
theorem thm2_equivalence_replay
    (step : CachedStep)
    (h_completed : step.status = StepStatus.completed)
    (recordedHash : Hash)
    (h_hash : step.inputHash = some recordedHash)
    (currentHash : Hash)
    (fn : Unit → String) :
    stepActivity (some step) currentHash fn = ActivityOutcome.replayed step.output ↔
    currentHash = recordedHash := by
  constructor
  · intro h
    exact (thm2_reprise_memes_entrees step h_completed recordedHash h_hash currentHash fn step.output h).1
  · intro h_eq
    unfold stepActivity
    simp only [h_completed, beq_self_eq_true, ↓reduceIte, h_hash]
    have : (recordedHash == currentHash) = true := by
      apply decide_eq_true
      exact h_eq.symm
    rw [this]
    rfl

end Formel.DurableWorkflow
