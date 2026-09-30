# Chantier — migration vers un namespace `nokido.*`

**Statut : OUVERT EN CONCEPTION, GELÉ EN EXÉCUTION.** Décision owner du 2026-09-09 :
*« retirer la promesse `pip install` de l'alpha publique et ne pas ouvrir maintenant la
migration `nokido/` »*. Ce document existe pour que le chantier soit **chiffré et
instruit** quand il s'ouvrira, pas pour l'ouvrir.

## Pourquoi

P4.2a a reproduit l'installation dans un venv réellement neuf. Trois ruptures, chacune
cachée par la précédente — la troisième est la seule qui compte :

> Le corps suppose la **disposition du dépôt**, pas un paquet installé. Une fois le wheel
> posé, `forge_secrets` vit dans `site-packages/app/` et `import forge_secrets` ne le
> trouve plus.

`nokido-agent` n'a jamais été installé ni testé installé.

## La mesure

`tools/forge_syspath_cartography.py` (lecture seule, aucune transformation) —
2026-09-10, zones `app/` + `tools/` + `recon_silo/` :

```
985 sites sys.path sur 2 433 fichiers lus, 0 illisible

portee      MODULE=478   FONCTION=70   CONDITIONNEL=437
verdict     MIGRABLE=745   A_INSTRUIRE=240
motif       CIBLE_NON_REDUITE=79  CIBLE_MULTIPLE=73  INTENTION_AMBIGUE=52
            CIBLE_HORS_DEPOT=28   SEMANTIQUE_DYNAMIQUE=8

ventilation                     interne  inconnue  multiple  externe
  PATH_FOR_IMPORT      911          745        70        70       26
  PATH_FOR_SUBPROCESS   28           20         4         2        2
  PATH_FOR_DATA         22           20         1         1        -
  PATH_FOR_PLUGIN        8            6         1         1        -
  UNKNOWN               16   intention_reellement_ambigue=12
                             analyseur_insuffisant=4
```

**`sys.path.insert()` n'est PAS une dette homogène** (owner, 2026-09-10). Cinq
populations, cinq gestes différents — et les 437 `CONDITIONNEL` traversent toutes
les cinq. `MIGRABLE = cible_interne(PATH_FOR_IMPORT)`, exactement.

⚠️ **`745 MIGRABLE` ne signifie pas 745 suppressions sûres.** Il signifie : *le
mécanisme observé correspond à une intention que le futur namespace pourrait
absorber*. Rien de plus. Le module le réimprime à chaque exécution.

**Pourquoi 681 → 745, et pourquoi ce n'est pas un relâchement.** Deux effets
opposés dans la même passe : exiger une cible **interne** a retiré 26 sites
externes (un `vendor/` résolu n'est pas une dette de namespace) ; apprendre au
réducteur à lire `Path(__file__).resolve().parents[1] / "app"` — la forme la plus
courante du dépôt — en a récupéré davantage. La hausse vient d'une meilleure
**résolution**, pas d'un critère plus permissif.

⚠️ **Le dénominateur, pas seulement le chiffre.** Les 1 186 `sys.path` annoncés en P4.2a
portaient sur **tout** le dépôt (2 555 fichiers) ; les 985 ci-dessus portent sur les trois
zones de code. Ce n'est pas une baisse, c'est un périmètre plus étroit — et le dire évite
de croire qu'une dette a diminué toute seule.

⚠️ **Deux limites de l'instrument, chiffrées plutôt que fondues dans le résultat**
(`par_motif` du rapport) :

| motif | ce que ça veut dire |
|---|---|
| `CIBLE_NON_REDUITE` (79) | limite de **l'outil**, pas du corps. Pousse vers `A_INSTRUIRE`, donc du côté prudent |
| `CIBLE_MULTIPLE` (73) | `sys.path` dans une boucle : un site insère **plusieurs** chemins. Population invisible avant la ventilation, et parmi les plus dangereuses à transformer |
| `INTENTION_AMBIGUE` (52) | le chemin sert à autre chose qu'un import — le **corps** est ambigu |
| `CIBLE_HORS_DEPOT` (28) | résolu, mais hors dépôt : pas une dette de namespace |
| `SEMANTIQUE_DYNAMIQUE` (8) | `importlib.import_module(nom)` non littéral — irréductible par construction |

**La ventilation à deux niveaux existe pour une seule raison** (owner) : sans
elle, `A_INSTRUIRE` mélange deux dettes de nature différente. Après séparation, la
dette réelle du corps sur `UNKNOWN` est **12**, pas 16 — les 4 autres sont mon
analyseur.

**Faux positif payé le jour même**, et gardé par NR : `numpy` n'a pas de point et n'est
pas stdlib, il passait donc pour un module frère migrable. `PATH_FOR_IMPORT` annoncé à
927 avant correction. Un module n'est candidat que s'il **existe** comme fichier du dépôt.

## Ce que la carte a appris, et qui change le plan

Les `sys.path.insert` ne sont pas des accidents. Beaucoup servent le patron **anti-dup**
du corps — atteindre un module frère plutôt que le réécrire :

```python
def _rm():
    """Le module matrice, seule source des sondes d'inventaire (anti-duplication)."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import forge_regression_matrix as RM
```

Un codemod qui les retirerait tous casserait le mécanisme qui empêche le corps de se
dupliquer. Et **437 des 985 sont `CONDITIONNEL`** (sous `try:`/`if:`) : le patron
`try: sys.path ; import X ; except ImportError:` est un repli, pas un chemin unique.

## Outillage

**Mesuré le 2026-09-10 : `libcst`, `rope`, `bowler`, `fissix`, `astor` sont ABSENTS de
`laforge_py314`.** Le plan repose donc sur des outils à installer — et la règle du corps
interdit de les poser dans l'environnement de Nokido (« un CLI tiers va dans un env
DÉDIÉ ; il ne partage pas l'environnement du système qu'il pilote »).

