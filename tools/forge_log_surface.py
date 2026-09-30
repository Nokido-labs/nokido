# -*- coding: utf-8 -*-
"""CENSUS de la surface d'observation de Nokido — ce qu'on peut voir, et d'ou.

POURQUOI CE MODULE EXISTE
=========================
Owner, 2026-09-05 : « il faut absolument collecter l'integralite des logs du corps de
Nokido […] sans ca on va passer notre temps a essayer de debugger en etant aveugle a
toute la surface ». Mesure du meme jour qui lui donne raison : deux daemons sont morts
en silence pendant 4 h, et leur cause n'existait NULLE PART — ni dans le journal du
superviseur (qui note `exited code=1` sans le traceback), ni dans le collecteur de
traces (`forge_trace_spine` : 11 producteurs sous contrat pour 60 sources auditees,
`hub_blackbox` = 2791 evenements sur 8 h et 0 mention des daemons tombes). Il a fallu
relancer chaque daemon a la main pour lui voler son stderr.

CE QUE CE MODULE FAIT — ET CE QU'IL NE FAIT PAS
===============================================
Il RECENSE, il n'ingere pas. L'ingestion normalisee est le travail de
`forge_trace_spine`, qui a son contrat de provenance et refuse par defaut ce qu'il ne
peut pas dater ; ce module-ci repond a la question d'avant : **quelles surfaces
existent, et lesquelles ce compte peut-il lire ?**

Il ne modifie AUCUNE ACL. Il produit la LISTE des sources illisibles avec leur raison,
pour qu'un elargissement soit une decision motivee et minimale — la lecon du 03/09 est
qu'elargir une ACL pour contourner une erreur de syntaxe affaiblit la securite pour
rien.

TROIS COMPTES, TROIS ANGLES MORTS
=================================
`LaForgeSbxOffline`, `LaForgeSbxOnline` et `LaForgeTrusted` ne voient PAS la meme
chose (mesure 2026-09-03 : « 1 backup » ou « 0 » selon le compte). Le census rend donc
l'etat POUR LE COMPTE COURANT et le nomme. Croiser trois executions avec `--fusion`
distingue « illisible ici » de « illisible partout » — seul le second justifie une ACL.

QUATRE ETATS, JAMAIS DEUX
=========================
`LISIBLE` · `ILLISIBLE` (existe, acces refuse) · `ABSENT` (n'existe pas) ·
`NON_APPLICABLE` (la source ne concerne pas cette machine). Confondre ILLISIBLE et
ABSENT est le defaut qui fait lire « rien a signaler » sur ce qu'on n'a pas pu ouvrir.
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/census-surface-logs"

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LISIBLE, ILLISIBLE, ABSENT, NON_APPLICABLE = "LISIBLE", "ILLISIBLE", "ABSENT", "NON_APPLICABLE"


def _profil_owner() -> Path:
    """Profil de l'owner. Les comptes de service ont HOME=C:\\Users\\Default, donc
    `Path.home()` y renvoie un dossier vide — piege deja paye sur pip."""
    return Path(os.environ.get("NOKIDO_OWNER_HOME", r"%USERPROFILE%"))


def _etat_fichier(p: Path) -> dict:
    """Etat d'UNE source fichier. Ouvre reellement : `exists()` ment sur ACL.

    Mesure 2026-09-04 : `.gitmodules` affichait `exists() = True` alors que la LECTURE
    rendait `PermissionError`. Tester l'existence ne dit rien du droit de lire.
    """
    try:
        st = p.stat()
    except FileNotFoundError:
        return {"etat": ABSENT}
    except OSError as exc:
        return {"etat": ILLISIBLE, "raison": "stat %s" % type(exc).__name__}
    base = {"octets": st.st_size, "age_h": round((time.time() - st.st_mtime) / 3600, 1)}
    # Un DOSSIER se teste par sa LISTABILITE, jamais par `open` : sous Windows,
    # ouvrir un repertoire leve `PermissionError` meme quand on a tous les droits.
    # Mesure 2026-09-05 : apres l'octroi des ACL, `.lmstudio`, `server-logs` et ses
    # sous-dossiers mensuels ressortaient ILLISIBLES — le census accusait a tort des
    # chemins qu'il venait d'ouvrir. Un garde qui crie a faux se fait desarmer.
    import stat as _stat
    if _stat.S_ISDIR(st.st_mode):
        try:
            entrees = len(os.listdir(p))
        except OSError as exc:
            return {"etat": ILLISIBLE, "raison": "listdir %s" % type(exc).__name__,
                    **base}
        return {"etat": LISIBLE, "dossier": True, "entrees": entrees, **base}
    if st.st_size == 0:
        return {"etat": LISIBLE, "vide": True, **base}
    try:
        with open(p, "rb") as fh:
            fh.read(1)
    except OSError as exc:
        return {"etat": ILLISIBLE, "raison": "open %s" % type(exc).__name__, **base}
    return {"etat": LISIBLE, **base}


def _famille_depot() -> dict:
    """Journaux ecrits par le corps lui-meme (logs/ et sandbox/)."""
    out: dict = {}
    for dossier, motifs in ((ROOT / "logs", ("*.log", "*.err", "*.out", "*.jsonl")),
                            (ROOT / "sandbox", ("*.log", "*.err", "*.jsonl",
                                                "*.heartbeat"))):
        for motif in motifs:
            try:
                chemins = list(dossier.glob(motif))
            except OSError as exc:
                out[str(dossier / motif)] = {"etat": ILLISIBLE,
                                             "raison": type(exc).__name__}
                continue
            for p in chemins:
                out[str(p.relative_to(ROOT))] = _etat_fichier(p)
    return out


def _famille_nssm() -> dict:
    """Redirections AppStdout/AppStderr — SEUL endroit ou meurt un service NSSM."""
    try:
        from nokido_agent.tools.forge_boot_diagnostic import logs_nssm
    except Exception as exc:  # noqa: BLE001
        return {"_erreur": {"etat": ILLISIBLE,
                            "raison": "forge_boot_diagnostic: %s" % type(exc).__name__}}
    brut = logs_nssm()
    out: dict = {}
    for svc, flux in (brut.get("services") or {}).items():
        for cle, v in flux.items():
            etat = v.get("etat")
            corresp = {"ABSENT": ABSENT, "ILLISIBLE": ILLISIBLE,
                       "NON_DECLARE": NON_APPLICABLE}.get(etat, LISIBLE)
            out["%s/%s" % (svc, cle[3:])] = {"etat": corresp, "detail": etat,
                                            "age_h": v.get("age_h"),
                                            "octets": v.get("octets")}
    return out


def _famille_docker() -> dict:
    """Journaux de la PROTHESE Docker : moteur, VM, et son parametrage."""
    h = _profil_owner()
    src = {
        "docker_desktop_log": h / "AppData" / "Local" / "Docker" / "log.txt",
        "docker_desktop_host": h / "AppData" / "Local" / "Docker" / "host",
        "docker_daemon_json": h / ".docker" / "daemon.json",
        "docker_config": h / ".docker" / "config.json",
        "docker_wsl_data": h / "AppData" / "Local" / "Docker" / "wsl",
    }
    return {k: _etat_fichier(v) for k, v in src.items()}


def _famille_lmstudio() -> dict:
    """LM Studio : prothese aussi — son serveur exige la session owner."""
    h = _profil_owner()
    base = h / ".lmstudio"
    src = {"lmstudio_dir": base,
           "lmstudio_server_logs": base / "server-logs",
           "lmstudio_conf": base / ".internal" / "http-server-config.json"}
    out = {k: _etat_fichier(v) for k, v in src.items()}
    rep = base / "server-logs"
    try:
        fichiers = sorted(rep.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in fichiers[:5]:
            out["lmstudio_log/" + p.name] = _etat_fichier(p)
    except OSError as exc:
        out["lmstudio_server_logs/*"] = {"etat": ILLISIBLE, "raison": type(exc).__name__}
    return out


def _famille_wsl() -> dict:
    """WSL porte la VM de Docker : sans lui, `vmmemWSL` reste une boite noire."""
    h = _profil_owner()
    out = {
        "wsl_config": h / ".wslconfig",
        "wsl_appdata": h / "AppData" / "Local" / "Packages",
    }
    res = {k: _etat_fichier(v) for k, v in out.items()}
    tmp = Path(os.environ.get("TEMP", r"C:\Windows\Temp"))
    for nom in ("wsl.log", "wslservice.log"):
        res["temp/" + nom] = _etat_fichier(tmp / nom)
    return res


def _famille_windows(profond: bool = False) -> dict:
    """EventLog Windows. Deux canaux nous concernent directement :

    - `System` / source `Service Control Manager` : demarrages et morts de services ;
    - `Security` 4624/4625 : ouvertures de session des TROIS comptes de service.

    `Security` exige un privilege que les comptes de service n'ont pas ; on le DIT au
    lieu de rendre une liste vide. La lecture reelle est deleguee au watcher existant
    (`forge_service_crash_watcher._query_crash_events`), jamais reecrite ici.
    """
    res: dict = {}
    try:
        from nokido_agent.tools.forge_service_crash_watcher import _query_crash_events
    except Exception as exc:  # noqa: BLE001
        res["eventlog_system_crashs"] = {
            "etat": ILLISIBLE,
            "raison": "lecteur indisponible (%s)" % type(exc).__name__}
        return res
    if not profond:
        res["eventlog_system_crashs"] = {
            "etat": NON_APPLICABLE,
            "raison": "lecture EventLog non demandee (--profond)"}
        return res
    try:
        ev = _query_crash_events(0)
        res["eventlog_system_crashs"] = {"etat": LISIBLE, "evenements": len(ev)}
    except Exception as exc:  # noqa: BLE001
        res["eventlog_system_crashs"] = {"etat": ILLISIBLE,
                                         "raison": "%s" % type(exc).__name__}
    return res


def census(profond: bool = False, familles_voulues: list | None = None) -> dict:
    """`familles_voulues` restreint le balayage.

    Le depot pese 10 681 fichiers : le recenser depasse le cap du canal `shell` du
    hub, et c'est justement par ce canal qu'on atteint `LaForgeSbxOnline` — le seul
    compte que `run_job` ne sait PAS prendre (mesure 2026-09-05 : `network=true` sur
    `run_job` rend un rapport signe `LaForgeSbxOffline`, le drapeau ne bascule pas le
    compte). Comparer les comptes n'a de sens que sur les familles CONTESTEES ;
    le depot est lisible par les trois, c'est etabli.
    """
    toutes = {
        "depot": _famille_depot,
        "nssm": _famille_nssm,
        "docker": _famille_docker,
        "lmstudio": _famille_lmstudio,
        "wsl": _famille_wsl,
    }
    choix = familles_voulues or list(toutes) + ["windows"]
    familles = {nom: fn() for nom, fn in toutes.items() if nom in choix}
    if "windows" in choix:
        familles["windows"] = _famille_windows(profond)
    compte: dict = {}
    for fam, src in familles.items():
        c: dict = {}
        for v in src.values():
            c[v["etat"]] = c.get(v["etat"], 0) + 1
        compte[fam] = c
    return {"ts": time.time(),
            "compte_execution": getpass.getuser(),
            "familles": familles,
            "resume": compte}


def fusion(rapports: list) -> dict:
    """Croise plusieurs census (un par compte) : que voit-on, et depuis OU ?

    Une source illisible ICI mais lisible AILLEURS ne justifie aucune ACL — il suffit
    de la lire depuis le bon compte. Seules celles illisibles PARTOUT sont candidates,
    et encore : `ABSENT` partout n'est pas un probleme d'ACL, c'est une source qui
    n'existe pas.
    """
    vue: dict = {}
    comptes = []
    for r in rapports:
        c = r.get("compte_execution", "?")
        comptes.append(c)
        for fam, src in (r.get("familles") or {}).items():
            for cle, v in src.items():
                vue.setdefault("%s::%s" % (fam, cle), {})[c] = v["etat"]
    candidats, couvertes, absentes = [], 0, 0
    for cle, par_compte in vue.items():
        etats = set(par_compte.values())
        if LISIBLE in etats:
            couvertes += 1
        elif etats <= {ABSENT, NON_APPLICABLE}:
            absentes += 1
        else:
            candidats.append({"source": cle, "par_compte": par_compte})
    return {"comptes": comptes, "sources": len(vue), "lisibles_par_au_moins_un": couvertes,
            "absentes_partout": absentes,
            "candidats_acl": sorted(candidats, key=lambda d: d["source"])}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — muet-ok : sortie non reconfigurable
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--profond", action="store_true",
                    help="interroge aussi l'EventLog Windows (plus lent)")
    ap.add_argument("--sortie", default="")
    ap.add_argument("--fusion", nargs="*", default=None,
                    help="croise plusieurs rapports JSON (un par compte)")
    ap.add_argument("--familles", default="",
                    help="liste separee par des virgules ; vide = toutes")
    a = ap.parse_args()
    if a.fusion is not None:
        rapports = [json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
                    for p in a.fusion]
        print(json.dumps(fusion(rapports), ensure_ascii=False, indent=1))
        return 0
    r = census(a.profond, [x for x in a.familles.split(",") if x] or None)
    if a.sortie:
        Path(a.sortie).write_text(json.dumps(r, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print("ecrit: %s" % a.sortie)
    print(json.dumps(r["resume"], ensure_ascii=False, indent=1))
    print("compte:", r["compte_execution"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
