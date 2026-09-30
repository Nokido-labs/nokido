# RecursiveMAS — Pipeline réel (design gelé 2026-07-03)

## Décision (user GO) : Path 1 = DESIGN PIPELINE, pas harden spectral

Le point dur est RÉPONDU (P3 Kaggle, gist a94b7795) : `cos_id 0.64`, `cos_ood 0.52`,
gap 0.11 (<0.15), zéro mode-collapse → le latent passe ET généralise aux topics jamais
vus. Le WARN `intruder-frac 1.0` (delta LoRA hors-spectre base) = risque d'oubli **SI B
doit rester généraliste** ; ici B = lecteur-de-latent DÉDIÉ dans un MAS → WARN tolérable
(verdict [[recursivemas_local_verdict_2026-06-29]]). Harden spectral = polir une métrique
qui ne mord pas sur le déploiement cible. La valeur du projet = **tokens économisés vs
baseline texte** — c'est CE pipeline qui la mesure. Spectral = déféré (re-run opt-in
`RMAS_SPECTRAL_REG` seulement si un jour B doit redevenir généraliste).

## Objectif mesurable

Prouver que 2 agents (A, B = self Qwen2.5-0.5B) qui échangent un **latent K=8 vecteurs**
au lieu de re-tokeniser le texte :
- **coupent l'input downstream** (~−51% mesuré au proto, à confirmer sur tâche réelle),
- **sans perdre la tâche** (qualité réponse ≥ baseline texte `agent_debate`/`@collab`).

Métrique de livraison = `tokens_latent / tokens_texte` par tour + `task_score_latent` vs
`task_score_texte` sur un jeu de topics OOD (jamais vus à l'entraînement du link).

## Architecture (tout local CPU — le latent path tourne sans GPU)

```
A (Qwen-0.5B base gelée) --encode topic/turn_i--> hidden last-layer
   --RecursiveLink (recursive_link_v1.pt) + RMS-norm--> K=8 soft-vectors
   --inputs_embeds--> B (Qwen-0.5B + LoRA r=8 co-adaptée) --> turn_next
Baseline (comparateur) = même A→B mais A émet du TEXTE, B re-tokenise (agent_debate).
```

- Latent path = `transformers` in-process (GGUF/ollama NE peut PAS : texte + last-hidden
  only). CPU OK (proto prouvé, latence ~4.8s/gen).
- `recursive_link_v1.pt` = link+LoRA entraînés P3 (K=8, r=8). **DÉPENDANCE EXTERNE : cet
  artefact est une sortie Kaggle, à rapatrier** (user : Kaggle output → `Nokido/sandbox/
  workspace/recursive_link_v1.pt`). Sans lui, harness = code prêt mais run bloqué.

## Harness (à écrire : `sandbox/workspace/recursivemas_pipeline.py`, run détaché)

1. Charger Qwen-0.5B base + LoRA + link (`recursive_link_v1.pt`).
2. Jeu de N topics OOD (hold-out P3, `rmas_bulk_05b.jsonl` split ood).
3. Pour chaque topic : (a) tour latent A→link→B, compter input tokens B + garder sortie ;
   (b) tour texte A→texte→B (baseline), idem.
4. Score qualité = cosine sémantique sortie vs référence (le juge P3, pas la CE).
5. Rapport : ratio tokens moyen, delta qualité, verdict `GAIN NET` si tokens↓ ≥30% ET
   qualité ≥ baseline−ε. Sort `recursivemas_pipeline_result.json`.
6. Déport : `run_job` détaché (torch import tape WORKSPACE_GUARD en inline), notify=claude.

## Séquencement

1. [user] rapatrier `recursive_link_v1.pt` de Kaggle.
2. [CLAUDE] écrire `recursivemas_pipeline.py` (governed_edit), lancer `run_job` détaché.
3. [auto] verdict GAIN NET / NUL → si NET : câbler le latent-hop dans `agent_debate` réel
   (option `latent=true`) = la vraie internalisation MAS souveraine.
4. Spectral hardening = seulement si étape 3 exige B généraliste (déféré, non bloquant).

Voir [[recursivemas_local_verdict_2026-06-29]], [[recursivemas_p2_state_blocker_2026-06-29]],
[[veille_recursivemas_2026-06-29]].
