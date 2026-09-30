"""tools/forge_bridge_habilitation.py - emet une habilitation pour la passerelle GitHub.

__FORGE_COLOR__ = "membrane/emission-habilitation"

POURQUOI « habilitation » ET PAS « capability ». Le depot porte deja dix-huit modules
`*capability*`, et ils parlent tous d'autre chose : ce que le systeme SAIT FAIRE
(audit, contrats, lignage, fraicheur). Reutiliser ce mot pour un jeton
d'autorisation fabriquerait une homonymie qu'aucune recherche ne demelerait ensuite.

CE QUE CET OUTIL FAIT, ET POURQUOI IL EST SEPARE DE LA PASSERELLE.
La passerelle ne lit pas le coffre -- c'est sa frontiere d'autorite, verifiee par un
NR. Il faut donc quelqu'un pour faire le pont entre le coffre et l'environnement du
processus : c'est l'OPERATEUR, et cet outil est sa main. Lui a le droit de lire le
coffre ; la passerelle, non. La separation n'a de sens que portee par deux fichiers
distincts, lances par deux gestes distincts.

CE QUI EST INTERDIT ICI, et c'est la raison d'etre du fichier :
  - la valeur d'un secret n'est JAMAIS un argument. Le dispatch des scripts
    privilegies journalise ses arguments en clair : un secret passe en parametre
    finirait dans les journaux. Meme discipline que l'outil de frappe des jetons
    d'agent, reprise plutot que reinventee ;
  - l'habilitation emise n'est pas imprimee sur la sortie standard. Une sortie de
    job est relue, archivee, parfois recopiee dans une conversation. Elle est ecrite
    dans un FICHIER que l'operateur va chercher ; la sortie ne porte que des
    metadonnees : identifiant, expiration, empreinte courte.

MOINDRE PRIVILEGE. Une habilitation ne vaut que pour une audience, une portee et une
RESSOURCE, et seuls les depots de la liste blanche de la passerelle sont acceptes :
emettre pour un depot qu'elle refuse produirait un jeton mort, donc un doute inutile.

DEUX MODES DE REJEU, et le choix est ecrit dans le jeton :
  single (defaut) usage unique -- pour un client qui sait en redemander un ;
  multi           cle durable -- pour une Action externe, qui presente une cle
                  STATIQUE a chaque appel et serait refusee des le deuxieme par un
                  usage unique. Ce n'est pas un relachement : expiration et
                  revocation restent exigees, et le mode est LISIBLE dans le jeton.

Usage :
    run action=trusted_script path=tools/forge_bridge_habilitation.py \
        script_args="--frapper-la-clef"                       (une fois, au debut)
    run action=trusted_script path=tools/forge_bridge_habilitation.py \
        script_args="--sujet action-chatgpt --ttl-jours 30 --rejeu multi"
"""

from __future__ import annotations

__FORGE_COLOR__ = "membrane/emission-habilitation"

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import secrets
import sys
import time

RACINE = pathlib.Path(__file__).resolve().parent.parent
CLEF = "NOKIDO_BRIDGE_CAPABILITY_KEY"
SORTIE = RACINE / "sandbox" / "bridge_habilitation.json"


