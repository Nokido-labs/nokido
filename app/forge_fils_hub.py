# -*- coding: utf-8 -*-
"""Introspection des FILS du hub -- owner 4/11 (« Introspection dans le hub », plutot que la trappe privilegiee).

Sonde e9a90d767 : le hub lit ~35 Mo toutes les ~10 s, hors regulation (60 s) et hors requetes journalisees ; ni le
compte de confiance ni py-spy n'atteignent son processus (AccessDenied). Le hub lit donc SES PROPRES fils :
sys._current_frames() echantillonne `n` fois ; chaque fil nomme, son haut de pile (fichier:ligne fonction, source),
et la liste des fils dont la ligne courante est un acces SQLite (execute/fetch/cursor/sqlite3). Lecture seule.
Expose par `hub action=fils` (rings 0-1). NR tests/nr/test_fils_hub_nr.py."""
__FORGE_COLOR__ = "proprioception/fils : le hub lit ses propres fils (pile, acces SQLite) pour nommer une boucle"

import json
import linecache
import logging
import os
import re
import sys
import threading
import time
from collections import deque
from nokido_agent.app.forge_db_path import racine_donnees

_SQLITE = re.compile(r"\.execute|executemany|executescript|\.fetch(one|all|many)|cursor\(|sqlite3\.connect")

# Sonde interne des lectures (owner 4/11, « observabilite parfaite ») : une lecture en cache dure ~30 ms, un echantillonnage
# a 1 s ne la voit presque jamais. Le hook d'audit note ce que le hub ouvre, le surveillant ecrit qui venait d'ouvrir quoi
# quand les compteurs sautent. Couper : creer sandbox/hub_lectures.off, lu a chaque tick (un hook d'audit ne se retire pas,
# il devient muet). NR tests/nr/test_fils_hub_lectures_nr.py.
_RACINE = racine_donnees()
_JOURNAL = _RACINE / "sandbox" / "hub_lectures.jsonl"
_JOURNAL_MAX_O = 2_000_000
_INTERRUPTEUR = _RACINE / "sandbox" / "hub_lectures.off"
_SEUIL_O = 5_000_000
_PAS_S = 0.1
_FENETRE_S = 2.0
_EVENEMENTS = ("open", "sqlite3.connect")
_ANNEAU: deque = deque(maxlen=300)
_ARMEE = {"fait": False, "muet": False}
_REPOS = re.compile(r"\| .*(\.sleep\(|\.wait\(|select\.select|\.acquire\(|\.join\(|\.recv\(|\.accept\()")
log = logging.getLogger(__name__)


def autorise(ring: int) -> bool:
    return int(ring) <= 1


def _pile(frame, profondeur: int) -> list:
    out = []
    while frame is not None and len(out) < profondeur:
        co = frame.f_code
        src = linecache.getline(co.co_filename, frame.f_lineno).strip()
        out.append("%s:%d %s | %s" % (co.co_filename.replace("\\", "/").split("/")[-1], frame.f_lineno,
                                      co.co_name, src[:120]))
        frame = frame.f_back
    return out


def echantillonner_fils(n: int = 5, pas_s: float = 1.0, profondeur: int = 8) -> dict:
    """{"echantillons": [{"t", "fils": [{"nom", "ident", "pile"}]}], "dans_sqlite": {nom: nb d'echantillons}}."""
    moi = threading.get_ident()
    noms = {t.ident: t.name for t in threading.enumerate()}
    echantillons, dans_sqlite = [], {}
    for k in range(max(1, int(n))):
        if k:
            time.sleep(pas_s)
        noms.update({t.ident: t.name for t in threading.enumerate()})
        fils = []
        for ident, frame in sys._current_frames().items():
            if ident == moi:
                continue
            pile = _pile(frame, profondeur)
            nom = noms.get(ident, "fil-%s" % ident)
            fils.append({"nom": nom, "ident": ident, "pile": pile})
            if pile and _SQLITE.search(pile[0].split(" | ", 1)[-1]):
                dans_sqlite[nom] = dans_sqlite.get(nom, 0) + 1
        echantillons.append({"t": round(time.time(), 2), "fils": fils})
    return {"echantillons": echantillons, "dans_sqlite": dans_sqlite}


