# Constat d'échec de la méthode de veille — 2026-08-31

Écrit AVANT de rattraper quoi que ce soit. Rattraper 342 dépôts avec la méthode
actuelle reviendrait à multiplier ses défauts par 342. Chaque point ci-dessous
est une mesure du jour, pas une impression.

## 1. La veille n'avait aucun dénominateur

Quatre outils existaient, chacun mesurant un **numérateur** :

| outil | ce qu'il compte | ce qu'il ignore |
|---|---|---|
| `forge_veille_audit` | les `watch_jobs` lancés | tout ce qui n'a jamais été lancé |
| `forge_veille_gap_recover` | les URLs déjà en `biblio_raw` sans contenu RAG | ce qui n'est jamais entré en biblio |
| `forge_veille_clone_ingest` | 12 dépôts **câblés en dur** dans son dict | les 330 autres |
| `forge_veille_github_direct` | les dépôts d'une campagne, en dur eux aussi | idem |

Aucun ne savait ce qui avait été **demandé**. Un dépôt nommé en conversation et
jamais recopié dans un dict était invisible pour les quatre — pas même comme
manquant. Un système qui indexe ses réponses mais pas ses questions refait
indéfiniment ses enquêtes ; ici il ne les faisait même pas.

**Mesure** : 342 dépôts externes cités, **161 demandes jamais ingérées**, dont la
plus ancienne remonte au 2026-05-29. Aucun rapport ne les avait jamais listées.

## 2. Les registres ne couvrent pas la période demandée

L'owner demande « depuis mars ». Le dépôt a été créé le **2026-03-08**. Or :

- `watch_jobs` ne remonte qu'au **2026-08-02** (45 jobs) ;
- le corpus conversationnel RAG couvre **2026-06-08 → 2026-08-22**.

Mars à juin ne sont dans AUCUN des deux. La seule source qui couvre la période
est le **code** : les scripts de campagne, dont les dépôts sont câblés en dur.
C'est pour cela que l'inventaire lit désormais `tools/`, `app/` et `C:/tmp` — 23
demandes n'existent QUE là. Et le corpus s'arrête au 22/08 : neuf jours de
conversations ne sont pas indexés, ce qui n'est signalé nulle part.

## 3. L'ingestion par clone avale du contenu GÉNÉRÉ

Décision owner du 30/08 : « il ne faut pas de limite à l'ingestion d'un dépôt
GitHub ». Elle tient — mais elle portait sur les **caps de volume**, pas sur la
nature de ce qu'on avale. Mesure sur les 13 dépôts déjà pris :

| dépôt | chunks | ce que c'est en majorité |
|---|---|---|
| `scalesim` | 80 137 | `test/**/golden_trace_*/*.csv` — traces de simulation |
| `tinytinytpu` | 27 077 | `.vcd` (formes d'onde), build Verilator, `.edif` |
| `codex` | 98 739 | source Rust — **utile** |

Les six plus gros `source` de toute la veille sont des `.vcd` et des
`FILTER_DRAM_TRACE.csv` : entre 4 000 et 8 200 chunks **chacun**. Ce n'est pas de
la connaissance, c'est de la sortie de machine. Le tri par liste noire
d'extensions ne les attrape pas : un `.csv` et un `.vcd` sont du texte.

**Conséquence directe** : sur 308 366 chunks de veille par clone, une large part
est du bruit qui a coûté du temps d'ingestion, occupe la base, et sera repayé à
chaque dédup, chaque compaction et chaque recherche lexicale.

## 4. Ce qui est ingéré n'est pas exploitable

- **0 vecteur** sur les 308 366 chunks `domain='sdk_gitingest'`. Toute la veille
  par clone est purement lexicale : aucune organisation sémantique n'est possible
  dessus, quelle que soit la dimension d'embedding.
- **6 fichiers digérés sur ~1 138** pour `codex`, le seul dépôt entamé. Les 12
  autres n'ont aucun digest.
- La voie `ecosysteme_github` ingère **1 chunk par dépôt** (description + topics) :
  26 dépôts à 1 chunk. C'est un annuaire, pas une veille.

Autrement dit la chaîne s'arrête après l'estomac : on avale, on ne digère pas, et
ce qu'on a avalé n'est pas rangé.

## 5. Chaque campagne réécrit un script

`C:/tmp` porte plus de cinquante scripts `veille_*.py` one-shot — `veille_biomed_v2`,
`v3`, `v4`, `veille_repos_v2`, `veille_3libs_clone`, `veille_cordiverse_deepseek_20260824`…
`forge_veille_github_direct` note déjà le défaut dans son propre code (« l'outil
avait ses cibles EN DUR : chaque campagne le réécrivait »), et l'a corrigé pour
lui seul. Le motif, lui, n'a pas été traité : la cible d'une veille est une
**donnée**, elle n'a rien à faire dans du code.

## 6. Deux dépôts « ingérés » qui ne contiennent rien

`ecqin/SysArray-nMigen` : **17 chunks**. `antonpaquin/SystolicArrayDemo` : **14**.
Ils comptent comme INGÉRÉS dans tous les rapports. Un seuil de plausibilité (un
dépôt de code sous ~100 chunks est suspect) les aurait signalés ; il n'existe pas.

## 7. Défaut de mon propre instrument, dit ici pour ne pas le rejouer

Ma première passe annonçait **364 dépôts absents**. Trois artefacts de mesure la
gonflaient, tous dans le sens qui m'arrangeait :

- `user/nokido` compté comme veille manquante (x771) — c'est le dépôt maison ;
- `settings/tokens`, `resources/articles`, `en/copilot` : l'interface du site
  occupe le même espace de noms que les dépôts ;
- `api.github.com/repos/<org>/<nom>` lu comme `repos/<org>` — des dépôts inventés.

Et un quatrième, plus grave : sans lire le rôle en tête de chunk, **une URL que
j'avais moi-même citée comptait comme une demande de l'owner**. Le tri par rôle
fait tomber 342 « dépôts cités » à 177 demandes réelles. Un chiffre qui arrange
celui qui le produit se vérifie avant d'être rapporté.

## Ce que la méthode doit devenir

1. **La liste des cibles est une donnée, pas du code** — un registre unique,
   alimenté par l'inventaire, consommé par les trois voies (clone / README / écosystème).
2. **Refuser le contenu généré à l'entrée** : traces de simulation, formes d'onde,
   lockfiles, sorties de build. Critère de forme (répertoire, motif de nom,
   homogénéité des lignes), pas d'extension.
3. **Un seuil de plausibilité par dépôt** : sous ~100 chunks pour un dépôt de code,
   le résultat est déclaré SUSPECT et non INGÉRÉ.
4. **Vectoriser ce qui entre**, sinon la veille reste un corpus lexical mort.
5. **Digérer par lot, en continu**, au lieu de laisser 1 132 fichiers sur 1 138 en
   attente derrière un plafond de tokens.

Instrument de mesure : `tools/forge_veille_backlog_github.py` (commit `00b221262`).
Rapports : `sandbox/veille_backlog_github.md`, `sandbox/veille_backlog_demandes.txt`.
