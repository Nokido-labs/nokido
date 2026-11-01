# Rejeu de la regulation RAM : fidelite mesuree (28/10/2026)

Livrable : `tools/forge_regulation_replay.py` (`__FORGE_COLOR__ = "regulation/rejeu : ..."`), NR
`tests/nr/test_regulation_replay_nr.py` (14 tests). Etape prealable a une recherche de seuils par basin-hopping,
qui n'est PAS faite dans ce lot. Aucun seuil reel modifie, aucun service touche, aucune ecriture en base.

## 1. Principe : le code existant est appele, pas recopie

Le rejeu appelle le **tick Hamilton reel** (`forge_resource_manager._regulation_hamilton_tick`), qui appelle a son
tour `plan_hamilton` -> `classe_hamilton` / `ordre_delestage`, `palier_pression_ram`, `regulation_hamilton_ram` et
`gestes_observes`. Le plancher RAM 60 s est calcule par le vrai `_noter_ram_fenetre`, nourri echantillon par
echantillon. Le delai de grace Docker vient du vrai `forge_docker_keeper.delai_de_grace`.

Le temps du rejeu, seules les **entrees** et les **sorties** du tick sont remplacees, puis restaurees (`_bac`, avec
un `finally`) :

| Branche du tick | Dans le systeme reel | Pendant le rejeu |
|---|---|---|
| `_SNAPSHOT`, `_RAM_FENETRE` | sampler a 3 s | vitaux journalises, plancher recalcule |
| `time` | horloge | horloge simulee (`_Horloge`) |
| `_registre_corps` | registre du superviseur | registre simule (modele : SUSPENDRE le retire, REPRENDRE le remet) |
| `attribuer_pression` | psutil | verdict lu dans les motifs journalises (sinon defaut `SOI`, et c'est dit) |
| `vetos_sommeil_actifs` | `sandbox/veto_sommeil/` | `{}` par defaut (historique ILLISIBLE) |
| `_memoire_privee_mb` | psutil | `None` (ILLISIBLE) sauf si `rss_mb` est fourni |
| `_HAMILTON_ETAT_RAM_PATH` | fichier json | etat en memoire (`_EtatEnMemoire`), rien sur le disque |
| `_ordre_superviseur`, `publier_palier_pression`, `_audit_lifecycle` | HTTP, hormone, audit | captures |
| seuils (`_SUPERVISOR_SLEEP_RAM_THRESHOLD`, `_HAMILTON_CIBLE_PCT`, `_PALIER_GENE_PCT`, `_CRITIQUE_LIBRE_GB`, `_HAMILTON_PAUSE_MAX_S`, `_HAMILTON_CALME_MIN_S`, `_HAMILTON_RECHUTE_FENETRE_S`, `_RAM_FENETRE_S`, env `LAFORGE_DETRESSE_LIBRE_GB`) | constantes | valeurs injectees |

Le rejeu **refuse de tourner** si l'echantillonneur est vivant dans le processus (le hub) : y remplacer les
attributs du module toucherait la regulation reelle. Le keeper Docker est importe sans son journal fichier et sans
le `basicConfig` qu'il pose sur le logger racine (NR `test_delai_docker_sans_effet_de_bord_journal`).

## 2. Signaux d'entree : ce qui est journalise, ce qui ne l'est pas

Fenetre 08:45-09:20 UTC, sortie de `inventorier_signaux` sur le depot vivant (lecture seule) :

| Signal | Source | Statut | Cadence / n | Ce qui manque au simulateur |
|---|---|---|---|---|
| ram_pct, ram_free_gb | `sandbox/vitals_history.jsonl` | PARTIEL | 15,2 s (n=124) | sampler a 3 s, 1 echantillon sur 5 journalise |
| ram_total_gb | derive used/pct | PARTIEL | 15,2 s | pas journalise, arrondi a 0,1 % |
| plancher 60 s | `resource_state.json` | ILLISIBLE | -- | instantane ecrase ; recalcule sur la serie a 15 s |
| palier de pression RAM | hormone `NORADRENALINE_PRESSION_RAM` | ILLISIBLE | -- | pas de serie ; recalcule par `palier_pression_ram` |
| verdict d'attribution (SOI/NON_SOI) | motifs `hamilton_arme`, `pression_hors_corps` | PARTIEL | n=16 | seulement aux ticks AVEC geste |
| registre des vivants | superviseur | ILLISIBLE | -- | suppose = TOML non `disabled` |
| RSS par service | `_memoire_privee_mb` | ILLISIBLE | -- | seule la somme apparait (« Mo vises ») |
| vetos de sommeil | `sandbox/veto_sommeil/` | ILLISIBLE | 2 temoins | seuls `sleep_refused` en temoignent |
| intentions (`get_active_intents`) | motifs docker `pause_skipped` | PARTIEL | n=3 | seulement quand le keeper tente une pause |
| etat des pauses Hamilton | `hamilton_pauses_ram.json` | ILLISIBLE | -- | instantane ; le rejeu part d'un etat vide |
| tick Hamilton | audit `hamilton_arme` | PARTIEL | n=20 | ticks sans geste absents ; gestes tronques a 200 caracteres |
| ordres sleep/wake | `sandbox/supervisor_ordres.jsonl` | LU | n=217 | l'ordre ne dit pas quel chemin l'a emis |
| sommeils hors Hamilton | ordres + audit | PARTIEL | n=11 | eviction : pas simulee |
| reveils des evinces | `regulation_evinces.json` | ILLISIBLE | -- | registre courant seulement |
| palier memoire du hub | `hub_mem_palier.json` | ILLISIBLE | -- | instantane ecrase par mem_watchdog |
| docker want/release | audit domaine docker | LU | n=5 | intentions docker (watch_jobs) : historique ILLISIBLE |
| services.toml de l'epoque | `proxy_deno/core/services.toml` | ILLISIBLE | -- | les deux copies ont un mtime POSTERIEUR a la fenetre |

76 lignes illisibles dans `lifecycle_actions.jsonl` sont **comptees** (`fen["rejets"]`), pas avalees.
Les journaux `logs/supervisor/*.log` n'apportent aucune entree a ce rejeu : ils ne portent ni la RAM ni les
decisions de la regulation.

## 3. Fidelite : fenetre du 28/10 au matin (endormissement des 13 executeurs)

**Fenetre** : 2026-10-28 08:45-09:20 UTC (hub redemarre a ~08:47, `reboot_detected` 08:47:45). **Journal** : 217
ordres RESOURCE_MANAGER. 206 sont attribues au tick Hamilton, 11 n'en viennent pas : une eviction auditee
(LlamaEmbed 09:00:10) et 10 sommeils a 09:06:31-33, que le tick Hamilton suivant (09:06:42, « RAM 77.1 % < seuil :
rien de neuf a ceder ») ne signe pas. Un seul processus ecrit les audits Hamilton (pid 19852, le hub) : il n'y a
pas deux regulateurs en parallele.

**Reglage du rejeu** : seuils ACTUELS (78 / 65 / 88 / 0,5 Go / 1,5 Go par defaut / 45 s / 120 s / 900 s / 60 s),
code `forge_resource_manager@f96fa75280` (worktree), TOML du depot vivant, ticks toutes les 60 s, latence du
snapshot 3 s. **Phase** calee sur le premier ordre journalise (08:53:54). C'est le seul parametre cale sur le
journal, et la section 3.3 montre ce qu'il pese.

### 3.1 Concordance (tolerance +/- 45 s, Dice = 2*apparies/(n_rejeu+n_journal))

| Variante | Perimetre | n_rejeu | n_journal | apparies | concordance | precision | rappel |
|---|---|---|---|---|---|---|---|
| A : seuils actuels, verdict strict (defaut SOI) | tout | 306 | 206 | 192 | **0,750** | 0,628 | 0,932 |
| A | executeurs | 91 | 46 | 46 | **0,672** | 0,506 | **1,000** |
| B : A + verdict journalise maintenu 300 s | tout | 264 | 206 | 192 | **0,817** | 0,727 | 0,932 |
| B | executeurs | 78 | 46 | 46 | 0,742 | 0,590 | 1,000 |
| C : B + registre sans NokidoLMStudio | tout | 258 | 206 | 192 | **0,828** | 0,744 | 0,932 |
| C | executeurs | 78 | 46 | 46 | 0,742 | 0,590 | 1,000 |

Comment lire ce tableau :
* **L'evenement cible est reproduit.** Le tick rejoue a 08:53:54 lit un plancher de 79,3 %, palier
  RALENTISSEMENT, verdict SOI. Il endort 42 services, les **13 executeurs** compris ; le reel en a endormi 41.
  Les 13 reprises sortent a 08:56:54, pour 08:57:13-23 au journal.
* **Rappel 1,000 sur les executeurs** : toute decision journalisee pour un executeur est reproduite. La
  precision tombe a 0,5-0,6 : le rejeu endort des executeurs que le reel a epargnes, sous un veto qu'il ne voit
  pas (section 3.2).
* Ecart temporel sur les decisions appariees : de -44,7 s a -0,7 s, mediane -18,3 s. Le rejeu est **toujours en
  avance**, parce que la vraie cadence des ticks vaut 63,8 s en moyenne (audits consecutifs), contre 60 s dans le
  rejeu.
* Signal RAM, controle independant. Un motif journalise donne la RAM de decision qu'il implique : cible + Mo a
  rendre / RAM totale. On la compare au plancher recalcule par le rejeu :

| Tick reel | RAM impliquee par le motif | Plancher du rejeu | Explication |
|---|---|---|---|
| 08:54:02 | 78,71 % | 79,3 % | les 4 echantillons sur 5 non journalises font remonter le plancher |
| 09:01:12 | 78,90 % | 79,0 % | idem |
| 09:02:07 | 78,51 % | 78,7 % | idem |
| 09:07:14 | 86,31 % | 89,5 % | les snapshots different : le tick reel est parti environ 20 s apres le tick rejoue |

### 3.2 Chaque ecart, explique (variante A)

| Heure | Ecart | n | Cause |
|---|---|---|---|
| 08:53 / 08:56 | SUSPENDRE puis REPRENDRE de NokidoLMStudio, en trop | 1+1 | **Registre ILLISIBLE.** Le TOML le declare DIFFERABLE, non disabled. Le motif reel compte 41+30 = 71 candidats, le rejeu 72 ; LMStudio est le seul DIFFERABLE que le reel n'ordonne jamais sur la fenetre. Variante C. |
| 09:00 | SUSPENDRE en trop : LMStudio + 6 executeurs (Antigravity, OpencodeNemotron, OpencodeDefaut2..5) | 7 | **Vetos ILLISIBLES.** Motif reel de 09:01:12 : « 41 a ceder ... **35** service(s) », donc 6 ecartes par veto (`regulation_hamilton_ram` saute les vetos). `sleep_refused` a 09:06:33 en temoigne pour Defaut2/3 (« tache ... en vol »). |
| 09:05 / 09:06 | REPRENDRE en trop (11) ; REPRENDRE du journal non reproduites (4) | 11 / 4 | Pour 7 des 11 : consequence de la ligne precedente, le rejeu reprend des services que le reel n'avait pas endormis. Les 4 autres (Capture, IngestDaemon, MemoryConsolidator, ServiceCrashWatcher) sont **la meme decision, decalee** : le rejeu reprend a 09:05:54, le reel a 09:06:4x (tick reel d'environ 30 s, avec des POST de reveil), au-dela des 45 s. |
| 09:06 | SUSPENDRE en trop | 21 | **Phase** : le tick rejoue (09:06:54) lit le snapshot de 09:06:50, avec 1,23 Go libres, donc DETRESSE et les UTILE admis (48 choisis). Le tick reel (~09:07:1x) lisait 86,3 % et plus de 1,5 Go libres (motif sans « detresse » : 27 cedes). Les sommeils reels de 09:06:3x (6 UTILE + 4 executeurs) viennent du chemin d'**eviction**, hors Hamilton. Vetos en plus. |
| 09:09 | REPRENDRE en trop (6 UTILE) | 6 | Consequence de la ligne precedente. |
| 09:15 / 09:16 | REPRENDRE en trop (25) ; REPRENDRE du journal non reproduites (10) | 25 / 10 | Les 10 sont la **meme decision decalee** (rejeu 09:15:54, reel 09:16:34-46, de 40 a 52 s). Les 15 restantes reprennent des services que seul le rejeu avait endormis. |
| 09:17 | SUSPENDRE en trop | 42 | **Verdict non journalise** au tick rejoue 09:17:54, d'ou le defaut SOI. Les verdicts journalises encadrant ce tick sont NON_SOI (09:16:46 et 09:20:58). La variante B, qui maintient le dernier verdict, les supprime (306 -> 264). |

