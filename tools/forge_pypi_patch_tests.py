#!/usr/bin/env python3
"""forge_pypi_patch_tests.py — rendre leur PRISE aux tests qui simulent une panne.

DEFAUT MESURE le 2026-09-10, apres la migration des imports :

    monkeypatch.setitem(sys.modules, "forge_npsc", None)   # import -> ImportError

Le code teste importe desormais `nokido_agent.tools.forge_npsc` — une entree
DIFFERENTE de `sys.modules`. Le patch n'a plus de prise : le test croit simuler
une panne, execute le chemin REEL, et passe pour la mauvaise raison. C'est un
FAUX VERT, la seule chose pire qu'un rouge.

Mesure : 63 NR touchent `sys.modules`, 42 visent un nom plat du depot. Cas
prouve : `test_le_handler_ne_leve_jamais` executait un vrai scan de 33 s et
rendait `npsc: 'OK'` la ou il devait constater une panne.

CE QUE FAIT CET OUTIL, ET RIEN D'AUTRE. Il AJOUTE une ligne jumelle visant le nom
namespace, juste apres la ligne existante. Il ne REMPLACE jamais le nom plat :
  - un patch qui garde les deux formes reste valide quel que soit le chemin ;
  - on ne retire rien a un garde existant (« on ne supprime pas l'ancien garde ;
    on corrige son domaine de validite ») ;
  - la transformation est idempotente : un nom deja namespace n'a pas de jumeau.

LA CARTE EST PARTAGEE avec le codemod (`forge_pypi_codemod.carte_modules`) : deux
cartes qui divergeraient donneraient deux verites sur la zone d'un module, et un
patch pose sur la mauvaise. Un NR verifie l'egalite.

DRY-RUN PAR DEFAUT. `--appliquer` est explicite.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "qualite/build : reaccord des simulations de panne apres migration"

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import forge_pypi_codemod as cm  # noqa: E402

NR = ROOT / "tests" / "nr"
NAMESPACE = cm.NAMESPACE
SORTIE = ROOT / "sandbox" / "chantier_pypi" / "patch_tests.json"

# UN INSTRUMENT NE LIT JAMAIS SON PROPRE VOCABULAIRE (regle du corps, 5 fois
# payee en trois jours). Le NR de cet outil porte des FIXTURES — des chaines
# `"from forge_x import y"` fabriquees pour eprouver la transformation. Les
# reecrire ne corrige aucun cablage : ca detruit le banc d'essai, et le banc
# valide alors la transformation... sur son propre resultat.
AUTO_EXCLUS = frozenset({"test_pypi_patch_tests_nr.py"})

# `sys.modules` cite avec un nom entre guillemets, sur la meme ligne. On reste
# volontairement sur UNE ligne : un patch etale sur plusieurs lignes est rare et
# sera compte en refus plutot que devine.
_MOTIF = re.compile(r"""sys\.modules[^\n]{0,40}?["']([A-Za-z0-9_.]+)["']""")


def carte() -> dict[str, str]:
    """module -> zone. Source unique, partagee avec le codemod."""
    return cm.carte_modules()


def jumeau(nom: str, carte_modules: dict[str, str]) -> str | None:
    """Nom namespace correspondant, ou None si le patch n'a pas a etre double."""
    if "." in nom:                      # deja qualifie : idempotence
        return None
    zone = carte_modules.get(nom)
    if zone is None:                    # hors depot : l'inconnu ne bouge pas
        return None
    return f"{NAMESPACE}.{zone}.{nom}"


# Un motif de CABLAGE dans une assertion : `"from forge_x import ..."`.
# Ces gardes verifient qu'un module DELEGUE au lieu de dupliquer, en cherchant la
# FORME de l'import. La migration l'a changee : le cablage existe toujours, le
# garde ne le reconnait plus (15 tests mesures le 2026-09-10).
# Les symboles sont OPTIONNELS : `"from forge_x import"` (sans suite) est une
# forme reelle, mesuree le 2026-09-10 dans `test_espace_vectoriel_preuve_nr`.
# Ne matcher que `import <symboles>` laissait passer ces gardes.
_MOTIF_IMPORT = re.compile(r'"from ([a-z0-9_]+) import ?([^"]*)"')


# Formes d'assertion que ce codemod sait transformer, et RIEN d'autre. Regle
# owner du 2026-09-10 : « assert CONDITION », « assert CONDITION, message »,
# « assert "X" in src » et « assert {"a","b"} <= imports » sont semantiquement
# differentes. Un transformateur correct sur le corps peut etre FAUX sur la
# semantique particuliere des tests : il doit savoir exactement transformer, ou
# le DIRE.
NON_TRANSFORMES: list[str] = []


def viser_la_cible(source: str, carte_modules: dict[str, str]) -> tuple[str, list[str]]:
    """REMPLACE la forme plate par la forme namespace dans l'oracle.

    On ne conserve PAS l'ancienne forme. Un oracle

        assert "from forge_x import y" in src or "from nokido_agent...x import y" in src

    passerait quelle que soit la forme : il ne protegerait plus rien. Le code ne
    porte plus qu'une forme apres migration ; l'oracle doit viser CELLE-LA, et
    rougir si le code revenait au chemin plat — c'est son role.

        assert "from forge_ports import probe" in src
        ->
        assert "from nokido_agent.tools.forge_ports import probe" in src

    Une disjonction heritee de la version precedente est RESSERREE sur la cible.
    """
    faits: list[str] = []
    sortie: list[str] = []
    lignes = source.splitlines(keepends=True)
    for index, ligne in enumerate(lignes):
        trouve = _MOTIF_IMPORT.search(ligne)
        if trouve is None or "assert" not in ligne:
            sortie.append(ligne)
            continue
        module, symboles = trouve.group(1), trouve.group(2)
        zone = carte_modules.get(module)
        if zone is None:                          # hors depot : on ne touche pas
            sortie.append(ligne)
            continue
        suffixe = f" {symboles}" if symboles else ""
        ancien = f'"from {module} import{suffixe}"'
        nouveau = f'"from {NAMESPACE}.{zone}.{module} import{suffixe}"'
        corps = ligne.strip()
        if not corps.startswith("assert "):
            sortie.append(ligne)
            continue
        reste = corps[len("assert "):].rstrip()

        # SEPARER LE MESSAGE DE LA CONDITION. `assert X, "msg"` enveloppe
        # naivement donne `assert (X, "msg" or Y)` — un TUPLE, donc TOUJOURS VRAI.
        # C'est exactement le faux vert que ce chantier combat, produit par
        # l'outil cense le reparer (revele par un SyntaxWarning, 2026-09-10).
        # ⚠️ La virgule d'un import multi-symboles vit DANS la chaine :
        #     assert "from forge_motivation import punish, reward" in bloc, (
        # Un balayage qui ignore les litteraux coupe apres `punish`, produit
        # `assert "from ...import punish` — non compilable — et l'oracle sort
        # en NON_TRANSFORME alors que la forme est parfaitement connue.
        # Mesure 2026-09-10 : 1 oracle perdu sur ce seul defaut.
        condition, message = reste, ""
        profondeur = 0
        quote = ""
        for pos, car in enumerate(reste):
            if quote:
                if car == quote and reste[pos - 1: pos] != "\\":
                    quote = ""
                continue
            if car in "\"'":
                quote = car
            elif car in "([{":
                profondeur += 1
            elif car in ")]}":
                profondeur -= 1
            elif car == "," and profondeur == 0:
                condition, message = reste[:pos], reste[pos:]
                break

        # On VISE : substitution pure, puis on resserre une eventuelle
        # disjonction heritee (`A or B` -> `B`).
        cible = condition.strip().replace(ancien, nouveau)
        if " or " in cible:
            morceaux = [m.strip() for m in cible.split(" or ")]
            gardes = [m for m in morceaux if NAMESPACE in m]
            if gardes:
                cible = gardes[0].strip("()")
        indentation = ligne[: len(ligne) - len(ligne.lstrip())]
        candidat = f"{indentation}assert {cible}{message}\n"

        # Ceinture : un `assert` devenu tuple est une regression silencieuse.
        #
        # On valide la CONDITION SEULE, jamais la ligne entiere. Forme reelle,
        # mesuree sur 3 NR le 2026-09-10 :
        #
        #     assert "from forge_x import" in CODE, (
        #         "message sur les lignes suivantes")
        #
        # La ligne entiere ne compile pas — la parenthese du MESSAGE reste
        # ouverte — alors que la transformation ne touche que la condition. Les
        # refuser aurait laisse ces oracles sur l'ancien cablage en le DISANT,
        # ce qui vaut mieux qu'un faux vert, mais moins que la corriger.
        # Le message est recopie VERBATIM ; la source complete est recompilee
        # par `main` avant toute ecriture, donc rien de non-parsable ne sort.
        import warnings as _w
        with _w.catch_warnings():
            _w.simplefilter("error", SyntaxWarning)
            try:
                compile(f"assert {cible}", "<visee>", "exec")
            except (SyntaxError, SyntaxWarning):
                # NON_TRANSFORME : on ne devine pas, on le DIT.
                NON_TRANSFORMES.append(f"{module} (forme non reecrivable)")
                sortie.append(ligne)
                continue
        if candidat == ligne:            # rien n'a change : deja cible
            sortie.append(ligne)
            continue
        sortie.append(candidat)
        faits.append(f"{module} -> {NAMESPACE}.{zone}.{module}")
    return "".join(sortie), faits


def fichiers_candidats() -> list[Path]:
    """NR touchant `sys.modules`. Denominateur du traitement."""
    return sorted(p for p in NR.glob("*.py")
                  if "sys.modules" in p.read_text(encoding="utf-8", errors="replace"))


def _fin_instruction(lignes: list[str], debut: int) -> int:
    """Index de la DERNIERE ligne de l'instruction commencee a `debut`.

    Un patch peut s'etaler sur plusieurs lignes :

        monkeypatch.setitem(sys.modules, "forge_watch_agent",
                            _faux_watch_agent(_muet, _muet))

    Inserer la jumelle apres la PREMIERE ligne couperait l'expression en deux.
    La v1 refusait ces cas (4 fichiers), et l'un d'eux — `test_veille_non_mesuree_nr`
    — laissait passer une VRAIE requete reseau : 601 s de timeout dans la CI.
    On suit donc l'equilibre des parentheses.
    """
    ouvertes = 0
    for i in range(debut, len(lignes)):
        ouvertes += lignes[i].count("(") - lignes[i].count(")")
        if ouvertes <= 0:
            return i
    return debut


def traiter_source(src: str, carte_modules: dict[str, str]) -> tuple[str, list[str]]:
    """Rend (source, jumeaux ajoutes). Insere la jumelle apres l'instruction."""
    ajoutes: list[str] = []
    lignes = src.splitlines(keepends=True)
    sortie: list[str] = []
    i = 0
    while i < len(lignes):
        ligne = lignes[i]
        sortie.append(ligne)
        noms = _MOTIF.findall(ligne) if "sys.modules" in ligne else []
        if not noms:
            i += 1
            continue
        nom = noms[0]
        cible = jumeau(nom, carte_modules)
        if cible is None or cible in src:
            i += 1
            continue
        fin = _fin_instruction(lignes, i)
        bloc = "".join(lignes[i:fin + 1])
        jumelle = bloc.replace(f'"{nom}"', f'"{cible}"').replace(f"'{nom}'", f"'{cible}'")
        if jumelle == bloc:              # substitution impossible : on ne devine pas
            i += 1
            continue
        # Recopie les lignes de continuation avant d'ajouter la jumelle.
        sortie.extend(lignes[i + 1:fin + 1])
        if not jumelle.endswith("\n"):
            jumelle += "\n"
        sortie.append(jumelle)
        ajoutes.append(f"{nom} -> {cible}")
        i = fin + 1
    return "".join(sortie), ajoutes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--appliquer", action="store_true", help="ECRIT (defaut : dry-run)")
    ap.add_argument("--motifs", action="store_true",
                    help="VISE la forme namespace dans les oracles de cablage "
                         "(remplace la forme plate ; ne conserve pas les deux)")
    ap.add_argument("--json", default=str(SORTIE))
    args = ap.parse_args()

    carte_modules = carte()
    if not carte_modules:
        print("[patch-tests] NON_CERTIFIANT — carte des modules VIDE")
        return 2
    candidats = fichiers_candidats()
    if not candidats:
        print("[patch-tests] NON_CERTIFIANT — aucun NR candidat : denominateur vide")
        return 2

    rapport = {"candidats": len(candidats), "fichiers_modifies": 0,
               "jumeaux_ajoutes": 0, "illisibles": [], "detail": [],
               "auto_exclus": sorted(AUTO_EXCLUS), "non_transformes": []}
    cibles = [p for p in (sorted(NR.glob("*.py")) if args.motifs else candidats)
              if p.name not in AUTO_EXCLUS]
    for chemin in cibles:
        src = chemin.read_text(encoding="utf-8", errors="replace")
        if args.motifs:
            nouveau, ajoutes = viser_la_cible(src, carte_modules)
        else:
            nouveau, ajoutes = traiter_source(src, carte_modules)
        if not ajoutes:
            continue
        try:
            compile(nouveau, str(chemin), "exec")   # jamais ecrire du non-parsable
        except SyntaxError as exc:
            rapport["illisibles"].append(f"{chemin.name} ({exc})")
            continue
        rapport["fichiers_modifies"] += 1
        rapport["jumeaux_ajoutes"] += len(ajoutes)
        rapport["detail"].append({"fichier": chemin.name, "ajouts": ajoutes[:6]})
        if args.appliquer:
            chemin.write_text(nouveau, encoding="utf-8")

    # UN REFUS MUET NE SE DISTINGUE PAS D'UN SUCCES. `NON_TRANSFORMES` etait
    # rempli et jamais lu : une forme que l'outil ne sait pas reecrire sortait
    # comme un fichier « rien a faire ».
    rapport["non_transformes"] = sorted(set(NON_TRANSFORMES))

    mode = "APPLIQUE" if args.appliquer else "dry-run"
    print(f"[patch-tests] {mode} — {rapport['candidats']} NR candidat(s), "
          f"{len(cibles)} balaye(s), {len(AUTO_EXCLUS)} auto-exclu(s), "
          f"{rapport['fichiers_modifies']} a modifier, "
          f"{rapport['jumeaux_ajoutes']} jumeau(x), "
          f"{len(rapport['illisibles'])} illisible(s), "
          f"{len(rapport['non_transformes'])} NON_TRANSFORME(s)")
    for d in rapport["detail"][:10]:
        print(f"    {d['fichier']} : {', '.join(d['ajouts'][:2])}")
    for nt in rapport["non_transformes"][:10]:
        print(f"    NON_TRANSFORME : {nt}")
    cible = Path(args.json)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
    print(f"  -> {cible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
