# -*- coding: utf-8 -*-
"""Deploie l'endpoint d'embedding BGE-M3 sur Modal, auth par le COFFRE.

Pourquoi pas `modal token set` : il ecrit `~/.modal.toml`, or les comptes de
service ont `HOME=C:\\Users\\Default` en LECTURE SEULE — mesure 2026-08-19 :
« Token verified successfully! » suivi de
`[Errno 13] Permission denied: 'C:\\Users\\Default/.modal.toml'`. Les tokens
etaient donc BONS et l'auth echouait quand meme, sur l'ECRITURE du cache.

Modal lit aussi `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` dans l'environnement :
on les tire du coffre DPAPI et on les injecte dans le sous-processus. Aucun
secret en argument (le hub journalise les args), aucun secret imprime.

    run action=trusted_script path=tools/forge_modal_deploy_embed.py            # verifie
    run action=trusted_script path=tools/forge_modal_deploy_embed.py --script_args="--deployer"
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

CIBLE = _ROOT / "tools" / "deploy_modal_bge_m3.py"
BIN = r"%USERPROFILE%\miniforge3\Scripts\modal.exe"
RE_URL = re.compile(r"https://[A-Za-z0-9\-\._]+\.modal\.run[^\s\"']*")


def _env_avec_tokens() -> dict:
    """Environnement enrichi des tokens Modal lus AU COFFRE (jamais du .env)."""
    from nokido_agent.app.forge_secrets import get_secret

    env = dict(os.environ)
    manquants = []
    for nom in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
        try:
            v = get_secret(nom) or ""
        except Exception:  # noqa: BLE001 - nom absent du coffre
            v = ""
        if not v:
            manquants.append(nom)
        else:
            env[nom] = v
    if manquants:
        raise SystemExit("absent(s) du coffre : %s -- lancer "
                         "forge_modal_auth_bootstrap.py d'abord" % ", ".join(manquants))
    # Cache Modal dans un dossier INSCRIPTIBLE (le HOME du service ne l'est pas).
    cache = _ROOT / "sandbox" / "modal_home"
    try:
        cache.mkdir(parents=True, exist_ok=True)
        env["MODAL_CONFIG_PATH"] = str(cache / ".modal.toml")
        env["HOME"] = str(cache)
        env["USERPROFILE"] = str(cache)
    except Exception:  # noqa: BLE001 - sans cache inscriptible, l'env suffit a Modal
        pass
    return env


def _lancer(args: list, env: dict, timeout: int = 900) -> tuple[int, str]:
    """Appelle le CLI Modal avec l'environnement porteur des tokens."""
    outil = BIN if Path(BIN).is_file() else "modal"
    try:
        r = subprocess.run([outil] + args, capture_output=True, text=True,
                           errors="replace", timeout=timeout, env=env,
                           cwd=str(_ROOT))
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT apres %ds" % timeout


INTENTION = _ROOT / "sandbox" / "modal_deploy.wanted"


