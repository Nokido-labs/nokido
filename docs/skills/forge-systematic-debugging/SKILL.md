---
name: forge-systematic-debugging
description: >
  Méthode de débogage en 4 phases (cause racine → motif → hypothèse →
  correctif) adaptée à la pile Nokido. À utiliser sur un test qui échoue, un
  bug en production, un comportement inattendu, une erreur du hub ou du pont
  stdio, un RAG vide, ou quand plusieurs correctifs ont déjà échoué. Pas de
  correctif sans cause racine ; après 3 échecs, remettre l'architecture en
  question.
---

# forge-systematic-debugging — RCA 4-phases pour Nokido

## Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

Si Phase 1 n'est pas faite, **aucun fix proposé**. Les patches symptômatiques
sont une violation du protocole de session Nokido (cf. CLAUDE.md règles 5-7).

**Cas vécu Nokido cité dans CLAUDE.md** : `forge_pii_detector.py` créé puis
supprimé après 4h car investigation Phase 1 manquante (anti-duplication
RAG pas faite). 9 KB et 4 heures perdues. C'est exactement ce que ce skill
empêche.

## Quand l'utiliser

Activer **systématiquement** pour :
- pytest qui échoue (tests E2E firewall, tests bridge, etc.)
- bug en prod sur le hub :8766 ou bridge stdio
- "Tool execution failed" / "Hub error 400" (cf. `laforge-ops`)
- Comportement inattendu dans `forge_*.py`
- `preflight_check_verbose` qui ne retourne rien sur un domaine connu
- `RAGEngine.search` qui retourne des chunks aberrants
- SkillGuardian qui rejette une skill légitime
- Latence anormale du circuit breaker `forge_llm_router`
- Drift détecté dans netcfg-agent qui n'a pas de cause apparente

**Indispensable quand :**
- Tu es sous pression temporelle (urgence = tentation de guesser)
- "Juste un fix rapide" semble évident
- Tu as déjà essayé plusieurs fixes
- Le précédent fix n'a rien résolu
- Tu ne comprends pas vraiment l'issue

**Ne pas skipper même si :**
- Le bug semble simple (les bugs simples ont une root cause aussi)
- Tu es pressé (rush garantit du rework)
- Stakeholder veut "fix maintenant" (systématique > thrashing)

## Les 4 phases

Tu dois compléter chaque phase **avant** la suivante.

### Phase 1 — Root Cause Investigation

**AVANT toute tentative de fix :**

1. **Lire les messages d'erreur en entier**
   - Stack trace complète, line numbers, codes d'erreur
   - Logs `mcp_audit.log` (source unifiée depuis commit 5a8248a)
   - `_log_network()` du hub si erreur HTTP

2. **Reproduire systématiquement**
   - Steps exacts ?
   - À chaque fois ou intermittent ?
   - Si non-reproductible → gather more data, **don't guess**

3. **Vérifier les changements récents**
   ```bash
   git log --oneline -20
   git diff HEAD~5 -- app/forge_*.py
   ```

4. **🌟 Check RAG Nokido — c'est Nokido, on a du RAG**

   Avant tout, query le RAG sur le domaine du bug :

   ```python
   from forge_self_correction import preflight_check_verbose, read_lessons

   # Lessons récentes : cas similaires déjà documentés ?
   print(read_lessons(3000))

   # Recherche ciblée sur les symptômes
   v = preflight_check_verbose(
       "<symptômes du bug, ex: 'mcp_stdio_bridge timeout hub error 400'>", ""
   )
   for r in v["results"][:5]:
       print(f"[{r['score']}] {r['source']}: {r['preview'][:200]}")
   ```

   Si match >50% sur un anchor_error précédent → **lire le module incriminé
   AVANT de proposer un fix**.

