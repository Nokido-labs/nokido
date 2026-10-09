"""
app/forge_dep_manager.py — Dependency auto-management pour code généré
extract imports → check missing → pip install → verify
"""

import ast, importlib.util, subprocess, sys
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

_STDLIB = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
_STDLIB.update(sys.builtin_module_names)


def extract_imports(file_path: str) -> list[str]:
    src = Path(file_path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return [i for i in imports if i and i not in _STDLIB and not i.startswith("_")]


def check_missing(imports: list[str]) -> list[str]:
    missing = []
    for pkg in tqdm(imports, desc="checking imports", unit="pkg"):
        if importlib.util.find_spec(pkg) is None:
            missing.append(pkg)
    return missing


# ── ALLOWLIST DERIVEE DES DECLARATIONS DU DEPOT (audit securite 2026-09-18, #11) ──
#
# Le defaut mesure : `forge_mcp_registry` (L5678-5684) extrait les blocs ```python
# du TEXTE DE RESULTAT d'une tache, les ecrit dans un fichier temporaire, puis
# appelle `manage(..., dry_run=False)`. Les noms arrivaient ici tels quels et
# partaient en `pip install` avec `sys.executable` — c'est-a-dire l'interpreteur
# DU HUB. Aucune allowlist, aucune confirmation.
#
# Ce que cela vaut : un nom absent du disque est cherche sur PyPI, et un paquet
# execute du code A L'INSTALLATION. Un producteur de resultat de tache choisissait
# donc ce qui s'execute dans l'environnement du hub, en ecrivant `import <nom>`.
# La chaine se referme avec le finding #6 du meme audit : du contenu web hostile
# atteignait le prompt systeme d'un agent, et cet agent produit des blocs de code.
#
# POURQUOI LE GARDE EST ICI et pas au site d'appel : `forge_dep_manager` est cite
# par quatre modules (`forge_mcp_registry`, `forge_dep_manager_auto`,
# `forge_handler_build`, et son propre `__main__`). Un garde pose sur un seul
# appelant laisse les trois autres ouverts, et se relit comme une protection
# generale. L'organe qui INSTALLE est celui qui doit refuser.
#
# POURQUOI UNE ALLOWLIST DERIVEE et pas une liste ecrite a la main : une liste
# figee se perime en silence. Le depot DECLARE deja ses dependances ; le seul cas
# legitime de cette fonction est de restaurer une dependance declaree mais absente
# de l'environnement — jamais d'en AJOUTER une que personne n'a decidee.
_FICHIERS_DECLARATION = ("requirements.txt", "requirements-ml.txt", "requirements-organisme.txt", "pyproject.toml")

# Un nom d'import n'est pas un nom de distribution. Ces alias couvrent les ecarts
# courants ; ils ne servent qu'a EVITER UN REFUS INJUSTE, jamais a elargir.
_ALIAS_IMPORT_VERS_DISTRIBUTION = {
    "yaml": "pyyaml", "cv2": "opencv-python", "pil": "pillow", "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "serial": "pyserial", "usb": "pyusb", "win32api": "pywin32", "win32com": "pywin32",
    "fitz": "pymupdf", "psycopg2": "psycopg2-binary", "attr": "attrs", "jwt": "pyjwt",
    "google": "google-api-python-client", "OpenSSL": "pyopenssl", "magic": "python-magic",
}


def _normaliser(nom: str) -> str:
    """Nom de distribution canonique (PEP 503) : casse et separateurs unifies."""
    return "".join("-" if c in "-_." else c for c in (nom or "").strip().lower())


def _racine_depot() -> Path:
    return Path(__file__).resolve().parent.parent


def paquets_declares() -> tuple[set[str], list[str]]:
    """Ce que le depot declare, et ce qu'on n'a PAS pu lire.

    Rend `(noms_normalises, illisibles)`. La seconde valeur n'est pas decorative :
    un fichier de declaration illisible doit produire un REFUS explicite, jamais un
    silence qui se lirait comme « rien n'est declare » (UNKNOWN != NO).
    """
    racine = _racine_depot()
    declares: set[str] = set()
    illisibles: list[str] = []
    for nom_fichier in _FICHIERS_DECLARATION:
        chemin = racine / nom_fichier
        if not chemin.exists():
            continue
        try:
            if nom_fichier.endswith(".toml"):
                specs = _specs_du_pyproject(chemin)
            else:
                specs = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError) as e:
            illisibles.append(f"{nom_fichier} ({type(e).__name__})")
            continue
        for spec in specs:
            nom = _nom_de_spec(spec)
            if nom:
                declares.add(nom)
    return declares, illisibles


