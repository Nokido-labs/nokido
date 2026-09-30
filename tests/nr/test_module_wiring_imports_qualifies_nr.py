# -*- coding: utf-8 -*-
"""NR — une pointe POINTEE se resout a un chemin reel, jamais a un segment.

__FORGE_COLOR__ = "observabilite/audit : non-regression du capteur de cablage"

DEUX PASSES, LE MEME JOUR, SUR LE MEME DEFAUT (2026-09-07).

**Passe 1.** `forge_module_wiring` faisait `n.module.split(".")[0]` : `from
app.forge_code_ast import analyze_ast` comptait donc pour `app`, et l'arete vers
`forge_code_ast` disparaissait. Mesure : **44 aretes perdues sur 1 361 imports pointes**.
C'est un DESACCORD ENTRE DEUX INSTRUMENTS qui a designe le defaut, pas une relecture du
code : `forge_body_regulation_audit` disait `CABLE — importe par 2 module(s)` pendant que
`module_wiring` disait `ORPHELIN, 0 voie`. La vue federee a montre l'ecart au lieu de
voter, et l'ecart a nomme le capteur fautif.

**Passe 2 — et ce NR attestait le defaut.** Le correctif d'alors creditait les segments
qui SUIVENT un paquet du depot, donc les segments INTERMEDIAIRES. Ce fichier verrouillait
`assert "app" in cibles` (« le paquet reste une cible legitime »). Mesure :
`from app.core.settings import X`, ecrit dans **45 fichiers**, creditait un module nomme
« core », resolu par nom vers `app/agents/core.py` — un fichier d'un AUTRE organe, qui
publiait donc « importe par 43 module(s) » sans qu'aucun import ne le vise. Et la vraie
cible, `app/core/settings/`, ne recevait rien. Fausse attribution ET attribution manquante.

Un segment intermediaire est un REPERTOIRE. **PACKAGE != MODULE.**

🪤 Un test peut verrouiller un defaut aussi surement qu'une capacite. Celui-ci le faisait.

⚠️ Deux denominateurs a ne pas confondre : 44 aretes perdues ne font pas 44 modules
orphelins. Apres la passe 1, `ORPHELIN 385 -> 383`, zero nouvelle regression — les autres
aretes retrouvees portaient sur des modules deja branches par une autre voie.

Et le correctif ne doit PAS rendre le capteur bavard : `import os.path` ne doit jamais
fabriquer une arete vers un `path.py` du depot.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_module_wiring as mw  # noqa: E402

# Un index minuscule, ecrit a la main : le contrat se lit sans dependre du depot reel.
INDEX = {
    "app.forge_code_ast": "app/forge_code_ast.py",
    "app.core": "app/core/__init__.py",
    "app.core.settings": "app/core/settings/__init__.py",
    "tools.forge_x": "tools/forge_x.py",
    # ⚠️ PAS d'entree `forge_videur` : `_index_pointes` ne peut pas en produire une.
    # Un fichier `app/forge_videur.py` y entre sous la clef `app.forge_videur`. Or
    # Nokido l'importe A PLAT (`import forge_videur`, via sys.path) -- cette pointe
    # n'est donc PAS resoluble par chemin, et c'est structurel, pas un manque d'index.
    # C'est la raison des 99 % d'aretes nommees : la seule identite disponible est le nom.
    "app.forge_videur": "app/forge_videur.py",
}


def test_une_pointe_pointee_se_resout_au_fichier_vise() -> None:
    """Passe 1 : l'arete doit atteindre le module, pas le paquet de tete."""
    assert mw._resoudre_import("app.forge_code_ast", INDEX) == (
        "chemin", "app/forge_code_ast.py")


def test_un_segment_intermediaire_n_est_JAMAIS_une_cible() -> None:
    """Passe 2 : `app.core.settings` vise le PAQUET settings, pas un module « core ».

    C'est la ligne qui valait 45 fausses aretes sur un fichier sans rapport."""
    genre, cible = mw._resoudre_import("app.core.settings", INDEX)
    assert (genre, cible) == ("chemin", "app/core/settings/__init__.py")
    assert "agents" not in cible, "l'arete ne peut pas atterrir dans un autre organe"


