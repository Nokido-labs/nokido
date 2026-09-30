# Fiche de sortie — Veille « TypeSafe / System One » (2026-09-23)

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION.
Pipeline B (connaissance) : aucune modification de code ici.

Sources : `docs.typesafe.ai` (114 pages via `llms.txt` + sitemap) et `github.com/typesafe-ai` (10 dépôts).
Ingestion `job_1f9e74bcb6c1` : 160 URL, **140 OK · 19 COURT · 1 ERR**, 2 790 chunks, `source LIKE 'watch:typesafe:%'`.
Archive brute : `E:/nokido_veille_staging/veille_typesafe.jsonl`. Écartées (dites, pas muettes) :
`C:/tmp/veille_typesafe_ecartees.json` — 41 (assets Mintlify + 40 docs du fork `vllm`, amont hors sujet).
L'unique ERR = `typesafe-ai.github.io/main/README.md` → HTTP 404 (dépôt sans README ; 0 doc vue par l'API) : rien de perdu.
Limites de la 1re version LEVÉES en § 8 (dépôts lus, chiffres vérifiés, ligne de base reproduite).

## 1. PATTERNS

| Pattern | Source |
|---|---|
| **Décision fermée typée** au lieu de texte généré : 3 primitives — `Choice` (une option parmi N), `Score` (niveaux ordonnés décrits), `Noul` (P(oui) d'une question oui/non). Le code garde le contrôle, le modèle ne rend que des décisions étroites | `/primitives`, `/concepts/system-one` |
| **Probabilité ≠ confiance.** La réponse porte la distribution complète ; `confidence` est une statistique DÉRIVÉE. Pour un Choice à n options : `conf = clamp((n·p_max − 1)/(n − 1), 0, 1)` (0 = distribution uniforme, 1 = certitude) | `/confidence` (formule lue dans le composant de la page) |
| **Confiance = second axe** : la réponse dit QUOI, la confiance dit S'IL FAUT AGIR. Trois bandes : agir / confirmer / ne pas agir (humain, clarification, autre système) | `/confidence`, `/patterns/confidence-routing` |
| **Seuils proportionnels au RISQUE de l'action**, pas un seuil global (ex. solde lisible à 0,6 ; virement auto > 0,85, confirmation entre 0,6 et 0,85) | `/patterns/confidence-routing` |
| **Fan-out spéculatif** : toutes les questions en un appel sur un état ingéré une fois ; questions indépendantes (pas de contexte caché entre elles). Annoncé : 13 questions ⇒ 12,2× moins cher, 10× plus rapide | `/patterns/fan-out`, cookbook `parallel_questions` |
| **Score composite** : décomposer un jugement en scores atomiques, pondérer DANS LE CODE | `/patterns/composite-scoring` |
| **Auto-cohérence** : router les probabilités incertaines vers revue humaine en gardant les valeurs visibles | cookbooks `consistency_*` |
| **Cascade** mini → vérif → raisonnement pour l'extraction structurée | cookbook `sde_cascade` |
| **Jaggedness publiée** : l'éditeur liste ses modes d'échec (lecture littérale, arithmétique, dates, indirection, grand état non pertinent, contenu adverse, critères contradictoires…) avec la parade — « garder l'arithmétique et la comparaison de dates DANS LE CODE » | `/model-jaggedness/jev-1.13` |
| Modèle **cloud** propriétaire (Jev 1.13) : texte seul, 64k contexte, ~100 ms, 0,042 $/Mtok en entrée (sortie gratuite), limites « ajustées dynamiquement » | `/models` |

## 2. NOKIDO_EXISTING (via `introspect` + lecture ciblée)

- `app/forge_routing_decision.py` — `RoutingDecision` porte **`confidence` ET `uncertainty` distincts**
  (l. 55-56 : « Pas 1-confidence »), `abstention` (l. 122, 4 appelants, attribution RÉSOLUE). C'est déjà la
  distinction probabilité/confiance de TypeSafe, du côté du routeur.
- `app/forge_frugal_cascade.py` — cascade « modèle le moins cher d'abord + porte de confiance », seuil
  `FRUGAL_CONFIDENCE_THRESHOLD=0.6` (l. 82). **Mais la confiance est une HEURISTIQUE de texte**
  (`_heuristic_confidence`, marqueurs d'hésitation, l. 149) **ou une auto-déclaration du LLM 0-10**
  (`_ask_self_confidence`, l. 204) — pas une distribution sur des réponses fermées. Procédure PROUVÉE
  `f3bc7c1c` (30/08) : la cascade passe par le routeur souverain.
- Doctrine déjà écrite qui recoupe « seuils ∝ risque » : `REQUESTED ≠ ACCEPTED ≠ ACHIEVED`, confirmer
  l'irréversible, « coût des 2 erreurs JAMAIS symétrique » (RULES_SHARED).
- `logprobs` : `findstr` sur `app/` et `tools/` ne rend rien — sous le compte offline ⇒ **ILLISIBLE**, pas absent.

## 3. EVIDENCE

| Élément | Niveau |
|---|---|
| `RoutingDecision` confidence/uncertainty séparés | **OBSERVED** (code lu) ; calibration non mesurée |
| Porte de la cascade frugale | **OBSERVED** (code lu) ; qualité de sa confiance heuristique **UNKNOWN** — jamais confrontée à une vérité terrain |
| Usage de distributions de probabilité (logprobs) d'un modèle local pour décider | **UNKNOWN** (recherche illisible) |
| « 12,2× moins cher » (fan-out) | **VERIFIED par calcul** (§ 8) — mécanisme générique, pas une propriété de Jev |
| Ligne de base BM25 du rerank (2/40 · 15/40 · 40/40) | **VERIFIED** — reproduite à l'identique en local (§ 8) |
| Gain Jev au rang 1 (2 → 7 / 40) | **DECLARED**, et **non significatif** même au meilleur cas (§ 8) |
| Gain Jev au top 10 (15 → 25 / 40) | **DECLARED**, significatif si ≤ ~4 pertes ; non reproduit (API cloud) |

## 4. GAPS

1. **La confiance de la cascade n'est pas calibrée** : heuristique de texte ou auto-déclaration. TypeSafe
   construit tout son produit sur l'idée inverse — une confiance DÉRIVÉE d'une distribution sur des réponses
   FERMÉES. L'auto-évaluation d'un LLM n'est pas une probabilité.
2. **Un seul seuil global (0,6)** là où le pattern exige un seuil par CONSÉQUENCE de l'action.
3. Pas de primitive locale « question fermée → distribution » (Choice/Noul) réutilisable par le routeur,
   le grader d'issue (fiche V2) ou le tri des passages RAG (cookbook `classifying_rag_passages`).
4. **Qualité de l'ingestion** : 18 pages de doc sur 114 contiennent des composants JSX/JS en ligne
   (`export function …`, dont un compresseur LZ entier) **ingérés dans le RAG avec la prose**.
   `veille_urls.py` ne retire pas les composants MDX ⇒ bruit en retrieval. Touche toute source Mintlify.

## 5. MINIMAL_EXPERIMENT (lecture seule, local, aucun appel cloud)

Calibration comparée sur UN jeu étiqueté existant (ex. décisions d'intention passées avec issue connue) :
(a) confiance actuelle de `forge_frugal_cascade` ; (b) confiance dérivée de la distribution d'un modèle
LOCAL contraint à répondre par une étiquette (probabilités des jetons d'étiquette via llama.cpp), formule
`(n·p_max − 1)/(n − 1)`. Mesure : ECE + courbe « taux d'action auto vs taux d'erreur » par seuil.
Préalable : établir si le serveur local expose les logprobs (mesure, pas supposition).
Aucun essai de l'API TypeSafe : ce serait un envoi cloud (Firewall pre/post-flight + feu vert owner).

## 6. NR

- `test_confiance_choice_formule_nr` : distribution uniforme ⇒ 0 ; one-hot ⇒ 1 ; n=2, p=0,75 ⇒ 0,5 ; borné [0,1].
- `test_seuil_par_consequence_nr` : une action irréversible n'est JAMAIS auto-exécutée au seuil d'une action
  en lecture seule (invariant, pas une valeur).
- `test_veille_sans_composant_mdx_nr` : une page contenant `export function` en tête ne produit aucun chunk
  de code JS.

## 7. DECISION

- **ADOPT (pattern)** : confiance dérivée d'une distribution sur réponses fermées + seuils par conséquence.
  À porter dans l'EXISTANT (`RoutingDecision`, `forge_frugal_cascade`), jamais dans un module parallèle.
- **REJECT par défaut (dépendance)** : API cloud propriétaire, limites instables — contraire au local-first.
  Réexaminable seulement sur mesure comparative et feu vert owner.
- **DEFER** : nettoyage MDX de `veille_urls.py` (touche un moteur partagé ⇒ NR d'abord).
- Lien : fournit à la fiche V2 la forme du grader (`Noul` = « l'état attendu est-il atteint ? » avec P) et
  à la fiche hybride un tri des passages avant génération.
- Contre-preuve à chercher : une confiance bien calibrée EN MOYENNE ne dit rien d'un cas isolé (TypeSafe
  l'écrit lui-même) ⇒ ne jamais s'en servir seule pour une action irréversible.

## 8. AU-DELÀ DES LIMITES (même jour, lecture + calcul + reproduction locale)

**Dépôts lus.**
- `system-one-adapter-python` : remplaçant « drop-in » de l'API System One **adossé à n'importe quel LLM**
  (OpenAI-compatible — donc pointable sur un llama.cpp local —, Anthropic, Gemini), explicitement « pour
  comparer TypeSafe à un LLM ». Mode `llm_answer_mode="probabilities"` = le LLM **ÉCRIT** ses probabilités en
  JSON (+ `normalize_probabilities`) : c'est de l'**auto-déclaration**, la faiblesse même de
  `_ask_self_confidence` (§ 2). Pas de logprobs. Utile comme banc de comparaison, pas comme source de calibration.
  Bonne pratique à retenir : `llm_attempts` journalise chaque appel (messages, schéma, réponse brute, erreur)
  et permet le REJEU exact d'une tentative.
- `skills/SKILL.md` (MIT) : skill d'agent « Build with TypeSafe » — lire la doc vivante (`llms.txt`, `.md`
  ajouté au chemin Mintlify), garder règles/calculs/exécution dans le code, « sélectionner au lieu de générer ».
  C'est un vecteur d'adoption (plugin Claude Code), pas une capacité.
- `Overwatch` : **hors sujet décision** — tableau de bord local SkyPilot/W&B/CloudWatch/coûts cloud. Deux
  principes d'`AGENTS.md` recoupent notre doctrine et la confirment : « ne pas inférer un statut structuré
  depuis les logs quand le fournisseur expose un champ autoritatif » ; « rapporter une ventilation
  indisponible comme **unknown** » ; inventaire complet d'abord « pour qu'une télémétrie manquante ne cache
  jamais une machine qui tourne » (= `UNKNOWN ≠ NO`).

**« 12,2× moins cher » — vérifié par calcul** (prix publié 0,042 $/Mtok, entrée seule) :
groupé 0,000497 $ ⇒ 11 833 jetons ; 13 appels 0,006090 $ ⇒ 145 000 jetons ⇒ document ≈ 11 097 jetons,
question ≈ 57. Le modèle « le document n'est envoyé qu'une fois », 13(d+q)/(d+13q), prédit **12,25×**
(plafond 13×). ⇒ gain **générique** (tout modèle facturé à l'entrée), pas un avantage de Jev.
« 10× plus rapide » = latences des 13 appels **sommées en série** (la page l'admet).

**Rerank CLERC — ligne de base reproduite à l'identique** (`C:/tmp/exp_typesafe_rerank_base.py`, code du
cookbook recopié, `seed=0`, venv isolé `C:/tmp/venv_rerank` + `bm25s` seul, aucun env partagé touché) :
corpus 3 565 · top 30 **40/40** · rang 1 **2/40** · top 10 **15/40** = chiffres publiés, exactement.
Échantillon et BM25 sont donc honnêtes ; seule l'étape Jev reste invérifiée (API cloud).

**Poids statistique du gain annoncé (n = 40, apparié).** IC95 Wilson : rang 1 BM25 [1,4 ; 16,5] %,
Jev [8,7 ; 32,0] % ; top 10 BM25 [24,2 ; 53,0] %, Jev [47,0 ; 75,8] %.
McNemar exact : **rang 1 (+5) jamais significatif**, p = 0,0625 même avec 0 perte ; top 10 (+10)
significatif tant que les pertes restent faibles (p = 0,002 à 0 perte ; 0,031 à +14/−4).
⇒ le titre « 5 % → 18 % » sur-vend ; le résultat robuste est le top 10.

**Reranker LOCAL sur la même tranche** (feu vert owner ; `NokidoLlamaReranker` bge-reranker-v2-m3 Q8,
`disabled = true` par politique, démarré pour le test puis REMIS à l'arrêt ; démarrage PROUVÉ par un rerank
témoin, pas par le `success` de la route). `C:/tmp/exp_typesafe_rerank_local.py` → `…_local.json` :
40/40 requêtes groupées OK, 0 repli, 0 troncature, 0 illisible, 316 s, 0 appel cloud.

| | BM25 | bge local | Jev (publié) |
|---|---|---|---|
| rang 1 | 2/40 | 3/40 (+2/−1, McNemar p = 1,0) | 7/40 |
| top 10 | 15/40 | 13/40 (+8/−10, p = 0,81) | 25/40 |
| MRR | 0,155 | 0,169 | — |

⇒ **le cross-encoder générique n'apporte RIEN sur cette tâche** (égal à BM25 aux erreurs près). Lecture la
plus probable, NON prouvée : bge mesure la proximité THÉMATIQUE, or le critère du Noul exclut précisément
« merely on a similar topic » — c'est une tâche de raisonnement juridique (la proposition précise invoquée),
pas de similarité. Si le 25/40 de Jev est réel, l'écart avec bge (13/40) est large (IC95 Wilson disjoints :
bge ≈ [20 ; 48] %, Jev [47 ; 76] %) — mais NON apparié et NON reproduit.
UNKNOWN : llama.cpp a-t-il tronqué des paires longues en silence côté serveur (aucune erreur remontée) ?
**Conséquence pour Nokido** : ne pas supposer que l'étage `bge` du RAG améliore le rang 1 sur des requêtes
« de raisonnement » ; le mesurer sur NOS requêtes avant de le réactiver (il reste `disabled`).
Prochain comparateur local honnête : même tranche avec un LLM local en mode Noul contraint (une étiquette,
probabilité tirée des logprobs si exposés) — c'est l'expérience du § 5, désormais avec un banc prêt.
