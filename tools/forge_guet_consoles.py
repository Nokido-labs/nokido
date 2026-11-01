"""tools/forge_guet_consoles.py -- guet PERMANENT et leger des consoles qui apparaissent sur le bureau de l'owner.

POURQUOI (owner 31/10, « encore la ! ») : des fenetres cmd « popent tres rapidement ». Deux guets ponctuels (2 min puis
25 min, pendant une CI et cinq jobs) n'ont rien vu. Un phenomene INTERMITTENT ne se refute pas par une lecture a
l'instant t (RULES_SHARED, « sonde de meme dimension que l'affirmation ») : il faut un JOURNAL. Choix owner : un guet
permanent dans la session de l'owner (tache planifiee Nokido-Guet-Fenetres, pythonw, sans console).

CE QU'IL ECRIT (logs/guet_consoles.jsonl, tournant 5 Mo x 2) :
  * un evenement par fenetre console VISIBLE nouvelle -- classe, titre, chaine de la fenetre, ET les processus console
    nes dans les FENETRE_NAISSANCE_S secondes : Windows Terminal etant l'hote par defaut, la fenetre d'un pop appartient
    a `WindowsTerminal.exe <- explorer.exe` et ne dit PAS qui l'a lancee ; le lanceur se lit sur ces naissances ;
  * l'identite de chaque naissance par `forge_process_inventory.ancetre_identifie` (superviseur -> parente), jamais
    devinee par le nom : sans preuve, « NON PROUVEE » ;
  * un TEMOIN toutes les TEMOIN_S secondes : fenetres visibles vues au plus. 0 = ce compte ne voit pas le bureau
    (ILLISIBLE) ; pas de temoin recent = guet mort. Un silence du journal n'est donc jamais lu « aucun pop ».
"""
from __future__ import annotations

__FORGE_COLOR__ = "proprioception/guet-consoles-visibles"

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


CLASSES_CONSOLE = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")
PROCS_CONSOLE = frozenset({"cmd.exe", "conhost.exe", "openconsole.exe", "powershell.exe", "pwsh.exe",
                           "windowsterminal.exe", "wt.exe"})
FENETRE_NAISSANCE_S = 3.0
TEMOIN_S = 600.0
JOURNAL = _racine_donnees() / "logs" / "guet_consoles.jsonl"


def nouvelles(fenetres, vues) -> list:
    """Les fenetres console (hwnd, pid, classe, titre) pas encore vues. Decision PURE."""
    return [f for f in fenetres if f[0] not in vues]


def naissances(procs: dict, maintenant: float, fenetre_s: float = FENETRE_NAISSANCE_S) -> list:
    """Pids des processus console nes depuis `fenetre_s` secondes. Decision PURE (procs = forme de `_vivants`)."""
    return sorted(pid for pid, p in procs.items()
                  if (p.get("nom") or "").lower() in PROCS_CONSOLE
                  and p.get("cree") is not None and float(p["cree"]) >= maintenant - fenetre_s)


def chaine(pid, procs: dict, profondeur: int = 6) -> list:
    """`nom[pid]` en remontant les parents ; un maillon disparu est DIT, jamais saute."""
    out, vus = [], set()
    while pid is not None and pid not in vus and len(out) <= profondeur:
        vus.add(pid)
        p = procs.get(pid)
        if p is None:
            out.append("ILLISIBLE[%s] (disparu)" % pid)
            break
        out.append("%s[%s]" % (p.get("nom"), pid))
        pid = p.get("ppid")
    return out


def evenement(fenetre, procs: dict, maintenant: float, identifier=None) -> dict:
    """Un pop : la fenetre, et les naissances console qui l'entourent, chacune avec son identite PROUVEE ou non."""
    hwnd, pid, classe, titre = fenetre
    nes = []
    for n in naissances(procs, maintenant):
        ident = None
        if identifier is not None:
            try:
                ident = identifier(n)
            except Exception as exc:  # noqa: BLE001 -- une identification en panne se DIT
                ident = {"identite": "ILLISIBLE (%s)" % type(exc).__name__}
        nes.append({"pid": n, "chaine": chaine(n, procs), "cmd": ((procs.get(n) or {}).get("cmd") or "")[:160],
                    "identite": (ident or {}).get("identite") or "NON PROUVEE"})
    return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(maintenant)), "type": "console_visible",
            "classe": classe, "titre": (titre or "")[:80], "fenetre": chaine(pid, procs), "naissances": nes}


