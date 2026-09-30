# GIT_WORKFLOW.md — le flux git de Nokido, opposable

> Distillé le 2026-08-21 depuis 4 références ingérées au RAG
> (`watch:github_best_practices:*`, 105 chunks) : trunkbaseddevelopment.com,
> GitHub Flow, Google eng-practices reviewer + developer. Adapté au contexte
> RÉEL : **un seul développeur humain (owner) + des agents LLM outillés**.
> Une règle qui n'est pas vérifiable par une commande n'est pas une règle.

## 1. Topologie — deux lignes, pas plus

```
alpha  = trunk       (dev actif + release/TestPyPI + branche par défaut GitHub)
beta   = stable/dist (sync depuis alpha, purge dist ; miroir Codeberg)
tags archive/*       (états historiques ; JAMAIS des branches de travail)
```

- **Trunk-based, variante « commit direct au trunk »** — la forme documentée
  pour les très petites équipes (trunkbaseddevelopment.com : *« lone developers
  commit straight to the trunk »*). Les branches de longue durée sont le
  problème n°1 que ces références combattent : Nokido n'en garde AUCUNE active.
- Une branche de courte durée est permise pour un travail risqué (spike,
  refactor large) — elle vit **moins d'une semaine** et meurt par merge ou
  abandon. Vérif : `git branch -avv` ne doit montrer aucune branche de travail
  datant de plus de 7 jours.
- `main` est hors circulation (`archive/main-2026-03-17`). Ne pas la ranimer.

## 2. La porte avant le trunk — le « reviewer » de Nokido est outillé

GitHub Flow exige une review avant merge ; Google exige qu'un CL améliore la
santé du code même s'il n'est pas parfait (*« better, not perfect »*). En
mono-dev, le reviewer humain n'existe pas — Nokido le REMPLACE par des gardes
exécutables, et c'est opposable :

| Rôle chez Google | Équivalent Nokido | Preuve |
|---|---|---|
| Reviewer (correctness) | porte locale `tools/ci_local.py` (13 gates, 5528 tests) | `rc=0` avant push |
| Reviewer (style) | flake8/ruff critique + pre-commit (secrets, AST) | hooks `.githooks/` |
| Reviewer (design) | revue externe à la demande (Codex/ultrareview/pairs M2M) | verdicts consignés |
| « CL must not break the build » | `ci-selfhosted.yml` sur chaque push alpha | `forge_ci_check --verdict <sha>` |

**Règles opposables :**
1. **Aucun push sans porte.** `forge_push_sovereign` passe par le pre-push
   egress ; le contourner (`--no-verify`) est interdit sauf incident déclaré.
2. **Après CHAQUE push : lire le verdict CI** (`forge_ci_check --verdict <sha>`).
   `cancelled`/`aucun run` = NON MESURÉ, jamais « vert » (cf. faux-vert temporel).
3. **Un commit rouge se répare par un commit AVANT tout autre travail** —
   Google : *« speed of response matters more than size of review queue »*.
4. Tout nouveau `test_*_nr.py` s'enregistre dans `PURE_TESTS` (le ratchet
   `test_suite_pure_ratchet_nr` le force déjà — c'est le « required check »).

## 3. Petits commits — la règle Google qui s'applique telle quelle

Google *small-cls* : un petit CL se relit vite, se reverte proprement, casse
moins. Directement applicable aux agents comme à l'owner :

5. **Un commit = un changement** (fix OU feature OU docs, pas un mélange).
   Staging TOUJOURS explicite par chemin (`git add -- <fichiers>`), jamais
   `git add -A` — le working tree porte du bruit d'agents.
6. **Ce qui se décrit avec « et... et... » se découpe.** Exception admise
   (Google aussi) : un lot mécanique uniforme (renames, bannières) = un commit.
7. Réparer un commit local non poussé = `--amend` (le code exécuté par
   trusted_script = exactement le code revu) ; un commit POUSSÉ ne s'amende
   jamais, il se corrige par un commit suivant.

## 4. Messages de commit — les « CL descriptions » de Google

Google *cl-descriptions* : première ligne = QUOI, corps = POURQUOI et contexte.
Convention Nokido déjà écrite dans `docs/CONTRIBUTING.md` (auteur unique,
pas de trailer d'agent). S'y ajoutent, opposables :

8. Sujet `type(scope): effet` ≤ 80 caractères (le superdépôt tronque au-delà).
9. **Le corps dit POURQUOI et cite la MESURE** (le sha, le rc, le chiffre) —
   pas « improved X ». Un futur lecteur (souvent un agent avec zéro contexte)
   doit comprendre sans ouvrir le diff.
10. Un fix référence ce qu'il répare (« CI rouge sur 42ed1530 ») ; une
    correction de doc dit ce qui était FAUX et ce qui est vrai.

## 5. Release — jamais depuis le flux courant

11. Publication = **tag `v*` sur le SOUS-module** (`git -C Nokido tag v*`),
    jamais depuis la racine ; TestPyPI d'abord, PyPI sur confirmation owner —
    règle du 2026-08-21 (`feedback_rien_de_public_avant_verifications`).
12. `beta` se synchronise DEPUIS alpha (merge de sync), jamais l'inverse.

## 6. Ce que ces références demandent et que Nokido NE fait PAS (assumé)

- **Pull requests systématiques** : sans second humain, une PR ne fait
  qu'ajouter du clic. On garde le commit direct au trunk + gates. Le jour où
  un contributeur externe arrive, GitHub Flow s'applique à LUI (fork → PR →
  CLA bot → review owner) — `CONTRIBUTING.md` racine le décrit déjà.
- **Branch protection serveur** : impossible en privé/gratuit (403 mesuré).
  Substitut réel : `_BRANCHES_PROTEGEES` dans `app/forge_git_egress.py`
  (suppression + force-push bloqués au pre-push). À reposer côté serveur au
  passage public (`docs/public_transition_checklist.md`).
- **Feature flags** (trunk-based) : hors sujet au périmètre actuel — le
  travail incomplet reste en sandbox/, pas derrière un flag en production.

## 7. Anti-patterns observés dans CE dépôt (ne pas répéter)

- Branches mortes accumulées 5 mois (12 refs, dont 6 à 0 commit unique) —
  triées le 21/08 ; une branche de travail qui survit à sa semaine = dette.
- `review/*` gardées « au cas où » alors que `git cherry` prouvait
  l'absorption — mesurer avant de conserver.
- Deux CI en parallèle (une seule à la fois : THROTTLE homéostat = STOP).
- Snapshot géant fourre-tout (`wip/rescue`, +5,8 M lignes) : un état à
  préserver se TAGUE (`archive/*`), les données lourdes vont hors git.

## Requêtes RAG (source de vérité de ce distillat)

```sql
SELECT source, substr(text,1,200) FROM rag_fts
WHERE rag_fts MATCH '"trunk based" OR "small CLs" OR "code review standard"'
  AND source LIKE 'watch:github_best_practices%' LIMIT 10;
```
