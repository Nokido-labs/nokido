#!/usr/bin/env python3
"""NR — cartographie des `sys.path` : une CARTE, jamais une autorisation.

Ecrit AVANT `tools/forge_syspath_cartography.py`, donc ROUGE a la premiere
execution. Il fixe le contrat que le module devra tenir.

POURQUOI CE MODULE EXISTE. P4.2a a mesure que le corps s'importe A PLAT :
4 449 `import forge_*` et 1 186 `sys.path.insert`. La tentation est de lancer
un codemod qui retire les `sys.path` et reecrit les imports. La regle owner du
2026-09-09 l'interdit :

    Aucune transformation automatique ne supprime un `sys.path`
    tant qu'on n'a pas prouve POURQUOI il etait la.

Ce module ne transforme RIEN. Il classe par INTENTION et par PORTEE, il nomme
la voie qui a repondu, et il refuse de conclure quand rien ne discrimine. Meme
patron que `forge_module_wiring` (BRANCHE / ORPHELIN / POINT_ENTREE), dont la
docstring dit deja : « il rend la carte, l'humain tranche ».

LE PIEGE QUE CES TESTS GARDENT. Un classeur qui met l'inconnu du cote favorable
fabrique une autorisation de supprimer. Ici l'inconnu va TOUJOURS du cote
`A_INSTRUIRE` — liste BLANCHE, jamais liste noire.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

carto = pytest.importorskip(
    "forge_syspath_cartography",
    reason="tools/forge_syspath_cartography.py pas encore ecrit — NR rouge attendu",
)


def _classer(src: str, nom: str = "essai.py"):
    """Passe une source en memoire au classeur et rend ses sites."""
    return carto.classer_source(src, nom)


# --------------------------------------------------------------- PORTEE


def test_portee_module_est_distinguee_de_portee_fonction():
    """La portee change tout : un `sys.path` en tete de module s'applique au
    processus entier, un `sys.path` dans une fonction ne s'applique qu'apres le
    premier appel. Mesure du 2026-09-08 : confondre les deux avait donne
    31 blocages annonces pour 1 seul reel."""
    haut = _classer(
        "import sys\n"
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent.parent\n"
        "sys.path.insert(0, str(ROOT / 'app'))\n"
        "import forge_secrets\n"
    )
    dedans = _classer(
        "import sys, os\n"
        "ROOT = os.path.dirname(__file__)\n"
        "def _rm():\n"
        "    sys.path.insert(0, os.path.join(ROOT, 'tools'))\n"
        "    import forge_regression_matrix as RM\n"
        "    return RM\n"
    )
    assert haut[0].portee == "MODULE"
    assert dedans[0].portee == "FONCTION"


def test_portee_conditionnelle_est_nommee_pas_avalee():
    """Un `sys.path` sous `try:` ou `if:` peut ne jamais s'executer. Ce n'est ni
    MODULE ni FONCTION : c'est CONDITIONNEL, et ca se dit."""
    sites = _classer(
        "import sys\n"
        "try:\n"
        "    sys.path.insert(0, '/opt/plugins')\n"
        "    import greffon\n"
        "except ImportError:\n"
        "    greffon = None\n"
    )
    assert sites[0].portee == "CONDITIONNEL"


# ----------------------------------------------------------- INTENTION


def test_import_de_module_du_depot_donne_path_for_import():
    """La seule intention qu'on saura migrer : le chemin sert a atteindre un
    module FRERE du depot, et l'import suit dans la meme portee."""
    sites = _classer(
        "import sys\n"
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent.parent\n"
        "sys.path.insert(0, str(ROOT / 'app'))\n"
        "from forge_db_path import open_writer\n"
    )
    assert sites[0].intention == "PATH_FOR_IMPORT"
    assert sites[0].voie, "la voie qui a repondu doit etre NOMMEE"
    assert "forge_db_path" in sites[0].imports_suivants


def test_sans_import_qui_suit_le_verdict_reste_inconnu():
    """CONTRE-EPREUVE — c'est le test qui compte. Un `sys.path` sans import
    derriere n'est PAS un `PATH_FOR_IMPORT` par defaut : il sert peut-etre a
    autre chose, ou a rien. L'inconnu ne va jamais du cote favorable."""
    sites = _classer(
        "import sys\n"
        "sys.path.insert(0, '/opt/quelque_chose')\n"
        "print('rien a voir')\n"
    )
    assert sites[0].intention == "UNKNOWN"
    assert sites[0].verdict == "A_INSTRUIRE"


def test_chemin_passe_a_un_subprocess_donne_path_for_subprocess():
    sites = _classer(
        "import sys, subprocess, os\n"
        "OUTILS = os.path.join(os.path.dirname(__file__), 'tools')\n"
        "sys.path.insert(0, OUTILS)\n"
        "subprocess.run([sys.executable, os.path.join(OUTILS, 'x.py')])\n"
    )
    assert sites[0].intention == "PATH_FOR_SUBPROCESS"


