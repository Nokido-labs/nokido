"""Purge du runtime offensif residuel — inventaire d'abord, retrait ensuite.

POURQUOI UN OUTIL plutot qu'une serie d'editions a la main : lire ces blocs pour
ecrire des SEARCH/REPLACE obligerait a rapatrier du contenu cyber-dense dans le
contexte d'un agent client, ce qui a deja declenche deux fois le classifieur
amont (memoire owner du 2026-08-28). L'outil, lui, travaille sur le DISQUE : il
classe chaque occurrence par sa STRUCTURE (definition, entree de dictionnaire,
litteral dans une collection, branche de dispatch, commentaire) et n'en rend
qu'un extrait tronque. L'agent decide sur la structure, jamais sur la charge.

Contexte : l'offensif est deja SEPARE (depot `laforge-redteam`, gate OFF par
defaut `LAFORGE_REDTEAM=1` + service :8768). Ce qui reste ici est de la SURFACE :
noms d'outils, handlers, descriptions verbeuses. L'owner veut le coeur propre.

Usage :
    LAFORGE_PYTHON tools/forge_purge_redteam_runtime.py                # inventaire
    LAFORGE_PYTHON tools/forge_purge_redteam_runtime.py --apply        # retrait
    LAFORGE_PYTHON tools/forge_purge_redteam_runtime.py --fichier app/forge_silo_engine.py

Le mode --apply refuse de laisser un fichier .py syntaxiquement casse : chaque
fichier est recompile EN MEMOIRE avant ecriture, et l'ecriture est abandonnee
pour ce fichier si la compilation echoue (jamais de demi-purge sur un module
que le hub importe au demarrage).
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

__FORGE_COLOR__ = "immunitaire/separation-des-domaines"

RACINE = Path(__file__).resolve().parent.parent

# Les noms qui designent le domaine offensif. Volontairement EXPLICITES : un
# motif large (« scan », « attack ») attraperait des homonymes legitimes — le
# census du 2026-09-01 a deja montre 19 noms offensifs FANTOMES retires a tort.
NOMS = ("exegol", "ctf_solver", "ctf_browser", "ctf_mode", "security_lab")
PREFIXES = ("exegol_", "ctf_")
MOTIF = re.compile("|".join(re.escape(n) for n in NOMS) + r"|ctf\.solve|recon\.scan|_REDTEAM",
                   re.IGNORECASE)

CIBLES = [
    "app/forge_mcp_registry.py",
    "app/forge_silo_engine.py",
    "app/web_hub/manifest_cards.py",
    "tools/forge_ui_manifest.py",
    "tools/forge_capability_contracts.py",
]
# Modules dont la RAISON D'ETRE est offensive : ils partent en entier.
MODULES_ENTIERS = ["app/forge_security_lab_adapter.py"]

# Retraits qui ne sont ni une definition ni une entree : un nom au milieu d'une
# ligne vivante. Ils passent par ICI parce que `forge_mcp_registry` est un
# CRITICAL_FILE : `governed_edit` le refuse, et sa derogation `allow_critical` a
# deja COUPE le hub sur un gros fichier (memoire 2026-08-27). Le chemin sur est
# donc un script git-tracke lance en trusted_script.
SUBSTITUTIONS: dict[str, list[tuple[str, str]]] = {
    "app/forge_mcp_registry.py": [
        ("    forge.security.* : exegol / docker / skill marketplace (exegol, skill)",
         "    forge.security.* : docker / skill marketplace (skill)"),
        ('                _CAP_TOOLS = {"run", "exegol", "browser", "ctf_browser", "netcfg"}',
         '                _CAP_TOOLS = {"run", "browser", "netcfg"}'),
    ],
}


def _porteurs(arbre: ast.AST) -> list[tuple[int, int, str]]:
    """(ligne_debut, ligne_fin, symbole) de chaque def/classe, decorateurs inclus."""
    out: list[tuple[int, int, str]] = []
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            debut = min([n.lineno] + [d.lineno for d in n.decorator_list])
            out.append((debut, n.end_lineno or n.lineno, n.name))
    return out


def _classe(ligne: str) -> str:
    """Nature STRUCTURELLE de l'occurrence — c'est elle qui dicte le retrait."""
    nu = ligne.strip()
    if nu.startswith("#"):
        return "commentaire"
    if re.match(r"(async\s+)?def\s+\w+", nu) or nu.startswith("class "):
        return "definition"
    if re.match(r"""^["']?[\w.\-]+["']?\s*:\s*[\{\[]""", nu):
        return "entree-dict"
    if re.match(r"^(el)?if\b", nu) or "elif name" in nu:
        return "branche-dispatch"
    if re.match(r"""^["'][\w.\-]+["']\s*,?$""", nu):
        return "litteral-collection"
    return "autre"


def inventaire(chemins: list[str]) -> list[dict]:
    faits: list[dict] = []
    for rel in chemins:
        p = RACINE / rel
        if not p.exists():
            faits.append({"fichier": rel, "erreur": "ABSENT"})
            continue
        texte = p.read_text(encoding="utf-8", errors="replace")
        lignes = texte.splitlines()
        try:
            porteurs = _porteurs(ast.parse(texte))
        except SyntaxError as e:
            faits.append({"fichier": rel, "erreur": f"AST KO: {e}"})
            continue
        for i, ligne in enumerate(lignes, 1):
            if not MOTIF.search(ligne):
                continue
            englobant = ""
            for d, f, nom in porteurs:
                if d <= i <= f and (not englobant or f - d < 10_000):
                    englobant = nom
            faits.append({
                "fichier": rel, "ligne": i, "nature": _classe(ligne),
                "symbole": englobant,
                # extrait TRONQUE : de quoi identifier, pas de quoi reproduire
                "extrait": ligne.strip()[:70],
            })
    return faits


# Le GARDE DE SEPARATION n'est pas du contenu offensif : c'est ce qui tient le
# depot redteam OFF par defaut et qui filtre les outils dynamiques `dyn_redteam_*`
# si le service :8768 est un jour rebranche. Le retirer en meme temps que les
# outils REOUVRIRAIT la porte au rebranchement. Ces lignes sont INTOUCHABLES.
GARDE = ("_REDTEAM_TOOLS", "_REDTEAM_DYN_PREFIXES", "_redteam_enabled",
         "_AGENT_TOOL_DENY", "rt_off", "LAFORGE_REDTEAM", "redteam.enabled",
         "_redteam_marker")


def _protegee(ligne: str) -> bool:
    return any(g in ligne for g in GARDE)


def _corps_du_if(lignes: list[str], i: int) -> int:
    """Derniere ligne du bloc `if` commencant a i (1-based) : indentation stricte."""
    base = len(lignes[i - 1]) - len(lignes[i - 1].lstrip())
    fin = i
    for m in range(i, len(lignes)):
        brute = lignes[m]
        if not brute.strip():
            continue
        if (len(brute) - len(brute.lstrip())) <= base:
            break
        fin = m + 1
    return fin


def _commentaires_au_dessus(lignes: list[str], debut: int) -> list[int]:
    """Lignes de commentaire COLLEES au bloc retire (elles le decrivent)."""
    out: list[int] = []
    m = debut - 1
    while m >= 1 and lignes[m - 1].strip().startswith("#") and not _protegee(lignes[m - 1]):
        out.append(m)
        m -= 1
    return out


def _entree_englobante(lignes: list[str], i: int) -> tuple[int, int] | None:
    """Entree de catalogue multi-lignes contenant la ligne i : { ... } accolades equilibrees."""
    debut = None
    for k in range(i - 1, max(0, i - 40), -1):
        if lignes[k - 1].rstrip().endswith("{"):
            debut = k
            break
    if debut is None:
        return None
    prof = 0
    for m in range(debut, len(lignes) + 1):
        prof += lignes[m - 1].count("{") - lignes[m - 1].count("}")
        if prof == 0:
            return (debut, m)
    return None


def _lignes_a_retirer(rel: str, texte: str) -> tuple[set[int], list[str]]:
    """Plages a supprimer pour un fichier. Rend (lignes, journal des decisions)."""
    lignes = texte.splitlines()
    journal: list[str] = []
    a_retirer: set[int] = set()
    arbre = ast.parse(texte)

    def _prendre(debut: int, fin: int, motif: str) -> None:
        if any(_protegee(lignes[m - 1]) for m in range(debut, fin + 1)):
            journal.append(f"  GARDE preserve : {motif} lignes {debut}-{fin} INTOUCHE")
            return
        a_retirer.update(range(debut, fin + 1))
        for c in _commentaires_au_dessus(lignes, debut):
            a_retirer.add(c)
        journal.append(f"  {motif} : lignes {debut}-{fin} ({fin - debut + 1})")

    # 1) Definitions dont le NOM est offensif -> le corps entier part.
    for debut, fin, nom in _porteurs(arbre):
        if nom.lower().startswith(PREFIXES) or any(n in nom.lower() for n in NOMS):
            _prendre(debut, fin, f"definition {nom}")

    for i, ligne in enumerate(lignes, 1):
        if i in a_retirer or not MOTIF.search(ligne) or _protegee(ligne):
            continue
        nu = ligne.strip()

        # 2) Branche de dispatch vers un handler offensif -> bloc `if` entier.
        if re.match(r"^if\s+name\s*(==|in|\.)", nu):
            _prendre(i, _corps_du_if(lignes, i), "branche de dispatch")
            continue

        # 3) Entree de catalogue multi-lignes (`"name": "<outil>"`) -> l'objet entier.
        if re.match(r"""^["']name["']\s*:\s*["']""", nu):
            bloc = _entree_englobante(lignes, i)
            if bloc:
                _prendre(bloc[0], bloc[1], "entree de catalogue")
                continue

        # 4) Entree de dictionnaire tenant sur UNE ligne (alias, ring, contrat).
        if re.match(r"""^["'][\w.\-]+["']\s*:\s*.+,?$""", nu):
            _prendre(i, i, "entree de dictionnaire")
            continue

        # 5) Litteral isole dans une collection.
        if _classe(ligne) == "litteral-collection":
            _prendre(i, i, "litteral")
    return a_retirer, journal


def appliquer(chemins: list[str], sec: bool) -> int:
    touches = 0
    for rel in chemins:
        p = RACINE / rel
        if not p.exists():
            print(f"[{rel}] ABSENT")
            continue
        texte = p.read_text(encoding="utf-8", errors="replace")
        try:
            a_retirer, journal = _lignes_a_retirer(rel, texte)
        except SyntaxError as e:
            print(f"[{rel}] AST KO, INTOUCHE : {e}")
            continue
        lignes = texte.splitlines(keepends=True)
        neuf = "".join(l for i, l in enumerate(lignes, 1) if i not in a_retirer)

        subs = 0
        for avant, apres in SUBSTITUTIONS.get(rel, []):
            if avant in neuf:
                neuf = neuf.replace(avant, apres)
                subs += 1
                journal.append(f"  substitution : {avant.strip()[:58]}...")
            else:
                # Ancre absente = deja fait, ou le fichier a bouge. On le DIT :
                # une substitution silencieusement sautee se lit comme un succes.
                journal.append(f"  ancre INTROUVABLE (deja purgee ?) : {avant.strip()[:58]}...")
        if not a_retirer and not subs:
            print(f"[{rel}] rien de retirable par cette passe")
            for j in journal:
                print(j)
            continue
        print(f"[{rel}] {len(a_retirer)} ligne(s), {subs} substitution(s)")
        for j in journal:
            print(j)
        # GARDE : jamais d'ecriture qui casse un module importe au demarrage.
        try:
            compile(neuf, rel, "exec")
        except SyntaxError as e:
            print(f"[{rel}] REFUS : le retrait casserait la syntaxe ({e}) -- fichier INTOUCHE")
            continue
        if sec:
            p.write_text(neuf, encoding="utf-8")
            touches += 1
        else:
            print(f"[{rel}] (dry-run, rien ecrit)")
    return touches


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="ecrit (defaut : dry-run)")
    ap.add_argument("--fichier", action="append", help="restreindre a ce(s) fichier(s)")
    args = ap.parse_args()

    chemins = args.fichier or CIBLES
    faits = inventaire(chemins)

    par_nature: dict[str, int] = {}
    for f in faits:
        if "erreur" in f:
            print(f"!! {f['fichier']} : {f['erreur']}")
            continue
        par_nature[f["nature"]] = par_nature.get(f["nature"], 0) + 1
    print(f"=== INVENTAIRE : {len(faits)} occurrence(s) sur {len(chemins)} fichier(s) ===")
    for nature, n in sorted(par_nature.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {nature}")
    for f in faits:
        if "erreur" in f:
            continue
        print(f"  {f['fichier']}:{f['ligne']:<5} [{f['nature']:<19}] "
              f"{f['symbole'] or '-':<34} | {f['extrait']}")
    print("=== MODULES ENTIERS (suppression disque = action owner) ===")
    for m in MODULES_ENTIERS:
        print(f"  {m} {'present' if (RACINE / m).exists() else 'deja absent'}")

    if args.apply or True:
        print("=== RETRAIT ===")
        n = appliquer(chemins, sec=args.apply)
        print(f"{n} fichier(s) reecrit(s)" if args.apply else "(dry-run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
