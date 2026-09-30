#!/usr/bin/env python3
"""
tools/nokido_web_hub.py - Launcher du hub FastAPI Nokido.

Demarre le hub web unique sur le port 7400 (par defaut).

USAGE:
    python tools/nokido_web_hub.py                 # port 7400
    LAFORGE_HUB_PORT=8080 python tools/nokido_web_hub.py
    python tools/nokido_web_hub.py --reload        # dev mode

Une fois lance :
    http://localhost:7400/          : dashboard
    http://localhost:7400/status    : status JSON
    http://localhost:7400/recon/    : proxy vers recon_silo (port 7410)
    http://localhost:7400/graph/    : proxy vers forge_graph_explorer (port 7420)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))  # forge_state_manager + autres modules app/

import os as _os

try:
    from app.web_hub.envfile import _CANDIDATES, load_env_file

    print(f"[nokido_web_hub] envfile candidates: {[str(p) for p in _CANDIDATES]}", flush=True)
    print(
        f"[nokido_web_hub] candidate exists: {[(p.name, p.exists()) for p in _CANDIDATES]}",
        flush=True,
    )
    injected = load_env_file()
    print(
        f"[nokido_web_hub] env loaded: {len(injected)} keys -> {sorted(injected.keys())}",
        flush=True,
    )
    print(
        f"[nokido_web_hub] LAFORGE_ADMIN_TOKEN set after load: {bool(_os.environ.get('LAFORGE_ADMIN_TOKEN'))}",
        flush=True,
    )
except Exception as _e:
    import traceback as _tb

    print(f"[nokido_web_hub] env load FAILED: {type(_e).__name__}: {_e}", flush=True)
    _tb.print_exc()


_JOURNAL_OUVERT = None      # reference gardee : faulthandler ecrit dedans jusqu'au bout


def _journal_de_vie(host: str, port: int) -> None:
    """DEMARRAGE, MORT DURE et CRASH du webhub, au meme endroit et dates.

    Le webhub n'ecrivait RIEN. Mesure 2026-08-29 : il a redemarre deux fois en
    deux minutes (19:07 puis 19:09) sans que rien ne dise pourquoi — ni meme
    qu'il avait redemarre. Seule une trace ajoutee a la main l'a revele. Un
    organe muet ne se diagnostique pas : on ne distingue meme pas « il tourne
    depuis le debut » de « il vient de renaitre », et toute enquete part d'une
    hypothese au lieu d'un fait.

    Ce journal couvre les TROIS facons de mourir, la ou le hub n'en couvre
    qu'une (`except Exception` autour de sa boucle) :
      * l'exception qui remonte      -> bloc CRASH, avec la trace ;
      * la mort DURE (abort, acces memoire, recursion) -> faulthandler, que
        `except` ne voit jamais passer ;
      * le process TUE de l'exterieur -> rien ne s'ecrit, et c'est justement
        l'information : un DEMARRAGE sans ARRET qui le precede se lit comme une
        mort violente. D'ou la ligne de demarrage, qui n'est pas decorative.
    """
    global _JOURNAL_OUVERT
    import datetime as _dt
    import faulthandler

    chemin = ROOT / "logs" / "webhub_vie.log"
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        _JOURNAL_OUVERT = open(chemin, "a", encoding="utf-8", buffering=1)
        _JOURNAL_OUVERT.write("\n%s DEMARRAGE pid=%s sur %s:%s\n" % (
            _dt.datetime.now().isoformat(timespec="seconds"), _os.getpid(), host, port))
        # all_threads : un blocage tient souvent dans un fil de travail, pas dans
        # le principal — ne dumper que celui-ci designerait un innocent.
        faulthandler.enable(file=_JOURNAL_OUVERT, all_threads=True)
    except OSError as ex:
        print("[nokido_web_hub] journal de vie indisponible (%s) : les redemarrages "
              "resteront muets" % type(ex).__name__, flush=True)


def _consigner_crash(exc: BaseException) -> None:
    import datetime as _dt
    import traceback as _tb

    trace = "\n%s CRASH : %s\n%s\n" % (
        _dt.datetime.now().isoformat(timespec="seconds"), exc, _tb.format_exc())
    print(trace, flush=True)
    if _JOURNAL_OUVERT is not None:
        try:
            _JOURNAL_OUVERT.write(trace)
            _JOURNAL_OUVERT.flush()
        except (OSError, ValueError):  # muet-ok : le crash est deja sur la sortie
            pass


def _veilleur_de_gel(host: str, port: int) -> None:
    """QUATRIEME facon de mourir : VIVANT MAIS GELE. Les trois autres sont
    couvertes par `_journal_de_vie` ; celle-ci ne l'etait par RIEN.

    Mesure 2026-09-17 : le webhub est tombe DEUX FOIS apres une page LLM avec
    la meme signature -- port LISTENING, process vivant, `/health` MUET 20 s.
    Ni `except Exception` (rien ne remonte), ni `faulthandler.enable` (qui ne
    se declenche que sur une mort DURE : abort, acces memoire, recursion) ne
    voient passer un gel. L'organe se tait donc exactement quand il faudrait
    qu'il parle, et trois sessions d'enquete sont reparties d'une hypothese.

    Le principe : on ne devine pas OU ca bloque, on le PHOTOGRAPHIE. La sonde
    est un appel `/health` depuis un thread du MEME process, donc le dump qui
    suit porte les vraies piles du bloqueur. Elle mesure le symptome dans sa
    propre dimension -- `/health` muet -- et non un indicateur voisin.

    CE VEILLEUR NE TUE RIEN, JAMAIS. Mesure 2026-09-05 : un garde a seuil arme
    SANS la distribution du signal a tue le hub 16 fois en deux jours, sur des
    gels qui existaient deja sans nuire. On ne choisit pas un seuil de mort
    avant d'avoir l'histogramme -- et c'est justement l'histogramme que ce
    veilleur produit, en datant CHAQUE gel et sa DUREE.

    Deux precautions payees ailleurs :
      * gel declare apres DEUX echecs consecutifs, pas un : un garde qui crie
        a faux se fait desarmer, et un hoquet isole n'est pas une panne ;
      * le veilleur ne leve JAMAIS. Le garde RSS du wrapper de job est mort
        sur son propre journal en emportant l'info qu'il venait de produire.
    """
    import datetime as _dt
    import faulthandler
    import threading
    import time as _t
    import urllib.request

    periode_s = 5.0       # entre deux sondes
    delai_sonde_s = 3.0   # au-dela, la sonde compte pour un echec
    echecs_pour_gel = 2   # ~10 s : bien sous les 20 s observees
    url = "http://127.0.0.1:%d/health" % port

    def _dire(texte: str) -> None:
        try:
            if _JOURNAL_OUVERT is not None:
                _JOURNAL_OUVERT.write(texte)
        except Exception:  # muet-ok : journaliser ne doit jamais casser le veilleur
            pass

    def _boucle() -> None:
        echecs = 0
        gele_depuis = None
        while True:
            try:
                _t.sleep(periode_s)
                try:
                    with urllib.request.urlopen(url, timeout=delai_sonde_s) as r:
                        vivant = 200 <= r.status < 500
                except Exception:
                    vivant = False

                if vivant:
                    if gele_depuis is not None:
                        _dire("%s DEGEL apres %.1f s\n" % (
                            _dt.datetime.now().isoformat(timespec="seconds"),
                            _t.monotonic() - gele_depuis))
                        gele_depuis = None
                    echecs = 0
                    continue

                echecs += 1
                if echecs < echecs_pour_gel or gele_depuis is not None:
                    # pas encore un gel, ou gel DEJA photographie : on ne
                    # redumpe pas en boucle, on attend le degel pour la duree
                    continue

                gele_depuis = _t.monotonic()
                _dire("\n%s GEL : /health muet sur %d sondes (%.0f s). "
                      "Piles de TOUS les fils ci-dessous ; aucune action prise.\n" % (
                          _dt.datetime.now().isoformat(timespec="seconds"),
                          echecs, echecs * periode_s))
                try:
                    if _JOURNAL_OUVERT is not None:
                        faulthandler.dump_traceback(file=_JOURNAL_OUVERT, all_threads=True)
                        _JOURNAL_OUVERT.flush()
                except Exception:  # muet-ok : un dump rate ne mange pas le GEL deja ecrit
                    pass
            except Exception:  # muet-ok : abandonner rendrait tout gel futur invisible
                # le veilleur survit a tout : une sonde qui casse ne doit pas
                # rendre le service AVEUGLE pour le reste de sa vie
                pass

    try:
        threading.Thread(target=_boucle, name="veilleur_de_gel", daemon=True).start()
        # PREUVE DE VIE. Un veilleur qui ne parle QUE sur echec est indiscernable
        # d'un veilleur qui n'a jamais demarre : on lirait son silence comme
        # "aucun gel" alors qu'il pourrait vouloir dire "aucune surveillance".
        # Meme regle que l'abstention d'un drain, qui s'ecrit avec son motif.
        _dire("%s VEILLEUR ARME : sonde %s toutes les %.0f s, gel a %d echecs, "
              "observation seule\n" % (
                  _dt.datetime.now().isoformat(timespec="seconds"),
                  url, periode_s, echecs_pour_gel))
    except Exception as ex:
        print("[nokido_web_hub] veilleur de gel non demarre (%s) : un gel "
              "resterait muet" % type(ex).__name__, flush=True)


def main() -> int:
    """Entree principale."""
    import argparse

    import uvicorn

    from app.forge_logging import installer_logging_non_bloquant
    from app.web_hub import HUB_PORT

    parser = argparse.ArgumentParser(description="Nokido Web Hub")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=HUB_PORT, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload dev mode")
    parser.add_argument("--log-level", default="info", help="uvicorn log level")
    args = parser.parse_args()

    print(f"[Nokido Hub] Starting on http://{args.host}:{args.port}")
    print(f"[Nokido Hub] Dashboard : http://{args.host}:{args.port}/")
    print(f"[Nokido Hub] Status    : http://{args.host}:{args.port}/status")
    print(f"[Nokido Hub] API docs  : http://{args.host}:{args.port}/docs")
    print()

    _journal_de_vie(args.host, args.port)
    _veilleur_de_gel(args.host, args.port)

    # Le log d'ACCES d'uvicorn part dans un pipe draine par le superviseur. Ecrit
    # depuis la boucle d'evenements, il la GELE des que le drain prend du retard :
    # photographie le 2026-09-17 a 22:47:31, pile arretee dans
    # logging/__init__.py:1144 `self.stream.flush()`, atteinte par le log d'acces
    # au travers de `_envoyer`. Le meme soir, les journaux par service du
    # superviseur tombaient de 3343 lignes a 38 pour l'heure, puis 1381 lignes
    # sortaient d'un coup a la fermeture : le tampon du pipe etait plein.
    #
    # `log_config=None` n'est PAS une option de confort : sans lui, uvicorn pose
    # sa configuration par defaut APRES cet appel et remet un StreamHandler
    # synchrone sur `uvicorn.access` -- la pose serait annulee a l'instant meme
    # ou elle vient d'etre faite, et rigoureusement invisible a la relecture.
    #
    # Le journal RACINE (« ») est detache aussi, depuis le 2026-09-29 : le portail a
    # regele a 08:55:30, pile de la boucle arretee dans logging/__init__.py:1163
    # `stream.write`, atteinte par `httpx` (« HTTP Request: GET ... » en INFO, une
    # ligne par sonde de /api/status, une douzaine par rafraichissement). httpx
    # journalise par le journal racine, que la liste ci-dessous ne couvrait pas : la
    # meme pathologie que le 17/09, entree par une autre porte. Detacher la racine
    # couvre tout journal qui y remonte, au lieu de les enumerer un par un.
    pose_journal = installer_logging_non_bloquant(
        ("", "uvicorn", "uvicorn.error", "uvicorn.access"), niveau=args.log_level)
    try:
        uvicorn.run(
            "app.web_hub.app:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level,
            log_config=None,
        )
    except BaseException as exc:      # noqa: BLE001 — on CONSIGNE puis on relaie
        # BaseException et pas Exception : un KeyboardInterrupt ou un SystemExit
        # sont des morts qu'on veut dater elles aussi. On re-leve juste apres :
        # journaliser ne doit rien changer au comportement, seulement le rendre
        # lisible.
        _consigner_crash(exc)
        raise
    finally:
        # Vide la file avant de rendre la main : ce qui reste en attente est
        # ECRIT, pas jete. Un arret qui perdrait la fin du journal ferait
        # disparaitre precisement les lignes qui precedent une mort.
        pose_journal.arreter()
    return 0


if __name__ == "__main__":
    sys.exit(main())
