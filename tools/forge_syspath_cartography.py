#!/usr/bin/env python3
"""forge_syspath_cartography.py — pourquoi ce `sys.path` est-il la ?

P4.2a a mesure que le corps s'importe A PLAT : 4 449 `import forge_*` et
1 186 `sys.path.insert`. Rendre `pip install nokido-agent` reel suppose de
migrer vers un namespace `nokido.*` — et la tentation est de lancer un codemod
qui retire les `sys.path` et reecrit les imports. La regle owner du 2026-09-09
l'interdit :

    Aucune transformation automatique ne supprime un `sys.path`
    tant qu'on n'a pas prouve POURQUOI il etait la.

CE MODULE NE TRANSFORME RIEN. Il classe, il nomme la voie qui a repondu, et il
refuse de conclure quand rien ne discrimine. Meme patron que
`forge_module_wiring` (BRANCHE / ORPHELIN / POINT_ENTREE), dont la docstring
pose la meme regle : « il rend la carte, l'humain tranche ».

CE QUE LA MESURE A DEJA MONTRE, et qui change le plan. Les `sys.path.insert`
du depot ne sont pas des accidents : beaucoup sont DANS une fonction, et ils
servent le patron anti-dup du corps — atteindre un module FRERE plutot que le
reecrire :

    def _rm():
        \"\"\"Le module matrice, seule source des sondes (anti-duplication).\"\"\"
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import forge_regression_matrix as RM

Un codemod qui les retire tous casserait le mecanisme que le corps utilise pour
ne pas se dupliquer. D'ou la classification par INTENTION, et pas par presence.

DEUX VERDICTS, ET PAS UN TROISIEME. `MIGRABLE` = le codemod SAIT quoi ecrire a
la place. `A_INSTRUIRE` = un humain regarde. Le mot « supprimable » n'apparait
nulle part, volontairement : un rapport qui l'ecrit sera lu comme une
autorisation, et quelqu'un lancera le sed.

LISTE BLANCHE. L'inconnu ne va JAMAIS du cote favorable : cible non resolue,
import dynamique, aucune voie qui repond -> `A_INSTRUIRE`.

Usage :
    LAFORGE_PYTHON tools/forge_syspath_cartography.py            # resume
    LAFORGE_PYTHON tools/forge_syspath_cartography.py --json out.json
    LAFORGE_PYTHON tools/forge_syspath_cartography.py --verdict MIGRABLE
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : pourquoi chaque sys.path existe, avant toute migration"

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Memes zones et memes exclusions que `forge_module_wiring` — on ne redefinit
# pas un perimetre concurrent, sinon deux cartes du meme corps divergent.
ZONES = ("app", "tools", "recon_silo")
IGNORES = {"_attic", "node_modules", "backups", "archive", ".git", "sandbox"}

VERDICTS = ("MIGRABLE", "A_INSTRUIRE")
PORTEES = ("MODULE", "FONCTION", "CONDITIONNEL")
INTENTIONS = (
    "PATH_FOR_IMPORT",
    "PATH_FOR_SUBPROCESS",
    "PATH_FOR_DATA",
    "PATH_FOR_PLUGIN",
    "UNKNOWN",
)

# Appels dont on sait reduire le resultat a un chemin symbolique. Tout autre
# appel rend la cible indeterminee — c'est le point ou l'AST cesse de savoir.
_APPELS_CHEMIN = {"str", "join", "abspath", "dirname", "normpath", "fspath"}
_ANCETRES_CONDITIONNELS = (ast.If, ast.Try, ast.While, ast.With, ast.AsyncWith)


@dataclass
class Site:
    """Un `sys.path.insert/append`, avec ce qu'on a pu en prouver."""

    fichier: str
    ligne: int
    forme: str  # "insert" | "append"
    portee: str
    cible: str
    # INTERNE / EXTERNE / MULTIPLE / INCONNUE — quatre gestes distincts. Une
    # cible EXTERNE resolue n'est PAS une dette de namespace : aucun `nokido.*`
    # n'absorbera jamais un `vendor/` ou un `site-packages`.
    cible_classe: str
    intention: str
    voie: str  # ce qui a repondu — vide seulement si UNKNOWN
    imports_suivants: list[str] = field(default_factory=list)
    verdict: str = "A_INSTRUIRE"
    # Pourquoi ce site n'est pas migrable. Sans ce champ, la limite de CET
    # instrument se confond avec la complexite du CORPS — et on croit mesurer
    # une dette la ou on mesure son propre reducteur.
    motif: str = ""