def _noter_audit(event, args) -> None:
    """Hook d'audit : tourne dans TOUT le hub, a chaque ouverture. Court, sans E/S, et ne leve jamais."""
    if event not in _EVENEMENTS or _ARMEE["muet"]:
        return
    try:
        chemin = args[0]
        if not isinstance(chemin, (str, bytes, os.PathLike)) or str(chemin).endswith(_JOURNAL.name):
            return   # un instrument ne se compte pas lui-meme : son journal masquait les vraies ouvertures
        pile, f = [], sys._getframe(1)
        while f is not None and len(pile) < 6:
            co = f.f_code
            pile.append("%s:%d %s" % (co.co_filename.replace("\\", "/").split("/")[-1], f.f_lineno, co.co_name))
            f = f.f_back
        _ANNEAU.append({"t": time.time(), "ev": event, "chemin": str(chemin)[-160:],
                        "fil": threading.current_thread().name, "pile": pile})
    except Exception:  # noqa: BLE001 -- muet-ok : une sonde ne casse jamais son porteur, ici chaque open() du hub
        return


def _fils_actifs(profondeur: int = 6, plafond: int = 8) -> dict:
    """Piles des fils qui travaillent a cet instant (les fils au repos sont ecartes)."""
    moi = threading.get_ident()
    noms = {t.ident: t.name for t in threading.enumerate()}
    out = {}
    for ident, frame in sys._current_frames().items():
        if ident == moi:
            continue
        pile = _pile(frame, profondeur)
        if pile and not _REPOS.search(pile[0]):
            out[noms.get(ident, "fil-%s" % ident)] = pile
        if len(out) >= plafond:
            break
    return out


def tick_lectures(lire, ecrire, etat: dict, actif, maintenant: float) -> None:
    """Un tour du surveillant. `etat["prec"]` = (octets, lectures) cumules au tour precedent."""
    if not actif():
        _ARMEE["muet"] = True
        etat.pop("prec", None)   # sinon la reprise fabriquerait un faux saut
        return
    _ARMEE["muet"] = False
    try:
        cur = lire()
    except Exception as e:  # noqa: BLE001
        if not etat.get("panne"):
            log.warning("[lectures] compteurs du hub ILLISIBLES (%s) : la sonde ne voit plus rien", type(e).__name__)
        etat["panne"] = True
        return
    etat["panne"] = False
    prec, etat["prec"] = etat.get("prec"), cur
    if prec is None:
        return
    octets, lectures = cur[0] - prec[0], cur[1] - prec[1]
    if octets < _SEUIL_O:
        return
    ouvertures = [e for e in list(_ANNEAU) if maintenant - e["t"] <= _FENETRE_S][-20:]
    ecrire({"ts": round(maintenant, 2), "mo": round(octets / 1e6, 1), "lectures": lectures,
            "octets_par_lecture": int(octets / max(lectures, 1)), "ouvertures": ouvertures, "fils": _fils_actifs(),
            "note": "" if ouvertures else "aucune ouverture recente : connexion deja ouverte ou lecture hors open()"})


def _ecrire(entree: dict) -> None:
    """Ajoute une ligne ; au-dela du plafond, garde la moitie recente (meme politique que la serie des vitaux)."""
    try:
        _JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with _JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entree, ensure_ascii=False, default=str) + "\n")
        if _JOURNAL.stat().st_size > _JOURNAL_MAX_O:
            lignes = _JOURNAL.read_text(encoding="utf-8", errors="replace").splitlines()
            _JOURNAL.write_text("\n".join(lignes[len(lignes) // 2:]) + "\n", encoding="utf-8")
    except OSError as e:
        log.warning("[lectures] journal non ecrit (%s)", type(e).__name__)


def _surveiller() -> None:
    import psutil

    moi, etat = psutil.Process(), {}

    def _lire():
        c = moi.io_counters()
        return c.read_bytes, c.read_count

    while True:
        try:
            tick_lectures(_lire, _ecrire, etat, lambda: not _INTERRUPTEUR.exists(), time.time())
        except Exception as e:  # noqa: BLE001
            log.warning("[lectures] tour ignore (%s: %s)", type(e).__name__, str(e)[:120])
        time.sleep(_PAS_S)


def armer_sonde_lectures() -> None:
    """Pose le hook et le surveillant, une seule fois par processus : un hook d'audit ne se retire pas."""
    if _ARMEE["fait"]:
        return
    _ARMEE["fait"] = True
    sys.addaudithook(_noter_audit)
    threading.Thread(target=_surveiller, name="forge_lectures_hub", daemon=True).start()