5. **Gather Evidence en système multi-composants**

   Nokido = système multi-couches : Client MCP → Bridge → Hub → Registry
   → Tool → DB. AVANT de fixer, ajoute du logging à CHAQUE frontière :

   ```python
   # Layer 1 : Client (Cline / Claude Desktop)
   logger.info(f"[CLIENT] sending tool={tool}, args_keys={list(args.keys())}")

   # Layer 2 : Bridge stdio
   logger.info(f"[BRIDGE] forward to hub :8766, frame_size={len(payload)}")

   # Layer 3 : Hub mcp_post
   logger.info(f"[HUB] received tool={name}, ring={ring}, agent={agent}")

   # Layer 4 : ToolRegistry
   logger.info(f"[REGISTRY] check_access ring_needed={ring_needed}")

   # Layer 5 : Tool execution
   logger.info(f"[TOOL] {name}({args}) -> ...")
   ```

   **Ce que ça révèle :** quelle couche échoue (client → bridge ✓,
   bridge → hub ✗ par exemple).

6. **Trace data flow**

   Si erreur profonde dans un call stack :
   - Where does the bad value originate ?
   - What called this with bad value ?
   - Trace remontante jusqu'à la source
   - Fix at source, not at symptom

### Phase 2 — Pattern Analysis

**Trouver le pattern AVANT de fixer :**

1. **Find Working Examples** — chercher du code similaire qui marche dans
   le même codebase :
   ```python
   # Si bug dans un broker, lire forge_collab_broker.py et forge_broker_base.py
   # Si bug dans un MCP tool, lire un autre tool registered avec succès
   ```

2. **Compare Against References** — si tu implémentes un pattern, lire la
   référence COMPLÈTEMENT. Pas de skim. Chaque ligne.

3. **Identify Differences** — lister chaque différence, **même les petites**.
   Ne pas dire "ça peut pas mater".

4. **Understand Dependencies**
   - Quels singletons ? (`app/forge_context.py`)
   - Quels env vars ? (`LAFORGE_AGENT`, `PYTHONIOENCODING`, etc.)
   - Quel ring de sécurité requis ? (`forge_tools.min_ring`)
   - Quels guards ? (`SemanticFirewall.pre_flight`, `SovereignMembrane`)

### Phase 3 — Hypothesis & Testing

**Méthode scientifique :**

1. **Une seule hypothèse à la fois** : "Je pense que X est root cause
   parce que Y". Écris-la. Sois spécifique.

2. **Test minimal** : la PLUS PETITE modif possible pour tester l'hypothèse.
   Une variable à la fois. Pas de fix multi-points.

3. **Verify avant de continuer** :
   - ✅ Marché → Phase 4
   - ❌ Pas marché → NOUVELLE hypothèse (pas un fix de plus)

4. **Quand tu sais pas** : dire "je comprends pas X". Ne pas faire semblant.
   Demander, chercher dans le RAG, lire le code.

### Phase 4 — Implementation

**Fix root cause, pas symptôme :**

1. **Crée un test failing d'abord** (delegate au skill `forge-tdd` jumeau).
   Pour Nokido :
   ```python
   # tests/test_<module>.py
   def test_reproduces_bug_<descr>():
       """Reproduit le bug X ; doit FAIL avant fix, PASS après."""
       ...
   ```

2. **Implement single fix** — UNE seule modif, pas de "while I'm here"
   refactor.

3. **Verify**
   - Test passe ?
   - Aucun autre test cassé ? (`pytest -x`)
   - Issue réellement résolue (manuellement reproduit) ?

4. **Si fix marche pas** :
   - **STOP**
   - Compte combien de fixes essayés
   - **< 3** : retour Phase 1 avec les nouvelles infos
   - **≥ 3** : **STOP et questionner l'architecture** (point 5)
   - **NE PAS** tenter le fix #4 sans discussion architecturale

5. **Si 3+ fixes ont échoué : questionner l'architecture**

   Pattern qui indique problème architectural :
   - Chaque fix révèle un nouveau couplage / shared state ailleurs
   - Les fixes demandent du "refactor massif"
   - Chaque fix crée un nouveau symptôme ailleurs

   **STOP et challenge :**
   - Est-ce que ce pattern est sain ?
   - On y reste par inertie ?
   - Refactor architecture vs. continuer à patcher symptômes ?

   **À discuter avec l'humain partenaire avant le 4e fix.**

   Ce N'EST PAS une hypothèse failed — c'est une mauvaise architecture.