# --------------------------------------------------------------- reduction


def _reduire_chemin(noeud: ast.AST) -> str:
    """Reduit une expression de chemin a une forme symbolique, ou UNKNOWN.

    On ne cherche pas a evaluer : on cherche a savoir si l'AST SAIT. Des qu'un
    appel inconnu ou un nom non resoluble apparait, la reponse est UNKNOWN —
    jamais une approximation optimiste.
    """
    if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
        return noeud.value
    if isinstance(noeud, ast.Name):
        if noeud.id == "__file__":
            return "FICHIER"
        # Un nom en MAJUSCULES est une constante de module par convention
        # (ROOT, APP, OUTILS...). Un nom minuscule vient d'un calcul local :
        # on ne le suit pas.
        return noeud.id if noeud.id.isupper() else "UNKNOWN"
    if isinstance(noeud, ast.Attribute):
        if noeud.attr == "__file__" or _nom_pointe(noeud).endswith("__file__"):
            return "FICHIER"
        # `.parent` / `.parents` remontent l'arborescence ; la ZONE est portee
        # par le segment qui SUIT (`....parents[1] / "app"`). Rendre UNKNOWN ici
        # gonflait `analyseur_insuffisant` d'une dette qui n'existe pas — c'est
        # la forme la plus courante du depot.
        if noeud.attr in ("parent", "parents"):
            return _reduire_chemin(noeud.value)
        return "UNKNOWN"
    if isinstance(noeud, ast.Subscript):
        return _reduire_chemin(noeud.value)
    if isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Div):
        # Path(...) / "app"
        gauche = _reduire_chemin(noeud.left)
        droite = _reduire_chemin(noeud.right)
        if "UNKNOWN" in (gauche, droite):
            return "UNKNOWN"
        return f"{gauche}/{droite}"
    if isinstance(noeud, ast.Call):
        nom = _nom_appel(noeud)
        if nom == "Path" or nom in _APPELS_CHEMIN:
            morceaux = [_reduire_chemin(a) for a in noeud.args]
            if not morceaux:
                return "UNKNOWN"
            if any(m == "UNKNOWN" for m in morceaux):
                return "UNKNOWN"
            return "/".join(m for m in morceaux if m)
        if nom in {"resolve", "parent", "parents"}:
            return _reduire_chemin(noeud.func.value) if isinstance(noeud.func, ast.Attribute) else "UNKNOWN"
        return "UNKNOWN"
    return "UNKNOWN"


def _nom_appel(noeud: ast.Call) -> str:
    if isinstance(noeud.func, ast.Name):
        return noeud.func.id
    if isinstance(noeud.func, ast.Attribute):
        return noeud.func.attr
    return ""


def _nom_pointe(noeud: ast.AST) -> str:
    if isinstance(noeud, ast.Name):
        return noeud.id
    if isinstance(noeud, ast.Attribute):
        return f"{_nom_pointe(noeud.value)}.{noeud.attr}"
    return ""


def _resoudre_attribut_parent(noeud: ast.AST) -> str:
    """`Path(__file__).resolve().parent.parent` -> FICHIER."""
    courant = noeud
    for _ in range(12):
        if isinstance(courant, ast.Attribute):
            if courant.attr == "__file__":
                return "FICHIER"
            courant = courant.value
        elif isinstance(courant, ast.Call):
            courant = courant.func
        elif isinstance(courant, ast.Name):
            return courant.id if courant.id.isupper() else ("FICHIER" if courant.id == "__file__" else "UNKNOWN")
        else:
            return "UNKNOWN"
    return "UNKNOWN"


# ------------------------------------------------------------ inspection


def _est_site(noeud: ast.AST) -> str:
    """Rend "insert"/"append" si le noeud touche `sys.path`, sinon ""."""
    if not isinstance(noeud, ast.Call) or not isinstance(noeud.func, ast.Attribute):
        return ""
    if noeud.func.attr not in ("insert", "append"):
        return ""
    if _nom_pointe(noeud.func.value) not in ("sys.path", "path"):
        return ""
    return noeud.func.attr


def _portee(pile: list[ast.AST]) -> str:
    """CONDITIONNEL prime : un `sys.path` sous `try:` peut ne jamais tourner."""
    if any(isinstance(n, _ANCETRES_CONDITIONNELS) for n in pile):
        return "CONDITIONNEL"
    if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in pile):
        return "FONCTION"
    return "MODULE"