def test_import_dynamique_donne_path_for_plugin():
    """`importlib.import_module(nom)` avec un nom NON litteral : l'AST ne peut
    pas savoir ce qui sera charge. C'est precisement la semantique dynamique que
    l'owner nomme — elle ne se migre pas mecaniquement."""
    sites = _classer(
        "import sys, importlib\n"
        "sys.path.insert(0, '/opt/greffons')\n"
        "def charger(nom):\n"
        "    return importlib.import_module(nom)\n"
    )
    assert sites[0].intention == "PATH_FOR_PLUGIN"


def test_cible_non_resoluble_ne_devient_jamais_migrable():
    """Si le chemin insere vient d'une variable que l'AST ne sait pas reduire,
    la cible est UNKNOWN — et un site dont la cible est inconnue ne peut pas
    etre declare migrable, meme si un import le suit."""
    sites = _classer(
        "import sys\n"
        "chemin = calculer_quelque_part()\n"
        "sys.path.insert(0, chemin)\n"
        "import forge_secrets\n"
    )
    assert sites[0].cible == "UNKNOWN"
    assert sites[0].verdict == "A_INSTRUIRE"


# ------------------------------------------------------------- SURETE


def test_le_module_ne_prononce_jamais_le_mot_supprimable():
    """Garde de vocabulaire. Un rapport qui ecrit « SUPPRIMABLE » sera lu comme
    une autorisation, et quelqu'un lancera le sed. Les deux seuls verdicts sont
    MIGRABLE (le codemod SAIT quoi ecrire) et A_INSTRUIRE (un humain regarde)."""
    src = (ROOT / "tools" / "forge_syspath_cartography.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "SUPPRIMABLE" not in src
    assert set(carto.VERDICTS) == {"MIGRABLE", "A_INSTRUIRE"}


def test_fichier_non_parsable_est_illisible_pas_absent():
    """Trois etats, jamais deux. Un fichier qui ne parse pas n'a pas « zero
    sys.path » : on n'a pas pu regarder. Confondre les deux, c'est le defaut que
    la constitution semantique interdit (UNKNOWN != NO)."""
    rapport = carto.cartographier_textes({"casse.py": "def f(:\n"})
    assert rapport["illisibles"] == 1
    assert "casse.py" in rapport["fichiers_illisibles"]


def test_le_rapport_imprime_son_denominateur():
    """Un filtre qui ecarte des donnees DIT combien. Sans denominateur, « 12
    sites migrables » ne se distingue pas de « je n'ai lu qu'un fichier »."""
    rapport = carto.cartographier_textes(
        {
            "a.py": "import sys\nsys.path.insert(0, '/x')\n",
            "b.py": "x = 1\n",
            "c.py": "def f(:\n",
        }
    )
    assert rapport["fichiers_lus"] == 3
    assert rapport["illisibles"] == 1
    assert rapport["sites"] == 1


def test_un_import_TIERS_ne_rend_pas_migrable():
    """FAUX POSITIF MESURE le 2026-09-10, sur la premiere carte reelle.

    Le classeur rendait :

        app/forge_agency.py:30   voie: import plat suivant: numpy

    `numpy` n'a pas de point et n'est pas stdlib — il passait donc pour un
    module FRERE du depot. Resultat : 927 `PATH_FOR_IMPORT` et 695 `MIGRABLE`
    annonces, surestimes dans le sens qui ARRANGE (un chantier plus facile
    qu'il n'est). Un module n'est candidat que s'il EXISTE comme fichier du
    depot ; sinon le `sys.path` sert peut-etre a atteindre un site-packages,
    un vendor, ou rien du tout.
    """
    sites = _classer(
        "import sys\n"
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent\n"
        "sys.path.insert(0, str(ROOT / 'vendor'))\n"
        "import numpy\n"
    )
    assert sites[0].intention != "PATH_FOR_IMPORT"
    assert sites[0].verdict == "A_INSTRUIRE"
    assert "numpy" not in sites[0].imports_suivants


def test_le_depot_est_le_denominateur_des_modules_plats():
    """L'ensemble des modules du depot est MESURE, pas suppose. S'il etait vide,
    tout deviendrait `A_INSTRUIRE` en silence — un instrument muet qui parait
    prudent."""
    modules = carto.modules_depot()
    assert len(modules) > 500, "le depot porte plus de 500 modules — ensemble non construit ?"
    assert "forge_secrets" in modules
    assert "numpy" not in modules


# ------------------------------------------- VENTILATION (owner 2026-09-10)
#
# « separer definitivement "le corps est ambigu" de "la cartographie ne sait pas
#   encore resoudre". Sinon le 304 A_INSTRUIRE melange deux dettes de nature
#   differente. »


def test_cible_interne_externe_multiple_inconnue_sont_distinguees():
    """Quatre classes de cible, parce qu'elles appellent quatre gestes distincts.

    Une cible EXTERNE resolue n'est pas une dette de namespace : aucun
    `nokido.*` n'absorbera jamais un `vendor/` ou un `site-packages`.
    """
    interne = _classer(
        "import sys\nfrom pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent.parent\n"
        "sys.path.insert(0, str(ROOT / 'app'))\n"
        "import forge_secrets\n"
    )
    externe = _classer("import sys\nsys.path.insert(0, '/opt/greffons')\n")
    multiple = _classer(
        "import sys\n"
        "for zone in ('app', 'tools'):\n"
        "    sys.path.insert(0, zone)\n"
    )
    inconnue = _classer(
        "import sys\nchemin = ailleurs()\nsys.path.insert(0, chemin)\n"
    )
    assert interne[0].cible_classe == "INTERNE"
    assert externe[0].cible_classe == "EXTERNE"
    assert multiple[0].cible_classe == "MULTIPLE"
    assert inconnue[0].cible_classe == "INCONNUE"


def test_une_cible_externe_resolue_n_est_pas_migrable():
    """CONTRE-EPREUVE de la ventilation. Le chemin est parfaitement resolu et un
    import le suit — mais il pointe HORS du depot. `MIGRABLE` dirait au codemod
    d'ecrire un `from nokido... import` pour un module qui n'y sera jamais."""
    sites = _classer(
        "import sys\nfrom pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent\n"
        "sys.path.insert(0, str(ROOT / 'vendor'))\n"
        "import forge_secrets\n"
    )
    assert sites[0].cible_classe == "EXTERNE"
    assert sites[0].verdict == "A_INSTRUIRE"
    assert sites[0].motif == "CIBLE_HORS_DEPOT"


def test_unknown_separe_ambiguite_reelle_et_analyseur_insuffisant():
    """LE POINT DE LA DEMANDE. Deux sites `UNKNOWN` d'intention, deux dettes :

        cible resolue + aucune voie   -> le CORPS est ambigu
        cible non resolue             -> MON analyseur est insuffisant

    Les confondre, c'est mesurer son propre outil en croyant mesurer le corps.
    """
    rapport = carto.cartographier_textes(
        {
            "ambigu.py": "import sys\nsys.path.insert(0, '/opt/x')\nprint('rien')\n",
            "insuffisant.py": "import sys\nc = calcule()\nsys.path.insert(0, c)\nprint('rien')\n",
        }
    )
    unknown = rapport["ventilation"]["UNKNOWN"]
    assert unknown["intention_reellement_ambigue"] == 1
    assert unknown["analyseur_insuffisant"] == 1


def test_la_ventilation_couvre_chaque_intention_et_se_boucle():
    """Somme de controle : aucune population ne se perd en route. Un tableau
    dont les sous-totaux ne font pas le total cache un cas non classe."""
    rapport = carto.cartographier_depot()
    total = sum(
        sum(sous.values()) for sous in rapport["ventilation"].values()
    )
    assert total == rapport["sites"], "la ventilation perd des sites"
    for intention in carto.INTENTIONS:
        assert intention in rapport["ventilation"]


def test_le_reducteur_lit_parents_index():
    """NON-REGRESSION DU REDUCTEUR. `Path(__file__).resolve().parents[1] / "app"`
    est la forme la plus courante du depot et elle sortait `UNKNOWN` —
    gonflant `analyseur_insuffisant` d'une dette qui n'existe pas."""
    sites = _classer(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))\n"
        "import forge_secrets\n"
    )
    assert sites[0].cible != "UNKNOWN"
    assert sites[0].cible_classe == "INTERNE"