def _enumerer() -> tuple:
    """(fenetres visibles enumerees, [(hwnd, pid, classe, titre)] des consoles visibles)."""
    import ctypes
    import ctypes.wintypes as W

    u32 = ctypes.windll.user32
    proc_t = ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)
    vues, total = [], [0]

    def _cb(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            total[0] += 1
            buf = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(hwnd, buf, 64)
            if buf.value in CLASSES_CONSOLE:
                pid = W.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                t = ctypes.create_unicode_buffer(128)
                u32.GetWindowTextW(hwnd, t, 128)
                vues.append((int(hwnd or 0), int(pid.value), buf.value, t.value))
        return True

    u32.EnumWindows(proc_t(_cb), 0)
    return total[0], vues


def _instantane() -> dict:
    from nokido_agent.tools.forge_process_inventory import _vivants

    return _vivants()[0]


def _identifieur(procs: dict):
    """Identifie un pid par `ancetre_identifie` (superviseur -> parente). Superviseur muet -> parente seule."""
    from nokido_agent.tools import forge_process_inventory as inv

    try:
        declares = inv._declares(3)
    except Exception:  # noqa: BLE001 -- superviseur injoignable : on identifie sans lui, et ca se voit (NON PROUVEE)
        declares = {}
    pid_service = {int(d["pid"]): nom for nom, d in declares.items()
                   if not nom.startswith("__") and d.get("status") == "running" and d.get("pid")}
    return lambda pid: (pid_service.get(pid) and {"identite": pid_service[pid]}) or inv.ancetre_identifie(
        pid, procs, pid_service, {})


def _journal():
    from nokido_agent.app.forge_log_rotation import get_rotating_logger

    log = get_rotating_logger("guet_consoles", path=JOURNAL, fmt="%(message)s", max_bytes=5 * 1024 * 1024,
                              backup_count=2)
    return lambda d: log.info(json.dumps(d, ensure_ascii=False))


def guetter(duree_s: float, intervalle_s: float = 0.1, enumerer=_enumerer, instantane=_instantane,
            identifieur=_identifieur, ecrire=None, horloge=time.time, dormir=time.sleep) -> dict:
    """Boucle de guet. `duree_s` <= 0 : sans fin (tache planifiee). Rend le bilan (evenements, temoins)."""
    ecrire = ecrire or _journal()
    debut = dernier_temoin = horloge()
    vues, visibles_max, n_evt, n_temoin = set(), 0, 0, 0
    premier = True
    while duree_s <= 0 or horloge() - debut < duree_s:
        total, fenetres = enumerer()
        visibles_max = max(visibles_max, total)
        neuves = nouvelles(fenetres, vues)
        vues.update(f[0] for f in fenetres)
        if neuves and not premier:  # les consoles deja ouvertes au demarrage ne sont pas des pops
            maintenant = horloge()
            procs = instantane()
            ident = identifieur(procs)
            for f in neuves:
                ecrire(evenement(f, procs, maintenant, ident))
                n_evt += 1
        premier = False
        if horloge() - dernier_temoin >= TEMOIN_S:
            ecrire({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "type": "temoin", "visibles_max": visibles_max,
                    "lisible": visibles_max > 0, "evenements": n_evt})
            dernier_temoin, visibles_max, n_temoin = horloge(), 0, n_temoin + 1
        dormir(intervalle_s)
    return {"evenements": n_evt, "temoins": n_temoin, "visibles_max": visibles_max}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="guet permanent des consoles visibles")
    ap.add_argument("--duree", type=float, default=0.0, help="secondes ; 0 = sans fin (tache planifiee)")
    ap.add_argument("--intervalle", type=float, default=0.1)
    a = ap.parse_args(argv)
    print(json.dumps(guetter(a.duree, a.intervalle)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