def _specs_du_pyproject(chemin: Path) -> list[str]:
    """Les specs de dependance d'un pyproject, et RIEN d'autre.

    Mesure du 2026-09-18 : lire ce fichier LIGNE A LIGNE faisait entrer 31 clefs
    TOML dans l'allowlist — `addopts`, `name`, `version`, `dev`, `all`, mais aussi
    `jax`, `mcp`, `h11`, `git`, `rag`, qui sont des noms REELS sur PyPI. Une
    allowlist polluee par la syntaxe du fichier qu'elle lit autorise ce que
    personne n'a declare : c'est le contraire de son objet.
    """
    import tomllib

    data = tomllib.loads(chemin.read_text(encoding="utf-8"))
    specs: list[str] = []
    projet = data.get("project") or {}
    specs.extend(projet.get("dependencies") or [])
    for groupe in (projet.get("optional-dependencies") or {}).values():
        specs.extend(groupe or [])
    for groupe in (data.get("dependency-groups") or {}).values():
        specs.extend(x for x in (groupe or []) if isinstance(x, str))
    build = data.get("build-system") or {}
    specs.extend(build.get("requires") or [])
    return [s for s in specs if isinstance(s, str)]


def _nom_de_spec(spec: str) -> str:
    """Nom normalise d'une spec de requirement, ou chaine vide si ce n'en est pas une."""
    spec = (spec or "").split("#", 1)[0].strip()
    if not spec or spec.startswith("-"):
        return ""
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", ";", " ", "@"):
        if sep in spec:
            spec = spec.split(sep, 1)[0]
    spec = spec.strip().strip('"\',')
    # un nom de distribution ne contient que [A-Za-z0-9._-] (PEP 508)
    if not spec or not all(c.isalnum() or c in "-_." for c in spec):
        return ""
    return _normaliser(spec)


def filtrer_autorises(packages: list[str]) -> tuple[list[str], dict[str, str]]:
    """Separe ce qui est declare par le depot de ce qui ne l'est pas.

    Rend `(autorises, refuses)` ou `refuses` associe chaque nom a son MOTIF. Le
    motif compte autant que le refus : un refus muet se lit comme une absence de
    besoin, et personne ne vient le corriger.
    """
    declares, illisibles = paquets_declares()
    autorises: list[str] = []
    refuses: dict[str, str] = {}
    for pkg in packages:
        canon = _normaliser(_ALIAS_IMPORT_VERS_DISTRIBUTION.get(pkg, pkg))
        if canon in declares or _normaliser(pkg) in declares:
            autorises.append(pkg)
        elif illisibles:
            refuses[pkg] = (
                "REFUS PAR PRUDENCE : declaration du depot partiellement illisible "
                f"({', '.join(illisibles)}) — on ne sait pas si ce paquet est declare"
            )
        else:
            refuses[pkg] = (
                "NON DECLARE PAR LE DEPOT : aucun de "
                f"{', '.join(_FICHIERS_DECLARATION)} ne le nomme. Installer ici "
                "reviendrait a laisser le texte d'un resultat de tache choisir ce "
                "qui s'execute dans l'environnement du hub. Pour l'autoriser, "
                "l'AJOUTER A LA DECLARATION du depot — c'est une decision, pas un effet de bord."
            )
    return autorises, refuses


def install_missing(packages: list[str], dry_run: bool = False) -> dict[str, bool]:
    autorises, refuses = filtrer_autorises(packages)
    results: dict[str, bool] = {}
    for pkg, motif in refuses.items():
        # Le refus est BRUYANT par construction : c'est la seule trace qu'un
        # appelant legitime aura pour faire declarer sa dependance.
        print(f"  [REFUSE] {pkg}: {motif}", file=sys.stderr)
        results[pkg] = False
    if refuses:
        print(
            f"  [dep_manager] {len(autorises)} autorise(s) sur {len(packages)} demande(s) ; "
            f"{len(refuses)} refuse(s) : {', '.join(sorted(refuses))}",
            file=sys.stderr,
        )
    for pkg in tqdm(autorises, desc="installing", unit="pkg"):
        if dry_run:
            print(f"  [DRY] pip install {pkg}")
            results[pkg] = True
            continue
        r = subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"], capture_output=True, text=True, errors="replace")
        results[pkg] = r.returncode == 0
        if not results[pkg]:
            print(f"  [FAIL] {pkg}: {r.stderr[:200]}", file=sys.stderr)
    return results


def verify_after_install(packages: list[str]) -> bool:
    for pkg in tqdm(packages, desc="verifying", unit="pkg"):
        if importlib.util.find_spec(pkg) is None:
            print(f"  [MISSING] {pkg} still not found", file=sys.stderr)
            return False
    return True


def manage(file_path: str, dry_run: bool = False) -> dict:
    imports = extract_imports(file_path)
    missing = check_missing(imports)
    if not missing:
        return {"success": True, "installed": {}, "missing_before": []}
    install_results = install_missing(missing, dry_run)
    _, refuses = filtrer_autorises(missing)
    verified = dry_run or verify_after_install([p for p, ok in install_results.items() if ok])
    return {
        "success": verified,
        "installed": install_results,
        "missing_before": missing,
        # Le refus remonte A L'APPELANT, pas seulement sur stderr : un appelant qui
        # ne voit que `success` ne saurait pas distinguer « rien a faire » de
        # « la moitie a ete refusee ».
        "refuses": refuses,
    }


if __name__ == "__main__":
    import json

    for f in sys.argv[1:]:
        result = manage(f)
        print(json.dumps(result, indent=2))
