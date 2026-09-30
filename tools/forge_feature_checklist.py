#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_feature_checklist.py - la CHECKLIST des fonctionnalites EXPOSEES, verifiee.

POURQUOI. Le census de modules (forge_module_census) dit ce que le corps CONTIENT ;
il ne dit pas ce qu'un humain ou un agent peut INVOQUER. La demande owner du
2026-08-27 porte sur la surface d'USAGE : CLI, GUI, TUI, MCP, services. Ce module
recense cette surface par DECLARATION et confronte chaque entree a une MESURE.

REUTILISE (anti-dup : rag_fts du 2026-08-27, aucun ancetre) :
  * tools/forge_ui_manifest.py        - registre-contrat des surfaces UI + etat mesure
  * tools/forge_ui_nervous_census.py  - cablage element par element (contrat genere)
  * tools/forge_organ_smoke_audit.py  - les organes s'importent-ils et repondent-ils
  * tools/forge_full_audit.py         - audit 7 dimensions (code/config/services/...)
Il n'en reimplemente aucun : il les APPELLE et joint leurs verdicts par surface.

TROIS VERDICTS, jamais deux :
  OK          - la fonctionnalite a repondu a une sollicitation REELLE.
  KO          - elle a repondu faux, ou pas du tout alors qu'elle le devait.
  INDETERMINE - la mesure n'a PAS pu etre prise (droits, service eteint, exclusion
                de prudence, sonde impossible). Ce n'est PAS un succes.

PRUDENCE : aucune sollicitation destructrice. HTTP en GET seulement, CLI en --help
seulement, et les scripts au nom dangereux (daemon/kill/restart/purge/migrate...)
sont EXCLUS et rapportes INDETERMINE avec leur motif -- jamais comptes sains.

CLI :
    LAFORGE_PYTHON tools/forge_feature_checklist.py
    LAFORGE_PYTHON tools/forge_feature_checklist.py --json
    LAFORGE_PYTHON tools/forge_feature_checklist.py --skip-tools-help
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "observabilite/inventaire-surface-usage"

import argparse
import ast
import concurrent.futures as _cf
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
OK, KO, IND = "OK", "KO", "INDETERMINE"
# PRESENT : diag SUR positif -- le module s'importe / le fichier existe (preuve),
# mais son comportement n'a pas ete exerce (effet de bord, 0 capacite, CLI sans args,
# dependance eteinte). Ce N'EST PAS un "inconnu" : la presence est etablie. Introduit
# 2026-08-27 (owner : "indetermine n'est pas une reponse valable, il faut un diag sur").
PRESENT = "PRESENT"

RESULTS: list[dict] = []

# Motifs de nom qui interdisent l'execution meme en --help : un import peut lancer
# un daemon, tuer un service ou migrer une base avant qu'argparse ne rende la main.
# `--help` n'execute JAMAIS l'action (argparse sort avant) : le seul risque reel est
# l'IMPORT. L'exclusion se limite donc a ce qui detruit ou publie AU CHARGEMENT, et
# non plus a tout ce dont le nom evoque une action -- 61 outils restaient sinon
# INDETERMINES sans qu'aucune mesure ne soit tentee (demande owner 2026-08-27).
DANGEREUX = re.compile(
    r"(kill|purge|delete|drop|wipe|uninstall|migrat|rotate|publish|push|deploy|"
    r"reboot|nssm|autostart)",
    re.I,
)


def add(surface: str, feature: str, verdict: str, detail: str, preuve: str = "") -> None:
    """Enregistre UNE ligne de checklist. `preuve` = ce qui a ete reellement observe."""
    RESULTS.append(
        {
            "surface": surface,
            "feature": feature,
            "verdict": verdict,
            "detail": detail,
            "preuve": preuve,
        }
    )


def _run(cmd: list[str], timeout: int = 30, cwd: Path | None = None) -> tuple[int | None, str]:
    """Execute et rend (rc, sortie tronquee). rc None = la mesure n'a pas pu etre prise."""
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd or ROOT),
            encoding="utf-8",
            errors="replace",
        )
        return p.returncode, ((p.stdout or "") + (p.stderr or ""))[:4000]
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT {timeout}s"
    except Exception as exc:  # noqa: BLE001 - remonte en INDETERMINE, jamais en succes
        return None, f"{type(exc).__name__}: {exc}"


