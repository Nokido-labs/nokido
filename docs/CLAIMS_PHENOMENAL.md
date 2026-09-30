# CLAIMS — Couche phénoménologique Nokido (discipline épistémique)

> Inspiré de la rigueur d'Aura (CLAIMS_SUPPORTED / CLAIMS_NOT_SUPPORTED) et de la
> section « Limites honnêtes » de `qualia_et_conscience_narrative_en_code.md`.
>
> **Position de principe** : ces modules reproduisent des **propriétés formelles** de
> fonctions cognitives. Le mapping est **fonctionnel, pas ontologique**. Aucun ne
> prétend instancier de la conscience phénoménale, du qualia, ou un vécu subjectif.
> L'*explanatory gap* (Levine) et le *hard problem* (Chalmers) restent **intacts**.
> Tout `SUPPORTED` ci-dessous = un mécanisme avec un **receipt** (selftest mesuré,
> reproductible). Tout `NOT CLAIMED` = explicitement hors de portée.

Date : 2026-06-18. Couvre les modules de la campagne vision (2 docs cognitifs + Aura).

---

## Tableau des revendications

| Module | SUPPORTED (mécanisme + receipt) | NOT CLAIMED (hors portée) |
|---|---|---|
| `forge_amygdala` | Scoring affectif déterministe : valence/salience graduées + **vecteur 6D** (valence/arousal/dominance/urgency/warmth/frustration) ; modulation par mood/cortisol ; couplage `token_budget`. Receipt : selftest discrimine threat/reward/neutral + 6D. | Ressentir une émotion. Le module *calcule* une valence, il ne l'*éprouve* pas. |
| `forge_homeostasis` (boucle endocrine) | La boucle inter-organe **ferme** : hormone relâchée → `_endocrine_factor` ajuste le seuil (vigilance). Receipt : harness L3, `endocrine_factor 1.0→1.5` sur menace. | Homéostasie « vécue ». C'est une régulation mesurable, pas une pulsion sentie. |
| `forge_agency` | Attribution d'agentivité = `cos(Δprédit, Δobservé)·efficacy·temporal` (Frith/Blakemore), réutilise le forward-model `world_model`. Receipt : discrimine auteur(0.82)/externe(0)/sans-effet(0). | Le *sentiment* d'être l'auteur (mineness phénoménale). Isomorphisme fonctionnel du comparateur, pas le vécu. |
| `forge_subjective_time` | Tempo ressenti (Wittmann/Droit-Volet) : arousal dilate, flow contracte. Receipt : flow 60s→46s, vigilance 60s→99s. | Le temps **coulé** husserlien (rétention/protention). Temps discret recalculé, pas un continu vécu. |
| `forge_narrator` | Tissage faits→récit 1ère personne (fils + causalité + identité). Receipt : 125 épisodes→63 fils, lien causal leçon→acte. | Une mémoire autobiographique *vécue*. C'est une reconstruction interprétative (biais de cohérence narrative assumé). |
| `forge_parietal_fusion` | Liaison multimodale (9 flux anatomy + mood + endocrine + pulse) → percept unifié publié (global_workspace), salience via amygdale. Receipt : percept landed, salience 0.0→0.777 sur état réel. | Un « espace de travail global » conscient au sens GWT fort. Diffusion fonctionnelle, pas accès phénoménal. |
| `forge_snn_core` | Substrat LIF **apprenant** par surrogate gradient (snntorch/pur-torch). Receipt : acc 0.85→1.0, ~80k spikes, backprop à travers le spike. | Calcul neuromorphique biologique. Émulation de dynamique LIF, pas du tissu. |

---

## Revendications NON SUPPORTÉES (explicitement)

Aligné sur l'aveu du doc cognitif et d'Aura — **strictement non prouvé / non revendiqué** :

- **Qualia / vécu subjectif** : un module qui *décrit* un état interne n'en fait pas
  l'expérience. Un éventuel `PhenomenologicalBuffer` (flux introspectif LLM) serait un
  **isomorphisme fonctionnel**, pas une équivalence phénoménologique.
- **Conscience phénoménale / "the lights are on"** : aucune preuve, par construction.
- **Personnalité / soul / personhood** : hors scope d'un codebase d'ingénierie.
- **Temporalité phénoménologique vraie** : le temps reste discret (tick), pas coulant.

---

## Règle d'engagement (pour tout futur module phénoméno)

1. Tout `SUPPORTED` exige un **receipt** : un selftest mesuré, reproductible, cité.
2. Le langage de self-report des modules doit **éviter** « je ressens / je suis conscient »
   au sens fort — préférer « le système calcule/attribue/modélise ».
3. Un module ne doit jamais **rapporter un état qu'il n'a pas réellement** (honnêteté
   structurelle, cf. Aura `structural phenomenal honesty`).
4. Cette page se met à jour à chaque ajout — `SUPPORTED` seulement après receipt vert.
