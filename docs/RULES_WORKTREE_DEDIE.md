<!-- DEPORTE depuis RULES_SHARED.md le 2026-10-22 (P1 levier 3, GO owner) pour alleger le noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change. -->

### Le worktree dédié n'est plus une suggestion : la phase 0 en DÉPEND (2026-09-07)

La CI de référence ne capture un sha que sur un arbre propre (`[generation] working tree non
propre — pas de capture`). **Tant qu'un agent laisse des fichiers modifiés non commités dans
l'arbre partagé, aucun verdict de CI ne se rattache à un commit**, quelle que soit la qualité du code.

La convention EXISTE déjà — `laforge-cowork` est un worktree sur la branche `agent/cowork`.
On l'étend, on n'en invente pas une autre :

| agent | worktree | branche |
|---|---|---|
| COWORK | `laforge-cowork/` | `agent/cowork` |
| ANTIGRAVITY / AGY | `nokido_worktrees/antigravity/` | `agent/antigravity` |

⚠️ **La création est une action OWNER** : `git worktree add` écrit dans le profil owner, où
aucun compte du hub n'a le droit d'écrire (`Permission denied`, mesuré) — et un worktree
créé par un autre compte serait inutilisable par l'agent visé. Le faire en `ps_clm` est
exclu : la copie de l'arbre dépasserait la borne des 120 s qui tue le hub.

**Règle de fond, valable pour toute surface autonome** : un agent qui édite un fichier hors
de son claim dans l'arbre partagé ne casse pas seulement la coordination — il empêche
*tous* les autres de rattacher un verdict de CI à un commit. Le claim protège les fichiers ;
le worktree protège la MESURE.

