"""NR — la route des composants d'interface ne sort plus de son dossier.

Revue defensive LOCAL-IPC du 2026-09-18. `ui_serve` (tools/nokido_hub.py)
prenait `component_id` dans l'URL et le concatenait tel quel :

    comp_path = ROOT / "sandbox" / "ui_components" / f"{component_id}.html"
    return HTMLResponse(comp_path.read_text(...))

Mesure sur arborescence jetable, AVANT correctif : `../../prive` et un chemin
ABSOLU rendaient le contenu d'un fichier situe hors du dossier. Deux formes sur
six — la profondeur qui marche depend de l'arborescence, donc « ../x echoue » ne
prouvait rien.

PORTEE REELLE, a ne pas surestimer : le suffixe `.html` est force par le code,
donc la lecture ne portait que sur des fichiers `.html`. Ce n'etait pas un acces
aux sources ni aux fichiers de configuration. Bornee reste exploitable.

DEUX CHOIX DE CONCEPTION que ce test verrouille :
  - le confinement porte sur le chemin RESOLU, pas sur le texte. Filtrer « .. »
    dans la chaine laisserait passer les liens, les chemins absolus et les
    encodages : c'est le meme motif qu'une liste de mots-clefs interdits en SQL,
    un garde qu'on franchit en reecrivant son entree ;
  - le refus est le MEME (404) pour « hors racine » et pour « absent », sinon la
    route devient un oracle d'existence de fichiers.

LIMITE DE CE TEST, nommee : `ui_serve` est une closure definie dans le corps du
module `nokido_hub`, dont l'import demarre des sondes de boot. On ne l'appelle
donc pas : on rejoue sa LOGIQUE sur une arborescence jetable, et on verifie par
AST que la source porte bien le confinement. C'est un cran en dessous d'un test
du chemin d'appel reel, et c'est dit plutot que masque.
"""

import ast
import tempfile
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture()
def arbre():
    """Un dossier de composants, et un fichier a NE PAS servir juste a cote."""
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "sandbox" / "ui_components"
    base.mkdir(parents=True)
    (base / "widget.html").write_text("<p>composant legitime</p>", encoding="utf-8")
    (tmp / "prive.html").write_text("CONTENU HORS RACINE", encoding="utf-8")
    return tmp, base


def _servir(base: Path, component_id: str) -> str:
    """La logique du correctif, a l'identique de `ui_serve`."""
    b = base.resolve()
    try:
        p = (b / f"{component_id}.html").resolve()
    except (OSError, ValueError):
        return "404"
    if not p.is_relative_to(b) or not p.is_file():
        return "404"
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "cid",
    [
        "../prive",
        "..\\prive",
        "../../prive",
        "../../../prive",
        "sous/../../prive",
        "./../../prive",
    ],
)
def test_aucune_forme_de_traversee_ne_sort_du_dossier(arbre, cid):
    _, base = arbre
    assert "HORS RACINE" not in _servir(base, cid), (
        f"la traversee {cid!r} lit un fichier hors du dossier des composants"
    )


def test_un_chemin_absolu_ne_sort_pas_non_plus(arbre):
    """`Path(base) / "/autre/chose"` ECRASE la base en pathlib — un filtre sur
    « .. » seul ne l'aurait jamais vu."""
    tmp, base = arbre
    assert "HORS RACINE" not in _servir(base, str(tmp / "prive"))


def test_le_composant_legitime_reste_servi(arbre):
    """MORSURE SYMETRIQUE — un confinement qui casse la route n'est pas un
    correctif, c'est une panne."""
    _, base = arbre
    assert _servir(base, "widget") == "<p>composant legitime</p>"


def test_hors_racine_et_absent_rendent_LA_MEME_chose(arbre):
    """Sinon la route devient un oracle : « ce fichier existe-t-il ? » se lirait
    dans la difference entre les deux reponses."""
    tmp, base = arbre
    assert _servir(base, "../../prive") == _servir(base, "composant-qui-n-existe-pas")


def test_la_source_porte_bien_le_confinement():
    """CONTROLE DE FORME — par AST, jamais par recherche de texte : le
    commentaire de cette fonction NOMME la traversee qu'elle corrige, et un
    scanner textuel s'accuserait lui-meme (motif paye 10 fois ce mois-ci)."""
    src = (RACINE / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    arbre_ast = ast.parse(src)
    fn = next(
        (n for n in ast.walk(arbre_ast)
         if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "ui_serve"),
        None,
    )
    assert fn is not None, "la route des composants a disparu ou a ete renommee"
    appels = {
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "is_relative_to" in appels, (
        "le confinement a la racine a disparu de `ui_serve` : la traversee du "
        "2026-09-18 est rouverte"
    )
    assert "resolve" in appels, (
        "le chemin n'est plus RESOLU avant comparaison — un confinement sur le "
        "texte se franchit par un lien ou un chemin absolu"
    )