Codes calcules par le rejeu (`concordance(...)["absents_*"][i]["code"]`) : SOMMEIL_EN_TROP 65, REPRISE_EN_TROP 43,
REPRISE_NON_REPRODUITE 14, VETO_TEMOIGNE 6, PRESSION_NON_VUE 0. La cause attachee a chaque code est **probable** ;
l'explication qui fait foi est le tableau ci-dessus.

### 3.3 Sensibilite (variante A, executeurs / tout)

| Tolerance | 15 s | 30 s | 45 s | 60 s | 90 s |
|---|---|---|---|---|---|
| concordance | 0,19 / 0,23 | 0,55 / 0,57 | 0,67 / 0,75 | 0,67 / 0,80 | 0,67 / 0,80 |

| Decalage de phase | -30 s | -20 s | -10 s | 0 | +10 s | +20 s | +30 s |
|---|---|---|---|---|---|---|---|
| concordance | 0,00 / 0,05 | 0,47 / 0,52 | 0,61 / 0,66 | 0,67 / 0,75 | 0,18 / 0,29 | 0,18 / 0,30 | 0,00 / 0,05 |

Latence du snapshot (0, 3, 6 s) : 0,672 sur les executeurs dans les trois cas.

**La fidelite depend de la phase.** A +10 s, le tick rejoue lit l'echantillon de 08:53:55 (76,4 %), son plancher
passe sous 78 %, et l'endormissement de 08:53 disparait. Le reel, lui, decidait sur des echantillons a 3 s. La cause
est le sous-echantillonnage de la serie (15 s) autour d'un plancher qui frole le seuil. C'est le premier manque a
combler avant toute optimisation.

