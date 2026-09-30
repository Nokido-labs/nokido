# ADR-001 : Suppression sous-système `/intent` Deno — DÉCISION REPORTÉE

**Date** : 2026-05-25
**Status** : Accepted (path DEPRECATED reversible)
**Auteur** : Claude session 2026-05-25

## Contexte

User a validé Phase 38 alternative "supprimer tout sous-système /intent Deno (cohérent OU statu quo absolu)" — Plan agent #38 disait :
- `brain.ts` = gatekeeper MCP (validation + vault + bus pump) — PAS NLU
- `hub_forwarder.ts` = vrai doublon mais cascade casse si supprimé seul
- `main.ts /intent` orchestre les 2

Suppression complète propre = git rm 4 fichiers Deno + patch consumers Python.

## Décision

**Path DEPRECATED reversible** (pas git rm immédiat) :
1. `tools/forge_dt_router_wire.py emit_routing_event()` : POST direct `hub :8766 /nervous_system/emit` en premier, fallback Deno `/intent` si hub fail (transition compat)
2. Code Deno garde EN PLACE (pas git rm) — annoté DEPRECATED via ce doc
3. Suppression réelle = Phase 42+ après ≥ 7 jours observation : si zéro consumer Deno actif → git rm propre

## Alternatives considérées

| Option | Pour | Contre | Verdict |
|--------|------|--------|---------|
| A. git rm immédiat brain.ts + main.ts + hub_forwarder.ts | Cohérent net | Casse kidney_monitor.ts getJobStatus, irréversible sans revert | rejeté (trop destructif sans observation) |
| B. Statu quo absolu | 0 risque | Continue dette polyglotte | rejeté (user a tranché Phase 38) |
| C. **Path DEPRECATED reversible** | Compat préservée + cible identifiée + suppression future | Dette transitoire ~7j | **retenu** |

## Conséquences

### Positives
- `forge_dt_router_wire` bypass Deno = 1 moins de hop réseau
- Observation 7j révèle vrais consumers Deno restants
- Décision suppression définitive informée (pas spéculation)

### Négatives
- Code Deno orphelin temporairement (lecture trompeuse)
- Doublon fallback dans `emit_routing_event` jusqu'à Phase 42

## Implementation

1. ✅ Phase 38 patch `forge_dt_router_wire.py` : POST hub direct + fallback Deno
2. ⏳ Phase 42 (J+7) : audit logs supervisor.ts pour vérifier zéro hit /intent depuis Python
3. ⏳ Phase 42 : si OK, `git rm proxy_deno/{main.ts, core/brain.ts, organs/hub_forwarder.ts, test_architecture.ts}` + supprimer fallback Deno dans `emit_routing_event`

## Validation

- [ ] Test smoke : `python -c "from forge_dt_router_wire import DTRouterWire; DTRouterWire().emit_routing_event({'test': True})"` → success via hub
- [ ] Phase 42 : audit `forge_audit_log query_recent action='POST /intent'` retourne 0 events sur 7 jours
- [ ] Phase 42 : `git rm` propre + commit `chore(deno): remove /intent subsystem`

## Liens

- Plan agent #38 (verdict honnête) : sub-agent `a616724d9c8cbf506`
- Phase 32 doc révisée : `docs/deno_justification.md`
- OWNERS.toml : entries `proxy_deno/core/supervisor.ts`, `nervous_system.ts` (conservés)
