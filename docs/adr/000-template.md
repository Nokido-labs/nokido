# ADR-XXX : <titre court verbe-actif>

**Date** : YYYY-MM-DD
**Status** : Proposed | Accepted | Deprecated | Superseded by ADR-YYY
**Auteur** : <agent ou humain>

## Contexte

État actuel du système. Quel problème observé ? Quelle critique
(Plan agent, cloud LLM, incident prod) déclenche cette décision ?

## Décision

**Action retenue** en 1-2 phrases. Verbe d'action clair.

Exemples :
- "Migrer `forge_hormones` SQLite (autorité endocrine) + view in-RAM."
- "Renommer `forge_code_atlas` → `forge_ast_index` (casser collision proprioception)."
- "Garder Deno supervisor.ts (justifications X, Y, Z)."

## Alternatives considérées

| Option | Pour | Contre | Verdict |
|--------|------|--------|---------|
| A. Statu quo | ... | ... | rejeté car ... |
| B. <alternative> | ... | ... | rejeté car ... |
| C. <décision> | ... | ... | **retenu** |

## Conséquences

### Positives
- Gain X
- Économie Y

### Négatives
- Coût migration Z
- Dette technique W

### Neutres
- Changement naming requis (X consumers à patcher)

## Implementation

Phases concrètes + estimation effort + commits ciblés :

1. **Step 1** : ... (commit `feat(X)`, ~2h)
2. **Step 2** : ... (commit `refactor(Y)`, ~1h)
3. **Step 3** : tests pytest (~30min)

## Validation

Critères mesurables :
- [ ] Tests pytest passent (N/N)
- [ ] Pas de régression sur services existants (audit /api/services/list)
- [ ] Memory updated (`MEMORY.md` + fichier décision)
- [ ] OWNERS.toml mis à jour

## Liens

- Critique source : <chemin sub-agent output ou cloud LLM thread_id>
- Memory associée : [[supervisor-centralization-2026-05-24]]
- Commit(s) : `feat(X): ...` SHA `abc1234`
- OWNERS.toml entry modifié : `module forge_X.py`
