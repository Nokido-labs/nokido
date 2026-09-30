"""Lance la passerelle MCP avec ses secrets lus au COFFRE, jamais depuis le TOML.

__FORGE_COLOR__ = "reseau/ingress : lanceur de la passerelle MCP exposee a ChatGPT"

DEFAUT PAYE LE 2026-09-14, ET C'EST CELUI-CI QUI A COUTE LE PLUS CHER EN TEMPS.
La passerelle a ete relancee a la main sans `NOKIDO_BRIDGE_OAUTH_APPARIEMENT`.
Or `forge_bridge_oauth.code_d_appariement()` est fail-closed par construction :

    attendu vide  ->  `if not attendu or not compare_digest(...)`  ->  403

Le consentement refusait donc TOUT code, y compris le bon. Cote operateur le
message est « Code errone » : il accuse la saisie, alors que la cause est une
variable absente du processus. Un fail-closed est la bonne decision de securite,
mais il rend le diagnostic muet quand on oublie de nourrir le serveur -- et la
seule facon de ne plus l'oublier est de ne plus dependre de la memoire de celui
qui lance.

POURQUOI LE SERVEUR NE LIT PAS LE COFFRE LUI-MEME. C'est deliberé et documenté
dans `forge_bridge_oauth` : « le processus qui LANCE le serveur lit le coffre ;
le serveur, lui, ne connait que son environnement et ne peut donc pas en
extraire autre chose ». C'est une frontiere d'autorite, pas une commodite : on
la respecte en mettant la lecture ICI, dehors.

Meme patron que `forge_tunnel_client_launch` (relais) et que le jeton GitHub du
pont : coffre -> environnement du SEUL sous-processus -> execution. Aucun secret
en argument (une cmdline se lit), aucun secret dans `services.toml` (il est
versionne, et le depot passe en public).

CE FICHIER N'AGIT PAS A L'IMPORT.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `valeurs_pair` — Les secrets du connecteur des pairs, lus au coffre sous LEURS noms, poses sous ceux du serveur.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

# Variables lues au coffre et transmises au serveur. La premiere est EXIGEE :
# sans elle le consentement refuse tout, donc la passerelle est inutilisable.
# Les trois suivantes sont optionnelles -- elles decrivent un client pre-inscrit,
# pour un connecteur qui ne sait pas s'enregistrer dynamiquement, et le module
# les exige ENSEMBLE ou pas du tout.
EXIGEE = "NOKIDO_BRIDGE_OAUTH_APPARIEMENT"
OPTIONNELLES = (
    "NOKIDO_BRIDGE_OAUTH_CLIENT_ID",
    "NOKIDO_BRIDGE_OAUTH_CLIENT_SECRET",
    "NOKIDO_BRIDGE_OAUTH_REDIRECT",
)

# Variables dont le NOM au coffre DIFFERE de celui attendu par le pont.
# {nom attendu par le pont: nom sous lequel le coffre le garde}
#
# DEFAUT MESURE le 2026-09-14. Le pont lit `NOKIDO_BRIDGE_GITHUB_TOKEN`
# (forge_github_bridge:322) tandis que le coffre garde le jeton sous
# `GITHUB_TOKEN` -- celui-la meme qui sert a publier. Sans ce pont nominal, le
# service demarre parfaitement, s'authentifie, accorde le consentement... et
# n'a AUCUN jeton pour appeler GitHub. L'appelant voit alors
#
#     owner = Nokido-labs   repositories visibles = 0
#
# et conclut a un probleme de DROITS sur l'organisation -- diagnostic plausible
# (il a deja ete vrai le 2026-09-11, un PAT fine-grained ne s'etend pas a une
# org) mais faux ici : il n'y avait pas de jeton du tout. Un nom qui differe
# d'un cote a l'autre ne se voit dans aucun journal.
ALIAS_COFFRE = {
    "NOKIDO_BRIDGE_GITHUB_TOKEN": "GITHUB_TOKEN",
    "NOKIDO_BRIDGE_CAPABILITY_KEY": "NOKIDO_BRIDGE_CAPABILITY_KEY",
}
PORT_PAR_DEFAUT = 8791

# PROFILS (2026-09-28, connecteur des pairs cloud). Le patron est le meme -- coffre ->
# environnement du SEUL sous-processus -- et le profil `github` reste le defaut, inchange.
# Le connecteur des pairs a SES secrets, jamais ceux du pont : un autre code d'appariement
# (choisi par l'owner, jamais genere par un agent), une autre clef de signature, un autre
# registre de clients. {nom attendu par le serveur: nom au coffre}.
PROFIL_PAIR = {
    "exigee": ("NOKIDO_BRIDGE_OAUTH_APPARIEMENT", "NOKIDO_PAIR_OAUTH_APPARIEMENT"),
    "alias": {"NOKIDO_BRIDGE_CAPABILITY_KEY": "NOKIDO_PAIR_CAPABILITY_KEY"},
    "registre": ("sandbox", "pair_oauth_clients.json"),
    "script": "forge_pair_mcp.py",
    "port": 8793,
}


def racine() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def lire(nom: str):
    """Rend la valeur du coffre, ou None. Ne journalise JAMAIS la valeur."""
    chemin_app = str(racine() / "app")
    if chemin_app not in sys.path:
        sys.path.insert(0, chemin_app)
    try:
        from forge_secrets import get_secret
    except Exception:  # noqa: BLE001 — muet-ok : l'absence est DITE par decider_lancement
        return None
    try:
        return get_secret(nom)
    except Exception:  # noqa: BLE001 — muet-ok : idem
        return None


def decider_lancement(valeurs: dict):
    """Rend (autorise, motif). Le motif ne contient AUCUNE valeur, meme tronquee."""
    if not (valeurs.get(EXIGEE) or "").strip():
        return False, (
            f"REFUS : {EXIGEE} introuvable au coffre. Le consentement est "
            f"fail-closed : sans cette valeur il refuserait TOUT code, y compris "
            f"le bon, en affichant « Code errone » a l'operateur. Poser la valeur "
            f"au coffre, puis relancer."
        )
    presents = [n for n in OPTIONNELLES if (valeurs.get(n) or "").strip()]
    if presents and len(presents) != len(OPTIONNELLES):
        manquants = [n for n in OPTIONNELLES if n not in presents]
        return False, (
            "REFUS : client pre-inscrit INCOMPLET — manque " + ", ".join(manquants)
            + ". Le module les exige ENSEMBLE : un identifiant sans secret ouvrirait "
              "sans authentifier, sans redirection declaree laisserait la "
              "redirection libre."
        )
    quoi = "appariement" + (" + client pre-inscrit" if presents else " seul")
    return True, f"secrets lus au coffre ({quoi})"


# Ou vivent les clients inscrits dynamiquement, quand personne ne l'a dit.
REGISTRE_PAR_DEFAUT = ("sandbox", "bridge_oauth_clients.json")


def environnement(valeurs: dict, base=None, registre=REGISTRE_PAR_DEFAUT) -> dict:
    """Seul canal admis pour les secrets : l'environnement du sous-processus.

    DEFAUT PAYE le 2026-09-14, DEUX FOIS DANS LA MEME SOIREE. Le serveur EXIGE
    `NOKIDO_BRIDGE_OAUTH_CLIENTS` explicitement -- c'est la bonne decision cote
    serveur, qui ne doit pas deviner ou ecrire. Mais elle n'etait posee que dans
    `services.toml` : un lancement par tout autre chemin (`run_job`, une console)
    partait donc SANS registre, les clients inscrits vivaient en memoire, et
    l'appelant recevait des heures plus tard

        error: invalid_request
        "Client ID '<uuid>' not found"

    alors que son identifiant etait bel et bien sur le disque. Le serveur ne
    devine pas ; le LANCEUR, lui, sait ou est la racine -- c'est son travail.
    Poser la valeur ICI supprime la dependance a la memoire de celui qui lance,
    sans toucher au contrat du serveur. Une valeur deja presente est RESPECTEE.
    """
    env = dict(os.environ if base is None else base)
    for nom, val in valeurs.items():
        if val:
            env[nom] = str(val)
    if not (env.get("NOKIDO_BRIDGE_OAUTH_CLIENTS") or "").strip():
        env["NOKIDO_BRIDGE_OAUTH_CLIENTS"] = str(racine().joinpath(*registre))
    return env


def commande(port: int = PORT_PAR_DEFAUT, passerelle: str = "github") -> list:
    """Ligne de commande — volontairement SANS le moindre secret."""
    if passerelle == "pair":
        return [sys.executable, str(racine() / "tools" / PROFIL_PAIR["script"]), "--port", str(port)]
    return [sys.executable, str(racine() / "tools" / "forge_github_bridge_mcp.py"),
            "--transport", "http", "--port", str(port)]


def valeurs_pair() -> dict:
    """Les secrets du connecteur des pairs, lus au coffre sous LEURS noms, poses sous ceux du serveur."""
    attendu, au_coffre = PROFIL_PAIR["exigee"]
    valeurs = {attendu: lire(au_coffre)}
    for attendu, au_coffre in PROFIL_PAIR["alias"].items():
        valeurs[attendu] = lire(au_coffre)
    return valeurs


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Lance la passerelle MCP avec les secrets du coffre.")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--passerelle", choices=("github", "pair"), default="github",
                    help="github (defaut, inchange) ou pair (connecteur des pairs cloud)")
    ap.add_argument("--dry-run", action="store_true",
                    help="verifie les secrets et imprime la commande, sans lancer")
    a = ap.parse_args(argv)

    if a.passerelle == "pair":
        valeurs = valeurs_pair()
        cle = "NOKIDO_BRIDGE_CAPABILITY_KEY"
        if not (valeurs.get(cle) or "").strip():
            print("AVERTISSEMENT : NOKIDO_PAIR_CAPABILITY_KEY introuvable au coffre -- clef ephemere : "
                  "les habilitations mourront au redemarrage (les pairs devront reconsentir).",
                  file=sys.stderr)
        autorise, motif = decider_lancement(valeurs)
        if not autorise:
            motif = motif.replace(EXIGEE, "NOKIDO_PAIR_OAUTH_APPARIEMENT (code choisi par l'owner)")
        print(motif, file=sys.stderr)
        if not autorise:
            return 2
        env = environnement(valeurs, registre=PROFIL_PAIR["registre"])
        cmd = commande(a.port or PROFIL_PAIR["port"], "pair")
        print("registre des clients OAuth :", env["NOKIDO_BRIDGE_OAUTH_CLIENTS"], file=sys.stderr)
        print("lancement :", " ".join(cmd), file=sys.stderr)
        if a.dry_run:
            print("DRY-RUN : rien n'a ete lance", file=sys.stderr)
            return 0
        return subprocess.call(cmd, env=env, cwd=str(racine()))

    a.port = a.port or PORT_PAR_DEFAUT
    valeurs = {nom: lire(nom) for nom in (EXIGEE,) + OPTIONNELLES}
    for attendu, au_coffre in ALIAS_COFFRE.items():
        valeurs[attendu] = lire(au_coffre)
    manquants = [n for n in ALIAS_COFFRE if not (valeurs.get(n) or "").strip()]
    if manquants:
        # NON bloquant : le pont demarre, mais il faut DIRE ce qu'il ne pourra
        # pas faire. Un service qui repond sans pouvoir travailler produit un
        # verdict « 0 resultat » que l'appelant impute a des droits manquants.
        print("AVERTISSEMENT : " + ", ".join(manquants) + " introuvable(s) au "
              "coffre — les appels GitHub echoueront et l'appelant lira « 0 "
              "depot », ce qui ressemble a un defaut de droits.", file=sys.stderr)
    autorise, motif = decider_lancement(valeurs)
    print(motif, file=sys.stderr)
    if not autorise:
        return 2

    env = environnement(valeurs)
    print("registre des clients OAuth :", env["NOKIDO_BRIDGE_OAUTH_CLIENTS"],
          file=sys.stderr)

    cmd = commande(a.port)
    print("lancement :", " ".join(cmd), file=sys.stderr)
    if a.dry_run:
        print("DRY-RUN : rien n'a ete lance", file=sys.stderr)
        return 0
    return subprocess.call(cmd, env=env, cwd=str(racine()))


if __name__ == "__main__":
    sys.exit(main())
