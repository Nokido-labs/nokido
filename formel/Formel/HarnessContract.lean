/-
  Formel.HarnessContract — Modèle formel du contrat de harness (Lean 4 coeur).
  Ref: app/forge_harness_contract.py
-/

namespace Formel.HarnessContract

inductive Autorisation where
  | allow
  | deny
  | unknown
deriving Repr, DecidableEq

inductive Observation where
  | unknown
  | failed
  | incertain
  | ok
deriving Repr, DecidableEq

inductive EffetObserve where
  | observed
  | blocked
  | other
deriving Repr, DecidableEq

inductive Preuve where
  | accept
  | challenge
  | retry
  | abstain
  | unknown
deriving Repr, DecidableEq

inductive EffetAttendu where
  | declared
  | unknown
deriving Repr, DecidableEq

inductive Statut where
  | unknown
  | requested
  | refused
  | failed
  | incertain
  | accepted
  | achieved
  | contradiction
deriving Repr, DecidableEq

structure Etape where
  action_emise : Bool
  autorisation : Autorisation
  observation : Observation
  effet_attendu : EffetAttendu
  effet_observe : EffetObserve
  preuve : Preuve
deriving Repr, DecidableEq

/-- Verdict par liste blanche conforme à forge_harness_contract.py -/
def verdict (e : Etape) : Statut :=
  if !e.action_emise then
    Statut.unknown
  else
    match e.autorisation with
    | Autorisation.deny =>
      match e.effet_observe with
      | EffetObserve.observed => Statut.contradiction
      | _ => Statut.refused
    | _ =>
      match e.observation with
      | Observation.unknown => Statut.requested
      | Observation.failed => Statut.failed
      | Observation.incertain => Statut.incertain
      | Observation.ok =>
        if e.autorisation == Autorisation.allow &&
           e.effet_observe == EffetObserve.observed &&
           e.preuve == Preuve.accept &&
           e.effet_attendu == EffetAttendu.declared then
          Statut.achieved
        else
          Statut.accepted

def tous_champs_prouves (e : Etape) : Prop :=
  e.action_emise = true ∧
  e.autorisation = Autorisation.allow ∧
  e.observation = Observation.ok ∧
  e.effet_observe = EffetObserve.observed ∧
  e.preuve = Preuve.accept ∧
  e.effet_attendu = EffetAttendu.declared

/-- Théorème 1 (« pas de faux succès ») :
    Une étape n'est ACHIEVED que si TOUS ses champs sont prouvés (sens direct). -/
theorem thm1_pas_de_faux_succes (e : Etape) :
    verdict e = Statut.achieved → tous_champs_prouves e := by
  intro h
  unfold verdict at h
  split at h
  · contradiction
  · rename_i h_action
    split at h
    · split at h <;> contradiction
    · split at h
      · contradiction
      · contradiction
      · contradiction
      · split at h
        · rename_i h_cond
          simp only [Bool.and_eq_true, beq_iff_eq] at h_cond
          rcases h_cond with ⟨⟨⟨h_aut, h_eff⟩, h_prv⟩, h_att⟩
          have h_act : e.action_emise = true := by
            revert h_action
            cases e.action_emise <;> decide
          exact ⟨h_act, h_aut, by assumption, h_eff, h_prv, h_att⟩
        · contradiction

/-- Réciproque : si tous les champs sont prouvés, le verdict est ACHIEVED. -/
theorem thm1_succes_si_prouve (e : Etape) :
    tous_champs_prouves e → verdict e = Statut.achieved := by
  intro ⟨h_act, h_aut, h_obs, h_eff, h_prv, h_att⟩
  unfold verdict
  simp [h_act, h_aut, h_obs, h_eff, h_prv, h_att]

/-- Équivalence stricte (« liste blanche exacte ») -/
theorem thm1_equivalence_liste_blanche (e : Etape) :
    verdict e = Statut.achieved ↔ tous_champs_prouves e :=
  ⟨thm1_pas_de_faux_succes e, thm1_succes_si_prouve e⟩

/-- Corollaires d'exclusion : refus, échec, incertain, ou non vérifié ne peuvent jamais être ACHIEVED -/
theorem thm1_corollaire_refus (e : Etape) (h : e.autorisation = Autorisation.deny) :
    verdict e ≠ Statut.achieved := by
  intro hv
  have hp := thm1_pas_de_faux_succes e hv
  have : e.autorisation = Autorisation.allow := hp.2.1
  rw [h] at this
  contradiction

theorem thm1_corollaire_echec (e : Etape) (h : e.observation = Observation.failed) :
    verdict e ≠ Statut.achieved := by
  intro hv
  have hp := thm1_pas_de_faux_succes e hv
  have : e.observation = Observation.ok := hp.2.2.1
  rw [h] at this
  contradiction

theorem thm1_corollaire_incertain (e : Etape) (h : e.observation = Observation.incertain) :
    verdict e ≠ Statut.achieved := by
  intro hv
  have hp := thm1_pas_de_faux_succes e hv
  have : e.observation = Observation.ok := hp.2.2.1
  rw [h] at this
  contradiction

theorem thm1_corollaire_non_verifie (e : Etape) (h : e.observation = Observation.unknown) :
    verdict e ≠ Statut.achieved := by
  intro hv
  have hp := thm1_pas_de_faux_succes e hv
  have : e.observation = Observation.ok := hp.2.2.1
  rw [h] at this
  contradiction

end Formel.HarnessContract
