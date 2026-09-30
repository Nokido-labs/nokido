"""tools/forge_tui_sonde.py -- sonde HEADLESS des TUI Textual de Nokido (Pilot, aucun terminal).

__FORGE_COLOR__ declare plus bas (le census lit la premiere ligne ancree).

POURQUOI CE MODULE EXISTE (chantier UI, 2026-09-24/25). Les deux TUI n'avaient AUCUNE sonde
d'execution : la campagne ui-acceptance juge des pages web, pas un terminal. Premiere passe
(scripts hors depot) : l'aide de la TUI multi-CLI etait effacee en < 1 s, et deux raccourcis
etaient inatteignables depuis un vrai terminal. La TUI v13 (app/Nokido.py, celle que sert le
bridge web :7440) restait ILLISIBLE : elle ouvre son journal dans logs/ A L'IMPORT, et les
comptes sandbox n'y ecrivent pas. Cet instrument est fait pour tourner sous `trusted_script`
(LaForgeTrusted ecrit dans logs/, comme le compte du bridge).

CE QU'IL JUGE, par TUI : montage (exception ?), raccourcis SURS presses un par un (jamais
quitter, jamais le presse-papier), texte RENDU scanne pour des marqueurs d'erreur (une vue qui
avale son exception peut l'ECRIRE a l'ecran). Rien n'est soumis a une saisie (celle de la TUI
v13 peut partir vers un LLM).

TROIS ETATS, jamais deux : PROUVE (monte, touches sans exception, aucun marqueur) · DEFAUT
(exception ou marqueur, NOMME) · ILLISIBLE (import/montage impossible ou borne de temps
atteinte -- ce n'est PAS un vert). Borne totale par TUI : `--borne-s` (defaut 22 s), pour tenir
sous le plafond des appels du hub.

USAGE : run action=trusted_script path=tools/forge_tui_sonde.py [script_args="--json"]
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/sonde-tui-headless"

import argparse
import asyncio
import importlib.util
import json
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TRACE: "Path | None" = None


def _jalon(msg: str) -> None:
    """Jalon ecrit AU FIL DE L'EAU (vide sur disque a chaque etape). Mesure 25/09 : une passe
    depasse le delai sans rapport ni pile -- seul un artefact ecrit pendant la marche dit ou
    elle s'est arretee."""
    if _TRACE is None:
        return
    import os as _os

    with open(_TRACE, "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
        f.flush()
        _os.fsync(f.fileno())


MARQUEURS = re.compile(r"Traceback|Exception|Error\b|erreur|ILLISIBLE|introuvable|not found|failed|échec|echec", re.I)
ACTIONS_EXCLUES = {"quit", "copy_all_log", "copy_last_reply", "copy_full_log"}


def texte_rendu(app) -> str:
    morceaux = []
    for w in app.screen.query("*"):
        for ligne in getattr(w, "lines", None) or []:
            morceaux.append(getattr(ligne, "text", str(ligne)))
        r = getattr(w, "renderable", None)
        if r is not None and not hasattr(w, "lines"):
            morceaux.append(str(r))
    return "\n".join(morceaux)


def marqueurs(txt: str) -> list[str]:
    return sorted({l.strip()[:140] for l in txt.splitlines() if MARQUEURS.search(l)})[:12]


async def _sonder(app, touches: list[str]) -> dict:
    res = {"touches": len(touches), "exceptions_touches": []}
    _jalon("run_test : entree")
    async with app.run_test(size=(220, 60)) as pilot:
        _jalon("run_test : monte")
        await pilot.pause(2.0)
        _jalon("montage : pause 2 s faite")
        res["exception_montage"] = repr(getattr(app, "_exception", None)) if getattr(app, "_exception", None) else None
        txt = texte_rendu(app)
        res["texte_montage_car"] = len(txt)
        res["marqueurs_montage"] = marqueurs(txt)
        app.set_focus(None)
        for k in touches:
            _jalon("touche %s" % k)
            try:
                await pilot.press(k)
                await pilot.pause(0.3)
                if getattr(app, "_exception", None):
                    res["exceptions_touches"].append("%s: %r" % (k, app._exception))
                    break
            except Exception as e:  # noqa: BLE001 — l'echec est NOMME dans le rapport
                res["exceptions_touches"].append("%s: %s: %s" % (k, type(e).__name__, str(e)[:120]))
        await pilot.pause(1.0)
        res["marqueurs_fin"] = marqueurs(texte_rendu(app))
        _jalon("run_test : sortie demandee")
    _jalon("run_test : sorti")
    await asyncio.sleep(1.0)
    return res


def _fils_vivants(avant: set) -> list[str]:
    """Fils NON demons encore vivants apres la fermeture de l'app, avec leur pile.

    Mesure 25/09 (TUI v13, RAG via hub) : run_test se referme, puis le processus ne se termine
    plus (asyncio.run attend son executeur). Dans le bridge :7440, chaque session fermee
    laisserait un processus derriere elle. On NOMME ce qui reste, au lieu de le supposer."""
    import threading
    import traceback as _tb

    piles = sys._current_frames()
    out = []
    for t in threading.enumerate():
        # seuls les fils NES pendant la sonde : ceux d'avant (autres tests, pytest) ne sont pas jugés
        if t is threading.main_thread() or t.daemon or not t.is_alive() or t.ident in avant:
            continue
        f = piles.get(t.ident)
        # Ouvrier d'executeur INACTIF (attend du travail dans concurrent/futures/thread.py
        # `_worker`) : l'arret normal le libere, il ne retient rien. Mesure 25/09 : compte a
        # tort, il faisait crier au defaut sur une TUI qui se ferme proprement.
        if f is not None and f.f_code.co_name == "_worker" and f.f_code.co_filename.replace(
                "\\", "/").endswith("concurrent/futures/thread.py"):
            continue
        ou = " < ".join("%s:%d %s" % (Path(fr.filename).name, fr.lineno, fr.name)
                        for fr in reversed(_tb.extract_stack(f)[-4:])) if f else "?"
        out.append("%s | %s" % (t.name, ou))
        _jalon("fil vivant apres fermeture : %s | %s" % (t.name, ou))
    return out


def _verdict(res: dict) -> str:
    if res.get("illisible"):
        return "ILLISIBLE"
    if res.get("texte_montage_car", 0) == 0:
        return "ILLISIBLE"  # lecteur aveugle : un ecran vide n'est pas un vert
    if res.get("exception_montage") or res.get("exceptions_touches") or res.get("marqueurs_fin"):
        return "DEFAUT"
    if res.get("fils_vivants_apres_fermeture"):
        return "DEFAUT"  # l'app fermee, le processus ne peut pas se terminer : arret NON propre
    return "PROUVE"


def _fabriquer_nokido_tui():
    import nokido_tui as nt
    return nt.NokidoTUI(), nt.NokidoTUI.BINDINGS


def _fabriquer_devops():
    spec = importlib.util.spec_from_file_location("nokido_tui_v13_sonde", ROOT / "app" / "Nokido.py")
    mod = importlib.util.module_from_spec(spec)
    # Inscrire le module AVANT de l'executer : Textual appelle inspect.getfile(App)
    # (chemin du CSS), qui passe par sys.modules. Mesure 25/09 sous trusted_script :
    # « DevOpsApp is a built-in class » -- defaut de l'INSTRUMENT, pas de la TUI.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    # ... et l'y REMETTRE apres : a l'import, app/Nokido.py purge son cache (« Cache Python
    # purge (dossier: app) ») et retire de sys.modules les modules de app/, dont celui-ci
    # (2e passage du 25/09, meme erreur malgre l'inscription prealable). En production la
    # TUI tourne en `__main__`, que cette purge ne touche pas.
    sys.modules[spec.name] = mod
    App = getattr(mod, "DevOpsApp")
    # Memes arguments que le VRAI lancement (app/forge_startup.py) : derniere assignation
    # connue, sinon le modele par defaut des reglages. Des noms factices fabriquaient un
    # « Modeles introuvables » que la sonde imputait a tort a la TUI (mesure 25/09).
    try:
        from nokido_agent.app.forge_startup import load_last_assignment
        dernier = load_last_assignment() or {}
    except Exception:  # noqa: BLE001 — repli explicite : modele par defaut des reglages
        dernier = {}
    defaut = getattr(getattr(mod, "settings", None), "ollama_model_default", "") or ""
    app = App(model_chat=dernier.get("chat", defaut), model_action=dernier.get("action", defaut),
              model_rag=dernier.get("rag", defaut), session_name="default", scorer=None, arch=None)
    return app, App.BINDINGS


TUIS = {
    "nokido_tui (multi-CLI, tools/nokido_tui.py)": _fabriquer_nokido_tui,
    "DevOpsApp (v13, app/Nokido.py, bridge :7440)": _fabriquer_devops,
}


async def sonder_tout(borne_s: float, seulement: str | None = None, pile: Path | None = None) -> dict:
    rapport = {}
    for nom, fabrique in TUIS.items():
        if seulement and seulement not in nom:
            continue
        t0 = time.time()
        if pile is not None:
            # Un montage qui BLOQUE la boucle ne peut pas etre coupe par wait_for (mesure
            # 25/09 : sonde v13 au-dela de 65 s). A l'echeance, la pile de TOUS les fils est
            # ecrite : elle dit ou le montage attend, au lieu de le supposer.
            import faulthandler
            _f = open(pile, "w", encoding="utf-8")
            # exit=True : la sonde SE TERMINE apres la pile. Sous trusted_script, le hub ne peut
            # pas tuer ce compte (TerminateProcess refuse, mesure 25/09) : pas d'orphelin.
            faulthandler.dump_traceback_later(borne_s + 5, repeat=False, file=_f, exit=True)
        import threading as _thr

        avant = {t.ident for t in _thr.enumerate()}
        try:
            _jalon("%s : import + construction" % nom)
            app, bindings = fabrique()
            _t_fabrique = round(time.time() - t0, 1)
            _jalon("construite en %.1f s" % _t_fabrique)
            # Un Binding peut porter des ALTERNATIVES (« ctrl+1,f2 ») : chacune est pressee.
            touches = [k.strip() for b in bindings if b.action not in ACTIONS_EXCLUES
                       for k in b.key.split(",")]
            res = await asyncio.wait_for(_sonder(app, touches), timeout=borne_s)
            res["import_et_construction_s"] = _t_fabrique
            res["fils_vivants_apres_fermeture"] = _fils_vivants(avant)
        except asyncio.TimeoutError:
            res = {"illisible": "borne de %.0f s atteinte" % borne_s}
        except Exception as e:  # noqa: BLE001 — import/montage impossible = ILLISIBLE, NOMME
            res = {"illisible": "%s: %s" % (type(e).__name__, str(e)[:200]),
                   "trace": traceback.format_exc()[-600:]}
        if pile is not None:
            import faulthandler
            faulthandler.cancel_dump_traceback_later()
        res["duree_s"] = round(time.time() - t0, 1)
        res["verdict"] = _verdict(res)
        rapport[nom] = res
    return rapport


# ── Chemin REEL du bridge :7440 (2026-09-25) ──────────────────────────────────────────────
# La sonde Pilot juge l'interface IN-PROCESS : ni l'interpreteur du bridge (miniforge de base,
# seul a porter textual_serve), ni son environnement (WebDriver), ni son protocole. MESURE du
# 25/09 : la sonde disait PROUVE, et une session websocket ouverte comme le navigateur ne
# recevait AUCUN octet en 120 s, sans fermeture. Le protocole : textual-serve lit au plus 10
# lignes de stdout pour trouver la balise, puis des paquets `D|M|P` + taille sur 4 octets. Un
# print() avant la balise consomme ces 10 lignes ; un print() bufferise vide APRES elle est lu
# comme un en-tete de paquet -- dans les deux cas le pont attend une taille absurde, sans fin.
LIGNES_LUES_PAR_TEXTUAL_SERVE = 10
BALISE = b"__GANGLION__\n"


def sonder_chemin_reel(python: str, borne_s: float, pile_apres_s: float | None = None,
                       script: Path | None = None) -> dict:
    """Lance app/Nokido.py EXACTEMENT comme le bridge et juge le debut de son flux stdout.

    `pile_apres_s` : l'enfant ecrit la pile de TOUS ses fils sur stderr a cette echeance
    (faulthandler) -- un demarrage muet dit alors OU il attend. Seule entorse au chemin reel :
    le script est lance par runpy (meme `__main__`, meme sys.path[0]) au lieu de son chemin.
    """
    import os
    import subprocess
    import threading

    script = Path(script) if script else ROOT / "app" / "Nokido.py"
    if not script.is_absolute():
        script = ROOT / script
    commande = [python, str(script)]
    if pile_apres_s:
        commande = [python, "-c", (
            "import faulthandler,runpy,sys;"
            "faulthandler.dump_traceback_later(%s, exit=False);"
            "sys.argv=[%r];sys.path.insert(0,%r);"
            "runpy.run_path(%r, run_name='__main__')"
        ) % (float(pile_apres_s), str(script), str(script.parent), str(script))]
    env = dict(os.environ, TEXTUAL_DRIVER="textual.drivers.web_driver:WebDriver", TEXTUAL_FPS="60",
               TEXTUAL_COLOR_SYSTEM="truecolor", TERM_PROGRAM="textual", COLUMNS="120", ROWS="40",
               PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8")
    t0 = time.time()
    proc = subprocess.Popen(commande, cwd=str(ROOT), env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lignes: list[str] = []
    obs: dict = {"balise_index": None, "paquets_valides": 0, "corruption": None, "t_balise_s": None}
    erreur = bytearray()

    def _lire_err() -> None:
        for bloc in iter(lambda: proc.stderr.read(4096), b""):
            if len(erreur) < 40000:
                erreur.extend(bloc)

    def _lire_out() -> None:
        while len(lignes) < 60:
            ligne = proc.stdout.readline()
            if not ligne:
                return
            if ligne == BALISE:
                obs["balise_index"] = len(lignes)
                obs["t_balise_s"] = round(time.time() - t0, 1)
                break
            lignes.append(ligne.decode("utf-8", "replace").rstrip()[:200])
        else:
            return
        while obs["paquets_valides"] < 40:  # la suite doit etre des paquets bien formes
            genre = proc.stdout.read(1)
            if not genre:
                return
            if genre not in (b"D", b"M", b"P"):
                obs["corruption"] = (genre + proc.stdout.read(120)).decode("utf-8", "replace")
                return
            taille = int.from_bytes(proc.stdout.read(4), "big")
            if taille > 50_000_000:
                obs["corruption"] = "taille de paquet absurde : %d" % taille
                return
            proc.stdout.read(taille)
            obs["paquets_valides"] += 1

    threading.Thread(target=_lire_err, daemon=True).start()
    lecteur = threading.Thread(target=_lire_out, daemon=True)
    lecteur.start()
    lecteur.join(borne_s)
    vivant = proc.poll() is None
    # Arret de l'ARBRE (l'app lance des enfants) ; le brain worker se detache par construction.
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    res = {
        "commande": " ".join(commande),
        "duree_s": round(time.time() - t0, 1),
        "lignes_avant_balise": lignes[:40],
        "nb_lignes_avant_balise": len(lignes),
        "vivant_a_l_echeance": vivant,
        "stderr_fin": erreur.decode("utf-8", "replace")[-2000:],
        **obs,
    }
    i = obs["balise_index"]
    if i is None and len(lignes) >= LIGNES_LUES_PAR_TEXTUAL_SERVE:
        res["verdict"], res["motif"] = "DEFAUT", (
            "%d lignes ecrites sur stdout avant la balise : textual-serve renonce apres %d"
            % (len(lignes), LIGNES_LUES_PAR_TEXTUAL_SERVE))
    elif i is None:
        res["verdict"], res["motif"] = ("DEFAUT", "processus mort avant la balise") if not vivant \
            else ("ILLISIBLE", "ni balise ni sortie en %.0f s" % borne_s)
    elif i >= LIGNES_LUES_PAR_TEXTUAL_SERVE:
        res["verdict"], res["motif"] = "DEFAUT", (
            "balise en ligne %d : textual-serve n'en lit que %d" % (i + 1, LIGNES_LUES_PAR_TEXTUAL_SERVE))
    elif obs["corruption"]:
        res["verdict"], res["motif"] = "DEFAUT", "flux corrompu apres la balise (texte hors paquet)"
    elif obs["paquets_valides"] == 0:
        res["verdict"], res["motif"] = "ILLISIBLE", "balise vue, aucun paquet dans la borne"
    else:
        res["verdict"], res["motif"] = "PROUVE", "balise en ligne %d, %d paquet(s) bien formes" % (
            i + 1, obs["paquets_valides"])
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--borne-s", type=float, default=22.0)
    ap.add_argument("--chemin-reel", action="store_true",
                    help="lance app/Nokido.py comme le bridge :7440 (interpreteur, WebDriver, protocole)")
    ap.add_argument("--python", default=None,
                    help="interpreteur du bridge (defaut : LAFORGE_PYTHON, sinon celui de la sonde)")
    ap.add_argument("--pile-apres", type=float, default=None,
                    help="chemin reel : pile de l'enfant ecrite sur stderr apres N s (demarrage muet)")
    ap.add_argument("--script", default=None,
                    help="chemin reel : TUI a lancer (defaut app/Nokido.py, celle du bridge ; "
                         "tools/nokido_tui.py = la TUI 13.6 a fenetre SSH en PTY)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--seulement", default=None, help="sous-chaine du nom de la TUI (ex. v13, multi)")
    ap.add_argument("--sortie", default=None, help="rapport JSON ecrit sur disque (lisible si l'appel expire)")
    ap.add_argument("--sans-rag", action="store_true",
                    help="USE_RAG=0 avant import : juge l'interface SANS le chargement RAG au montage "
                         "(mesure 25/09 : RAGEngine() charge toutes les lignes actives de rag_chunks "
                         "dans la boucle de la TUI v13 -- lecteur long sur la base, ecran gele)")
    a = ap.parse_args()
    if a.chemin_reel:
        import os as _os
        python = a.python or _os.environ.get("LAFORGE_PYTHON") or sys.executable
        res = sonder_chemin_reel(python, a.borne_s, a.pile_apres, a.script)
        if a.sortie:
            sortie = Path(a.sortie) if Path(a.sortie).is_absolute() else ROOT / a.sortie
            sortie.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["verdict"] == "PROUVE" else 1
    if a.sans_rag:
        import os as _os
        _os.environ["USE_RAG"] = "0"
    if a.sortie and not Path(a.sortie).is_absolute():
        a.sortie = str(ROOT / a.sortie)  # le repertoire courant de trusted_script n'est pas le depot
    pile = (Path(a.sortie).with_suffix(".pile.txt") if a.sortie else None)
    global _TRACE
    if a.sortie:
        _TRACE = Path(a.sortie).with_suffix(".trace.txt")
        _TRACE.write_text("", encoding="utf-8")
    # boucle geree a la main : asyncio.run attendrait l'executeur par defaut, et un fil bloque
    # y retient le processus indefiniment (mesure 25/09) -- la sonde doit RENDRE, et nommer le fil.
    boucle = asyncio.new_event_loop()
    rapport = boucle.run_until_complete(sonder_tout(a.borne_s, a.seulement, pile))
    _jalon("sondes rendues")
    if a.sortie:
        Path(a.sortie).write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=1))
    else:
        for nom, r in rapport.items():
            print("%-48s %-9s %5.1f s | %s" % (nom, r["verdict"], r["duree_s"],
                  r.get("illisible") or "touches=%d exc=%s marqueurs=%s" % (
                      r.get("touches", 0), r.get("exceptions_touches"), r.get("marqueurs_fin"))))
    return 0 if all(r["verdict"] == "PROUVE" for r in rapport.values()) else 1


if __name__ == "__main__":
    _rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # os._exit : les fils nommes dans le rapport retiendraient sinon le processus (trusted_script
    # ne peut pas le tuer : TerminateProcess refuse, mesure 25/09).
    import os as _os_fin

    _os_fin._exit(_rc)