def _classer_cible(cible: str, pile: list[ast.AST]) -> str:
    """INTERNE / EXTERNE / MULTIPLE / INCONNUE.

    L'ordre compte : un `sys.path` dans une boucle insere PLUSIEURS chemins, et
    ce fait prime sur la reduction du chemin courant.
    """
    if any(isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)) for n in pile):
        return "MULTIPLE"
    if cible == "UNKNOWN":
        return "INCONNUE"
    bas = cible.replace("\\", "/").lower()
    if any(marque in bas for marque in ("site-packages", "dist-packages", "vendor")):
        return "EXTERNE"
    if bas.startswith("/") or (len(bas) > 1 and bas[1] == ":"):
        return "EXTERNE"
    segments = [s for s in bas.split("/") if s]
    if any(s in {z.lower() for z in ZONES} for s in segments):
        return "INTERNE"
    # Base symbolique ancree sur le depot (FICHIER, ROOT, APP...) sans zone
    # nommee : interne, mais on ne sait pas laquelle.
    if segments and (segments[0] == "fichier" or cible.split("/")[0].isupper()):
        return "INTERNE"
    return "INCONNUE"


def _conteneur(pile: list[ast.AST], arbre: ast.AST) -> ast.AST:
    """Le bloc dans lequel on cherchera les imports qui SUIVENT."""
    for noeud in reversed(pile):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return noeud
    return arbre


def _imports_plats_apres(conteneur: ast.AST, ligne: int) -> list[str]:
    """Modules a nom PLAT importes apres cette ligne, dans la meme portee.

    Un module plat (`forge_secrets`) est le candidat de la migration ; un import
    pointe (`app.forge_secrets`) ou stdlib ne dit rien sur le `sys.path`.
    """
    trouves: list[str] = []
    for noeud in ast.walk(conteneur):
        if getattr(noeud, "lineno", 0) <= ligne:
            continue
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                if _est_plat(alias.name):
                    trouves.append(alias.name)
        elif isinstance(noeud, ast.ImportFrom):
            if noeud.level == 0 and noeud.module and _est_plat(noeud.module):
                trouves.append(noeud.module)
    return trouves


_MODULES_DEPOT: set[str] | None = None


def modules_depot(racine: Path | None = None) -> set[str]:
    """Les modules que le depot porte REELLEMENT, par leur nom de fichier.

    C'est le denominateur de toute la classification. Sans lui, le classeur a
    surestime dans le sens qui l'arrange : `numpy` n'a pas de point et n'est pas
    stdlib, il passait donc pour un module frere migrable (mesure du
    2026-09-10 : 927 `PATH_FOR_IMPORT` annonces avant correction).
    """
    global _MODULES_DEPOT
    if racine is None and _MODULES_DEPOT is not None:
        return _MODULES_DEPOT
    base = racine or ROOT
    noms: set[str] = set()
    for zone in ZONES:
        dossier = base / zone
        if not dossier.is_dir():
            continue
        for chemin in dossier.rglob("*.py"):
            # RELATIF a la zone, jamais le chemin absolu. Le depot lui-meme peut
            # vivre sous un dossier qui porte un nom ignore : la CI de reference
            # juge le SHA dans `sandbox/ci_reference_wt/`, donc « sandbox »
            # apparaissait dans CHAQUE chemin et l'ensemble sortait VIDE — un
            # classeur muet qui paraissait prudent (mesure 2026-09-10).
            if any(part in IGNORES for part in chemin.relative_to(dossier).parts):
                continue
            noms.add(chemin.stem)
    if racine is None:
        _MODULES_DEPOT = noms
    return noms


def _est_plat(nom: str) -> bool:
    """Nom sans point, non stdlib, ET porte par le depot.

    Les trois conditions comptent. Un `sys.path` suivi d'un import TIERS vise
    peut-etre un vendor ou un site-packages : ce n'est pas la meme migration,
    et ca ne se decide pas ici.
    """
    if "." in nom:
        return False
    if nom in sys.stdlib_module_names:
        return False
    return nom in modules_depot()


def _sert_a(arbre: ast.AST, cible: str, ligne: int, motifs: tuple[str, ...]) -> str:
    """La cible (ou le module) est-elle utilisee par un des motifs, apres coup ?

    Rend le motif qui a repondu — la VOIE — ou "" si aucun.
    """
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        if getattr(noeud, "lineno", 0) <= ligne:
            continue
        nom = _nom_pointe(noeud.func) if isinstance(noeud.func, ast.Attribute) else _nom_appel(noeud)
        for motif in motifs:
            if motif in nom:
                return nom
    return ""