def _intention_deployer() -> bool:
    """`sandbox/modal_deploy.wanted` vaut --deployer.

    `run_job` lance un script DETACHE mais ne lui passe aucun argument, et un
    `modal deploy` (build image + BGE-M3) depasse largement le cap de 115 s d'un
    appel synchrone : sans ce relais, le deploiement n'etait declenchable par
    AUCUN canal. On reutilise le vocabulaire d'intention deja parle par le corps
    (docker.wanted / llama.wanted / embed.wanted) plutot que d'inventer un
    second mecanisme. Consomme a la lecture : une intention de deploiement ne
    doit pas re-declencher un build a chaque passage.
    """
    try:
        if not INTENTION.is_file():
            return False
        INTENTION.unlink()
        print("intention %s consommee -> deploiement" % INTENTION.name)
        return True
    except Exception as e:  # noqa: BLE001 - intention illisible : on ne deploie pas
        print("intention illisible (%s) -- pas de deploiement" % type(e).__name__)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Deploiement Modal de l'embedder")
    ap.add_argument("--deployer", action="store_true",
                    help="lance reellement `modal deploy` (sinon verification seule)")
    args = ap.parse_args()
    if not args.deployer and _intention_deployer():
        args.deployer = True

    env = _env_avec_tokens()
    print("tokens lus au coffre : OK (non imprimes)")

    print("\n=== VERIFICATION AUTH (modal app list) ===")
    rc, out = _lancer(["app", "list"], env, timeout=120)
    print("  rc=%d" % rc)
    for l in out.splitlines()[:12]:
        print("    " + l[:150])
    if rc != 0:
        print("  -> auth toujours KO : on ne deploie pas sur une auth non prouvee")
        return 2

    # QUEL WORKSPACE REPOND AUJOURD'HUI ? (2026-09-06) L'app peut etre `deployed` et
    # l'endpoint rendre malgre tout `404 workspace ... is disabled` : c'est alors que
    # l'URL conservee au coffre appartient a un ANCIEN workspace, tandis que les jetons
    # actuels en servent un autre. Une app vivante et une URL morte ne se contredisent
    # pas -- elles ne parlent pas du meme espace. On demande donc au CLI le profil
    # courant, et on compare son nom au prefixe de l'URL enregistree.
    print("\n=== WORKSPACE COURANT (modal profile list) ===")
    rc_p, out_p = _lancer(["profile", "list"], env, timeout=60)
    if rc_p == 0:
        for l in out_p.splitlines()[:12]:
            print("    " + l[:150])
    else:
        print("    profil illisible (rc=%d) -- ne pas conclure sur le workspace" % rc_p)
    try:
        from nokido_agent.app.forge_secrets import get_secret as _gs

        _u = _gs("LAFORGE_MODAL_EMBED_URL") or ""
    except Exception:  # noqa: BLE001
        _u = ""
    if _u:
        # https://<workspace>--<app>-<fn>.modal.run : le prefixe AVANT '--' est le
        # workspace pour lequel l'URL a ete emise.
        _pref = _u.split("//", 1)[-1].split("--", 1)[0]
        print("    URL au coffre emise pour le workspace : %s" % _pref)
    else:
        print("    aucune URL au coffre -- rien a comparer")

    if not args.deployer:
        print("\n[verification seule] relancer avec --deployer pour publier "
              "l'endpoint (cible : %s)" % CIBLE.name)
        return 0

    if not CIBLE.is_file():
        print("cible absente :", CIBLE)
        return 3

    print("\n=== DEPLOIEMENT (build image + BGE-M3, peut durer plusieurs minutes) ===")
    rc, out = _lancer(["deploy", str(CIBLE)], env, timeout=1800)
    print("  rc=%d" % rc)
    for l in out.splitlines()[-40:]:
        print("    " + l[:170])

    urls = RE_URL.findall(out)
    if not urls:
        print("\n  aucune URL .modal.run dans la sortie -- endpoint non publie ?")
        return 4 if rc != 0 else 0

    url = sorted(set(urls), key=len)[-1]
    print("\n  ENDPOINT :", url)
    try:
        from nokido_agent.app.forge_secrets import get_secret, set_secret

        deja = ""
        try:
            deja = get_secret("LAFORGE_MODAL_EMBED_URL") or ""
        except Exception:  # noqa: BLE001 - nom absent du coffre
            deja = ""
        if deja and deja != url:
            print("  coffre : une AUTRE url est deja posee -- non ecrasee "
                  "(verifier laquelle est vivante)")
        else:
            set_secret("LAFORGE_MODAL_EMBED_URL", url)
            print("  coffre : LAFORGE_MODAL_EMBED_URL pose, relecture %s"
                  % ("CONFORME" if (get_secret("LAFORGE_MODAL_EMBED_URL") or "") == url
                     else "DIVERGENTE (!)"))
    except Exception as e:  # noqa: BLE001
        print("  coffre indisponible (%s) : noter l'URL manuellement" % type(e).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
