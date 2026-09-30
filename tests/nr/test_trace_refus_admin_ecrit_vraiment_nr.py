# -*- coding: utf-8 -*-
"""NR — une trace de refus doit etre ECRITE, pas seulement ECRITE DANS LE CODE.

MESURE DU 2026-09-21 QUI JUSTIFIE CE FICHIER
    Trois routes gardees ont rendu 401 en runtime, hub redemarre a 19:32 avec le
    correctif charge (le pid en LISTEN sur :8766 a demarre 71 min APRES la
    derniere modification du fichier). La vue d'audit -- FRAICHE, mtime a -24 s,
    +46 observations sur la fenetre -- n'en a enregistre AUCUNE :

        by_tool          sans `_admin_tok_ok`
        by_via           sans `admin_tok_refuse:*`
        by_decision      DENY fige a 89

    Et dans la MEME fenetre, deux cles `via` neuves apparaissaient
    (`delegated:OPENAI_PROXY`, `delegated:DENOHUBMCP`). La vue savait donc
    ecrire une cle neuve : elle n'avait simplement rien recu. C'est ce controle
    qui interdit de lire ce vide comme un defaut d'instrument.

CAUSE, reproduite par EXECUTION et non par lecture
    `_journaliser_refus_admin` et `_admin_tok_ok` sont des fonctions SOEURS dans
    `_build_app`. La premiere lisait `required_scope`, qui est un PARAMETRE de la
    seconde. Un parametre de soeur n'est pas une closure : NameError a chaque
    refus, avale par `except Exception: pass`.

        EXISTS != CALLED != PRODUCED != JOURNALIZED

    Le `except` avait ete justifie par « une trace qui echoue ne doit pas
    transformer un refus en erreur 500 ». C'etait vrai -- et cela a transforme
    LA PANNE DE LA TRACE en silence. Un best-effort protege l'appelant ; il ne
    dispense jamais de prouver que l'effet a lieu.

    Consequence mesuree : les SEPT sites d'appel etaient morts d'un seul defaut,
    ceux de `_admin_tok_ok` comme ceux de `swarm_run` / `recon_run` / `ctf_run`.

CE QUE CE FICHIER VERROUILLE
    La PROPRIETE (« la trace est ecrite »), jamais la POSITION d'un symbole. Les
    tests chargent la fonction REELLE extraite du hub et comptent les captures.
    Un refactoring qui deplace la ligne ne les casse pas ; un refactoring qui
    casse l'ecriture les fait rougir.

CONTRE-EPREUVE OBLIGATOIRE
    Le meme harnais applique a une version FAUTIVE construite ici doit rendre
    ZERO capture. Sans elle, un test qui compte toujours 1 ne distingue rien --
    et c'est exactement le faux vert qui a laisse passer ce defaut.

POURQUOI UN MODULE TEMPORAIRE PLUTOT QU'UNE EVALUATION DYNAMIQUE
    Le firewall du hub refuse l'evaluation dynamique de source, et il a raison.
    On ecrit donc la fonction extraite dans un fichier et on l'IMPORTE : c'est le
    chemin reel d'un module Python, et le garde n'a pas a etre contourne.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
_HUB = _RACINE / "tools" / "nokido_hub.py"

_MODULE_VIDEUR = "nokido_agent.app.forge_videur"


# ─────────────────────────────────────────────────────────────────────────────
# Harnais : on charge la fonction TELLE QU'ELLE EST DANS LE DEPOT.
# ─────────────────────────────────────────────────────────────────────────────
def _source_hub() -> str:
    return _HUB.read_text(encoding="utf-8", errors="replace")


def _extraire(nom: str, source: str | None = None) -> str:
    """Rend le source d'une fonction imbriquee, desindente et compilable.

    `ast.get_source_segment` desindente la PREMIERE ligne seulement : les
    suivantes gardent l'indentation de `_build_app`. On retire donc `col_offset`
    a chaque ligne de suite, et jamais par un `dedent` global qui echouerait.
    """
    src = source if source is not None else _source_hub()
    arbre = ast.parse(src)
    for n in ast.walk(arbre):
        if isinstance(n, ast.FunctionDef) and n.name == nom:
            seg = ast.get_source_segment(src, n)
            assert seg, "source introuvable pour %s" % nom
            lignes = seg.splitlines()
            marge = n.col_offset
            suite = [
                ligne[marge:] if ligne[:marge].strip() == "" else ligne
                for ligne in lignes[1:]
            ]
            return "\n".join([lignes[0]] + suite)
    raise AssertionError("fonction %s absente de %s" % (nom, _HUB.name))


class _FauxRequest:
    """Le strict necessaire : des en-tetes et un chemin d'URL."""

    def __init__(self, chemin: str = "/api/ring_buffer/stats") -> None:
        self.headers = {"laforge-agent-name": "CLAUDE"}
        self.url = types.SimpleNamespace(path=chemin)