def _import_dynamique(arbre: ast.AST, ligne: int) -> str:
    """`importlib.import_module(x)` / `__import__(x)` avec x NON litteral.

    C'est la semantique que l'AST ne voit pas — celle qui interdit la
    transformation mecanique.
    """
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        if getattr(noeud, "lineno", 0) <= ligne:
            continue
        nom = _nom_pointe(noeud.func) if isinstance(noeud.func, ast.Attribute) else _nom_appel(noeud)
        if nom not in ("importlib.import_module", "import_module", "__import__"):
            continue
        if noeud.args and isinstance(noeud.args[0], ast.Constant):
            continue  # nom litteral : l'AST sait ce qui est charge
        return nom
    return ""


# ------------------------------------------------------------- classement


def classer_source(src: str, nom: str = "<memoire>") -> list[Site]:
    """Rend les sites `sys.path` d'une source, classes. Leve SyntaxError."""
    arbre = ast.parse(src, filename=nom)
    sites: list[Site] = []

    def _descendre(noeud: ast.AST, pile: list[ast.AST]) -> None:
        forme = _est_site(noeud)
        if forme:
            sites.append(_classer_site(noeud, forme, pile, arbre, nom))
        for enfant in ast.iter_child_nodes(noeud):
            _descendre(enfant, pile + [noeud])

    _descendre(arbre, [])
    return sites


def _classer_site(
    appel: ast.Call, forme: str, pile: list[ast.AST], arbre: ast.AST, nom: str
) -> Site:
    argument = appel.args[1] if forme == "insert" and len(appel.args) > 1 else (
        appel.args[0] if appel.args else None
    )
    cible = "UNKNOWN"
    if argument is not None:
        cible = _reduire_chemin(argument)
        if cible == "UNKNOWN":
            cible = _resoudre_attribut_parent(argument)

    ligne = appel.lineno
    portee = _portee(pile)
    conteneur = _conteneur(pile, arbre)
    imports = _imports_plats_apres(conteneur, ligne)

    # Les voies, dans l'ordre. La PREMIERE qui repond gagne, et elle est nommee.
    intention, voie = "UNKNOWN", ""
    if imports:
        intention, voie = "PATH_FOR_IMPORT", f"import plat suivant: {imports[0]}"
    elif (dyn := _import_dynamique(arbre, ligne)):
        intention, voie = "PATH_FOR_PLUGIN", f"import dynamique: {dyn}"
    elif (sub := _sert_a(arbre, cible, ligne, ("subprocess", "Popen", "check_output", "run"))):
        intention, voie = "PATH_FOR_SUBPROCESS", f"appel externe: {sub}"
    elif (dat := _sert_a(arbre, cible, ligne, ("open", "read_text", "read_bytes", "glob", "iterdir"))):
        intention, voie = "PATH_FOR_DATA", f"lecture de fichier: {dat}"

    cible_classe = _classer_cible(cible, pile)

    # Liste BLANCHE : n'est migrable que ce qui est PROUVE migrable — et la
    # cible doit etre INTERNE. Un chemin externe parfaitement resolu ferait
    # ecrire au codemod un `from nokido... import` pour un module qui n'y sera
    # jamais.
    migrable = (
        intention == "PATH_FOR_IMPORT" and cible_classe == "INTERNE" and bool(imports)
    )
    if migrable:
        motif = ""
    elif intention == "PATH_FOR_PLUGIN":
        motif = "SEMANTIQUE_DYNAMIQUE"  # l'AST ne peut pas savoir : irreductible
    elif cible_classe == "EXTERNE":
        motif = "CIBLE_HORS_DEPOT"  # pas une dette de namespace
    elif cible_classe == "MULTIPLE":
        motif = "CIBLE_MULTIPLE"  # plusieurs chemins par un seul site
    elif cible == "UNKNOWN":
        motif = "CIBLE_NON_REDUITE"  # limite de CE reducteur, pas du corps
    else:
        motif = "INTENTION_AMBIGUE"  # le chemin sert a autre chose qu'un import
    return Site(
        fichier=nom,
        ligne=ligne,
        forme=forme,
        portee=portee,
        cible=cible,
        cible_classe=cible_classe,
        intention=intention,
        voie=voie,
        imports_suivants=imports,
        verdict="MIGRABLE" if migrable else "A_INSTRUIRE",
        motif=motif,
    )


# --------------------------------------------------------------- rapports


