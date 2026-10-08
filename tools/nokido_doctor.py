"""nokido_doctor.py — dit a l'utilisateur ce que Nokido a besoin de trouver sur sa machine.

Point d'entree `nokido-doctor`. Il ne repare rien, ne demarre rien, n'installe
rien : il REGARDE, et il nomme ce qu'il n'a pas pu voir.

Ce qu'il repond, et ce qu'il ne repond pas :

    INSTALLE   <- la question par defaut
    VIVANT     <- `--vivant` : ce qui BAT, organe par organe (forge_nervous_map.autorites)
    DEMARRE    <- `nokido_ensure_service`
    CAPABLE    <- forge_organ_agents.probe()

`--vivant` (owner 2026-10-01 : « tu ne mesures pas un etat fige mais un corps
vivant ») : le README ne porte plus d'instantane -- il designe cette commande, qui
demande l'etat au corps SUR LA MACHINE DU LECTEUR. Quatre etats, jamais deux (vivant,
incertain, ne bat plus, illisible), et un organe coupe par politique n'est jamais dit
mort. Elle ne demarre rien, et une observation n'echoue pas : rc 2 seulement quand la
source elle-meme est illisible.

Les confondre est le defaut le plus courant du diagnostic d'installation : un
`ollama.exe` present ne prouve aucun runner charge, et un port qui repond ne
prouve pas qu'un modele est en memoire.

Code de retour : 1 seulement si un prerequis EXIGE PAR LE PROFIL est ABSENT et
PROUVE absent. Un `ILLISIBLE` n'echoue pas — il s'affiche et il s'explique,
parce qu'un outil qui echoue sur ce qu'il n'a pas pu lire se fait desarmer.

Profils (decision owner du 2026-10-07) : `dev` (defaut, l'offre « hub d'agents pour
devs » : Python, Git, Deno, llama-server et le modele bge-m3) ; `complet` (l'organisme
du poste de reference : REQUIS + services `essential` du TOML, dont Ollama et netcfg).
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
        if im.get("obtenir"):
            out.append("            obtenir : %s" % im["obtenir"])
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
        if m["etat"] != P.PRESENT and m.get("telecharger"):
            out.append("       telecharger : %s" % m["telecharger"])
    out.append("")

    out.append("PROFIL %s (--profil complet pour l'organisme du poste de reference)" % b.get("profil", "?"))
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


def _autorites() -> dict:
    """forge_nervous_map.autorites(), sous ses deux noms d'import (wheel puis depot)."""
    try:
        from nokido_agent.app import forge_nervous_map as N  # type: ignore
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import forge_nervous_map as N  # noqa: E402
    return N.autorites()


# (cle, libelle) dans l'ordre d'affichage. COUPE n'est pas un etat du pouls : c'est
# une POLITIQUE (disabled=true), donc lue sur le superviseur, jamais deduite du pouls.
_GROUPES_VIVANT = (
    ("OUI", "VIVANT (pouls frais, porteur present)"),
    ("INCERTAIN", "INCERTAIN (pouls frais, porteur non attribuable)"),
    ("NON", "NE BAT PLUS (pouls perime ou orphelin)"),
    ("COUPE", "COUPE PAR POLITIQUE (disabled : un choix, pas une panne)"),
    ("INCONNU", "ILLISIBLE (aucun pouls lisible)"),
)


def _coupe_par_politique(fiche: dict) -> bool:
    sup = fiche.get("supervisor")
    sup = sup.get("valeur") if isinstance(sup, dict) else sup
    return bool(fiche.get("eteint_par_decision") or "eteint par decision" in str(sup or ""))


def _groupe(fiche: dict) -> str:
    vivant = fiche.get("producteur_vivant") or "INCONNU"
    # Un pouls frais PRIME sur la politique : `disabled` veut dire « pas demarre
    # d'office », et un organe a la demande reveille bat bel et bien (mesure
    # 2026-10-01 : NokidoIngestDaemon). La politique ne range que ce qui ne bat pas.
    if vivant in ("OUI", "INCERTAIN"):
        return vivant
    return "COUPE" if _coupe_par_politique(fiche) else vivant


