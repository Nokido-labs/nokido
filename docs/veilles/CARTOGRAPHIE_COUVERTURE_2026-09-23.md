# Cartographie de couverture du corpus de veilles — 2026-09-23

Direction owner : `ingéré ≠ retrouvé ≠ lu ≠ synthétisé ≠ décidé ≠ intégré`. Ce document est le DÉNOMINATEUR de
toute la suite : ce qui a été demandé, ce qui est sur disque, ingéré, lu, synthétisé, décidé. Le registre
`REGISTRE_SUBSTANCE_2026-09-23.md` est le registre des DÉCISIONS, pas de ce qui existe.

Mesures : `C:/tmp/inventaire_demande_veilles.py` et `C:/tmp/cartographie_veilles.py` (lecture seule, comptes par
index, aucune lecture longue pendant l'ingestion 6f). Journaux : `C:/tmp/*.json` de même nom.

## 1. Les quatre stocks

| stock | demandé / présent | ingéré | lu par un extracteur | synthétisé / décidé |
|---|---|---|---|---|
| **A. Veilles par URL du 23/09** (18 listes `C:/tmp/veille_*.json`) | ~385 URL | 361 sources, 8 429 chunks, 23 thèmes | **0 / 361** | fiches pour ~17-18 thèmes / 23 (à la main) ; registre des décisions |
| **B. Dépôts de code (E:)** | registre 342 cibles ; 271 dumps v2 (8,0 Go), **270 dumps v3** filtrés (3,0 Go), 46 v3_src_v1, 11 archives staging | **224 dumps** vus ingérés dans les journaux ; campagne 6f en cours | **0** | **aucune** |
| **C. Campagne « roadmap_ameliorations_veille »** (clôturée le 12/09) | 172 items ; 3 112 pages non citées | — | **159 pages lues / 3 112**, **2 750 jamais ouvertes** | 172 verdicts terminaux (LIVRÉ / DÉJÀ LIVRÉ / REJETÉ) |
| **D. Historique `biblio_raw`** | 2 515 éléments | 1 856 « promoted » (= ingérés, PAS « mécanisme extrait ») | inconnu | 158 suggestions du digest, **provenance en texte libre** |

## 2. Thèmes du stock A SANS aucune synthèse
`github_best_practices`, `mcp_gouvernance`, `openrouter`, `rag_long`, `ressources`.

## 3. Ce que le corps sait déjà faire, et à quelle échelle il le fait (mesuré)

| brique | rôle | échelle réelle |
|---|---|---|
| `app/forge_veille_digest.py` (DIGEST → SUGGEST, LLM local) | croise veille × anatomie × roadmap, dédup par empreinte | 158 suggestions ; sources NON rattachées aux chunks ⇒ couverture ILLISIBLE |
| `tools/forge_epistemic_extract_claims.py` | assertions, réévaluation, supersession, porte de promotion | **169 assertions sur 74 chunks, aucun de veille** ; toutes par `qwen2.5-coder:1.5b`, qualité NON évaluée ; 14 réévaluations |
| `chunk_claims.abstract_embedding` | base d'un regroupement par sens | colonne présente, usage non établi |
| cycle `biblio_raw` (`searching → reviewed → promoted / rejected / cold_rag`) | état de décision bibliographique | en place pour 2 515 éléments |
| `tools/forge_savoir_census.py` | où vit le savoir, et par quoi il est atteignable | existe (bornes `MAX(rowid)`, jamais `COUNT(*)`) |

## 4. Leçon déjà écrite par la campagne C, à ne pas repayer
« L'UNITÉ DE DÉPOUILLEMENT EST FAUSSE POUR UN SITE DE DOC » : 839/922 pages Hugging Face (91 %) = documentation de
bibliothèque crawlée page par page ; un verdict par page = 38 lots pour la même information. Le flux arXiv brut
(`ai_papers:`) : 14 à 18 pages hors domaine par lot de 22. ⇒ **regrouper AVANT de lire** (par bibliothèque, par
dépôt, par thème), jamais un verdict par page.

## 5. Conclusion mesurée
Le corps STOCKE sa veille, il ne la COMPREND pas encore seul : extraction automatique ≈ 0 % du corpus de veille ;
toute la synthèse existante est manuelle (campagne C, fiches du 23/09). La prochaine capacité à prouver n'est pas
une collecte de plus : c'est la transformation `corpus → extraction → déduplication → regroupement → mécanismes →
décision`, avec provenance par source.

## 6. Ce qui N'EST PAS mesuré ici (dit, pas supposé)
- l'état par cible du registre `sandbox/veille_targets.json` (champ d'état non reconnu par l'instrument : défaut
  de l'instrument, 342 « ? ») ;
- la couverture du digest (provenance en texte libre) ;
- `active=0` dans le stock A (exigerait de lire les lignes pendant l'ingestion) ;
- l'historique des veilles lancées (`watch_jobs` purgé) ;
- la part du stock D déjà reprise dans les stocks A ou C (recouvrements non calculés).
