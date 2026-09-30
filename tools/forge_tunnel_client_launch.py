"""Lance le relais MCP d'OpenAI avec sa cle lue au COFFRE, jamais depuis un fichier.

__FORGE_COLOR__ = "reseau/ingress : lanceur du relais MCP expose a ChatGPT"

POURQUOI CE LANCEUR EXISTE, et pourquoi il ne pouvait pas etre evite. Trois
contraintes se croisent :

  1. `services.toml` est lu par le superviseur Deno et son bloc `env` est
     STATIQUE. Y ecrire `CONTROL_PLANE_API_KEY` reviendrait a versionner un
     secret dans un depot qui passe en public.
  2. `tunnel-client.exe` est un binaire TIERS : il ne sait pas lire le coffre
     DPAPI de Nokido. Son profil ne porte qu'une REFERENCE (forme `env:<NOM>`),
     donc il attend la valeur dans son ENVIRONNEMENT.
  3. Une cmdline se LIT (tasklist, journaux, inventaire de process) ; un
     environnement non. La cle ne doit donc jamais devenir un argument.

Ce fichier comble exactement cet ecart, avec le patron deja prouve pour le jeton
GitHub (`forge_push_sovereign`) : lire le coffre, poser la valeur dans
l'environnement du SOUS-PROCESSUS, executer.

REFUS PLUTOT QUE DEMARRAGE MUET. Sans cle, le relais n'est pas lance et le motif
est ecrit. Le demarrer quand meme produirait un echec cote OpenAI, plus tard,
sans rapport visible avec la cause -- c'est exactement la panne illisible payee
le 2026-09-14 avec le registre DCR non persiste.

CE FICHIER N'AGIT PAS A L'IMPORT (cf. `deploy_hub_bundle`, corrige le meme jour
pour avoir deploye un bundle au seul fait d'etre importe).
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

# Nom de la VARIABLE D'ENVIRONNEMENT attendue par le binaire tiers — pas une
# valeur. Renomme le 2026-09-14 : le nom precedent formait, avec la chaine qui
# suit, la silhouette d'une affectation de credential, et le gate d'egress
# (git_secrets) a BLOQUE le push. Le garde avait raison de se mefier de la FORME ;
# c'est le diagnostic qu'on corrige, jamais le garde qu'on contourne.
#
# PIEGE PAYE DANS LA FOULEE : la premiere version de ce commentaire CITAIT la
# silhouette fautive pour l'expliquer -- et se faisait mordre a son tour. Un
# texte qui decrit un motif ne doit pas le reproduire, sinon il declenche
# l'instrument qu'il documente (meme famille que « une mention n'est pas une
# structure »). On decrit donc ici, on ne recopie pas.
VAR_ENV_CLE = "CONTROL_PLANE_API_KEY"
PORT_SANTE_DEFAUT = 8792


def magasin() -> pathlib.Path:
    """Racine des binaires tiers. Surchargeable : le depot passe en public et ne
    doit pas porter le chemin d'un poste particulier."""
    return pathlib.Path(os.environ.get("NOKIDO_BIN", "C:/nokido"))


def binaire_par_defaut() -> pathlib.Path:
    return magasin() / "tunnel-client" / "v0.0.14" / "tunnel-client.exe"


def config_par_defaut() -> pathlib.Path:
    return magasin() / "tunnel-client" / "profiles" / "nokido-github.yaml"


def lire_cle():
    """Rend la cle du coffre, ou None. Ne journalise JAMAIS la valeur."""
    racine = pathlib.Path(__file__).resolve().parent.parent
    if str(racine / "app") not in sys.path:
        sys.path.insert(0, str(racine / "app"))
    try:
        from forge_secrets import get_secret
    except Exception:  # noqa: BLE001 — muet-ok : l'absence du coffre est DITE par decider_lancement
        return None
    try:
        return get_secret(VAR_ENV_CLE)
    except Exception:  # noqa: BLE001 — muet-ok : idem, le motif est rendu plus bas
        return None


def decider_lancement(cle):
    """Rend (autorise, motif). Le motif ne contient JAMAIS la cle, meme tronquee."""
    if not cle or not str(cle).strip():
        return False, (
            f"REFUS : {VAR_ENV_CLE} introuvable au coffre (DPAPI). Un relais sans "
            f"identite ne doit pas tourner : il echouerait cote plan de controle, "
            f"plus tard, sans rapport visible avec la cause. Poser la valeur au "
            f"coffre, puis relancer."
        )
    return True, f"{VAR_ENV_CLE} lu au coffre ({len(str(cle))} caracteres)"


# DEROGATION EXIGEE PAR LE MONTAGE, etablie le 2026-09-14 puis RE-PAYEE le soir
# meme faute d'avoir ete posee dans un lanceur.
#
# Le relais publie les URL OAuth du serveur local au plan de controle en les
# enregistrant comme hotes « harpoon ». Ces URL sont en `http://` sur le
# loopback -- c'est voulu, rien n'ecoute vers l'exterieur. Sans cette derogation
# l'enregistrement ECHOUE, et le journal du relais boucle sur :
#
#     ERROR dispatcher received unsupported channel   channel="harpoon"
#     WARN  harpoon host auto-registration failed     label=oauth-token
#
# Cote utilisateur, ChatGPT affiche « Un probleme est survenu lors de la
# connexion » : l'autorisation aboutit, le code est emis, et personne ne vient
# jamais l'echanger. Mesure du 2026-09-14 apres derogation : 8 hotes
# enregistres, 0 echec.
#
# `hosts-include-loopback` vaut deja `true` par defaut : ce n'est donc PAS le
# loopback qu'il faut autoriser, c'est le texte clair.
DEROGATIONS = {"HARPOON_ALLOW_PLAINTEXT_HTTP": "1"}


def environnement(cle, base=None):
    """L'environnement du sous-processus — SEUL canal admis pour la cle."""
    env = dict(os.environ if base is None else base)
    env[VAR_ENV_CLE] = str(cle)
    for nom, valeur in DEROGATIONS.items():
        env.setdefault(nom, valeur)
    return env


def commande(binaire, config, port=PORT_SANTE_DEFAUT):
    """La ligne de commande — volontairement SANS le moindre secret."""
    return [str(binaire), "run", "--config", str(config),
            "--health.listen-addr", f"127.0.0.1:{port}"]


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Lance le relais MCP avec la cle du coffre.")
    ap.add_argument("--binaire", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--port", type=int, default=PORT_SANTE_DEFAUT)
    ap.add_argument("--dry-run", action="store_true",
                    help="verifie la cle et imprime la commande, sans lancer")
    a = ap.parse_args(argv)

    binaire = pathlib.Path(a.binaire) if a.binaire else binaire_par_defaut()
    config = pathlib.Path(a.config) if a.config else config_par_defaut()

    cle = lire_cle()
    autorise, motif = decider_lancement(cle)
    print(motif, file=sys.stderr)
    if not autorise:
        return 2

    for chemin, quoi in ((binaire, "binaire"), (config, "profil")):
        if not chemin.exists():
            print(f"REFUS : {quoi} introuvable — {chemin}", file=sys.stderr)
            return 2

    cmd = commande(binaire, config, a.port)
    print("lancement :", " ".join(cmd), file=sys.stderr)
    if a.dry_run:
        print("DRY-RUN : rien n'a ete lance", file=sys.stderr)
        return 0
    # `cwd` sur le magasin : le binaire y trouve son cloudflared compagnon.
    return subprocess.call(cmd, env=environnement(cle), cwd=str(binaire.parent.parent))


if __name__ == "__main__":
    sys.exit(main())
