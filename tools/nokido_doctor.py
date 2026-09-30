"""nokido_doctor.py — dit a l'utilisateur ce que Nokido a besoin de trouver sur sa machine.

Point d'entree `nokido-doctor`. Il ne repare rien, ne demarre rien, n'installe
rien : il REGARDE, et il nomme ce qu'il n'a pas pu voir.

Ce qu'il repond, et ce qu'il ne repond pas :

    INSTALLE   <- la seule question traitee ici
    DEMARRE    <- `nokido_ensure_service`
    CAPABLE    <- forge_organ_agents.probe()

Les confondre est le defaut le plus courant du diagnostic d'installation : un
`ollama.exe` present ne prouve aucun runner charge, et un port qui repond ne
prouve pas qu'un modele est en memoire.

Code de retour : 1 seulement si un prerequis REQUIS ou ESSENTIEL est ABSENT et
PROUVE absent. Un `ILLISIBLE` n'echoue pas — il s'affiche et il s'explique,
parce qu'un outil qui echoue sur ce qu'il n'a pas pu lire se fait desarmer.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

__FORGE_COLOR__ = "infra/bootstrap : diagnostic d'installation, presence des prerequis externes"

# Deux noms d'import pour un seul module, et il faut que les DEUX marchent :
# depuis le depot c'est `app.forge_install_prerequis`, depuis la wheel installee
# c'est `nokido_agent.app.forge_install_prerequis`. Un entrypoint qui ne connait
# que la premiere forme s'installe parfaitement et meurt au premier lancement —
# defaut deja paye (« reparer les entrypoints CLI morts a l'installation »).
# L'ordre compte : le paquet installe d'abord, le depot en repli.
try:
    from nokido_agent.app import forge_install_prerequis as P  # type: ignore
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import forge_install_prerequis as P  # noqa: E402

_MARQUE = {P.PRESENT: "[ok]", P.ABSENT: "[--]", P.ILLISIBLE: "[??]"}


def rendre_texte(b: dict, verbeux: bool = False) -> str:
    out: list[str] = []
    out.append("Nokido — diagnostic d'installation")
    out.append("  OS %s · compte %s · %d prerequis examines"
               % (b["os"], b["compte"], b["total"]))
    out.append("  %d presents · %d absents · %d illisibles"
               % (b["present"], b["absent"], b["illisible"]))
    if b["toml_services"] != P.PRESENT:
        out.append("  note : la declaration des services (%s) est %s — normal depuis"
                   % (b["toml_chemin"], b["toml_services"]))
        out.append("         une installation par paquet. La sonde ne voit alors que le")
        out.append("         PATH : un binaire installe ailleurs peut etre annonce absent.")
    out.append("")

    for niveau in (P.REQUIS, P.ESSENTIEL, P.OPTIONNEL):
        lignes = [l for l in b["lignes"] if l["niveau"] == niveau]
        if not lignes:
            continue
        out.append("%s" % niveau)
        for l in lignes:
            if l["etat"] == P.PRESENT and not verbeux:
                out.append("  %s %-20s %s" % (_MARQUE[l["etat"]], l["cle"], l["detail"]))
                continue
            out.append("  %s %-20s %s" % (_MARQUE[l["etat"]], l["cle"], l["detail"]))
            if l["etat"] != P.PRESENT:
                out.append("       sert a   : %s" % l["capacite"])
                out.append("       sans lui : %s" % l["absent_alors"])
                if l["install"]:
                    out.append("       installer: %s" % l["install"])
        out.append("")

    out.append("IMAGES DE CONTENEURS (declarees par les fichiers compose)")
    out.append("  Certaines capacites n'existent QUE sous forme d'image : SearXNG et")
    out.append("  crawl4ai n'ont aucun binaire equivalent, une sonde de PATH les")
    out.append("  declarerait absents a tort. Presence reelle : `docker images`.")
    for im in b["images"]:
        out.append("  %-9s %-32s %s" % ("[" + im["origine"] + "]", im["image"], im["capacite"]))
    out.append("")

    env = b["fichier_env"]
    out.append("CONFIGURATION")
    out.append("  %s %-20s (gabarit Nokido.env.example : %s)"
               % (_MARQUE.get(env["etat"], "[??]"), env["fichier"], env["gabarit"]))
    if env["etat"] == P.ABSENT and env["gabarit"] == P.PRESENT:
        out.append("       copier le gabarit : cp Nokido.env.example Nokido.env")
    out.append("")

    mods = b["modeles"]
    out.append("MODELES DE POIDS (jamais inclus dans un paquet — a telecharger)")
    for m in mods:
        out.append("  %s %-46s %s  (%s)"
                   % (_MARQUE[m["etat"]], m["cle"], m["detail"], m["usage"]))
    out.append("")

    if b["bloquants"]:
        out.append("BLOQUANT — absent et prouve absent : " + ", ".join(b["bloquants"]))
    else:
        out.append("Aucun prerequis critique prouve absent.")
    if b["indetermines_critiques"]:
        out.append("INDETERMINE — pas pu verifier (ce n'est PAS une absence) : "
                   + ", ".join(b["indetermines_critiques"]))
    out.append("")
    out.append("Rappel : ce rapport dit ce qui est INSTALLE. Pour savoir ce qui TOURNE, "
               "voir `nokido_ensure_service` ; pour ce qui est CAPABLE, forge_organ_agents.probe().")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="nokido-doctor",
        description="Verifie la presence des prerequis externes de Nokido.")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--requis-seulement", action="store_true",
                    help="ignore les prerequis optionnels")
    ap.add_argument("-v", "--verbeux", action="store_true",
                    help="detaille aussi les prerequis presents")
    a = ap.parse_args(argv)

    b = P.bilan(inclure_optionnels=not a.requis_seulement)
    if a.json:
        print(json.dumps(b, indent=2, ensure_ascii=False))
    else:
        print(rendre_texte(b, verbeux=a.verbeux))
    return 1 if b["bloquants"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