def _brancher_capture(monkeypatch) -> list:
    """Remplace `capture` par un compteur, en creant les modules si besoin.

    On ne depend PAS de l'importabilite reelle de `forge_videur` : le sujet du
    test est le code du hub. Mais on n'esquive pas l'import non plus -- la
    fonction execute son `from ... import capture` pour de bon.
    """
    recus: list = []

    def _faux(identity, tool="", extra=None):
        recus.append({"identity": identity, "tool": tool, "extra": extra or {}})

    for nom in ("nokido_agent", "nokido_agent.app", _MODULE_VIDEUR):
        if nom not in sys.modules:
            module = types.ModuleType(nom)
            if nom != _MODULE_VIDEUR:
                module.__path__ = []  # paquet, sinon l'import du fils echoue
            monkeypatch.setitem(sys.modules, nom, module)
    monkeypatch.setattr(sys.modules[_MODULE_VIDEUR], "capture", _faux, raising=False)
    return recus


_compteur = [0]


def _charger(source_fn: str, nom_fn: str, dossier: Path):
    """Materialise la fonction dans un module et l'importe.

    Aucune evaluation dynamique : un fichier, un `spec`, un import -- le chemin
    reel d'un module Python.
    """
    _compteur[0] += 1
    fichier = dossier / ("nr_trace_%d.py" % _compteur[0])
    fichier.write_text(source_fn, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(fichier.stem, fichier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, nom_fn)


# ─────────────────────────────────────────────────────────────────────────────
# LE TEST QUI COMPTE : l'effet a-t-il lieu ?
# ─────────────────────────────────────────────────────────────────────────────
def test_un_refus_admin_produit_une_capture(monkeypatch, tmp_path):
    """Le coeur. Avant correctif : ZERO capture, en silence."""
    recus = _brancher_capture(monkeypatch)
    fn = _charger(_extraire("_journaliser_refus_admin"),
                  "_journaliser_refus_admin", tmp_path)
    fn(_FauxRequest(), "porteur_de_test", "aucun_chemin_accepte")
    assert len(recus) == 1, (
        "le refus n'a produit AUCUNE capture : la trace existe dans le code et "
        "ne s'execute pas (NameError avale par le best-effort ?)"
    )


def test_la_capture_porte_la_decision_et_la_cause(monkeypatch, tmp_path):
    recus = _brancher_capture(monkeypatch)
    fn = _charger(_extraire("_journaliser_refus_admin"),
                  "_journaliser_refus_admin", tmp_path)
    fn(_FauxRequest(), "porteur_de_test", "aucun_chemin_accepte")
    ident, extra = recus[0]["identity"], recus[0]["extra"]
    assert extra.get("decision") == "DENY"
    assert ident.get("via", "").startswith("admin_tok_refuse:"), (
        "le `via` doit NOMMER la cause : un 401 muet etait deja observable, "
        "c'est la cause qui manquait"
    )
    assert ident["via"].endswith("aucun_chemin_accepte")
    assert recus[0]["tool"] == "_admin_tok_ok"


def test_les_quatre_causes_de_refus_sont_distinguables(monkeypatch, tmp_path):
    """Quatre chemins de decision ; un refus doit dire LEQUEL."""
    recus = _brancher_capture(monkeypatch)
    fn = _charger(_extraire("_journaliser_refus_admin"),
                  "_journaliser_refus_admin", tmp_path)
    causes = ("jwt_scope", "pas_de_maitre_configure",
              "no_auth_hors_loopback", "aucun_chemin_accepte")
    for cause in causes:
        fn(_FauxRequest(), "porteur_de_test", cause)
    vus = {r["identity"]["via"] for r in recus}
    assert len(vus) == len(causes), "des causes distinctes se confondent : %s" % vus


def test_le_porteur_ne_sort_jamais_de_la_trace(monkeypatch, tmp_path):
    """Invariant de securite : seul le hash voyage, jamais le porteur."""
    recus = _brancher_capture(monkeypatch)
    fn = _charger(_extraire("_journaliser_refus_admin"),
                  "_journaliser_refus_admin", tmp_path)
    porteur_temoin = "valeur-temoin-qui-ne-doit-pas-fuir"
    fn(_FauxRequest(), porteur_temoin, "aucun_chemin_accepte")
    assert porteur_temoin not in repr(recus), "LE PORTEUR A FUIT DANS LA TRACE"
    assert recus[0]["identity"].get("token_h"), "le hash doit etre present"
    assert len(recus[0]["identity"]["token_h"]) <= 32


def test_un_refus_sans_porteur_capture_aussi(monkeypatch, tmp_path):
    """`tok` vide est le cas le PLUS frequent -- il ne doit pas etre muet."""
    recus = _brancher_capture(monkeypatch)
    fn = _charger(_extraire("_journaliser_refus_admin"),
                  "_journaliser_refus_admin", tmp_path)
    fn(_FauxRequest(), "", "aucun_chemin_accepte")
    assert len(recus) == 1
    assert recus[0]["extra"].get("porteur_present") is False


def test_la_route_est_portee_par_la_trace(monkeypatch, tmp_path):
    recus = _brancher_capture(monkeypatch)
    fn = _charger(_extraire("_journaliser_refus_admin"),
                  "_journaliser_refus_admin", tmp_path)
    fn(_FauxRequest("/admin/job/zzz"), "x", "aucun_chemin_accepte")
    assert recus[0]["extra"].get("route") == "/admin/job/zzz"


# ─────────────────────────────────────────────────────────────────────────────
# CONTRE-EPREUVE : le harnais doit SAVOIR rendre zero.
# ─────────────────────────────────────────────────────────────────────────────
_FAUTIF = (
    "def _tracer_fautif(request, tok, chemin):\n"
    "    try:\n"
    "        from nokido_agent.app.forge_videur import capture as _cap\n"
    "        _cap({'via': chemin}, '_admin_tok_ok',\n"
    "             {'scope_requis': nom_non_lie or ''})\n"
    "    except Exception:\n"
    "        pass\n"
)

_SAIN = (
    "def _tracer_sain(request, tok, chemin):\n"
    "    try:\n"
    "        from nokido_agent.app.forge_videur import capture as _cap\n"
    "        _cap({'via': chemin}, '_admin_tok_ok', {'decision': 'DENY'})\n"
    "    except Exception:\n"
    "        pass\n"
)


def test_le_harnais_detecte_une_version_fautive(monkeypatch, tmp_path):
    """Sans ceci, un test qui compte toujours 1 ne distingue rien.

    On reconstruit EXACTEMENT le defaut mesure : un nom libre resolu nulle part,
    sous un best-effort qui avale.
    """
    recus = _brancher_capture(monkeypatch)
    _charger(_FAUTIF, "_tracer_fautif", tmp_path)(
        _FauxRequest(), "x", "aucun_chemin_accepte")
    assert recus == [], (
        "le harnais ne distingue rien : il compte une capture la ou le code "
        "fautif n'en produit aucune"
    )


def test_le_harnais_valide_une_version_saine(monkeypatch, tmp_path):
    """Symetrique : il ne doit pas rendre zero pour tout le monde."""
    recus = _brancher_capture(monkeypatch)
    _charger(_SAIN, "_tracer_sain", tmp_path)(
        _FauxRequest(), "x", "aucun_chemin_accepte")
    assert len(recus) == 1


# ─────────────────────────────────────────────────────────────────────────────
# GENERALISATION : la famille entiere, pas seulement le cas paye.
# ─────────────────────────────────────────────────────────────────────────────
# Noms toujours presents dans un module, qu'aucun import ne lie : les compter
# comme orphelins faisait crier le detecteur sur 32 fonctions saines (mesure du
# 2026-09-21, 36 signalements dont 32 `__file__`).
#
#     UN GARDE QUI CRIE A FAUX SE FAIT DESARMER
_IMPLICITES = {
    "__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__",
    "__builtins__", "__debug__", "__annotations__", "__path__", "__dict__",
    "__class__", "__module__", "__qualname__",
}


def _tous_parametres(fn) -> set:
    """TOUS les parametres, y compris positional-only.

    Oublier `posonlyargs` ICI alors que `_noms_libres` les compte produit une
    asymetrie qui accuse une closure saine : mesure du 2026-09-21 sur
    `forge_db_observatoire.execute(self, sql, ..., /)`, ou `self` et `sql`
    etaient declares introuvables parce que le detecteur ne lisait qu'`args`.
    """
    noms = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    noms |= {a.arg for a in getattr(fn.args, "posonlyargs", [])}
    if fn.args.vararg:
        noms.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        noms.add(fn.args.kwarg.arg)
    return noms


def _noms_libres(fn: ast.FunctionDef) -> set:
    """Noms LUS par la fonction sans y etre lies. Portee propre uniquement."""
    lies = _tous_parametres(fn)
    if fn.args.vararg:
        lies.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        lies.add(fn.args.kwarg.arg)
    lus: set = set()
    pile = list(fn.body)
    while pile:
        n = pile.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # la fille a sa propre portee -- ne pas s'attribuer son contenu
        if isinstance(n, ast.Name):
            (lies if isinstance(n.ctx, ast.Store) else lus).add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                lies.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            lies.add(n.name)
        pile.extend(ast.iter_child_nodes(n))
    for n in ast.walk(fn):
        if isinstance(n, ast.comprehension):
            for x in ast.walk(n.target):
                if isinstance(x, ast.Name):
                    lies.add(x.id)  # une comprehension a sa propre portee
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            lies.update(n.names)
    import builtins
    return lus - lies - set(dir(builtins)) - _IMPLICITES


def _portee_englobante(cible: ast.FunctionDef, arbre: ast.AST) -> set:
    """Ce qu'une closure REELLE peut voir : parametres et locaux des ANCETRES.

    Un parametre de fonction SOEUR n'en fait pas partie -- c'est tout le defaut.
    """
    parent = {}
    for n in ast.walk(arbre):
        for c in ast.iter_child_nodes(n):
            parent[c] = n
    visibles: set = set()
    noeud = cible
    while noeud in parent:
        noeud = parent[noeud]
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visibles |= _tous_parametres(noeud)
            for n in ast.walk(noeud):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visibles.add(n.name)
                elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    visibles.add(n.id)
                elif isinstance(n, (ast.Import, ast.ImportFrom)):
                    for al in n.names:
                        visibles.add((al.asname or al.name).split(".")[0])
        elif isinstance(noeud, ast.Module):
            visibles |= _noms_de_portee_module(noeud)
    return visibles


def _noms_de_portee_module(module: ast.Module) -> set:
    """Tout ce que la portee MODULE lie, y compris sous `try` / `if` / `with`.

    MESURE DU 2026-09-21 : ne lire que `module.body` laissait 13 faux positifs.
    Un `import torch` place dans un `try: ... except ImportError:` -- la forme
    normale d'un import optionnel -- est un `ast.Try` dans `body`, pas un
    `ast.Import` : il etait donc declare non lie, et toute closure le lisant
    etait accusee.

        DESCENDRE DANS LES STRUCTURES DE CONTROLE, JAMAIS DANS LES FONCTIONS

    La nuance porte tout : entrer dans les `FunctionDef` ferait passer les
    locaux d'une fonction pour des globales, et le detecteur absoudrait
    exactement le defaut qu'il doit attraper.
    """
    noms: set = set()
    pile = list(module.body)
    while pile:
        n = pile.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            noms.add(n.name)
            continue  # sa portee interne n'appartient pas au module
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            noms.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                noms.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            noms.add(n.name)
        pile.extend(ast.iter_child_nodes(n))
    return noms


def test_aucune_fonction_de_trace_ne_lit_un_nom_non_lie():
    """La famille `_journaliser_*` : aucun nom libre hors portee englobante.

    Generalise le defaut paye au lieu de le corriger seul. Un nom resolu
    uniquement par une fonction SOEUR est precisement ce qu'on interdit.
    """
    arbre = ast.parse(_source_hub())
    fautes = []
    vues = 0
    for n in ast.walk(arbre):
        # `async def` INCLUS : ne filtrer que `FunctionDef` ecartait 164 closures
        # sur 692 dans le depot (mesure 2026-09-21) sans le dire. Un garde dont
        # la portee exclut un quart de sa cible ment sur sa couverture.
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not n.name.startswith("_journaliser"):
            continue
        vues += 1
        orphelins = _noms_libres(n) - _portee_englobante(n, arbre)
        if orphelins:
            fautes.append("%s (L%d) lit %s" % (n.name, n.lineno, sorted(orphelins)))
    assert vues, (
        "AUCUNE fonction `_journaliser*` examinee : le garde ne couvre rien. "
        "Un zero de couverture n'est pas un zero de defaut")
    assert not fautes, (
        "nom(s) lu(s) sans etre lie(s) -- NameError garanti a l'execution, et "
        "avale par le best-effort : " + " | ".join(fautes)
    )


def test_le_detecteur_de_noms_libres_distingue_deux_cas_construits():
    """Contre-epreuve du detecteur lui-meme."""
    fautif = ast.parse(
        "def _build():\n"
        "    def _journaliser_x(a):\n"
        "        return scope_de_la_soeur\n"
        "    def _garde(a, scope_de_la_soeur=None):\n"
        "        return _journaliser_x(a)\n"
    )
    sain = ast.parse(
        "def _build():\n"
        "    def _journaliser_x(a, scope=None):\n"
        "        return scope\n"
    )
    for arbre, attendu in ((fautif, True), (sain, False)):
        cible = [n for n in ast.walk(arbre)
                 if isinstance(n, ast.FunctionDef) and n.name == "_journaliser_x"][0]
        orphelins = _noms_libres(cible) - _portee_englobante(cible, arbre)
        assert bool(orphelins) is attendu, (
            "le detecteur ne distingue pas le cas %s" % ("fautif" if attendu else "sain"))


def test_le_garde_couvre_aussi_les_fonctions_async():
    """Une closure `async def` se verifie comme les autres.

    Le hub est un serveur ASGI : ses handlers sont `async`. Un detecteur qui
    ne filtre que `ast.FunctionDef` laisse passer precisement les fonctions
    qui portent les routes.
    """
    arbre = ast.parse(
        "def _build():\n"
        "    async def _journaliser_async(a):\n"
        "        return scope_de_la_soeur\n"
        "    def _garde(a, scope_de_la_soeur=None):\n"
        "        return _journaliser_async(a)\n"
    )
    cible = [n for n in ast.walk(arbre)
             if isinstance(n, ast.AsyncFunctionDef)][0]
    assert _noms_libres(cible) - _portee_englobante(cible, arbre) == {
        "scope_de_la_soeur"}, "une closure async echappe au detecteur"


def test_un_import_optionnel_du_module_est_une_liaison():
    """Contre-epreuve : 13 faux positifs mesures le 2026-09-21.

    L'import place sous `try/except ImportError` est la forme NORMALE d'une
    dependance optionnelle. Le lire comme « non lie » accusait des closures
    saines dans huit modules.
    """
    arbre = ast.parse(
        "try:\n"
        "    import torch\n"
        "    HAS_TORCH = True\n"
        "except ImportError:\n"
        "    HAS_TORCH = False\n"
        "\n"
        "def _build():\n"
        "    def _journaliser_x(a):\n"
        "        return torch if HAS_TORCH else None\n"
    )
    cible = [n for n in ast.walk(arbre)
             if isinstance(n, ast.FunctionDef) and n.name == "_journaliser_x"][0]
    assert not (_noms_libres(cible) - _portee_englobante(cible, arbre)), (
        "un import optionnel du module est pris pour un nom non lie")


def test_la_portee_module_n_absout_pas_les_locaux_d_une_fonction():
    """Symetrique : descendre dans les `try` ne doit pas ouvrir les fonctions.

    Si `_noms_de_portee_module` entrait dans les `FunctionDef`, la variable
    locale d'une fonction voisine passerait pour une globale -- et le
    detecteur absoudrait le defaut qu'il existe pour attraper.
    """
    arbre = ast.parse(
        "def voisine():\n"
        "    locale_de_la_voisine = 1\n"
        "    return locale_de_la_voisine\n"
        "\n"
        "def _build():\n"
        "    def _journaliser_x(a):\n"
        "        return locale_de_la_voisine\n"
    )
    cible = [n for n in ast.walk(arbre)
             if isinstance(n, ast.FunctionDef) and n.name == "_journaliser_x"][0]
    assert _noms_libres(cible) - _portee_englobante(cible, arbre) == {
        "locale_de_la_voisine"}


def test_le_detecteur_ne_crie_pas_sur_les_noms_implicites():
    """Contre-epreuve du correctif : 32 faux positifs mesures le 2026-09-21.

    `__file__` n'est lie par aucun import et existe dans tout module. Le
    signaler faisait du detecteur un garde qu'on desarme.
    """
    arbre = ast.parse(
        "def _build():\n"
        "    def _journaliser_x(a):\n"
        "        return __file__ + __name__\n"
    )
    cible = [n for n in ast.walk(arbre)
             if isinstance(n, ast.FunctionDef) and n.name == "_journaliser_x"][0]
    assert not (_noms_libres(cible) - _portee_englobante(cible, arbre)), (
        "les noms implicites de module sont pris pour des orphelins")


def test_le_detecteur_voit_les_parametres_positional_only():
    """Contre-epreuve du correctif : une closure saine accusee a tort.

    `execute(self, sql, /)` met tout dans `posonlyargs`. Les compter d'un cote
    et pas de l'autre accuse la closure de lire des noms non lies.
    """
    arbre = ast.parse(
        "def execute(self, sql, /):\n"
        "    def _journaliser_x():\n"
        "        return self, sql\n"
    )
    cible = [n for n in ast.walk(arbre)
             if isinstance(n, ast.FunctionDef) and n.name == "_journaliser_x"][0]
    assert not (_noms_libres(cible) - _portee_englobante(cible, arbre)), (
        "les parametres positional-only du parent sont ignores")


def test_le_detecteur_corrige_rougit_toujours_sur_le_vrai_defaut():
    """Symetrique indispensable : elargir la portee ne doit pas tout absoudre."""
    arbre = ast.parse(
        "def _build():\n"
        "    def _journaliser_x(a):\n"
        "        return scope_de_la_soeur\n"
        "    def _garde(a, scope_de_la_soeur=None):\n"
        "        return _journaliser_x(a)\n"
    )
    cible = [n for n in ast.walk(arbre)
             if isinstance(n, ast.FunctionDef) and n.name == "_journaliser_x"][0]
    assert _noms_libres(cible) - _portee_englobante(cible, arbre) == {"scope_de_la_soeur"}


def test_les_appelants_de_admin_tok_ok_transmettent_le_scope():
    """Le scope requis doit VENIR de l'appelant, pas etre devine.

    Propriete, pas position : on verifie que chaque appel situe DANS
    `_admin_tok_ok` transmet `required_scope`, quelle que soit sa ligne.
    """
    arbre = ast.parse(_source_hub())
    parent = {}
    for n in ast.walk(arbre):
        for c in ast.iter_child_nodes(n):
            parent[c] = n
    manquants = []
    for n in ast.walk(arbre):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_journaliser_refus_admin"):
            continue
        noeud, englobante = n, None
        while noeud in parent:
            noeud = parent[noeud]
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                englobante = noeud
                break
        if englobante is None or englobante.name != "_admin_tok_ok":
            continue  # les autres appelants n'ont pas de scope a transmettre
        transmis = any(k.arg == "required_scope" for k in n.keywords) or len(n.args) >= 4
        if not transmis:
            manquants.append(n.lineno)
    assert not manquants, (
        "appel(s) depuis `_admin_tok_ok` sans transmettre `required_scope` : %s "
        "-- le lire depuis la soeur est justement le defaut du 2026-09-21"
        % manquants
    )


def test_la_fonction_accepte_un_scope_optionnel():
    """Optionnel : trois appelants (`swarm_run`/`recon_run`/`ctf_run`) n'en ont pas."""
    arbre = ast.parse(_source_hub())
    cible = [n for n in ast.walk(arbre)
             if isinstance(n, ast.FunctionDef)
             and n.name == "_journaliser_refus_admin"][0]
    noms = [a.arg for a in cible.args.args]
    assert "required_scope" in noms, (
        "`required_scope` doit etre un PARAMETRE : le lire depuis la soeur leve "
        "NameError")
    assert len(cible.args.defaults) >= 1, (
        "le scope doit etre OPTIONNEL (3 appelants n'en ont pas)")
    assert noms[-1] == "required_scope", "le parametre optionnel vient en dernier"


def test_le_fichier_de_test_n_est_pas_tronque():
    """Garde-fou paye le 2026-09-21 : l'ecriture gouvernee a coupe ce fichier en
    plein milieu d'une expression, et l'a declare « relecture disque identique ».

        AST VALIDE != CONTENU COMPLET

    `arbre = ast.parse` -- sans parenthese -- se parse tres bien : c'est une
    assignation. Le test ampute passait donc TRIVIALEMENT, son corps s'arretant
    avant la moindre assertion. Un faux vert produit non par une erreur, mais
    par une TRONCATURE SILENCIEUSE.

    On verifie donc que chaque fonction de test porte au moins une assertion :
    une coupure au milieu redeviendrait visible.
    """
    arbre = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    muets = []
    for n in arbre.body:
        if not (isinstance(n, ast.FunctionDef) and n.name.startswith("test_")):
            continue
        if not any(isinstance(x, ast.Assert) for x in ast.walk(n)):
            muets.append(n.name)
    assert not muets, (
        "fonction(s) de test sans aucune assertion -- fichier tronque ? : %s"
        % muets)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))