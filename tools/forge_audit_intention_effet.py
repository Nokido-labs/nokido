"""forge_audit_intention_effet.py — ce qui tourne porte-t-il une INTENTION et un EFFET ?

Demande owner du 2026-08-25 : « ce qui n'est pas utile a l'instant T ne devrait pas
tourner ; l'autoregulation doit couper ce qui ne porte pas d'intention reelle AVEC effet ;
couvrir l'INTEGRALITE de ce qui tourne ».

CE QU'IL AJOUTE, et que rien d'autre ne couvre (verifie avant ecriture) :
  - `forge_process_inventory` dit QUI tourne et ce qu'on n'arrive pas a voir ;
  - `forge_regulation_efficacy` dit a quel DEBIT les effecteurs tirent vs leur budget ;
  - `forge_regulation_loops` dit le debit THEORIQUE d'apres les parametres declares ;
  - `forge_body_regulation_audit` classe les MODULES (REGULE/SUPERVISE/ZONE_MORTE).
Aucun ne croise, par unite VIVANTE : le cout engage, l'intention qui la reclame, et
l'effet date qu'elle produit. C'est le seul angle depuis lequel « couper ce qui ne sert
pas » devient une decision et non une impression.

TROIS PRECAUTIONS, dites d'avance parce qu'elles changent les chiffres :
  1. COUT = `private` (engagement anonyme), JAMAIS `rss`. Mesure du 2026-08-25 : qdrant
     affichait 4,48 Go de rss pour 0,14 Go engages — le reste etait du cache de fichiers,
     que l'OS reprend seul. Imputer sur `rss` surestime massivement et designe des
     coupables innocents.
  2. EFFET = une trace DATEE (heartbeat frais, connexion etablie, acte de regulation).
     L'absence d'effet n'est PAS une preuve d'inutilite : c'est une absence de PREUVE
     d'utilite. Le verdict distingue les deux, il ne les fond pas.
  3. ILLISIBLE est un TROISIEME etat. Chaque compteur imprime son denominateur.

Cet outil n'agit sur rien. Il DESIGNE, avec un cout chiffre, et laisse la decision.

Usage : LAFORGE_PYTHON tools/forge_audit_intention_effet.py
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

__FORGE_COLOR__ = "sympathique/interoception-intention"

import collections
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "sandbox")
FRAIS_S = 900.0            # heartbeat / drapeau d'intention encore frais
SUPERVISEUR = "http://127.0.0.1:8765/supervisor/status"

# Les CINQ drapeaux d'intention reellement implementes (get_active_intents).
# Cinq, pour ~54 services declares : c'est la mesure de l'approximation, pas un detail.
FLAGS = {"docker.wanted": "docker", "llama.wanted": "llama",
         "lmstudio.wanted": "lmstudio", "rerank.wanted": "rerank",
         "embed.wanted": "embed"}


def _processus() -> tuple[dict, int]:
    procs, illisibles = {}, 0
    for p in psutil.process_iter(["pid", "name", "memory_info", "create_time", "ppid"]):
        try:
            mi = p.info["memory_info"]
            up = max(1.0, time.time() - p.info["create_time"])
            # EFFET DANS LE TEMPS, pas a l'instant t. Le temps CPU consomme depuis le
            # demarrage est CUMULE : il ne peut pas etre rate entre deux rafales, la ou
            # un comptage de connexions ETABLIES l'est systematiquement. Mesure du
            # 2026-08-25 : le sidecar Qdrant, qui SERT la recherche dense (prouve la
            # minute d'avant), ressortait « sans effet » sur le seul critere reseau.
            try:
                ct = p.cpu_times()
                cpu_s = float(ct.user + ct.system)
            except Exception:  # noqa: BLE001
                cpu_s = -1.0       # illisible, surtout pas 0.0
            procs[p.info["pid"]] = {
                "nom": p.info["name"] or "?",
                "prive": float(getattr(mi, "private", 0) or 0),
                "ppid": p.info["ppid"],
                "depuis_h": up / 3600.0,
                "cpu_s": cpu_s,
                "cpu_part": (cpu_s / up) if cpu_s >= 0 else None,
            }
        except Exception:  # noqa: BLE001 - muet-ok : compte en ILLISIBLE juste apres
            illisibles += 1
    return procs, illisibles


def _registre() -> tuple[dict, str | None]:
    try:
        with urllib.request.urlopen(SUPERVISEUR, timeout=10) as r:
            return (json.loads(r.read()).get("services") or {}), None
    except Exception as exc:  # noqa: BLE001
        return {}, type(exc).__name__


def _declarations() -> dict:
    try:
        import tomllib

        with open(os.path.join(ROOT, "proxy_deno", "core", "services.toml"), "rb") as f:
            return {s.get("name"): s for s in tomllib.load(f).get("service", [])}
    except Exception as exc:  # noqa: BLE001
        print("services.toml ILLISIBLE (%s) — les declarations manqueront"
              % type(exc).__name__)
        return {}


def _intentions() -> dict:
    out = {}
    for fic, cle in FLAGS.items():
        try:
            st = os.stat(os.path.join(SB, fic))
            out[cle] = (time.time() - st.st_mtime) < FRAIS_S
        except FileNotFoundError:
            out[cle] = False
        except Exception:  # noqa: BLE001
            out[cle] = None            # illisible, surtout PAS False
    return out


def _chaines() -> int | None:
    try:
        import sqlite3

        sys.path.insert(0, ROOT)
        from nokido_agent.app.forge_db_path import db_path

        cn = sqlite3.connect(db_path(), timeout=3.0)
        n = cn.execute("SELECT COUNT(*) FROM agent_chain_nodes WHERE status IN "
                       "('pending','running','retry_pending')").fetchone()[0]
        cn.close()
        return n
    except Exception:  # noqa: BLE001
        return None


def _reseau() -> tuple[collections.Counter, collections.Counter, str | None]:
    etab, ecoute = collections.Counter(), collections.Counter()
    try:
        for c in psutil.net_connections(kind="inet"):
            if not c.pid:
                continue
            if c.status == "ESTABLISHED":
                etab[c.pid] += 1
            elif c.status == "LISTEN":
                ecoute[c.pid] += 1
    except Exception as exc:  # noqa: BLE001
        return etab, ecoute, type(exc).__name__
    return etab, ecoute, None


def _actes_7j() -> collections.Counter:
    out = collections.Counter()
    try:
        now_u = datetime.now(timezone.utc).timestamp()
        with open(os.path.join(SB, "lifecycle_actions.jsonl"), encoding="utf-8",
                  errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    ts = datetime.fromisoformat(str(d.get("ts"))).timestamp()
                except Exception:  # noqa: BLE001 - muet-ok : ligne abimee, comptee nulle part
                    continue
                if now_u - ts > 7 * 86400:
                    continue
                ex = d.get("extra") or {}
                cible = str(ex.get("target") or d.get("target") or "")
                if cible:
                    out[cible] += 1
    except Exception:  # noqa: BLE001 - muet-ok : journal absent -> 0 acte connu
        pass
    return out


def _pouls(service: str):
    """Age du dernier battement EMIS par l'organe, ou None s'il n'a jamais battu.

    None n'est pas zero : c'est « cet organe ne temoigne pas », et le contrat le
    traduira en `illisible` sur ce terme-la, pas en manquement.
    """
    try:
        sys.path.insert(0, ROOT)
        from nokido_agent.app.forge_organ_afferent import dernier_pouls

        age, _raison = dernier_pouls(service)
        return age
    except Exception:  # noqa: BLE001 - muet-ok : nerf indisponible -> mesure absente
        return None


def sc_obj(service: str) -> str:
    """Objectif declare du service, ou chaine vide si illisible."""
    try:
        return _contrat(service).get("objectif") or ""
    except Exception:  # noqa: BLE001
        return ""


def _contrat(service: str) -> dict:
    """Contrat du service, lu par l'UNIQUE lecteur de declarations du corps."""
    try:
        sys.path.insert(0, ROOT)
        from nokido_agent.app.forge_service_capabilities import contrat_de

        return contrat_de(service)
    except Exception as exc:  # noqa: BLE001
        return {"source": "ABSENT", "intention": None, "objectif": None,
                "pourquoi": "lecteur de contrat indisponible (%s)" % type(exc).__name__}