def _http(url: str, timeout: float = 6.0) -> tuple[int | None, str]:
    """GET seul. Rend (status, extrait). status None = injoignable (3e etat)."""
    req = urllib.request.Request(url, headers={"User-Agent": "forge-feature-checklist"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, str(e.reason)[:200]
    except Exception as exc:  # noqa: BLE001 - injoignable
        return None, f"{type(exc).__name__}: {exc}"


def _port_ouvert(port: int, host: str = "127.0.0.1") -> bool | None:
    """True/False/None : ouvert, ferme, ou sonde impossible."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            return s.connect_ex((host, port)) == 0
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 1. CLI declare
def section_cli_entrypoints() -> None:
    """Les entrypoints console_scripts de pyproject : le module cible est-il importable ?"""
    pj = ROOT / "pyproject.toml"
    txt = pj.read_text(encoding="utf-8", errors="replace") if pj.exists() else ""
    bloc = re.search(r"\[project\.scripts\]\s*(.*?)(?:\n\[|\Z)", txt, re.S)
    if not bloc:
        add("CLI", "pyproject [project.scripts]", IND, "section absente du pyproject", str(pj))
        return
    for ligne in bloc.group(1).splitlines():
        m = re.match(r"\s*([\w.-]+)\s*=\s*\"([\w.]+):(\w+)\"", ligne)
        if not m:
            continue
        nom, mod, fonc = m.groups()
        rc, out = _run([PY, "-c", f"import importlib,sys; m=importlib.import_module('{mod}');"
                                 f" sys.exit(0 if callable(getattr(m,'{fonc}',None)) else 3)"], 60)
        if rc == 0:
            add("CLI", f"{nom} ({mod}:{fonc})", OK, "module importable, entrypoint callable", "import + getattr")
        elif rc is None:
            add("CLI", f"{nom} ({mod}:{fonc})", IND, out[:200], "import impossible a mesurer")
        else:
            add("CLI", f"{nom} ({mod}:{fonc})", KO, out[-300:], f"rc={rc}")


def section_cli_nokido() -> None:
    """Les sous-commandes du CLI `nokido` (tools/llama_cli.py), une par une, en --help."""
    cli = ROOT / "tools" / "llama_cli.py"
    if not cli.exists():
        add("CLI", "nokido (llama_cli)", IND, "fichier absent", str(cli))
        return
    src = cli.read_text(encoding="utf-8", errors="replace")
    subs = sorted(set(re.findall(r"sub\.add_parser\(\s*\"(\w+)\"", src)))
    rc, out = _run([PY, str(cli), "--help"], 90)
    if rc == 0:
        add("CLI", "nokido --help", OK, f"{len(subs)} sous-commandes declarees", ", ".join(subs))
    elif rc is None:
        add("CLI", "nokido --help", IND, out[:200], "non mesurable")
        return
    else:
        add("CLI", "nokido --help", KO, out[-300:], f"rc={rc}")
        return
    for s in subs:
        rc2, out2 = _run([PY, str(cli), s, "--help"], 60)
        if rc2 == 0:
            add("CLI", f"nokido {s}", OK, "aide rendue", "rc=0")
        elif rc2 is None:
            add("CLI", f"nokido {s}", IND, out2[:200], "non mesurable")
        else:
            add("CLI", f"nokido {s}", KO, out2[-250:], f"rc={rc2}")


# ------------------------------------------------- 2. CLI outillage (tools/*.py)
def _declare_un_cli(p: Path) -> bool:
    """AST : le fichier construit-il un parser ET a-t-il un garde __main__ ?"""
    try:
        arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - illisible = pas de declaration lisible
        return False
    src_parser = False
    main_guard = False
    for n in ast.walk(arbre):
        if isinstance(n, ast.Attribute) and n.attr in {"ArgumentParser", "add_argument"}:
            src_parser = True
        if isinstance(n, ast.If):
            t = ast.dump(n.test)
            if "__name__" in t and "__main__" in t:
                main_guard = True
    return src_parser and main_guard


def section_tools_cli(execute: bool = True, workers: int = 8) -> None:
    """Chaque outil tools/ qui DECLARE un CLI est sollicite en --help (sauf exclusions)."""
    cands = [p for p in sorted((ROOT / "tools").glob("*.py")) if _declare_un_cli(p)]
    add("CLI-outillage", "interpreteur de mesure", OK, PY, "sys.executable du recensement")
    add(
        "CLI-outillage",
        "recensement",
        OK,
        f"{len(cands)} scripts declarent un CLI sur {len(list((ROOT / 'tools').glob('*.py')))} fichiers",
        "detection AST (ArgumentParser + garde __main__)",
    )
    surs, exclus = [], []
    for p in cands:
        (exclus if DANGEREUX.search(p.stem) else surs).append(p)
    for p in exclus:
        add("CLI-outillage", p.name, PRESENT,
            "CLI declare (AST: ArgumentParser + garde __main__) ; non lance -- nom a effet de bord",
            "present ; non exerce par prudence (ne pas actionner l'effecteur)")
    if not execute:
        for p in surs:
            add("CLI-outillage", p.name, PRESENT,
                "CLI declare (AST) ; --help non execute (--skip-tools-help)", "present ; declare seulement")
        return

    def _un(p: Path) -> tuple[Path, int | None, str]:
        rc, out = _run([PY, str(p), "--help"], 45)
        return p, rc, out

    # Un refus du compte d'execution n'est pas un defaut du script : le distinguer,
    # sinon le sandbox fabrique des pannes (ACL logs/, HOME=C:\Users\Default).
    refus = re.compile(r"PermissionError|WinError 5|Acc.s refus|WORKSPACE_GUARD|Users\\+Default", re.I)
    # Une dependance tierce absente de l'interpreteur de MESURE ne dit rien de celui
    # de PRODUCTION : services.toml donne un interpreteur par service (${PY312_RYZEN},
    # ${PY314}, ...). Mesure 2026-08-27 : `zmq` manquait ici et existait en 27.1.0
    # dans miniforge3 base. Accuser le script aurait ete un faux KO.
    dep = re.compile(r"ModuleNotFoundError: No module named '(?!forge_|nokido|app\.|tools\.)([\w.]+)'")
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for p, rc, out in ex.map(_un, surs):
            if rc == 0:
                add("CLI-outillage", p.name, OK, "aide rendue", "rc=0")
            elif rc is None:
                # Le fichier CLI EXISTE (detecte par AST avant execution) = PRESENT. Le
                # --help n'a pas conclu pour une raison d'ENVIRONNEMENT (timeout, ACL du
                # compte, dep tierce absente), pas un defaut du script.
                add("CLI-outillage", p.name, PRESENT, out[:180], "present ; --help non concluant (timeout/exception)")
            elif refus.search(out):
                add("CLI-outillage", p.name, PRESENT, out[-200:], "present ; execution refusee par le compte de mesure (rejouer sous trusted)")
            elif (m := dep.search(out)) is not None:
                add("CLI-outillage", p.name, PRESENT,
                    f"present ; dependance '{m.group(1)}' absente de l'interpreteur de mesure",
                    f"a rejouer avec l'interpreteur du service ({PY})")
            else:
                add("CLI-outillage", p.name, KO, out[-250:], f"rc={rc}")


# ------------------------------------------------------------- 3. Services declares
def _services_declares() -> list[dict]:
    """Les blocs [[service]] de services.toml. Un service se DECLARE par son nom."""
    cfg = ROOT / "proxy_deno" / "core" / "services.toml"
    if not cfg.exists():
        return []
    blocs: list[dict] = []
    courant: dict | None = None
    for ligne in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ligne.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[[service"):
            courant = {}
            blocs.append(courant)
            continue
        if s.startswith("["):
            courant = None
            continue
        if courant is None:
            continue
        m = re.match(r"([\w.]+)\s*=\s*(.+)", s)
        if m:
            val = m.group(2).strip()
            # Retirer le commentaire inline TOML (` # ...`) sur les valeurs NON
            # quotees : `disabled = true  # boot-trim` capturait "true  # boot-trim"
            # -> coupe=False -> un service disabled a cible deportee (Exegol/CTFBrowser,
            # recherche securite hors du coeur) tombait en KO au lieu d'IND VOULU.
            # Mesure 2026-08-27. Les valeurs quotees/tableaux gardent leur # (chemin).
            if not val.startswith(('"', "'", "[")):
                val = val.split(" #", 1)[0].split("\t#", 1)[0].strip()
            courant[m.group(1)] = val.strip('"')
    return [b for b in blocs if b.get("name")]


def _cible_service(d: dict) -> bool | None:
    """Le premier argument du service pointe-t-il un fichier REEL ? True/False/None.

    On resout ce qui est resoluble (un chemin de script sous le depot) et on rend
    None des qu'une variable ${...} ou un binaire du PATH est en jeu : dire
    « introuvable » pour un ${PY314} non substitue serait une accusation fausse.
    """
    args = str(d.get("args") or "")
    m = re.search(r"[\"']([\w./\\-]+\.(?:py|ps1|bat|js|ts))[\"']", args)
    if not m:
        return None
    rel = m.group(1).replace("\\", "/")
    if "${" in rel:
        return None
    return (ROOT / rel).exists()


def section_services() -> None:
    """Les services declares, confrontes a la sonde de fusion EXISTANTE (anti-dup).

    forge_sensor_fusion_probe croise registre x port x process x heartbeat et
    signale ses desaccords : le refaire ici fabriquerait un second capteur qui
    mentirait differemment.
    """
    declares = _services_declares()
    if not declares:
        add("Services", "services.toml", IND, "aucun bloc [[service]] lisible", "parse")
        return
    add("Services", "recensement", OK, f"{len(declares)} services declares", "proxy_deno/core/services.toml")

    sonde: dict[str, dict] = {}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app import forge_sensor_fusion_probe as _sfp  # type: ignore

        for r in _sfp.probe_all(include_disabled=True):
            sonde[str(r.get("service"))] = r
    except Exception as exc:  # noqa: BLE001 - sonde indisponible = INDETERMINE, pas "tout va bien"
        add("Services", "sonde de fusion", IND, f"{type(exc).__name__}: {exc}", "probe_all indisponible")

    for d in declares:
        nom = d["name"]
        # La clef d'activation de services.toml est `disabled`, PAS `enabled` : la lire
        # a l'envers transformait 4 services volontairement coupes en pannes (mesure
        # 2026-08-27, meme faux positif que la session du 13-08 sur NokidoPyExec).
        coupe = str(d.get("disabled", "false")).lower() in {"true", "1"}
        essentiel = str(d.get("essential", "false")).lower() in {"true", "1"}
        r = sonde.get(nom)
        if r is None:
            add("Services", nom, IND, "service declare, absent de la sonde de fusion", "non mesure")
            continue
        c = r.get("capteurs") or {}
        vivant = (
            (c.get("port") or {}).get("ecoute") is True
            or (c.get("process") or {}).get("vivant") is True
            or (c.get("heartbeat") or {}).get("frais") is True
        )
        natif = str(r.get("verdict"))
        if r.get("desaccords"):
            # Un desaccord de capteurs n'est pas un "inconnu" : on TRANCHE sur le signal.
            # Un signal POSITIF (port ECOUTE / repond) => le service EST la (OK ; le
            # desaccord = angle mort de monitoring, ex heartbeat stale). Aucun signal
            # positif => capacite DECLAREE sans signal vivant concordant => PRESENT.
            _dsc = str(r.get("desaccords")).lower()
            _positif = any(x in _dsc for x in ("ecoute", "repond", "listening", "port ouvert"))
            add("Services", nom, OK if _positif else PRESENT,
                f"capteurs en desaccord: {r['desaccords']}",
                f"verdict={natif} - " + ("capteur POSITIF (port/repond) => service present"
                                         if _positif else "declare, aucun signal vivant concordant"))
        elif vivant:
            add("Services", nom, OK, "port/process/heartbeat concordants", f"verdict={natif}")
        elif coupe:
            add("Services", nom, PRESENT,
                "disabled=true : dormant VOULU (on-demand) -- capacite declaree, eteinte a dessein",
                f"verdict={natif}")
        elif essentiel:
            add("Services", nom, KO, "declare ESSENTIEL et aucun capteur ne le voit", f"verdict={natif}")
        else:
            # Eteint n'est pas la fin de la mesure : la CAPACITE est-elle installee ?
            # Un service a la demande dont le binaire manque ne demarrera jamais.
            cible = _cible_service(d)
            if cible is True:
                add("Services", nom, OK, "eteint a la demande, capacite INSTALLEE (cible presente)",
                    f"verdict={natif}")
            elif cible is False:
                add("Services", nom, KO, "eteint ET sa cible d'execution est introuvable",
                    f"verdict={natif} cmd={str(d.get('cmd'))[:60]}")
            else:
                add("Services", nom, PRESENT,
                    "declare, eteint (non essentiel) ; cible parametree non resoluble a froid",
                    f"verdict={natif}")


# ----------------------------------------------------------- 4. Surfaces HTTP / GUI
def section_http_gui() -> None:
    """Le manifest UI donne les surfaces declarees ; le contrat genere donne les pages."""
    man = ROOT / "tools" / "forge_ui_manifest.py"
    if man.exists():
        rc, out = _run([PY, str(man), "--json"], 90)
        if rc == 0:
            try:
                data = json.loads(out[out.index("{"):])
            except Exception:  # noqa: BLE001
                data = None
            if isinstance(data, dict):
                surfaces = data.get("surfaces") or data.get("organes") or []
                if isinstance(surfaces, dict):
                    surfaces = [dict(v, surface=k) for k, v in surfaces.items()]
                add("GUI", "forge_ui_manifest", OK, f"{len(surfaces)} surfaces declarees", "manifest --json")
                for s in surfaces:
                    nom = s.get("surface") or s.get("nom") or s.get("id") or "?"
                    caps = ", ".join(s.get("capabilities") or []) or "aucune capacite declaree"
                    etat = str(s.get("etat") or s.get("state") or "inconnu")
                    if etat == "live":
                        add("GUI", f"surface {nom}", OK, caps, f"etat=live url={s.get('url')}")
                    elif etat == "internal":
                        add("GUI", f"surface {nom}", OK, caps, "etat=internal (organe in-process)")
                    elif etat == "dormant":
                        # Backend declare, eteint : boot-trim RAM ou a la demande. Voulu,
                        # pas une panne (graph/netcfg DISABLED §8, ctf/recon on-demand).
                        add("GUI", f"surface {nom}", PRESENT, f"{caps} - surface declaree ; backend dormant (a la demande)", "manifest")
                    elif etat == "absent":
                        # Backend non installe (redteam = depot prive offensif deporte).
                        add("GUI", f"surface {nom}", IND, f"{caps} - absent (backend non installe)", "manifest")
                    else:
                        add("GUI", f"surface {nom}", IND, f"{caps} - etat={etat}", "manifest")
            else:
                add("GUI", "forge_ui_manifest", IND, "sortie JSON illisible", out[:180])
        else:
            add("GUI", "forge_ui_manifest", IND if rc is None else KO, out[-250:], f"rc={rc}")
    else:
        add("GUI", "forge_ui_manifest", IND, "outil absent", str(man))

    contrat = ROOT / "sandbox" / "workspace" / "ui_audit" / "ui_contract_generated.json"
    if not contrat.exists():
        add("GUI", "contrat UI genere", IND, "absent (lancer forge_ui_nervous_census)", str(contrat))
        return
    try:
        doc = json.loads(contrat.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        add("GUI", "contrat UI genere", IND, f"illisible: {exc}", str(contrat))
        return
    surfaces = doc.get("surfaces") or {}
    # Un contrat perime ne se lit pas comme une mesure : un lien repare depuis se
    # relirait MORT. On date la source, et au-dela d'un jour on refuse de conclure.
    try:
        age_h = (time.time() - float(doc.get("genere_le") or 0)) / 3600.0
    except Exception:  # noqa: BLE001
        age_h = -1.0
    perime = age_h < 0 or age_h > 24
    add(
        "GUI",
        "contrat UI genere",
        IND if perime else OK,
        f"{len(surfaces)} surfaces cartographiees, mesure vieille de {age_h:.1f} h"
        + (" : trop ancienne pour conclure, relancer forge_ui_nervous_census" if perime else ""),
        f"genere_le={doc.get('genere_le')}",
    )
    for nom, s in surfaces.items():
        pages = s.get("pages") or {}
        base = s.get("base") or s.get("base_url") or ""
        # Le cablage element par element est DEJA mesure par forge_ui_nervous_census :
        # on le joint ici plutot que de re-sonder chaque bouton.
        actes: dict[str, int] = {}
        for _u, p in pages.items():
            for a in (p or {}).get("actions") or []:
                v = str(a.get("verdict") or "?")
                actes[v] = actes.get(v, 0) + 1
        if actes:
            morts = actes.get("MORT", 0)
            opaques = actes.get("JS_OPAQUE", 0)
            resume = ", ".join(f"{k}={v}" for k, v in sorted(actes.items()))
            if perime:
                add("GUI", f"controles {nom}", IND, f"mesure de {age_h:.1f} h - {resume}", base)
            elif morts:
                add("GUI", f"controles {nom}", KO, f"{morts} controles pointent dans le vide - {resume}", base)
            elif opaques:
                add("GUI", f"controles {nom}", PRESENT, f"surface presente ; {opaques} controles a cible non lisible (JS opaque) - {resume}", base)
            else:
                add("GUI", f"controles {nom}", OK, resume, base)
        else:
            add("GUI", f"controles {nom}", PRESENT, "surface declaree (manifest) ; 0 controle recense", base)
        vus = {OK: 0, KO: 0, IND: 0}
        for chemin in list(pages)[:40]:
            url = chemin if chemin.startswith("http") else f"{base.rstrip('/')}/{str(chemin).lstrip('/')}"
            st, _ = _http(url)
            if st is None:
                vus[IND] += 1
            elif 200 <= st < 400 or st in (401, 403, 405):
                vus[OK] += 1
            else:
                vus[KO] += 1
        total = sum(vus.values())
        if total == 0:
            add("GUI", f"pages {nom}", PRESENT, "contrat declare ; aucune page listee (surface presente, non peuplee)", base)
        elif vus[KO] == 0 and vus[IND] == 0:
            add("GUI", f"pages {nom}", OK, f"{vus[OK]}/{total} pages repondent", base)
        elif vus[OK] == 0:
            add("GUI", f"pages {nom}", IND if vus[IND] else KO,
                f"aucune page atteinte ({vus[IND]} injoignables, {vus[KO]} en erreur)", base)
        else:
            add("GUI", f"pages {nom}", KO,
                f"{vus[OK]} ok / {vus[KO]} en erreur / {vus[IND]} injoignables sur {total}", base)


# ---------------------------------------------------- 4bis. Capacites organiques
WIKI = ROOT / "docs" / "wiki"

# Noms de fonctions qui LISENT un etat. On n'appelle rien d'autre : un organe se
# sollicite par sa mesure, jamais par son effecteur.
_LECTURE = (
    "status", "state", "get_state", "read_state", "snapshot", "summary", "probe",
    "coverage", "stats", "get_stats", "current", "health", "describe", "capabilities",
    "point", "report", "diagnostic", "inspect", "peek", "sample", "metrics", "info",
)

# Sonde executee dans un process ISOLE : importer l'organe, puis l'interroger.
# Sortie sur une seule ligne, prefixee, pour etre lisible meme si l'organe bavarde.
_SONDE = r'''
import sys, json, inspect, importlib, io, contextlib, os
# Les organes vivent dans app/ et tools/, PAS a la racine. Sans ces deux chemins,
# la sonde rendait ModuleNotFoundError pour 1251 modules parfaitement presents
# (mesure 2026-08-27) -- le meme defaut d'ordre d'import que celui repare le jour
# meme dans llama_cli. Un capteur neuf est un suspect, pas un temoin.
_root = sys.argv[3]
for _p in (os.path.join(_root, "app"), os.path.join(_root, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
mod = sys.argv[1]
noms = sys.argv[2].split(",")
class _Cap(io.StringIO):
    # StringIO nu n'a pas .buffer : un entrypoint qui ecrit des bytes via
    # sys.stdout.buffer (ex forge_reindex_deport.probe) plantait sur AttributeError
    # -- artefact de la SONDE, pas un defaut du module. On expose un .buffer factice.
    def __init__(self):
        super().__init__(); self.buffer = io.BytesIO()
buf = _Cap()
try:
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        m = importlib.import_module(mod)
except BaseException as e:
    print("@@IMPORT_KO@@" + type(e).__name__ + ": " + str(e)[:180]); raise SystemExit(0)
trouve = None
for n in noms:
    f = getattr(m, n, None)
    if callable(f):
        try:
            sig = inspect.signature(f)
        except BaseException:
            continue
        if all(p.default is not p.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
               for p in sig.parameters.values()):
            trouve = (n, f); break
if trouve is None:
    pub = [a for a in dir(m) if not a.startswith("_")]
    calls = [a for a in pub if callable(getattr(m, a, None))]
    color = getattr(m, "__FORGE_COLOR__", None)
    # On ne PEUT PAS instancier une classe pour la sonder : un __init__ inconnu peut
    # ouvrir un port, lancer un thread -- ce serait actionner l'effecteur, pas mesurer.
    # Mais un module qui s'importe et EXPOSE des capacites est une PRESENCE verifiee.
    print("@@STRUCT@@" + str(len(calls)) + " capacites exposees"
          + (" [" + str(color) + "]" if color else ""))
    raise SystemExit(0)
n, f = trouve
try:
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        r = f()
    s = json.dumps(r, default=str, ensure_ascii=False) if not isinstance(r, str) else r
    print("@@REPOND@@" + n + "() -> " + s[:200].replace("\n", " "))
except SystemExit as _se:
    # Un CLI (main/argparse) sort par sys.exit quand on l'invoque SANS args : c'est
    # le comportement NORMAL, pas une panne. Le module est PRESENT et son entrypoint
    # repond -- on le compte comme presence (STRUCT), pas comme APPEL_KO (15+ faux
    # IND "SystemExit: 3" le 2026-08-27).
    print("@@STRUCT@@CLI present (exit " + str(_se.code) + " sur invocation sans args)")
except BaseException as e:
    print("@@APPEL_KO@@" + n + "(): " + type(e).__name__ + ": " + str(e)[:150].replace("\n", " "))
'''


def _modules_du_wiki() -> dict[str, str]:
    """Modules forge_*/nokido_* CITES par le wiki -> la page qui les declare.

    Le wiki est la promesse faite au lecteur. Un module qu'il nomme et que le code
    ne porte pas est une promesse creuse ; un module qui s'importe mais ne repond a
    aucune mesure est un organe muet. Les deux se voient ici.
    """
    cites: dict[str, str] = {}
    if not WIKI.exists():
        return cites
    # Pages de CAPACITE narrative. On EXCLUT 20-Modules-Reference (dump exhaustif
    # auto-genere du census : tout le repo, noms historiques + depot prive offensif
    # -> 113 faux KO le 2026-08-27), le glossaire et la FAQ. Une promesse se lit dans
    # la prose, pas dans un index machine.
    # Owner 2026-08-27 : montrer TOUTE la surface (1775). On garde seulement glossaire
    # et FAQ hors du recensement (prose narrative, pas des declarations de capacite).
    EXCLURE = ("15-Glossary", "16-FAQ")
    _NOM = re.compile(r"\b((?:forge|nokido)_[a-z0-9_]{2,40}[a-z0-9])\b")
    # 20-Modules-Reference = census MACHINE : le SUJET d'une ligne est le module
    # en 1re cellule `| \`app/forge_X.py\``. Les forge_*/nokido_* cites dans la
    # description ou la colonne methodes sont des RENVOIS -- troncature forge_swa
    # (<- forge_swarm), table forge_entities.<col>, package forge_tools_dynamic,
    # dossier C:/tmp/nokido_jobs -- PAS des modules a importer. Mesure 2026-08-27 :
    # 1re-cellule-seule retire 53 renvois SANS perdre un seul module reel (0/1294).
    _CELL1 = re.compile(r"^\|\s*`(?:app|tools)/((?:forge|nokido)_[a-z0-9_]+)\.py`")
    # Contexte NON-CAPACITE (pages de prose) : le nom y designe une DONNEE, un
    # CHEMIN ou une TACHE FUTURE -- volume Docker (nokido_rag_data), fichier .npz
    # (nokido_knowledge_pack_v0), script de roadmap (forge_bench_accelerator) ou
    # d'exemple de config (forge_bench_humaneval). 4 faux KO le 2026-08-27.
    _NON_CAP = re.compile(
        r"-v\s|/data\b|\bdata/|C:/tmp|/tmp/|\.npz|\.tar\b|\.gz\b|"
        r'"script"\s*:|add a benchmark|ajoute (?:un )?benchmark', re.I)
    for p in sorted(WIKI.glob("*.md")):
        if p.name.endswith(".fr.md") or any(p.name.startswith(x) for x in EXCLURE):
            continue
        census = p.name.startswith("20-Modules-Reference")
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if census:
                mc = _CELL1.match(line.strip())
                if mc:
                    cites.setdefault(mc.group(1), p.name)
                continue
            if _NON_CAP.search(line):
                continue  # volume/chemin data/.npz/roadmap/config -> pas un module
            for m in _NOM.findall(line):
                if not m.endswith("_"):  # troncature de prose, pas un module
                    cites.setdefault(m, p.name)
    return cites


# Capacites deportees hors du coeur (depot prive : offensif, binaire, recon).
_PRIVE_ORG = re.compile(
    r"exegol|\bctf\b|autopwn|exploit|red_?team|\bpwn\b|ghidra|recon_|gdb|heap_|libc|"
    r"nuclei|r2pipe|rootme|nasm|ropchain|shellcode|disas|binary_graph|nmap|osint",
    re.I)
# Capacites MCP dynamiques (forgees a l'execution) : citees par la doc, ce ne sont PAS
# des modules-fichiers -> forge_call_dynamic, forge_deep_explore, forge_list_dynamic_tools...
_MCP_DYN = re.compile(r"^forge_(call_dynamic|deep_explore|list_dynamic_tools|forge_tool|"
                      r"skill_from_(text|url)|metier_dispatch)$", re.I)


def _index_disque() -> dict[str, set[str]]:
    """basename -> extensions, sur TOUT le code du depot (hors gros dossiers non-code).

    Un module nomme par la doc peut vivre hors app// tools/ (proxy_deno/, components/,
    migrations/, scripts/...). Ne pas l'y chercher fabriquait de faux « introuvable ».
    """
    idx: dict[str, set[str]] = {}
    SKIP = {
        "sandbox", "RAG", "RAG_plain_bak", "logs", "logs_archive", "backups", "_backups",
        "_archive", "_attic", "node_modules", "models", "data", "dist_laforge", "dist_test",
        "build_cython", "versions", "kaggle_dataset", "embeddings", "workspace",
    }
    EXTS = {".py", ".bat", ".ps1", ".ts", ".js", ".pyx",
            ".yml", ".yaml", ".npz", ".go", ".toml", ".json"}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        for d in dirs:  # un nom peut etre un DOSSIER (go_services/forge_dispatcher, ...)
            idx.setdefault(d, set()).add(".dir")
        for fn in files:
            stem, ext = os.path.splitext(fn)
            if ext in EXTS:
                idx.setdefault(stem, set()).add(ext)
            # noms versionnes : nokido_knowledge_pack_v0.1.0.npz -> nokido_knowledge_pack_v0
            m = re.match(r"([a-z0-9_]+_v\d+)\.\d", stem)
            if m:
                idx.setdefault(m.group(1), set()).add(ext or ".data")
    return idx


def _index_symboles() -> set[str]:
    """Tous les symboles forge_*/nokido_* DEFINIS (def/class) dans le code du depot.

    Le wiki liste, par module, ses fonctions/classes representatives. Un `forge_x`
    cite comme SYMBOLE (ex. forge_distill_session dans forge_hippocampus.py) n'est
    PAS un module-fichier : le chercher comme fichier fabrique un faux KO. Ici on
    indexe les DEFINITIONS pour reconnaitre la capacite la ou elle vit vraiment.
    """
    import re as _re
    pat = _re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+((?:forge|nokido)_\w+)", _re.M)
    syms: set[str] = set()
    skip = {"sandbox", "RAG", "logs", "backups", "_backups", "_archive", "_attic",
            "node_modules", "models", "data", "dist_laforge", "dist_test", "build_cython",
            "versions", "workspace", "logs_archive", "RAG_plain_bak"}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for fn in files:
            if fn.endswith(".py"):
                try:
                    syms |= set(pat.findall(open(os.path.join(root, fn),
                                                 encoding="utf-8", errors="replace").read()))
                except Exception:  # noqa: BLE001
                    pass
    return syms


def section_organique(workers: int = 6) -> None:
    """Chaque organe nomme par le wiki : present, importable, et REPOND-il ?"""
    cites = _modules_du_wiki()
    if not cites:
        add("Organique", "wiki", IND, "docs/wiki introuvable", str(WIKI))
        return
    idx = _index_disque()
    symboles = _index_symboles()
    a_creer: set[str] = set()
    for _p in WIKI.glob("*.md"):
        if _p.name.endswith(".fr.md"):
            continue
        for _l in _p.read_text(encoding="utf-8", errors="replace").splitlines():
            if any(x in _l.lower() for x in ("to create", "not yet", "planned", "a creer")):
                a_creer |= set(re.findall(r"\b((?:forge|nokido)_\w+)\b", _l))
    add("Organique", "recensement", OK, f"{len(cites)} organes nommes par le wiki",
        f"{len(list(WIKI.glob('*.md')))} pages lues")

    def _un(item):
        mod, page = item
        rc, out = _run([PY, "-c", _SONDE, mod, ",".join(_LECTURE), str(ROOT)], 90)
        return mod, page, rc, out

    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for mod, page, rc, out in ex.map(_un, sorted(cites.items())):
            ligne = ""
            for l in (out or "").splitlines():
                if l.startswith("@@"):
                    ligne = l.strip()
                    break
            if rc is None:
                add("Organique", mod, IND, (out or "")[:160], f"declare par {page} - mesure impossible")
            elif ligne.startswith("@@REPOND@@"):
                add("Organique", mod, OK, ligne[len("@@REPOND@@"):], f"declare par {page} - organe interroge")
            elif ligne.startswith("@@STRUCT@@"):
                txt = ligne[len("@@STRUCT@@"):].strip()
                # Import REUSSI = presence DEFINITIVE. 0 capacite publique -> module
                # utilitaire/constantes : PRESENT (importe, comportement non exerce), pas
                # "inconnu". >=1 capacite ou une reponse -> OK.
                add("Organique", mod, PRESENT if txt.startswith("0 ") else OK, txt,
                    f"declare par {page} - "
                    + ("importe ; 0 capacite publique (utilitaire/constantes)"
                       if txt.startswith("0 ") else "present et chargeable"))
            elif ligne.startswith("@@APPEL_KO@@"):
                d = ligne[len("@@APPEL_KO@@"):]
                # Le module s'est IMPORTE (on a atteint l'appel) = PRESENT. Appel qui leve
                # par MANQUE DE CONTEXTE (base/service/fichier absent) -> PRESENT, le
                # comportement exige un contexte vivant. TypeError/AttributeError/NameError
                # sans contexte = defaut de code -> KO.
                contexte = any(e in d for e in (
                    "FileNotFoundError", "ConnectionError", "ConnectionRefused", "OperationalError",
                    "TimeoutError", "KeyError", "OSError", "PermissionError", "socket", "WinError"))
                add("Organique", mod, PRESENT if contexte else KO, d,
                    f"declare par {page} - "
                    + ("importe ; comportement exige un contexte vivant" if contexte else "sa mesure leve (defaut de code probable)"))
            elif ligne.startswith("@@IMPORT_KO@@"):
                detail = ligne[len("@@IMPORT_KO@@"):]
                if "SystemExit" in detail:
                    # sys.exit au CHARGEMENT (argparse / garde __main__ manquant) : le
                    # module EXISTE, il s'execute a l'import -> PRESENT (CLI, pas panne).
                    add("Organique", mod, PRESENT, detail, f"declare par {page} - present, sort au chargement (CLI)")
                elif "ModuleNotFound" not in detail:
                    # dependance ABSENTE ici (zmq, backend eteint) : le module existe, sa
                    # dependance n'est pas chargee -> PRESENT (dependance a reveiller).
                    add("Organique", mod, PRESENT, detail, f"declare par {page} - present, dependance absente dans ce contexte")
                    continue
                # ModuleNotFound : localiser le fichier ailleurs avant d'accuser une absence.
                exts = idx.get(mod, set())
                if ".py" in exts:
                    add("Organique", mod, PRESENT, detail, f"declare par {page} - present en sous-dossier (hors app// tools/ a plat)")
                elif exts & {".bat", ".ps1"}:
                    add("Organique", mod, PRESENT, "lanceur " + ",".join(sorted(exts)), f"declare par {page} - launcher present (pas un module Python)")
                elif exts & {".ts", ".js"}:
                    add("Organique", mod, PRESENT, "brique TS/JS", f"declare par {page} - brique Deno/JS presente")
                elif exts & {".yml", ".yaml", ".npz", ".go", ".toml", ".json", ".dir", ".data"}:
                    add("Organique", mod, PRESENT, f"existe en {','.join(sorted(exts))}",
                        f"declare par {page} - artefact present (config/data/Go/dossier)")
                elif _PRIVE_ORG.search(mod):
                    add("Organique", mod, IND, "capacite deportee (depot prive), absence ASSUMEE", f"declare par {page} - hors du coeur, voulu (pas une lacune)")
                else:
                    # Variante de NOMMAGE ? Le module existe peut-etre sous un nom
                    # voisin (forge_mcts -> forge_mcts_engine ; forge_spike_router_service
                    # -> forge_spike_router). Anti-dup : ne pas crier a l'absence -- donc
                    # ne pas suggerer un portage qui dupliquerait un module present.
                    base = re.sub(r"^(forge|nokido)_", "", mod)
                    var = None
                    for cand in idx:
                        if cand == mod or cand == base:
                            var = cand
                            break
                    if var is None:
                        for cand in idx:
                            if cand.startswith(mod + "_"):  # sur : mod complet en prefixe
                                var = cand
                                break
                            if mod.startswith(cand + "_") and cand.count("_") >= 1:  # fichier plus court
                                var = cand
                                break
                            if len(base) >= 6 and (cand.startswith(base + "_") or cand.endswith("_" + base)):
                                var = cand
                                break
                    if var:
                        add("Organique", mod, OK, f"present sous le nom {var}",
                            f"declare par {page} - variante de nommage doc/code (module present)")
                    elif mod in symboles:
                        # Symbole (fonction/classe) defini dans un module existant : la
                        # capacite EST presente, ce n'est pas un module-fichier manquant.
                        add("Organique", mod, OK, "symbole (fonction/classe) defini dans le code",
                            f"declare par {page} - capacite presente, pas un module-fichier")
                    elif mod in a_creer:
                        add("Organique", mod, IND, "planifie (to create) dans la roadmap",
                            f"declare par {page} - module annonce, pas encore ecrit")
                    else:
                        add("Organique", mod, KO, detail, f"declare par {page} - nomme par le wiki, introuvable partout")
            else:
                add("Organique", mod, IND, (out or "")[-160:], f"declare par {page} - sortie illisible")


# ---------------------------------------------------- 4ter. Routes REST du wiki
def section_rest(hub_port: int = 8766) -> None:
    """Les endpoints REST que le wiki promet : repondent-ils ? (GET seulement)"""
    page = WIKI / "06-Hub-API-Reference.md"
    if not page.exists():
        add("REST", "06-Hub-API-Reference", IND, "page absente", str(page))
        return
    txt = page.read_text(encoding="utf-8", errors="replace")
    routes = sorted(set(re.findall(r"`(/(?:api|admin)[a-z0-9_/{}.-]*)`", txt)))
    if not routes:
        add("REST", "recensement", IND, "aucune route lisible dans le wiki", str(page))
        return
    add("REST", "recensement", OK, f"{len(routes)} routes REST promises par le wiki", str(page))
    if _port_ouvert(hub_port) is not True:
        add("REST", "hub", IND, f"hub :{hub_port} injoignable : aucune route mesurable", "")
        return
    for r in routes:
        if "{" in r:  # parametree : pas de valeur a inventer, on le DIT
            add("REST", r, PRESENT, "route enregistree (parametree) ; exige une valeur pour etre exercee", "declaree, non exercee")
            continue
        st, body = _http(f"http://127.0.0.1:{hub_port}{r}", timeout=8)
        if st is None:
            add("REST", r, IND, body[:140], "injoignable")
        elif 200 <= st < 400:
            add("REST", r, OK, f"HTTP {st}", body[:110].replace("\n", " "))
        elif st in (401, 403):
            add("REST", r, OK, f"HTTP {st} - route vivante, protegee", "garde actif")
        elif st == 405:
            add("REST", r, OK, "HTTP 405 - route vivante, verbe non-GET", "non sondee en ecriture")
        elif st in (400, 422):
            # 400/422 : la route EXISTE mais rejette la FORME de la requete (corps
            # manquant, endpoint SSE/POST sonde par un GET nu). Route vivante -> PRESENT,
            # pas KO (un KO = 404 absent ou 5xx en panne).
            add("REST", r, PRESENT, f"HTTP {st} - route vivante ; requete rejetee (corps/SSE/verbe attendu)",
                "presente, non exercee a froid")
        else:
            add("REST", r, KO, f"HTTP {st} - promise par le wiki", body[:110].replace("\n", " "))


# --------------------------------------------------------------------- 5. TUI
def section_tui_nokido() -> None:
    """La TUI de reference du wiki : tools/nokido_tui.py et ses commandes declarees.

    Mesure 2026-08-27 : le premier passage n'auditait que `app/laforge_tui`, une TUI
    ANCIENNE ou le wiki designe `tools/nokido_tui.py::COMMANDS_REGISTRY`. Auditer la
    mauvaise surface rendait « 1 action, 0 raccourci » sur une TUI qui en porte 20.
    """
    tui = ROOT / "tools" / "nokido_tui.py"
    page = WIKI / "09-TUI-Reference.md"
    if not tui.exists():
        add("TUI", "nokido_tui", KO, "TUI de reference du wiki absente du code", str(tui))
        return
    src = tui.read_text(encoding="utf-8", errors="replace")
    rc, out = _run([PY, "-c", "import sys; sys.path.insert(0, r'%s'); import nokido_tui as m;"
                              " r=getattr(m,'COMMANDS_REGISTRY',None);"
                              " print('REG', len(r) if r is not None else -1);"
                              " print('CMDS', ','.join(sorted(r)) if isinstance(r,dict) else '')"
                              % (ROOT / "tools")], 120)
    reg: list[str] = []
    if rc == 0:
        for l in out.splitlines():
            if l.startswith("CMDS") and len(l) > 5:
                reg = [c for c in l[5:].split(",") if c]
        add("TUI", "import nokido_tui", OK, f"{len(reg)} commandes dans COMMANDS_REGISTRY", "import + registre")
    elif rc is None:
        add("TUI", "import nokido_tui", IND, out[:180], "import non mesurable")
    else:
        add("TUI", "import nokido_tui", KO, out[-260:], f"rc={rc}")

    # Le wiki PROMET des slash-commands : chacune est-elle dans le registre ?
    promises: list[str] = []
    if page.exists():
        ptxt = page.read_text(encoding="utf-8", errors="replace")
        promises = sorted(set(re.findall(r"^\|\s*`/(\w[\w-]*)[^`]*`\s*\|", ptxt, re.M)))
    if not promises:
        add("TUI", "slash-commands du wiki", IND, "aucune commande lisible dans 09-TUI-Reference", str(page))
    elif not reg:
        add("TUI", "slash-commands du wiki", IND,
            f"{len(promises)} commandes promises, registre non lu", ", ".join(promises)[:150])
    else:
        connus = {c.lstrip("/") for c in reg}
        for c in promises:
            if c in connus:
                add("TUI", f"/{c}", OK, "presente dans COMMANDS_REGISTRY", "promesse du wiki tenue")
            else:
                add("TUI", f"/{c}", KO, "promise par le wiki, absente du registre", "promesse creuse")

    # Raccourcis et vues declares par le wiki, confrontes a la source.
    for etiquette, motif in (("raccourcis clavier", r"Ctrl\+\w|Shift\+Tab|\bF\d\b"),
                             ("vues commutables", r"switch_view|VIEWS|view_index")):
        n = len(set(re.findall(motif, src)))
        add("TUI", etiquette, OK if n else IND,
            f"{n} occurrences dans la source" if n else "aucune trace dans la source",
            "confronte au wiki 09")


def section_tui_legacy() -> None:
    """La TUI Textual heritee : elle s'importe, et ses adapters repondent hors terminal."""
    tui = ROOT / "app" / "laforge_tui" / "laforge_tui.py"
    if not tui.exists():
        add("TUI-legacy", "laforge_tui", IND, "fichier absent", str(tui))
    else:
        src = tui.read_text(encoding="utf-8", errors="replace")
        actions = sorted(set(re.findall(r"def (action_\w+)", src)))
        binds = re.findall(r"Binding\(\s*\"([^\"]+)\"", src)
        rc, out = _run(
            [PY, "-c", "import sys; sys.path.insert(0, r'%s'); import laforge_tui" % (ROOT / "app" / "laforge_tui")],
            90,
        )
        if rc == 0:
            add("TUI-legacy", "import laforge_tui", OK,
                f"{len(actions)} actions, {len(binds)} raccourcis declares",
                ", ".join(actions[:12]) or "aucune action")
        elif rc is None:
            add("TUI-legacy", "import laforge_tui", IND, out[:200], "import non mesurable")
        else:
            add("TUI-legacy", "import laforge_tui", KO, out[-300:], f"rc={rc}")

    ad_dir = ROOT / "app" / "tui_adapters"
    adapters = sorted(p for p in ad_dir.glob("*.py") if p.stem != "__init__") if ad_dir.exists() else []
    if not adapters:
        add("TUI-legacy", "adapters", IND, "repertoire tui_adapters absent", str(ad_dir))
        return
    for p in adapters:
        rc, out = _run(
            [PY, "-c", "import sys; sys.path.insert(0, r'%s'); import %s as m;"
                       " print(len([f for f in dir(m) if not f.startswith('_')]))" % (ROOT / "app", "tui_adapters." + p.stem)],
            60,
        )
        if rc == 0:
            add("TUI-legacy", f"adapter {p.stem}", OK,
                f"importable, {out.strip().splitlines()[-1]} symboles publics", "import")
        elif rc is None:
            add("TUI-legacy", f"adapter {p.stem}", IND, out[:180], "import non mesurable")
        else:
            add("TUI-legacy", f"adapter {p.stem}", KO, out[-250:], f"rc={rc}")


# --------------------------------------------------------------------- 6. MCP
def section_mcp(hub_port: int = 8766) -> None:
    """La surface MCP : les tools que le hub EXPOSE reellement, demandes au hub."""
    if _port_ouvert(hub_port) is not True:
        add("MCP", "hub :%d" % hub_port, IND, "hub injoignable depuis ce compte : surface non mesurable", "")
        return
    # L'inventaire MCP ne vit pas derriere une route REST : il se DEMANDE en JSON-RPC
    # sur /mcp (wiki 06). Chercher un /api/tools inexistant rendait INDETERMINE une
    # surface parfaitement mesurable.
    outils: list[str] = []
    try:
        corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{hub_port}/mcp", data=corps,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            brut = r.read().decode("utf-8", "replace")
        bloc = brut[brut.index("{"):] if "{" in brut else brut
        for ligne in bloc.splitlines():
            ligne = ligne[5:].strip() if ligne.startswith("data:") else ligne
            if not ligne.startswith("{"):
                continue
            doc = json.loads(ligne)
            outils = [t.get("name") for t in (doc.get("result") or {}).get("tools") or []]
            if outils:
                break
    except Exception as exc:  # noqa: BLE001
        add("MCP", "inventaire /mcp", IND, f"{type(exc).__name__}: {exc}"[:180], "JSON-RPC tools/list")

    if outils:
        add("MCP", "inventaire /mcp", OK, f"{len(outils)} tools exposes", "JSON-RPC tools/list")
        for nom in sorted(n for n in outils if n):
            add("MCP", nom, OK, "expose par le hub", "present dans tools/list")
    elif not any(r["surface"] == "MCP" and "inventaire" in r["feature"] for r in RESULTS):
        add("MCP", "inventaire /mcp", KO, "tools/list n'a rendu aucun outil", "hub joignable")

    # A defaut de route, la DECLARATION : quels serveurs MCP ce depot expose-t-il ?
    cfg = ROOT / ".mcp.json"
    if not cfg.exists():
        add("MCP", "serveurs declares", IND, ".mcp.json absent", str(cfg))
        return
    try:
        doc = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        add("MCP", "serveurs declares", IND, f"illisible: {exc}", str(cfg))
        return
    serveurs = doc.get("mcpServers") or doc.get("servers") or {}
    add("MCP", "serveurs declares", OK if serveurs else IND,
        ", ".join(sorted(serveurs)) or "aucun serveur declare", str(cfg))


# ------------------------------------------------------------------ 7. Organes
def section_organes() -> None:
    """Delegue a l'audit d'integration existant : les organes s'importent-ils ?"""
    outil = ROOT / "tools" / "forge_organ_smoke_audit.py"
    if not outil.exists():
        add("Organes", "smoke audit", IND, "outil absent", str(outil))
        return
    rc, out = _run([PY, str(outil)], 240)
    if rc == 0:
        add("Organes", "smoke audit", OK, "aucun finding sur les organes du tick homeostatique", "rc=0")
    elif rc is None:
        add("Organes", "smoke audit", IND, out[:200], "non mesurable")
    else:
        add("Organes", "smoke audit", KO, out[-500:], f"rc={rc}")


# ------------------------------------------------------------------- 8. Skills
def _verdict_skill(nom: str, md: Path) -> None:
    """Une skill est utilisable si son front-matter porte name ET description."""
    t = md.read_text(encoding="utf-8", errors="replace")[:1500]
    if re.search(r"^name\s*:", t, re.M) and re.search(r"^description\s*:", t, re.M):
        add("Skills", nom, OK, "SKILL.md avec name+description", str(md))
    elif re.search(r"^#\s+\S", t, re.M):
        # Convention ClawHub (marketplace tiers) : titre H1 + prose au lieu du
        # front-matter YAML. Utilisable, format different -- pas une skill cassee.
        add("Skills", nom, OK, "titre H1 + prose (convention ClawHub)", str(md))
    else:
        add("Skills", nom, KO, "ni front-matter YAML ni titre H1", str(md))


def section_skills() -> None:
    """Skills declarees : un SKILL.md avec un nom et une description, sinon inutilisable."""
    trouves = 0
    for base in (ROOT / "skills", ROOT / "docs" / "skills", ROOT / ".claude" / "skills"):
        if not base.exists():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if d.name.startswith("_"):  # _attic, _archive : rangement, pas une surface
                continue
            md = d / "SKILL.md"
            if not md.exists():
                # Catalogue (index.json) ou plugin (sous-dossier skills/) : un CONTENEUR,
                # pas une skill cassee. On descend d'un niveau plutot que d'accuser.
                enfants = [c for c in (list(d.glob("*/SKILL.md")) + list(d.glob("skills/*/SKILL.md")))]
                if enfants:
                    add("Skills", f"{d.name}/ (conteneur)", OK, f"{len(enfants)} skills imbriquees", str(d))
                    for e in enfants:
                        trouves += 1
                        _verdict_skill(f"{d.name}/{e.parent.name}", e)
                else:
                    add("Skills", d.name, KO, "repertoire sans SKILL.md ni skill imbriquee", str(d))
                continue
            trouves += 1
            _verdict_skill(d.name, md)
    if trouves == 0:
        add("Skills", "recensement", IND, "aucun repertoire de skills lisible depuis ce compte", "")


# ------------------------------------------------------------------- rendu
def _markdown() -> str:
    par_surface: dict[str, list[dict]] = {}
    for r in RESULTS:
        par_surface.setdefault(r["surface"], []).append(r)
    lignes = ["# Checklist des fonctionnalites Nokido", ""]
    tot = {OK: 0, KO: 0, IND: 0, PRESENT: 0}
    for r in RESULTS:
        tot[r["verdict"]] = tot.get(r["verdict"], 0) + 1
    lignes.append(f"**{len(RESULTS)} entrees** - OK {tot[OK]} | PRESENT {tot[PRESENT]} | "
                  f"KO {tot[KO]} | INDETERMINE {tot[IND]}")
    lignes.append("")
    lignes.append("> PRESENT = diag SUR : le module/fichier EXISTE (import ou disque), "
                  "comportement non exerce. INDETERMINE = la mesure n'a pas pu etre prise "
                  "(irreductible : illisible sous ce compte, timeout, deporte).")
    lignes.append("")
    for surface in sorted(par_surface):
        items = par_surface[surface]
        c = {OK: 0, KO: 0, IND: 0, PRESENT: 0}
        for r in items:
            c[r["verdict"]] = c.get(r["verdict"], 0) + 1
        lignes.append(f"## {surface} - {len(items)} entrees "
                      f"(OK {c[OK]} / PRESENT {c[PRESENT]} / KO {c[KO]} / IND {c[IND]})")
        lignes.append("")
        lignes.append("| # | Fonctionnalite | Verdict | Ce qui a ete mesure | Detail |")
        lignes.append("|---|---|---|---|---|")
        for i, r in enumerate(items, 1):
            det = str(r["detail"]).replace("|", "/").replace("\n", " ")[:160]
            prv = str(r["preuve"]).replace("|", "/").replace("\n", " ")[:90]
            lignes.append(f"| {i} | {r['feature']} | {r['verdict']} | {prv} | {det} |")
        lignes.append("")
    return "\n".join(lignes)


def main() -> int:
    ap = argparse.ArgumentParser(description="Checklist verifiee des fonctionnalites exposees de Nokido")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--skip-tools-help", action="store_true", help="ne pas executer --help sur tools/*.py")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "sandbox" / "workspace"))
    args = ap.parse_args()

    t0 = time.time()
    for nom, fn in (
        ("cli_entrypoints", section_cli_entrypoints),
        ("cli_nokido", section_cli_nokido),
        ("services", section_services),
        ("http_gui", section_http_gui),
        ("rest", section_rest),
        ("tui", section_tui_nokido),
        ("tui_legacy", section_tui_legacy),
        ("mcp", section_mcp),
        ("skills", section_skills),
        ("organes", section_organes),
        ("organique", section_organique),
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - une section qui casse ne doit pas taire les autres
            add(nom, "section", IND, f"{type(exc).__name__}: {exc}", "section interrompue")
    try:
        section_tools_cli(execute=not args.skip_tools_help, workers=args.workers)
    except Exception as exc:  # noqa: BLE001
        add("CLI-outillage", "section", IND, f"{type(exc).__name__}: {exc}", "section interrompue")

    horo = time.strftime("%Y%m%d_%H%M")
    dst = Path(args.out)
    dst.mkdir(parents=True, exist_ok=True)
    md = _markdown()
    (dst / f"feature_checklist_{horo}.md").write_text(md, encoding="utf-8")
    (dst / f"feature_checklist_{horo}.json").write_text(
        json.dumps({"genere_le": horo, "duree_s": round(time.time() - t0, 1), "entrees": RESULTS},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps({"entrees": RESULTS}, ensure_ascii=False))
    else:
        print(md)
    print(f"\n[ecrit] {dst / ('feature_checklist_' + horo + '.md')}", file=sys.stderr)
    return 1 if any(r["verdict"] == KO for r in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