### 3.4 Hors de la fenetre calee : la fidelite ne tient pas (09:00-10:45, variante B)

Concordance de **0,29 a 0,30** (0,58 a 0,60 a 600 s de tolerance). Trois causes, verifiees une a une :
1. **Derive de phase.** Le rejeu garde des ticks fixes a 60 s, alors que la cadence reelle moyenne vaut 63,8 s.
   L'episode de 10:00:57-10:01:45 (plancher reel 79,4 %, motif « 37 service(s) pour 3490 Mo », dont on deduit
   79,4 %) dure moins de 60 s : le tick reel de 10:01:45 le saisit, les ticks rejoues de 10:01:07 et 10:02:07
   l'encadrent sans le voir.
2. **47 sommeils a 10:37:11-21 sans aucune signature Hamilton.** Ils suivent le redemarrage du hub a 10:35 (nouveau
   pid 15084) et `evict_detresse` a 10:37:04 (0,06 Go libres) ; ce sont des UTILE plus des DIFFERABLE, donc
   l'eviction cumulee. La regle d'attribution, prudente, garde comme Hamilton un sommeil sans audit Hamilton dans
   les 120 s : ces 47 sommeils comptent contre la fidelite.
3. Les 37 reprises de 10:0x decoulent de la cause 1.

## 4. Fonction de cout (exposee, pas optimisee)

