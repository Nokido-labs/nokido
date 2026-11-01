# Décisions owner du 24/10/2026 (choix multiple, session Claude Code)

Consignées pour que toute surface les applique ; chacune clôt ou oriente un item de roadmap.

## 1. Planificateur « AlphaGo » de la roadmap — `P1_planificateur_alphago_roadmap_arene_20261018`

**Mesure** (rapport `sandbox/workspace/rapport_alphago_serie_20261022.md`) : sur 16 prédictions, l'item prédit
avance dans 56 % des cas, mais le répondeur prédit n'en livre que 6 % (aveugle aux pannes du jour).

**Décision : garder la prédiction de l'ITEM, abandonner celle de l'EXÉCUTANT.** Le choix de l'exécutant appartient à
l'exécuteur, qui voit l'état réel : coupe-circuit (`fc5592ab8`), charge des files (`daf0f0ffa`), conseiller souverain
(`6c5193f2f`, `28f7b1814`). Fin de l'observation.

## 2. Sous-agents — `P1_essai_mesure_sous_agents_claude_20261017`

**Décision : jouer l'essai mesuré des sous-agents Claude**, avec l'**accord explicite de l'owner** à chaque fois et à
sa demande (geste owner : réarmer le hook d'exception, 24 h, 6 appels). **Sur les LLM gratuits, déléguer à des
sous-agents dès que c'est possible**, sans attendre. L'item reste ouvert jusqu'au réarmement et aux 6 mesures.

## 3. Budget Mammouth épuisé — `P2_mammouth_absence_budget_gestion_20261024`

**Décision : gel + repli gratuit.** Budget épuisé = voie GELÉE dans la matrice (`geler_voie`, `3e3ce9f0e` :
SANS_SOLDE / QUOTA_EPUISE, score None, jamais retirée, à re-sonder), le swarm bascule sur les free tiers puis Claude
en dernier ; aucune recharge automatique.