def test_un_depot_sous_un_dossier_ignore_reste_lisible(tmp_path):
    """DEFAUT REVELE PAR LA CI DE REFERENCE, 2026-09-10 — invisible en local.

    Le filtre `IGNORES` testait les parts du chemin ABSOLU. La CI de reference
    juge le SHA dans `sandbox/ci_reference_wt/`, donc « sandbox » apparaissait
    dans CHAQUE chemin et tous les fichiers etaient ecartes :

        modules_depot() -> set()   ->   plus aucun import plat reconnu
                                   ->   TOUT bascule en A_INSTRUIRE

    L'instrument devenait MUET en paraissant PRUDENT — la pire des pannes pour
    un classeur. Le filtre doit porter sur le chemin RELATIF a la zone.
    """
    depot = tmp_path / "sandbox" / "ci_reference_wt"
    (depot / "app").mkdir(parents=True)
    (depot / "app" / "forge_temoin_x.py").write_text("X = 1\n", encoding="utf-8")
    (depot / "app" / "_attic").mkdir()
    (depot / "app" / "_attic" / "forge_vieux.py").write_text("Y = 1\n", encoding="utf-8")

    modules = carto.modules_depot(depot)
    assert "forge_temoin_x" in modules, "depot sous 'sandbox' rendu illisible"
    assert "forge_vieux" not in modules, "_attic doit rester ecarte, lui"


def test_append_compte_autant_que_insert():
    """`sys.path.append` fait la meme chose que `insert` du point de vue de la
    migration. Ne scanner que `insert` sous-estimerait la dette en silence."""
    sites = _classer("import sys\nsys.path.append('/x')\n")
    assert len(sites) == 1
    assert sites[0].forme == "append"