def rendre_vivant(a: dict) -> str:
    """L'etat vivant des organes, groupe par etat ; les sources illisibles sont DITES."""
    out = ["Nokido — ce qui bat sur cette machine, organe par organe", ""]
    for nom, etat in (a.get("sources") or {}).items():
        out.append("  source %-18s %s" % (nom, etat))
    groupes: dict = {}
    for f in a.get("organes") or []:
        groupes.setdefault(_groupe(f), []).append(f)
    for cle, libelle in _GROUPES_VIVANT:
        fiches = sorted(groupes.get(cle, []), key=lambda f: str(f.get("organe")))
        out += ["", "%s — %d" % (libelle, len(fiches))]
        for f in fiches:
            age = f.get("age_s")
            demande = cle in ("OUI", "INCERTAIN") and _coupe_par_politique(f)
            out.append("  %-32s %-28s %s%s%s" % (
                f.get("organe"), f.get("service") or "(hors registre)",
                f.get("producteur_preuve") or "",
                "" if age is None else "  [pouls il y a %d s]" % int(age),
                "  (a la demande)" if demande else ""))
    out += ["", "Instantane de CETTE machine, a cet instant : relancer pour mesurer de nouveau."]
    return "\n".join(out)


def _capacites_hote():
    """`forge_host_capabilities`, sous ses deux noms d'import (wheel installee d'abord, depot en repli)."""
    try:
        from nokido_agent.app import forge_host_capabilities as H  # type: ignore
    except ImportError:
        from app import forge_host_capabilities as H  # noqa: E402
    return H


def rendre_modeles(s: dict) -> str:
    out = ["MODELES SUGGERES pour cette machine (memoire d'inference : %.1f Go)" % s["memoire_inference_go"],
           "  Verifies sur Hugging Face, le registre Ollama et LM Studio ; licence Apache-2.0.", ""]
    if s["trop_petite"]:
        out.append("  Aucun modele du catalogue ne tient : il faut au moins %.1f Go de memoire d'inference."
                   % s["minimum_go"])
    for role, titre in (("code", "Pour le code"), ("chat", "Pour la conversation")):
        if not s["suggestions"].get(role):
            continue
        out.append(titre)
        for m in s["suggestions"][role]:
            out.append("  %s  (%.1f Go, %s)" % (m["nom"], m["taille_go"], m["licence"]))
            out.append("     llama.cpp : %s" % m["gguf"])
            out.append("                 sha256 %s" % m["sha256"])
            out.append("     Ollama    : ollama pull %s" % m["ollama"])
            out.append("     LM Studio : lms get %s" % m["lmstudio"])
        out.append("")
    out.append("Les embeddings (bge-m3) et le reranker sont epingles a part : ils sont exiges par le RAG,"
               " voir MODELES DE POIDS dans `nokido-doctor`.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="nokido-doctor",
        description="Verifie la presence des prerequis externes de Nokido "
                    "(--vivant : ce qui bat, organe par organe).")
    ap.add_argument("--vivant", action="store_true",
                    help="ce qui BAT sur cette machine, organe par organe (ne demarre rien)")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--requis-seulement", action="store_true",
                    help="ignore les prerequis optionnels")
    ap.add_argument("-v", "--verbeux", action="store_true",
                    help="detaille aussi les prerequis presents")
    ap.add_argument("--profil", choices=sorted(P.PROFILS), default="dev",
                    help="ce qui BLOQUE : dev (defaut, hub d'agents pour devs) ou complet (organisme entier)")
    ap.add_argument("--modeles", action="store_true",
                    help="les modeles verifies qui tiennent sur CETTE machine, avec la commande llama.cpp / Ollama / LM Studio")
    a = ap.parse_args(argv)

    if a.modeles:
        try:
            s = _capacites_hote().suggerer_modeles()
        except Exception as exc:  # noqa: BLE001 - mesure de l'hote illisible : le DIRE, rc 2
            print("ILLISIBLE : la memoire de cette machine n'a pas pu etre mesuree (%s: %s)"
                  % (type(exc).__name__, exc))
            return 2
        print(json.dumps(s, indent=2, ensure_ascii=False) if a.json else rendre_modeles(s))
        return 0

    if a.vivant:
        try:
            etat = _autorites()
        except Exception as exc:  # noqa: BLE001 - source illisible : le DIRE, rc 2
            print("ILLISIBLE : l'etat vivant n'a pas pu etre lu (%s: %s)"
                  % (type(exc).__name__, exc))
            return 2
        print(json.dumps(etat, indent=2, ensure_ascii=False, default=str) if a.json
              else rendre_vivant(etat))
        return 0

    b = P.bilan(inclure_optionnels=not a.requis_seulement, profil=a.profil)
    if a.json:
        print(json.dumps(b, indent=2, ensure_ascii=False))
    else:
        print(rendre_texte(b, verbeux=a.verbeux))
    return 1 if b["bloquants"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