def _charger_pont():
    """La passerelle, chargee PAR SON CHEMIN : on signe avec SA fonction, jamais
    avec une copie -- deux implementations de la signature divergeraient un jour."""
    chemin = RACINE / "tools" / "forge_github_bridge.py"
    if not chemin.exists():
        raise SystemExit("passerelle introuvable : %s" % chemin)
    spec = importlib.util.spec_from_file_location("forge_github_bridge", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coffre():
    chemin = str(RACINE / "app")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    from forge_secrets import get_secret, set_secret  # noqa: PLC0415
    return get_secret, set_secret


def _empreinte(valeur: str) -> str:
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()[:8]


def frapper_la_clef() -> int:
    get_secret, set_secret = _coffre()
    if get_secret(CLEF):
        print("[clef] deja presente au coffre -- aucune ecriture. La remplacer "
              "invaliderait toutes les habilitations en cours.")
        return 0
    if not set_secret(CLEF, secrets.token_hex(32)):
        print("[clef] ECHEC d'ecriture : ce compte n'a pas l'ecriture sur le coffre "
              "machine -- relancer en trusted_script.")
        return 1
    valeur = get_secret(CLEF) or ""
    print("[clef] frappee : %d caracteres, empreinte %s"
          % (len(valeur), _empreinte(valeur)))
    print("[clef] la passerelle la lira dans SON environnement, pas au coffre : "
          "c'est le lanceur qui l'y pose.")
    return 0


def emettre(sujet: str, ressource: str, ttl_jours: int, rejeu: str) -> int:
    get_secret, _ = _coffre()
    clef = get_secret(CLEF)
    if not clef:
        print("[emission] clef ABSENTE du coffre. La frapper d'abord : "
              "--frapper-la-clef")
        return 1
    pont = _charger_pont()
    if ressource not in pont.DEPOTS_AUTORISES:
        print("[emission] REFUS : %r hors liste blanche de la passerelle (%s). Un "
              "jeton pour un depot qu'elle refuse serait mort a la naissance."
              % (ressource, sorted(pont.DEPOTS_AUTORISES)))
        return 2
    if rejeu not in ("single", "multi"):
        print("[emission] REFUS : mode de rejeu %r inconnu" % rejeu)
        return 2

    # La passerelle signe avec la clef de SON environnement : on l'y pose le temps
    # de l'emission, dans ce processus seulement.
    os.environ[CLEF] = clef
    jti = "bridge-%d-%s" % (int(time.time()), secrets.token_hex(4))
    exp = int(time.time()) + ttl_jours * 86400
    jeton = pont.forger_capacite({
        "sub": sujet, "aud": pont.AUDIENCE, "scope": pont.SCOPE,
        "resource": ressource, "exp": exp, "jti": jti, "replay": rejeu,
    })

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({"jti": jti, "sub": sujet, "resource": ressource,
                                  "replay": rejeu, "exp": exp,
                                  "habilitation": jeton}, indent=1),
                      encoding="utf-8")
    try:
        os.chmod(SORTIE, 0o600)
    except OSError:
        pass          # muet-ok : les ACL Windows ne suivent pas ce mode

    print("[emission] habilitation ECRITE dans %s" % SORTIE)
    print("[emission]   sujet     : %s" % sujet)
    print("[emission]   ressource : %s" % ressource)
    print("[emission]   portee    : %s" % pont.SCOPE)
    print("[emission]   audience  : %s" % pont.AUDIENCE)
    print("[emission]   rejeu     : %s" % rejeu)
    print("[emission]   expire le : %s"
          % time.strftime("%Y-%m-%d %H:%M", time.localtime(exp)))
    print("[emission]   jti       : %s" % jti)
    print("[emission]   empreinte : %s" % _empreinte(jeton))
    print("[emission] la VALEUR n'est pas affichee : une sortie de job est relue, "
          "archivee, parfois recopiee. Aller la chercher dans le fichier.")
    print("[emission] revocation : poser ce jti dans NOKIDO_BRIDGE_REVOKED, puis "
          "relancer la passerelle.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frapper-la-clef", action="store_true",
                    help="cree la clef de signature au coffre (une seule fois)")
    ap.add_argument("--sujet", default="", help="a QUI cette habilitation est remise")
    ap.add_argument("--ressource", default="Nokido-labs/nokido")
    ap.add_argument("--ttl-jours", type=int, default=30)
    ap.add_argument("--rejeu", default="single", choices=("single", "multi"))
    opts = ap.parse_args(argv)

    if opts.frapper_la_clef:
        return frapper_la_clef()
    if not opts.sujet:
        print("--sujet est requis : une habilitation sans destinataire nomme ne "
              "peut ni s'auditer ni se revoquer utilement.")
        return 2
    if opts.ttl_jours < 1 or opts.ttl_jours > 365:
        print("--ttl-jours hors bornes (1 a 365)")
        return 2
    return emettre(opts.sujet, opts.ressource, opts.ttl_jours, opts.rejeu)


if __name__ == "__main__":
    raise SystemExit(main())