def cartographier_textes(sources: dict[str, str]) -> dict:
    """Carte a partir de sources en memoire. Imprime son DENOMINATEUR.

    Un fichier qui ne parse pas n'a pas « zero sys.path » : il est ILLISIBLE.
    Trois etats, jamais deux.
    """
    sites: list[Site] = []
    illisibles: list[str] = []
    for nom, src in sources.items():
        try:
            sites.extend(classer_source(src, nom))
        except (SyntaxError, ValueError, RecursionError):
            illisibles.append(nom)

    par_intention: dict[str, int] = {i: 0 for i in INTENTIONS}
    par_portee: dict[str, int] = {p: 0 for p in PORTEES}
    par_verdict: dict[str, int] = {v: 0 for v in VERDICTS}
    par_motif: dict[str, int] = {}
    # VENTILATION A DEUX NIVEAUX (owner, 2026-09-10) : « separer definitivement
    # "le corps est ambigu" de "la cartographie ne sait pas encore resoudre" ».
    # Sans elle, `A_INSTRUIRE` melange deux dettes de nature differente.
    ventilation: dict[str, dict[str, int]] = {i: {} for i in INTENTIONS}
    for site in sites:
        par_intention[site.intention] += 1
        par_portee[site.portee] += 1
        par_verdict[site.verdict] += 1
        if site.motif:
            par_motif[site.motif] = par_motif.get(site.motif, 0) + 1
        seau = ventilation[site.intention]
        if site.intention == "UNKNOWN":
            cle = (
                "analyseur_insuffisant"
                if site.cible_classe in ("INCONNUE", "MULTIPLE")
                else "intention_reellement_ambigue"
            )
        else:
            cle = f"cible_{site.cible_classe.lower()}"
        seau[cle] = seau.get(cle, 0) + 1

    return {
        "fichiers_lus": len(sources),
        "illisibles": len(illisibles),
        "fichiers_illisibles": illisibles,
        "sites": len(sites),
        "par_intention": par_intention,
        "par_portee": par_portee,
        "par_verdict": par_verdict,
        "par_motif": par_motif,
        "ventilation": ventilation,
        "detail": [asdict(s) for s in sites],
    }


def _fichiers(racine: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    for zone in ZONES:
        base = racine / zone
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            # Meme correction que `modules_depot` : relatif a la zone.
            if any(part in IGNORES for part in chemin.relative_to(base).parts):
                continue
            try:
                sources[str(chemin.relative_to(racine)).replace("\\", "/")] = chemin.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                sources[str(chemin.relative_to(racine)).replace("\\", "/")] = "def (:"
    return sources


def cartographier_depot(racine: Path | None = None) -> dict:
    return cartographier_textes(_fichiers(racine or ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", metavar="FICHIER", help="ecrit le rapport complet")
    ap.add_argument("--verdict", choices=VERDICTS, help="ne lister que ces sites")
    ap.add_argument("--limite", type=int, default=25)
    args = ap.parse_args()

    rapport = cartographier_depot()
    print(
        f"[syspath] {rapport['sites']} site(s) sur {rapport['fichiers_lus']} fichier(s) lu(s), "
        f"{rapport['illisibles']} illisible(s)"
    )
    for cle in ("par_portee", "par_verdict", "par_motif"):
        detail = ", ".join(f"{k}={v}" for k, v in rapport[cle].items() if v)
        print(f"  {cle[4:]:<10} {detail}")

    print("\n  ventilation — l'ambiguite du CORPS n'est pas l'insuffisance de l'OUTIL :")
    for intention in INTENTIONS:
        seaux = rapport["ventilation"][intention]
        if not seaux:
            continue
        print(f"    {intention:<22} {sum(seaux.values())}")
        for cle, valeur in sorted(seaux.items()):
            print(f"        {cle:<32} {valeur}")

    if args.verdict:
        montres = [s for s in rapport["detail"] if s["verdict"] == args.verdict]
        print(f"\n  {len(montres)} site(s) {args.verdict} — {min(args.limite, len(montres))} montre(s) :")
        for site in montres[: args.limite]:
            print(f"    {site['fichier']}:{site['ligne']}  {site['portee']:<12} {site['cible']}")
            if site["voie"]:
                print(f"        voie: {site['voie']}")

    print(
        "\n  Ce rapport ne propose AUCUNE suppression : `MIGRABLE` dit que le codemod\n"
        "  saurait quoi ecrire, pas que le site est inutile."
    )
    if args.json:
        Path(args.json).write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(f"  -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