def _evaluer(objectif, mesures) -> tuple:
    try:
        sys.path.insert(0, ROOT)
        from nokido_agent.app.forge_service_capabilities import evaluer_objectif

        return evaluer_objectif(objectif, mesures)
    except Exception as exc:  # noqa: BLE001
        return "illisible", "evaluateur indisponible (%s)" % type(exc).__name__, "INCONNUE"


def _heartbeat_age(svc: str, decl: dict) -> float | None:
    """Age du heartbeat DECLARE. None = aucun declare. inf = declare mais absent.
    -1 = illisible : ce n'est ni frais ni perime, c'est inconnu."""
    hb = (decl.get(svc) or {}).get("heartbeat")
    if not hb:
        return None
    try:
        return time.time() - os.stat(os.path.join(ROOT, hb)).st_mtime
    except FileNotFoundError:
        return float("inf")
    except Exception:  # noqa: BLE001
        return -1.0


def main() -> int:
    procs, illisibles_proc = _processus()
    registre, err_reg = _registre()
    decl = _declarations()
    intents = _intentions()
    etab, ecoute, err_net = _reseau()
    actes = _actes_7j()
    pid2svc = {int(s["pid"]): n for n, s in registre.items() if s.get("pid")}
    vm = psutil.virtual_memory()

    print("=" * 96)
    print("AUDIT INTENTION / EFFET — %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 96)
    print("Machine  : RAM %.1f/%.1f Go (%.0f%%) | %d process lus, %d ILLISIBLES"
          % (vm.used / 2**30, vm.total / 2**30, vm.percent, len(procs), illisibles_proc))
    print("Registre : %d services declares%s"
          % (len(registre), "" if err_reg is None else "  [INJOIGNABLE: %s]" % err_reg))
    print("Intention: %d drapeaux IMPLEMENTES pour %d services declares -> %s | chaines=%s"
          % (len(FLAGS), len(decl), json.dumps(intents), _chaines()))
    print("Reseau   : %s"
          % ("ILLISIBLE (%s) — l'effet reseau ne sera pas mesurable" % err_net if err_net
             else "%d process ESTABLISHED, %d en LISTEN" % (len(etab), len(ecoute))))

    lignes = []
    for nom, s in sorted(registre.items()):
        pid = s.get("pid")
        if not pid or int(pid) not in procs:
            continue
        pid = int(pid)
        cout = procs[pid]["prive"] + sum(v["prive"] for v in procs.values()
                                         if v["ppid"] == pid)
        d = decl.get(nom) or {}
        hb = _heartbeat_age(nom, decl)
        essentiel = bool(d.get("essential"))
        caps = d.get("capabilities") or []

        # Temps CPU de l'ARBRE : un launcher ne consomme rien, ses enfants travaillent.
        cpu_illisible = procs[pid]["cpu_s"] < 0
        cpu_arbre = sum(v["cpu_s"] for v in
                        [procs[pid]] + [w for w in procs.values() if w["ppid"] == pid]
                        if v["cpu_s"] >= 0)
        cpu_pct = (None if cpu_illisible
                   else 100.0 * cpu_arbre / max(1.0, procs[pid]["depuis_h"] * 3600.0))

        # LE JUGEMENT N'EST PLUS UNE HEURISTIQUE D'ICI : c'est le CONTRAT declare
        # (ou derive) qui tranche, et l'audit ne fait plus que fournir les mesures.
        # Un outil qui invente ses propres criteres redonne exactement l'approximation
        # qu'on cherchait a supprimer — et il diverge du regulateur des le lendemain.
        mesures = {
            "emis_s": _pouls(nom),
            "hb_s": None if (hb is None or hb == -1.0) else hb,
            "cpu_pct": cpu_pct,
            "conn": None if err_net else etab.get(pid, 0),
            "listen": None if err_net else bool(ecoute.get(pid, 0)),
            "actes": actes.get(nom, 0),
        }
        contrat = _contrat(nom)
        etat, pourquoi, nature = _evaluer(contrat.get("objectif"), mesures)
        verdict = {
            "atteint": "TIENT SON CONTRAT",
            "manque": "MANQUE SON OBJECTIF",
            "illisible": "NON MESURABLE",
            "sans_objet": "CONTRAT SANS OBJECTIF",
        }.get(etat, "?")
        # LE SIGNAL DE VIE DOIT EMANER DE L'ORGANE (correction owner 2026-08-25).
        # Un contrat tenu par la seule PALPATION — cpu, sockets — ne prouve pas que
        # l'organe temoigne : il prouve qu'un observateur arrive a lui prendre le
        # pouls. Ce n'est pas un echec, et c'est pour ca qu'il faut le NOMMER : sans
        # ce verdict distinct, la palpation delivre un satisfecit qui dispense
        # d'innerver l'organe, et le corps reste sourd a ce qu'il fait vraiment.
        if etat == "atteint" and nature == "PALPATION":
            verdict = "VIVANT MAIS DENERVE"
        if contrat.get("source") == "ABSENT":
            verdict = "SANS CONTRAT"
            pourquoi = contrat.get("pourquoi", "")
        contrat = dict(contrat, nature=nature)

        effets = []
        if hb is not None and 0 <= hb < FRAIS_S:
            effets.append("hb frais")
        if etab.get(pid):
            effets.append("%d conn" % etab[pid])
        if actes.get(nom):
            effets.append("%d actes" % actes[nom])
        if cpu_illisible:
            effets.append("cpu illisible")
        elif cpu_pct and cpu_pct >= 0.1:
            effets.append("cpu %.1f%%" % cpu_pct)
        lignes.append((cout, nom, verdict, essentiel, caps, hb,
                       ecoute.get(pid, 0), effets, procs[pid]["depuis_h"],
                       contrat, pourquoi))

    lignes.sort(reverse=True)
    print("\n" + "=" * 96)
    print("SERVICES VIVANTS — juges par leur CONTRAT (intention + objectif chiffre)")
    print("=" * 96)
    for cout, nom, verdict, ess, caps, hb, nb_ecoute, effets, age, contrat, pourquoi in lignes:
        print("%-26s %7.2fG %4.0fh %-22s %s"
              % (nom[:26], cout / 2**30, age, verdict,
                 "[%s] %s" % (contrat.get("source", "?"),
                              str(contrat.get("intention") or "-")[:30])))
        print("%34s objectif=%-28s %-9s -> %s"
              % ("", str(contrat.get("objectif") or "-")[:28],
                 contrat.get("nature", "?"), str(pourquoi)[:52]))

    print("\n" + "=" * 96)
    par, cout_par = collections.Counter(), collections.Counter()
    for cout, nom, verdict, *_ in lignes:
        v = verdict.rstrip("*")
        par[v] += 1
        cout_par[v] += cout
    print("SYNTHESE — %d services vivants sur %d declares" % (len(lignes), len(decl)))
    for v, n in par.most_common():
        print("   %-24s %3d services   %6.2f Go engages" % (v, n, cout_par[v] / 2**30))

    non_rat = collections.Counter()
    cout_non_rat = 0.0
    for pid, v in procs.items():
        if pid in pid2svc or v["ppid"] in pid2svc:
            continue
        non_rat[v["nom"]] += 1
        cout_non_rat += v["prive"]
    innerves = sum(1 for _c, n, *_ in lignes
                   if any(x in (sc_obj(n) or "") for x in ("hb", "emis")))
    print("\nINNERVATION : %d services vivants sur %d EMETTENT un signal (heartbeat ou "
          "moelle afferente)." % (innerves, len(lignes)))
    print("Les autres ne sont connus que par PALPATION — on leur prend le pouls, ils ne")
    print("temoignent pas. Un organe denerve fonctionne ; il ne dit simplement rien de")
    print("ce qu'il fait, et aucune regulation ne peut raisonner sur ce silence.")

    print("\nHORS CHAMP DE LA REGULATION : %d process, %.2f Go engages"
          % (sum(non_rat.values()), cout_non_rat / 2**30))
    for n, c in non_rat.most_common(12):
        print("   %-30s x%-4d" % (n, c))
    print("\nCe bloc n'est ni justifie ni condamne : il est INCONNU du registre, donc")
    print("hors de portee de toute regulation. C'est la mesure de sa COUVERTURE reelle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
