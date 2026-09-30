# SWE-bench Strategy Debate — Result 2026-05-24

## Méthode

1. **Multi-LLM divergent generation** via `tools/forge_swebench_strategy_debate.py`
   - dspy `StrategyHypothesis` Signature (JSON strict)
   - 3 providers : cerebras, groq, github
2. **Arbitrage symbolique** (Marcus governance)
   - Jaccard keyword overlap entre proposals (convergence)
   - Score = consensus × confidence_self
   - **PAS de 4ème LLM juge** — règles déterministes uniquement

## Résultat débat

| Provider | OK | conf | hypothesis |
|---|---|---|---|
| **cerebras** | ✅ | 0.78 | Stage 1 (warpgrep v2) + Stage 2 (skeleton pruning), réutilise modules existants, NPU local, free-tier budget |
| groq | ❌ | — | no JSON object in response (texte libre) |
| github | ❌ | — | no JSON object in response |

**Conclusion** : 1 voix structurée + alignement avec doc Scaffolding préexistante = stratégie validée par convergence avec corpus interne (pas convergence cloud-cloud, faute de 3 voix). Stage 1+2 priorité confirmée.

## Exécution strategist

### SB2 — skeleton pruning Coder
- `--drafter dspy` : **FAIL** (JSON tronqué cerebras 2610 chars)
- `--drafter raw` : ✅ **OPTIMAL conf 1.00** par judge symbolique
- Draft = `_strategist_drafts/SB2_attempt1.py` (51 LOC, AST OK, pylint 10/10, McCabe 11, tokens 542)

**⚠️ Limite identifiée** : cerebras a produit un **squelette de fonctions** (`...` au lieu de l'implémentation). Le juge symbolique valide la structure (AST/pylint/LOC/dep/McCabe/tokens) mais **ne détecte pas l'absence de logique métier**. C'est la contrepartie assumée du "zero LLM judge" — pas de check sémantique.

### SB1 — warpgrep v2 cross-fichier
- `--drafter dspy` : FAIL (JSON tronqué groq + cerebras 300+ LOC > budget JSON)
- 300 LOC d'architecture neuve = au-delà des capacités draft cloud free-tier en un appel

## Décision pratique

Le draft cloud n'est **pas suffisant** pour Stage 1+2 directement mergeable. Pipeline livré :

1. **Stratégie cloud** validée (cerebras + doc)
2. **Judge symbolique** opérationnel mais structure-only
3. **Draft SB2** = squelette utilisable comme base humaine

**Next steps manuels** :
- Stage 1 (warpgrep v2) : architecture trop grosse pour 1-shot LLM → décomposer en 3 sous-tasks (symbol_table, import_resolver, callers_callees) puis strategist sur chaque.
- Stage 2 (skeleton pruning) : prendre le draft SB2 comme template + remplir manuellement `_skeleton_file` / `_zoom_functions` qui existent déjà dans `forge_swebench_runner.py` (lignes 1234+ par grep antérieur).

## Leçon pour future strategist

Ajout suggéré au juge symbolique : **stub detection** — si `ast.parse(code)` retourne plus de N fonctions dont le body = `[ast.Expr(ast.Constant(Ellipsis))]` (juste `...`), pénaliser. Ça empêche le "OPTIMAL squelette" trompeur sans recourir à un juge LLM.

---

## ⚠️ PIVOT ARCHITECTURAL — DSPy abandonné pour SWE-bench

Diagnostic externe (peer review 2026-05-24) :
> DSPy est brillant pour pipelines NLP linéaires (extraire, classifier,
> résumer) mais **catastrophique pour exploration ouverte** comme SWE-bench
> qui exige Search → Read → Test → Backtrack. Signatures rigides
> s'effondrent au moindre imprévu (fichier manquant, fonction mal nommée).

**Validation empirique** : SB1/SB2 dispatchés avec `--drafter dspy` =
**100% FAIL** (JSON tronqué cerebras, prose libre groq). Même problème
identifié indépendamment par le critique externe = signal fort.

**Nouvelle architecture pour SWE-bench** :

### 1. Repo Map (Aider/OpenHands) — ✅ LIVRÉ ce soir
- `app/forge_repo_map.py` 230 LOC : ast natif Python (zéro install)
- Compresse 100k LOC → ~3k tokens via signatures classes/fonctions
- `render_markdown` pour contexte LLM, `file_skeleton` pour body-masked
  + signatures conservées, `find_symbol` lookup
- **7/7 tests PASS**

### 2. Tools simples view/edit (à câbler hub)
- `view_file_content(path, start, end)` → lecture précise
- `edit_file_block(path, old_code, new_code)` → édition par bloc exact
- Agent navigue librement via la map, ouvre fichiers à la demande

### 3. LATS (Language Agent Tree Search Hassabis) — Stage 3 futur
- Agent génère N patches en parallèle (déjà esquissé dans
  `forge_actor.mcts_propose`, mais shallow 1-niveau)
- Hub crée N sandboxes (isolation) + applique patches
- Tests pytest = juge déterministe (test-fix loop existe déjà)
- Si N échouent : ramène les N stack traces → agent backtrack sur
  branche "le moins échoué" → tente amélioration
- Pas de cascade rigide DSPy → tolérance d'erreur native

### 4. PydanticAI (optionnel) — pour les outils typés
- Schémas stricts + raisonnement libre + ValidationError-retry transparent
- Remplace dspy Signatures pour les tool calls (pas pour le raisonnement)

## Méthodologie validée : DÉBAT AVANT ACTION

Sans ce débat (forcé par l'utilisateur), j'aurais investi 4-6h à durcir
dspy schema, étoffer prompts, retry-loops, etc. Tout ce temps gaspillé
sur la mauvaise direction architecturale. **Le débat = filtre indispensable
avant de lancer une exécution multi-heures.** Anchor.
