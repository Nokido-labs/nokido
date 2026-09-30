# Justification Deno dans Nokido — décision Phase 32 (2026-05-25)

## Contexte

Critique passe 2 Plan-fusion + cerebras : "3 runtimes (Python+Deno+SQLite) pour 1 APU = Deno = vanité technique si pas de natif WASM". Cerebras tranche : **migrer Deno → Python**.

## Composants Deno actuels

| Module | Rôle | Équivalent Python |
|--------|------|-------------------|
| `supervisor.ts` | Orchestrateur 40+ services, heartbeat 3-tier, circadian, runAs sandbox, pre-spawn gate | `asyncio` + `supervisord` OR NSSM |
| `nervous_system.ts` | Bus pub/sub typed events | Redis pub/sub OR `asyncio.Queue` |
| `brain.ts processLLMIntent` | NLU cervelet | `forge_nlu.py FastClassifier` (existe déjà) |
| `hub_forwarder.ts` | Relais default_executor → hub :8766 | Route Starlette redirect |
| `organs/*` | Adapters typed | Python adapters + `typing.Protocol` |

## Verdict cerebras (thread `th_1779664844_1d3b`)

> "Deno ne se justifie pas — Arguments (permissions, ESM, single-binary) sont purement ergonomiques : ils ne compensent pas le coût d'un projet polyglotte."

## Décision : MAINTIEN DENO CIBLÉ (compromis)

**3 contre-arguments qui résistent** :

1. **`supervisor.ts` porte logique critique** : circadianLoop (6 phases NREM3...), heartbeatLoopForTier (3 tiers), pre-spawn gate, quick-fail circuit breaker. Migration = 3-5 jours refactor + risque casse comportement vital.

2. **`nervous_system.ts` SystemBus** = bus pub/sub natif typed. Remplacement = Redis (daemon supplémentaire) ou asyncio.Queue (perd inter-process). Aucun gain mesurable.

3. **Permissions Deno natives** (`--allow-net=127.0.0.1:8766`) = sécurité réelle hardware-level que Python n'a pas natif.

## Migration ciblée (vs tout-ou-rien)

## CORRECTION Phase 38 (2026-05-25)

**Plan agent #38 a invalidé ma proposition `brain.ts → forge_nlu`** :
- `brain.ts processLLMIntent` ≠ NLU classification. C'est un **gatekeeper MCP** (validation schéma + vault + bus pump + routage tool.name → organe wasm/exegol/default).
- `forge_nlu.FastClassifier` = triage texte intention chat/action/rag.
- **Axes disjoints**. Homonymie "NLU" trompeuse. Pas un doublon.

`hub_forwarder.ts` = vrai doublon mais cascade casse si suppression (default_executor du mapToolToOrgan dépend).

**Décision révisée** :
- ✅ Garde `supervisor.ts`, `nervous_system.ts`, `brain.ts` (gatekeeper), `hub_forwarder.ts`
- 🚫 Phase 38 migration partielle Deno = **annulée** (faux positifs identifiés)
- 📝 Patch documentaire seul : retire mentions "brain.ts NLU" trompeuses

Verdict Phase 38 honnête : la critique Phase 32 cerebras "Deno vanité" reste théoriquement défendable mais le coût migration réel = casser des fonctions vitales (gatekeeper validation, vault, bus typed). **Statu quo Deno**.

## Effort réel migration partielle

**ANCIENNE estimation Phase 32** (faussée par Plan-fusion) : 2-3j.
**RÉELLE estimation post-Plan #38** : effort utile = 30min patch documentaire. Reste = statu quo.

## Conditions GO migration ciblée

1. Tests pytest non-régression `forge_nlu` vs `brain.ts` (50 inputs)
2. ADR `001-deno-partial-migration.md`
3. Audit consumers Deno organs avant suppression

## Liens
- cerebras passe 2 : `th_1779664844_1d3b`
- Plan-fusion passe 2 : `ab0848fe9bb303af1`
- Memory : [[supervisor-centralization-2026-05-24]] [[roadmap-deno-nervous-system]]
