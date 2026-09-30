"""forge_runtime_smoke.py — le hub DEMARRE-t-il, et REPOND-il ?

La chaine de publication prouve qu'un paquet s'installe, s'importe et que ses
entrypoints repondent. Elle ne demarre aucun service. Ce script comble le
dernier cran :

    INSTALLE  ->  DEMARRE  ->  REPOND  ->  SERT SES OUTILS

Il est ecrit pour tourner sur une machine NUE — un runner GitHub, la machine
d'un contributeur qui vient de cloner. Il ne suppose ni modele charge, ni
service tiers, ni configuration prealable : ce sont precisement les conditions
ou un demarrage casse sans qu'on sache pourquoi.

TROIS PRINCIPES, tous payes ailleurs dans ce depot :

1. **Une attente est BORNEE et son echec est un ECHEC.** Un `sleep` fixe rend
   le test instable ; une attente infinie transforme une panne en timeout de
   job, sans diagnostic.
2. **Un demarrage rate DOIT rendre son journal.** Sans le log, « le hub n'a pas
   repondu » est indiscernable de « le port etait pris », de « une dependance
   manquait » et de « il a demarre puis il est mort ». Le journal est imprime
   dans TOUS les cas, y compris en succes.
3. **Ne jamais conclure d'un silence.** Port ferme, process mort, reponse
   invalide et timeout sont QUATRE etats distincts, et le rapport les nomme.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

__FORGE_COLOR__ = "infra/bootstrap : smoke de demarrage du hub, du port a la liste d'outils"

ROOT = Path(__file__).resolve().parents[1]


def _port_ouvert(hote: str, port: int, delai: float = 1.0) -> bool:
    """Délègue à `forge_ports.probe`, la primitive du dépôt.

    Signalé par le cliquet de duplication le 2026-09-19 : j'avais réécrit ici
    une sonde de port que `tools/forge_ports.py` fournit déjà. Réutiliser avant
    de reconstruire — et le repli reste local, pour qu'un smoke ne dépende pas
    d'un import pour dire si un port écoute.
    """
    try:
        from nokido_agent.tools.forge_ports import probe  # noqa: PLC0415

        return bool(probe(port, host=hote, timeout=delai))
    except Exception:  # noqa: BLE001  # muet-ok : repli local ci-dessous
        try:
            with socket.create_connection((hote, port), timeout=delai):
                return True
        except OSError:
            return False


def _http(url: str, corps: dict | None = None, delai: float = 10.0) -> tuple[int, str]:
    """Rend (code, texte). Code 0 = pas de reponse HTTP du tout (distinct d'un 500)."""
    donnees = json.dumps(corps).encode() if corps is not None else None
    req = urllib.request.Request(url, data=donnees, method="POST" if corps else "GET")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            return r.status, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(20000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return 0, "%s: %s" % (type(e).__name__, e)


def smoke(port: int = 8766, attente_s: int = 120, demarrer: bool = True,
          journal: Path | None = None) -> dict:
    hote = "127.0.0.1"
    r: dict = {"port": port, "etapes": [], "verdict": "INCONNU", "journal": ""}

    def note(cle, etat, detail=""):
        r["etapes"].append({"etape": cle, "etat": etat, "detail": str(detail)[:600]})
        print("  %-22s %-12s %s" % (cle, etat, str(detail)[:150]), flush=True)

    proc = None
    log = journal or (Path(os.environ.get("RUNNER_TEMP") or ".") / "nokido_hub_smoke.log")

    # Le controle n'a de sens QUE si l'on s'apprete a demarrer : en mode
    # `--sans-demarrage` le port DOIT deja etre ouvert, c'est la premisse.
    # Appliquer le garde dans les deux cas rendait l'option inutilisable.
    if demarrer and _port_ouvert(hote, port):
        note("port initial", "DEJA_OUVERT",
             "un service ecoute deja sur %d — le smoke jugerait quelqu'un d'autre" % port)
        r["verdict"] = "INDETERMINE"
        return r
    if not demarrer and not _port_ouvert(hote, port):
        note("port initial", "FERME",
             "--sans-demarrage suppose un hub deja lance sur %d, rien n'ecoute" % port)
        r["verdict"] = "ECHEC"
        return r

    if demarrer:
        cible = ROOT / "tools" / "nokido_hub.py"
        if not cible.is_file():
            note("demarrage", "ECHEC", "introuvable: %s" % cible)
            r["verdict"] = "ECHEC"
            return r
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            fh = open(log, "wb")
            proc = subprocess.Popen([sys.executable, str(cible)], cwd=str(ROOT),
                                    stdout=fh, stderr=subprocess.STDOUT, env=env)
            note("demarrage", "LANCE", "pid=%s journal=%s" % (proc.pid, log))
        except OSError as e:
            note("demarrage", "ECHEC", "%s: %s" % (type(e).__name__, e))
            r["verdict"] = "ECHEC"
            return r

    # --- attente BORNEE, qui distingue « pas encore » de « mort » -----------
    debut = time.time()
    ouvert = not demarrer  # deja verifie ci-dessus
    mort = False
    # Pas de `while ... else` ici : sa clause `else` s'execute AUSSI quand la
    # boucle ne tourne jamais, donc le mode `--sans-demarrage` aurait crie
    # TIMEOUT sur un hub parfaitement vivant. La condition est explicite.
    while not ouvert and time.time() - debut < attente_s:
        if proc is not None and proc.poll() is not None:
            mort = True
            note("attente port", "PROCESS_MORT",
                 "le hub a quitte avec le code %s avant d'ouvrir le port" % proc.returncode)
            break
        if _port_ouvert(hote, port):
            ouvert = True
            note("attente port", "OUVERT", "%.1fs" % (time.time() - debut))
            break
        time.sleep(1.0)
    if not ouvert and not mort and demarrer:
        note("attente port", "TIMEOUT", "%ds sans ouverture" % attente_s)

    if ouvert:
        code, txt = _http("http://%s:%d/health" % (hote, port))
        sain = code == 200 and '"ok"' in txt.replace(" ", "")
        note("health", "PASS" if sain else ("HTTP_%d" % code if code else "SANS_REPONSE"),
             txt[:200])

        # tools/list : un port qui repond ne prouve pas que les outils sont servis.
        code, txt = _http("http://%s:%d/mcp" % (hote, port),
                          {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        nb = -1
        if code == 200:
            try:
                brut = txt
                if brut.lstrip().startswith("event:") or "data:" in brut[:200]:
                    for l in brut.splitlines():
                        if l.startswith("data:"):
                            brut = l[5:].strip()
                            break
                nb = len(json.loads(brut).get("result", {}).get("tools", []))
            except (ValueError, TypeError, AttributeError):
                nb = -1
        # TRANSPORT != APPLICATIF != CAPACITE. Un 401/403 n'est pas une panne :
        # il prouve que le hub a recu la requete, l'a comprise et a APPLIQUE son
        # controle d'acces. C'est meme le comportement voulu — le contraire
        # serait un endpoint d'outils ouvert a tous. Mais il ne prouve pas que
        # les outils sont servis, alors il a son propre etat. Mesure du
        # 2026-09-19 sur le hub reel : `/health` 200 et `tools/list` 401.
        if nb > 0:
            etat, detail = "PASS", "%d outils" % nb
        elif code in (401, 403):
            etat, detail = "GOUVERNE", (
                "HTTP %d — le hub repond et exige une autorisation ; la liste "
                "d'outils n'est donc pas prouvee, mais rien n'est casse" % code)
        elif code:
            etat, detail = "HTTP_%d" % code, txt[:200]
        else:
            etat, detail = "SANS_REPONSE", txt[:200]
        note("mcp tools/list", etat, detail)

    if proc is not None:
        # L'arret RAPPORTE son issue. Un process qui survit a la fin du smoke
        # tient le port et fera echouer la passe suivante sur « port deja
        # ouvert » — un symptome a des lieues de sa cause si personne ne l'a dit.
        etat_arret, motif = "OK", ""
        try:
            proc.terminate()
            proc.wait(timeout=20)
        except (subprocess.TimeoutExpired, OSError) as e:
            motif = "terminate refuse (%s), kill force" % type(e).__name__
            try:
                proc.kill()
                proc.wait(timeout=10)
                etat_arret = "TUE"
            except (subprocess.TimeoutExpired, OSError) as e2:
                etat_arret = "SURVIT"
                motif = "%s puis kill en echec (%s) — pid %s tient peut-etre le port" % (
                    motif, type(e2).__name__, proc.pid)
        note("arret", etat_arret, motif)

    if proc is None:
        r["journal"] = "(aucun journal : le hub n'a pas ete demarre par ce smoke)"
    else:
        try:
            r["journal"] = log.read_text(encoding="utf-8", errors="replace")[-6000:]
        except OSError as e:
            r["journal"] = "journal illisible: %s" % e

    etats = {e["etape"]: e["etat"] for e in r["etapes"]}
    if etats.get("health") == "PASS" and etats.get("mcp tools/list") in ("PASS", "GOUVERNE"):
        # « demarre et repond » est le contrat de ce smoke. Exiger la liste
        # d'outils en clair exigerait de lui fournir un jeton, donc de tester
        # l'authentification plutot que le demarrage — un autre sujet.
        r["verdict"] = "PASS" if etats.get("mcp tools/list") == "PASS" else "PASS_GOUVERNE"
    elif etats.get("port initial") == "DEJA_OUVERT":
        r["verdict"] = "INDETERMINE"
    else:
        r["verdict"] = "ECHEC"
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Smoke de demarrage du hub Nokido.")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--attente", type=int, default=120)
    ap.add_argument("--sans-demarrage", action="store_true",
                    help="suppose le hub deja lance ailleurs")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sortie", help="ecrit le rapport JSON dans ce fichier")
    a = ap.parse_args(argv)

    print("=== SMOKE RUNTIME — le hub demarre-t-il et sert-il ses outils ? ===", flush=True)
    r = smoke(port=a.port, attente_s=a.attente, demarrer=not a.sans_demarrage)

    print("\nVERDICT : %s" % r["verdict"], flush=True)
    # Le journal est imprime DANS TOUS LES CAS. Un demarrage rate sans son
    # journal ne se diagnostique pas, et un succes sans journal ne se relit pas.
    print("\n--- journal du hub (fin) " + "-" * 40, flush=True)
    print(r["journal"] or "(vide)", flush=True)
    print("-" * 64, flush=True)

    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    if a.sortie:
        Path(a.sortie).write_text(json.dumps(r, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    # INDETERMINE ne vaut pas ECHEC : un port deja pris n'est pas une panne du
    # hub, c'est une mesure qu'on n'a pas pu prendre.
    return 0 if r["verdict"] in ("PASS", "PASS_GOUVERNE", "INDETERMINE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