6. **Anchor la solution dans le RAG**

   ```python
   from forge_self_correction import anchor_solution

   anchor_solution(
       problem="Description courte (les futurs LLMs la chercheront)",
       solution="Ce qui a été fait + WHY + nom de fichier exact",
       example="Snippet code réutilisable",
       domain="bridge",  # ou rag, security, llm, netcfg, ctf, ...
   )
   ```

   Si erreur stockable mais non corrigée :
   ```python
   from forge_self_correction import anchor_error
   anchor_error(error_msg="...", context="...", solution="leçon", domain="...")
   ```

## Red flags — STOP et reprendre le process

Si tu te surprends à penser :
- "Quick fix maintenant, j'investigue après" ← nope
- "Essaye de changer X et voir" ← nope
- "Ajoute plusieurs changements, run tests" ← nope
- "Skip le test, je vérifie manuellement" ← nope
- "C'est probablement X, je fixe" ← nope
- "Je comprends pas tout mais ça pourrait marcher" ← nope
- "Le pattern dit X mais je vais l'adapter" ← nope
- "Encore un fix" (après 2+ échecs) ← nope, **questionne l'architecture**
- Chaque fix révèle un nouveau bug ailleurs ← problème architectural

**Tous ces signaux = STOP, retour Phase 1.**

## Signaux de l'humain partenaire = "tu fais mal"

À surveiller :
- "C'est pas le cas ?" → tu as supposé sans vérifier
- "Ça va nous montrer... ?" → tu aurais dû ajouter du logging
- "Stop guessing" → tu proposes des fixes sans comprendre
- "Ultrathink" → questionne les fondamentaux, pas les symptômes
- "On est bloqué ?" (frustré) → ton approche ne marche pas

**Quand tu vois ça : STOP. Retour Phase 1.**

## Common rationalisations (à débunker)

| Excuse | Réalité |
|---|---|
| "Issue simple, pas besoin de process" | Les bugs simples ont aussi une root cause |
| "Urgence, pas le temps" | Systematic est PLUS RAPIDE que thrash |
| "Try this first, investigate after" | Le 1er fix donne le ton |
| "Test après confirmation" | Untested fixes don't stick |
| "Multi-fixes saves time" | Tu peux pas isoler ce qui a marché |
| "Ref trop longue, j'adapte" | Compréhension partielle = bug garanti |
| "Je vois le problème, je fixe" | Voir symptôme ≠ comprendre root cause |
| "Encore un fix" (après 2+) | 3+ échecs = problème architectural |

## Anti-patterns Nokido spécifiques

1. **Skipper le `read_lessons(3000)` de start-of-session** — tu vas refaire
   un bug déjà documenté.
2. **Skipper le `preflight_check_verbose` sur le domaine du bug** — un
   anchor_error précédent contient peut-être déjà la solution.
3. **Patcher un module sans `anchor_solution` après** — le prochain LLM
   refera le bug.
4. **Modifier `forge_mcp_registry` ou `nokido_hub` sans test** — ces
   fichiers sont les colonnes vertébrales, casser ça = tout par terre.
5. **Bypasser `SemanticFirewall.pre_flight` parce que "ça bloque mon
   debug"** — Règle d'Or n°4. Bypass jamais.

## Quick reference

| Phase | Activités | Critère succès |
|---|---|---|
| **1. Root Cause** | Lire erreurs, reproduire, check changements, RAG/lessons, evidence multi-couches | Comprendre QUOI et POURQUOI |
| **2. Pattern** | Working examples, compare, list différences | Identifier les différences |
| **3. Hypothèse** | Forme théorie, test minimal | Confirmé ou nouvelle hypothèse |
| **4. Implementation** | Test failing, fix, verify, anchor | Bug résolu + RAG mis à jour |

## Liens

- Source originale : `obra/superpowers/skills/systematic-debugging`
- Nokido tools cités :
  - `app/forge_self_correction.py` — preflight_check, anchor_error,
    anchor_solution, read_lessons
  - `app/forge_rag_engine.py` — RAGEngine.search
  - `logs/lessons_learned.md` — trace humaine
  - `mcp_audit.log` — logs unifiés hub/bridge/registry
- Skill jumeau : `forge-tdd` (Phase 4 step 1)
- CLAUDE.md du repo Nokido — règles d'or, exemple `forge_pii_detector`
