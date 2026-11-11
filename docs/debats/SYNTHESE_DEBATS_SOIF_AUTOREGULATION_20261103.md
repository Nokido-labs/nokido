# Synthèse des débats du 3/11 — Claude × AGY

Demandés par l'owner : « il faut quelque chose de solide qui renforce le code et le corps » (soif + physiologie),
puis « l'auto-régulation du corps et du code efficace ». Chaque position a été écrite AVANT de lire l'autre.

- Texte d'AGY, débat 1 : commit `72d10a76e` (`docs/debats/debat_soif_physiologie_agy_20261103.md`, branche de tâche).
- Texte d'AGY, débat 2 : commit `7b0a1bc02` (`docs/debats/debat_autoregulation_agy_20261103.md`, branche de tâche).
- Positions de Claude : `C:/tmp/laforge_jobs/position_claude_debat_physio_20261103.md`, `..._autoregulation_20261103.md`.

## Débat 1 — le corps détecte seul ses manques de physiologie

**Convergence (indépendante)** : option B sans registre séparé. L'homologue biologique est déclaré DANS le module et
extrait par le census (comme `__FORGE_COLOR__`) ; instrument `physiologie_fts` en FTS indexé, remesurable ; un trou
ouvre une lacune EXTERNE dont la piste est la veille (budget + arbitre de saillance) ; NR obligatoire.

| Point | AGY | Claude | Retenu |
|---|---|---|---|
| Déclaration | chaîne `"system/term"` | dict | **dict** `mecanisme, termes, sources, invariant, nr` (la FTS a besoin des termes) |
| « Couvert » | `score ≥ 3` chunks (veille ×2) OU validé par une veille | ≥ 2 sources dont 1 référence | **≥ 2 sources distinctes ET ≥ 1 référence en texte intégral (≥ 5 chunks)**. Mesure 3/11 : PMC7046449 = 65 chunks à lui seul ; 5 résumés DOI (1-2 chunks) sur les cytokines ne couvrent rien |
| Code renforcé | le juge du RSI rejette un candidat « homologue » sans test de rétroaction négative | gate census « homologue sans NR » | **les deux** : gate observé puis bloquant, + juge du RSI |
| Risque | candidats en file périmés si l'arbre bouge | — | NR d'invariant dans `tests/nr/` (hors des modules édités) |

## Débat 2 — auto-régulation efficace

Grille commune (OpenStax A&P m45989) : capteur + centre + effecteur + consigne ; efficace = l'effecteur agit sur la
variable mesurée.

| Boucle | État (AGY, preuves fonction:ligne) |
|---|---|
| Admission des jobs / RAM | **OUVERTE** : `request_resources` ne connaît que les modèles, 0 Go rendu sur refus |
| Carcasse Docker/WSL | FERMÉE (c806a85e8) |
| Sampler + barème Hamilton | **OUVERTE** : Hamilton exige `verdict == "SOI"` ; la carcasse comptée `NON_SOI` → aucune action ; auto-éviction seulement à 90 % |
| Soif | FERMÉE (fd9c6f988, 17bf6b2d0) |
| RSI | FERMÉE (17bf6b2d0) |
| Vidage qdrant | **OUVERTE** : effecteur sur la mauvaise variable (cache mappé) |
| Adrénaline hub | OUVERTE, assumée (`NO_RECEPTOR_REASON`) |

**Mécanisme retenu** (AGY, complété) : un effecteur unique de substrat. `request_resources`, sur échec des évictions
de modèles, appelle les gardiens de substrat (relâche d'une ressource vivante SANS intention : carcasse Docker…)
avant tout refus. Ajout Claude : chaque effecteur MESURE le gain physique (RAM disponible avant/après) et abandonne
une voie à rendement nul ; un refus d'admission prouve soit une libération, soit « rien à libérer » (cas du 3/11 au
soir : 87 % tenus par 3 veilles légitimes + qdrant, refus correct).

**Invariants** : refus ⇒ effecteur appelé et résultat mesuré ; ressource sans intention coupée en ≤ grâce, avec
réfractaire (anti-oscillation) ; une seule consigne par variable ; hormone émise ⇒ récepteur ou raison déclarée.

## Tour 2 (même soir, après implémentation : e405a7a93, d5d966ea5)

Matière mesurée : `sandbox/workspace/matiere_debats_20261103.md` (allostasie, contrôle intégral, sommeil COUVERTS ;
comportement de maladie TROU : 5 DOI de 1-2 chunks, même après une veille « full text »).
AGY : débat 2 tour 2 `ebf8b8fcf` ; débat 1 tour 2 `8c097e2a1` (3e essai, mode court : 1er = fichier non suivi refusé,
2e = 896 k jetons sans réponse, print_timeout). Positions de Claude écrites avant lecture.

**Débat 1 — accords** : arXiv = référence pour un mécanisme de CONTRÔLE seulement, jamais biologique ; Wikipédia jamais
référence ; texte intégral par veille rapide EuropePMC/PMC ; escalade par `irresolution_proposee` après 2 échecs ;
NR 3 = le NR de l'homologue joint d'office au périmètre du juge, dispense si le patch modifie ce NR.
5 homologues proposés (admission → autorégulation rénale ; keeper → autophagie ; ressources → torpeur / charge
allostatique ; endocrine → demi-vie et clairance ; circadien → noyau suprachiasmatique) : invariants à préciser en NR.

**Débat 2 — accords** : deux risques de d5d966ea5 (réfractaire de l'effecteur par processus ; Docker lancé à la main sans
intention coupé sur refus) ; allostasie = intention posée par l'ÉTAPE et AVANT la recherche (T+1) ; consigne circadienne.
**Découverte d'AGY** : un régulateur PI (`decision_pi`) existe déjà dans l'admission mais le seuil dur le court-circuite
sur le chemin réel → brancher l'intégral existant plutôt qu'en écrire un. Hamilton : autoriser le délestage auxiliaire
sous détresse critique même `NON_SOI`. Corrections : seuil de stérilité qdrant = 0,3 Go (pas 0,5) ; `MAX_RAM_PCT` = 85
(pas 88, vérifié dans le code et l'environnement).

## Matière de veille (owner : « il faut de la matière pour nourrir la réflexion »)

Lancées le 3/11 : comportement de maladie (2 passes ; 5 sources, résumés seulement → lacune encore ouverte),
sommeil/consolidation (16 sources web), revues de comportement de maladie en texte intégral, allostasie / régulation
prédictive (Sterling), boucles de rétroaction biologiques / contrôle intégral.