| outil | rôle | pourquoi lui |
|---|---|---|
| **LibCST** | transformation massive contrôlée | CST : conserve commentaires et formatage, infrastructure de *codemods* prévue pour un dépôt entier, et **signale les fichiers qu'il ne sait pas transformer** |
| **Rope** | refactoring sémantique | déplacement de modules/packages, renommage, mise à jour des imports, module → package |

**Bowler écarté** : son propre dépôt renvoie vers LibCST, `fissix`/`lib2to3` ayant une
grammaire figée.

🔬 **Non mesuré, à mesurer avant tout engagement :** LibCST parse-t-il la grammaire
**Python 3.14** du dépôt ? Le protocole tient en trois gestes — venv dédié, `pip install
libcst rope`, parser les 2 433 fichiers et compter les refus. Tant que ce chiffre n'existe
pas, « LibCST fera le gros du travail » est une hypothèse, pas un plan.

## Règles du chantier

1. **Aucune transformation automatique ne supprime un `sys.path` tant qu'on n'a pas prouvé
   pourquoi il était là.** (owner, 2026-09-09)
2. **Deux verdicts, jamais un troisième.** `MIGRABLE` = le codemod sait quoi écrire.
   `A_INSTRUIRE` = un humain regarde. Le mot « supprimable » est banni du vocabulaire de
   l'outil, et un NR le vérifie : un rapport qui l'écrit sera lu comme une autorisation.
3. **Liste blanche.** L'inconnu ne va jamais du côté favorable.
4. **Par familles, avec cliquet.** Chaque passe : codemod → NR ciblés → CI → wheel → venv
   vierge. Le compteur de sites plats doit **décroître de façon monotone**, gardé comme le
   ratchet NR l'est déjà. Jamais un `sed` global suivi d'une prière.
5. **Le codemod est lui-même testé** — entrées/sorties attendues — avant de toucher le
   dépôt.
6. **Aucun « cleanup » de `sys.path` en préparation du namespace.** (owner, 2026-09-10)
   Chaque suppression exige une raison mesurée **et** la preuve que la nouvelle voie
   d'import prend effectivement le relais.

## Ordre figé (owner, 2026-09-10)

```
cartographie sys.path  →  séparation intention réelle / résolution insuffisante
                       →  cartographie STABILISÉE
                       →  venv chantier isolé
                       →  évaluation LibCST / Rope
                       →  micro-codemod expérimental (échantillon minuscule)
                       →  mesure AST/imports  →  NR
                       →  seulement alors, migration par familles
```

**LibCST n'est pas une dépendance du plan** : c'est un *outil candidat à évaluer dans
un environnement de chantier isolé*. Protocole minimal avant tout engagement —
(1) venv dédié, (2) version réellement installée, (3) parsing de l'intégralité des
fichiers pertinents, (4) **zéro parse failure sur Python 3.14**, (5) conservation des
constructions particulières du dépôt, (6) alors seulement un codemod expérimental sur
un échantillon minuscule et représentatif. Rope ensuite, pour ce que LibCST couvre
mal : le refactoring **sémantique** (résolution et déplacement de modules).

Aucun de ces outils n'entre dans `laforge_py314`.

## Ce qui n'est PAS décidé

- La forme du namespace (`src/nokido/{app,tools}` vs autre découpage).
- Le sort des cinq entry points console pendant la transition.
- Si `recon_silo/` suit la même migration.

## Critère de sortie

Un venv **vierge**, `pip install nokido-agent`, les cinq entry points qui répondent, et le
témoin `P4_REPRO_WITNESS` en `PROVEN` sur le mode `pypi_public`. Tant que ce témoin
n'existe pas, le README ne promet pas l'installation — c'est la règle P6 :

> Toute méthode d'installation promise dans le README a soit un témoin `PROVEN`, soit un
> statut explicitement `UNVERIFIED`/`EXPERIMENTAL`.