`cout(rejeu, fen, poids)` renvoie ses composantes brutes et leur somme ponderee (poids par defaut : 1 par heure
d'executeur endormi, 1 par minute de pression GENE+ sans rien de cede, 1 par arret Docker) :

| Rejeu | temps_endormi_executeurs_s | pics_ram_s | arrets_docker | total |
|---|---|---|---|---|
| A, 08:45-09:20 | 14 898 | 0 | 0 (aucun release dans la fenetre) | 4,14 |
| C, 08:45-09:20 | 13 260 | 0 | 0 | 3,68 |
| Journal reel, meme fenetre (reference) | 9 724 | -- | -- | -- |
| C + `seuil_sommeil=82` (demonstration seulement) | 2 340 | 0 | 0 | 0,65 |
| B, 09:00-10:45 | 6 240 | 0 | **2** sur 4 releases | 3,73 |

Detail Docker sur 09:00-10:45, avec le palier rejoue CALME et une grace reelle de 180 s : les releases de 09:23:39
et 09:29:16 sont rattrapes par un `want` dans les 180 s (09:24:40, 09:30:21) ; ceux de 09:35:29 et 10:39:58 ne le
sont pas. Dans le reel, ces quatre releases passaient par « arret immediat » (`release_claim`). Ce terme est donc un
**contrefactuel**.

**Limites a lever avant tout basin-hopping** (elles sont aussi rendues par `cout()["limites"]`) :
1. **Boucle ouverte.** La RAM rejouee est celle qui a ete observee : endormir un service dans le rejeu ne la fait
   pas baisser. `pics_ram_s` mesure la pression sans cession, pas une RAM contrefactuelle. Un optimiseur
   « gagnerait » en montant les seuils (seuil 82 : 2 340 s), sans que le rejeu puisse en montrer le prix en RAM.
   Il faut d'abord un modele de reponse RAM, par exemple la RSS par service, qui n'est pas journalisee.
2. Phase et cadence des ticks : il faudrait caler les ticks sur les audits Hamilton journalises (« ticks
   observes ») et prendre une periode d'environ 63,8 s.
3. Il faudrait journaliser la serie RAM a 3 s (ou au moins le plancher), le verdict a CHAQUE tick, les vetos poses
   et leves, et le registre des vivants.
4. L'eviction (`request_resources`, `delester_jusqu_au_manque`) n'est pas simulee.

## 5. Affirmation | Preuve | Etat

| Affirmation | Preuve | Etat |
|---|---|---|
| Le rejeu appelle le code existant, rien n'est recopie | NR `test_couleur_declaree_et_aucune_copie_de_logique` (aucune des 8 fonctions redefinie) ; `test_rejeu_appelle_le_tick_reel_et_les_fonctions_pures` (espions sur le tick, la regulation, le palier, les gestes, le plan : tous appeles) | VERT |
| Les seuils sont injectes, puis le module et l'environnement restaures | NR `test_seuils_injectes_puis_restaures` | VERT |
| Aucun etat vivant touche (snapshot, superviseur, audit, vetos, fenetre RAM, fichier d'etat) | NR `test_aucun_etat_vivant_touche` (ces fonctions levent si on les appelle) ; refus si l'echantillonneur est vivant | VERT |
| Le keeper Docker est importe sans effet de bord sur les journaux | NR `test_delai_docker_sans_effet_de_bord_journal` | VERT |
| Aucun except muet | NR (verification AST) | VERT |
| L'illisible est compte et inventorie | NR `test_lecture_journal_compte_l_illisible`, `test_inventaire_dit_l_illisible` ; 76 rejets reels comptes | VERT |
| L'endormissement des 13 executeurs (08:53:54) est reproduit aux seuils actuels | rejeu sur le depot vivant : 13/13 SUSPENDRE et 13/13 REPRENDRE apparies, plancher 79,3 % (le motif implique 78,71 %) ; NR `test_fidelite_fenetre_reelle_28_10` (fixture extraite verbatim, 9 noms non caviardes) | VERT |
| Concordance sur 08:45-09:20 : 0,750 (A), 0,817 (B), 0,828 (C) ; executeurs 0,672-0,742 avec un rappel de 1,0 | section 3.1, sortie de `concordance()` | MESURE |
| Chaque ecart est explique | section 3.2 (7 groupes, causes appuyees sur les motifs et sleep_refused) | MESURE, causes PROBABLES pour les vetos (historique ILLISIBLE) |
| La fidelite tient en dehors de la fenetre calee | 09:00-10:45 : 0,29-0,30 | **FAUX** (derive de phase, eviction non simulee) |
| La fidelite est robuste a la phase | +10 s : 0,18 ; -30 s ou +30 s : 0 | **FAUX** (phase calee sur 1 point du journal) |
| La fonction de cout est exposee | `cout()` ; NR `test_cout_expose_ses_composantes` ; section 4 | VERT, en BOUCLE OUVERTE |
| Les seuils sont prets pour un basin-hopping | -- | **NON** : il faut d'abord lever les limites 1 et 2 de la section 4 |

## 6. Reproduire (lecture seule)

```
python -m pytest tests/nr/test_regulation_replay_nr.py -q
python tools/forge_regulation_replay.py --racine "<depot vivant>" --debut 2026-10-28T08:45:00Z \
    --fin 2026-10-28T09:20:00Z --toml "<depot vivant>/proxy_deno/core/services.toml" [--verdict-maintien 300] \
    [--seuil seuil_sommeil=82]
```

Mesures prises le 28/10 vers 17:30 locale : NR sous Python 3.12 (`python -m pytest`) ; rejeu sous LAFORGE_PYTHON
3.14.4 (bac `run` du hub, lecture seule du depot vivant `%NOKIDO_ROOT%`). Code vivant
`3fc7bad7df` et code du worktree `f96fa75280` : ils different. Le 28/10 au matin, le code vivant reveillait par
`/supervisor/wake/` ; le worktree reveille par `/supervisor/service/start/`. Le rejeu lit les deux routes comme
REPRENDRE.