def test_un_paquet_est_designe_par_son_init() -> None:
    """Sans cette entree, un import de paquet retombe dans la resolution par nom."""
    assert mw._resoudre_import("app.core", INDEX) == ("chemin", "app/core/__init__.py")


def test_une_pointe_pointee_hors_depot_ne_fait_AUCUNE_arete() -> None:
    """`import os.path` ne doit pas fabriquer d'arete vers un `path.py` du depot.

    Et elle ne retombe pas en resolution par NOM : ce serait rendre ambigue une pointe
    qui ne l'etait pas."""
    for pointe in ("os.path", "xml.etree.ElementTree", "concurrent.futures",
                   "app.module.qui.n.existe.pas"):
        genre, _ = mw._resoudre_import(pointe, INDEX)
        assert genre == "absent", "%s doit etre ABSENT, pas une arete" % pointe


def test_une_pointe_NUE_reste_une_clef_de_resolution() -> None:
    """Nokido importe a plat (`import forge_x` via sys.path) : 99 % des aretes.

    Une pointe nue designe un NOM ; c'est a l'appelant de refuser si le nom est ambigu."""
    assert mw._resoudre_import("forge_videur", INDEX) == ("nom", "forge_videur"), (
        "le fichier EXISTE (app/forge_videur.py) mais la pointe nue ne le designe pas : "
        "seul le nom est disponible")
    assert mw._resoudre_import("nom_inconnu", INDEX) == ("nom", "nom_inconnu")
    assert mw._resoudre_import("app.forge_videur", INDEX) == (
        "chemin", "app/forge_videur.py"), "ecrit en pointe, le MEME module est prouvable"


# --- imports RELATIFS : la resolution la plus sure, et je l'avais jetee -------------

REL = {
    "app.collab_modes": "app/collab_modes/__init__.py",
    "app.collab_modes.mode_panel": "app/collab_modes/mode_panel.py",
    "app.forge_videur": "app/forge_videur.py",
}


def test_un_import_relatif_se_resout_a_son_paquet() -> None:
    """PAYE dans la passe ID-03 elle-meme. En ecartant `n.level > 0` sans remplacer,
    `mode_panel.py` est passe BRANCHE -> ORPHELIN : son UNIQUE importeur le vise par
    `from .mode_panel`, et aucune pointe absolue ne le nomme."""
    assert mw._resoudre_relatif(
        "app/collab_modes/dispatch.py", 1, "mode_panel", REL) == (
        "chemin", "app/collab_modes/mode_panel.py")


def test_un_import_relatif_remonte_d_un_cran() -> None:
    """`from ..forge_videur import X` depuis un sous-paquet vise le paquet PARENT."""
    assert mw._resoudre_relatif(
        "app/collab_modes/dispatch.py", 2, "forge_videur", REL) == (
        "chemin", "app/forge_videur.py")


def test_from_point_import_vise_le_paquet_lui_meme() -> None:
    """`from . import X` : le module est None, la cible est le `__init__` du paquet."""
    assert mw._resoudre_relatif("app/collab_modes/dispatch.py", 1, None, REL) == (
        "chemin", "app/collab_modes/__init__.py")


def test_un_relatif_qui_remonte_au_dela_de_la_racine_est_ABSENT() -> None:
    """Pas de cible inventee, et pas d'exception : ABSENT est un etat, pas un crash."""
    genre, _ = mw._resoudre_relatif("app/collab_modes/dispatch.py", 9, "x", REL)
    assert genre == "absent"


def test_un_relatif_non_trouve_ne_retombe_PAS_sur_un_nom() -> None:
    """Sinon une arete determinee par construction redeviendrait ambigue."""
    genre, _ = mw._resoudre_relatif("app/collab_modes/dispatch.py", 1, "absent_ici", REL)
    assert genre == "absent", "ni chemin, ni nom : on ne devine pas"


def test_l_heuristique_des_paquets_a_ete_RETIREE() -> None:
    """`_PAQUETS` etait le support de la passe 2 du defaut. Une constante morte qui
    documente une heuristique supprimee est un piege pour le prochain lecteur."""
    assert not hasattr(mw, "_PAQUETS"), (
        "la resolution se fait contre l'arborescence REELLE, pas contre une liste de "
        "paquets ecrite a la main")
    assert not hasattr(mw, "_cibles_import"), "remplacee par _resoudre_import"
