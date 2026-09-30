# Sprint X (futur) - Planner local pour deleguer l'orchestration

Date : 2026-04-27
Status : NOTE pour reprise ulterieure, pas avant Sprint Q5 termine

## Contexte

Aujourd'hui (avril 2026) c'est Claude Sonnet 4.7 qui orchestre :
- Decide quel LLM consulter
- Lance les rounds en parallele (subprocess detached)
- Synthetise les retours
- Gere le sequencage des taches

Cela consomme des tokens Claude (cher) a chaque tour.

## Objectif

Faire de Claude un "expensive cognition fallback" appele uniquement quand
le planner local manque de confiance (pattern FrugalGPT cascading).

## Pre-requis (ne pas commencer ce sprint avant que ce qui suit soit fait)

1. Sprint Q5 lessons termine (P0+P1 = 22h) :
   - Schema lessons + hash chain + sanitization + workflow draft->validated
   - Permet au planner d'avoir une memoire fiable a injecter
   
2. Sprint Q4 memory injector pipeline :
   - top-K leçons match semantique
   - Système prompt cached pour les politiques/securite
   - User prefix pour les leçons contextuelles
   
3. Phase 4 auto-doc tools :
   - Champ `_meta.next_steps_suggestions` dans chaque tools/call retour
   - `_meta.quota_health` pour decider routing
   - `tools/list` enrichi avec hint d'enchainement

4. Audit providers complet :
   - Forge_provider_errors.py classifier
   - Circuit breaker par provider
   - Health check periodique

5. forge_cognitive_router._estimate_complexity calibre
   - Aujourd'hui : regex/longueur basique
   - Cible : classifier ML léger (Ollama tiny ou rules-based)

## Architecture cible

```
User input
    |
    v
[forge_cognitive_router] --> decide complexity score
    |
    v
[Planner local : Qwen-Coder-32B sur Ollama]
    |
    v
Plan d'execution = sequence d'appels d'outils + memoire injectee
    |
    v
[Dispatcher] execute le plan, consulte LLM tier UNIQUEMENT si :
    - Confidence du planner < 0.7
    - Tache marquee comme "creative writing" / "high-stakes decision"
    - Erreur recurrente sur tentative locale
    |
    v
Resultat + lecons extractees -> alimentation lessons (cycle ferme)
```

## Choix de modele pour le planner

Candidats Ollama deja installes (a verifier) :
- qwen2.5-coder:32b (32B, ctx 32K) - reasoning + code
- qwen2.5-coder:7b (7B, ctx 32K) - rapide
- llama-3.3-70b (si dispo) - generaliste

Critere de selection : tokens/seconde sur Ryzen 8700G + qualite plan execution.

## Effort estime

40-60h cumulatives, etalees sur 3-4 sprints distincts.
Pas avant que Q5 + Q4 + Phase 4 ne soient livres.

## Decision : note actee, sprint reporte
