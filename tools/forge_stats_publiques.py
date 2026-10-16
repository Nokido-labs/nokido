# -*- coding: utf-8 -*-
"""Statistique publique de la vitrine : une petite carte SVG en bas du README de Nokido-labs/nokido.

Lance par l'Action quotidienne du depot PUBLIC (.github/workflows/stats-publiques.yml, decision owner
2026-10-13), stdlib seule. Archive dans la branche `stats` (GitHub ne garde le trafic que 14 jours
glissants) et rend `stats.svg`, que le bas du README affiche.

Sources, chacune DITE quand elle manque -- jamais un zero de remplacement :
- trafic (vues, visiteurs, clones) : API GitHub, jeton `STATS_TOKEN` (acces en lecture a
  l'administration du depot) ; sans jeton -> « trafic non mesure » ;
- clones de NOS CI : runs du workflow d'installation sur le depot public (chacun clone le depot) --
  sans cette correction, 248 clones en 14 jours se liraient comme 248 lecteurs ;
- telechargements PyPI 30 jours (pypistats.org), etoiles ;
- GLOBAL (owner 15/10 : « des stats globales, du reel pour PyPI, nos CI deduites du total ») : serie PyPI journaliere
  HORS MIROIRS archivee jour par jour (cumul depuis le premier jour connu, au-dela des 180 j de pypistats) ;
  telechargements de NOS CI deduits run par run (TIRAGES_PAR_JOB, lu dans le code des workflows) ; cumul des assets
  des releases GitHub, nos imports de pack deduits. Ce qui ne peut pas etre deduit est DIT (installations locales,
  spec illisible), jamais devine ;
- taille de l'organisme : le tampon `<!-- STATS:... -->` que tools/forge_post_commit.py ecrit deja
  dans le README -- relu, jamais recalcule (un seul producteur).

    python tools/forge_stats_publiques.py --depot Nokido-labs/nokido --sortie stats/ [--readme README.md]
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : statistique publique de la vitrine (trafic GitHub, PyPI, tampon STATS)"

import argparse
import datetime as _dt
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

PAQUETS = ("nokido-agent", "netcfg-agent", "netcfg-agent-mcp")
WORKFLOW_INSTALL = "installation-complete.yml"
WORKFLOW_RELEASE = "release.yml"
# Ce que CHAQUE job de nos CI publiques tire de PyPI ou des releases, sur un runner neuf (lu dans le code le 15/10) :
# installation-complete -> `pip install -e .` du clone + `_pack` (asset de release) ; organisme -> requirements-
# organisme.txt (netcfg-agent, netcfg-agent-mcp) ; paquet -> extra [organisme] (idem) + nokido-agent SI la spec vient de
# PyPI (sinon la wheel du clone). release.yml : l'etape « PyPI sert-il... » telecharge la wheel publiee.
TIRAGES_PAR_JOB = {
    "Installation complete": {"pack": 1},
    "Organisme complet": {"netcfg-agent": 1, "netcfg-agent-mcp": 1},
    "Parcours paquet": {"netcfg-agent": 1, "netcfg-agent-mcp": 1},
}
_SPEC = re.compile(r"SPEC_PAQUET:\s*(\S+)")
_TAMPON = re.compile(r"<!-- STATS:(?P<sha>\w+):(?P<date>[\d-]+) (?P<champs>[^>]*?) -->")


def _jeton(nom: str):
    """Le COFFRE fait autorite (poste de l'owner) ; l'environnement n'est qu'un repli -- le runner de l'Action
    GitHub n'a pas de coffre, il recoit le secret par `secrets.STATS_TOKEN` / `github.token`."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        valeur = get_secret(nom)
        if valeur:
            return valeur
    except Exception:  # noqa: BLE001 -- muet-ok : hors du poste, pas de coffre ; repli dit dans la docstring
        pass
    return os.environ.get(nom) or None


def _get_json(url: str, jeton: str | None = None):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "nokido-stats-publiques"})
    if jeton:
        req.add_header("Authorization", "Bearer " + jeton)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _essayer(url, jeton=None):
    """(donnees, None) ou (None, cause) : une source muette se nomme, elle ne vaut pas zero."""
    try:
        return _get_json(url, jeton), None
    except Exception as e:  # noqa: BLE001 -- la cause est rendue a l'appelant, jamais avalee
        return None, "%s: %s" % (type(e).__name__, str(e)[:120])


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 -- on suit a la main, SANS le jeton
        return None


def _journal_job(api: str, job_id, jeton: str | None) -> str:
    """Journal d'un job. L'API redirige vers un stockage signe : on suit la redirection SANS le jeton (le transmettre
    a l'hote du blob le ferait refuser, et l'exposerait)."""
    req = urllib.request.Request("%s/actions/jobs/%s/logs" % (api, job_id),
                                 headers={"User-Agent": "nokido-stats-publiques"})
    if jeton:
        req.add_header("Authorization", "Bearer " + jeton)
    try:
        with urllib.request.build_opener(_SansRedirection).open(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        cible = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
        if not cible:
            raise
        with urllib.request.urlopen(urllib.request.Request(cible, headers={"User-Agent": "nokido-stats-publiques"}),
                                    timeout=60) as r:
            return r.read().decode("utf-8", "replace")


def tirages_ci(api: str, jeton: str | None, deja: set, get=None, journal=None) -> tuple[dict, dict]:
    """({run_id: {jour, workflow, comptes, inconnus}}, manques) pour les runs TERMINES pas encore comptes.

    Un run deja dans l'archive n'est jamais recompte (idempotent d'un releve a l'autre). La spec du parcours paquet
    n'est lue dans le journal que pour un lancement manuel (un push construit toujours la wheel du clone) ; illisible,
    elle compte dans `inconnus`, jamais comme un telechargement ni comme zero."""
    get = get or _essayer
    journal = journal or _journal_job
    runs, manques = {}, {}
    for wf in (WORKFLOW_INSTALL, WORKFLOW_RELEASE):
        for page in range(1, 6):
            d, err = get("%s/actions/workflows/%s/runs?per_page=100&status=completed&page=%d" % (api, wf, page), jeton)
            if err:
                manques["ci:" + wf] = err
                break
            lot = d.get("workflow_runs") or []
            for run in lot:
                rid = str(run.get("id") or "")
                if not rid or rid in deja or run.get("status", "completed") != "completed":
                    continue
                jobs, err = get("%s/actions/runs/%s/jobs?per_page=100" % (api, rid), jeton)
                if err:
                    manques["ci:run:" + rid] = err
                    continue
                comptes, inconnus = {}, 0
                for job in jobs.get("jobs") or []:
                    if job.get("conclusion") in (None, "skipped", "cancelled") and not job.get("steps"):
                        continue
                    nom = job.get("name") or ""
                    if wf == WORKFLOW_RELEASE:
                        if any((s.get("name") or "").startswith("PyPI sert-il") and s.get("conclusion") == "success"
                               for s in job.get("steps") or []):
                            comptes["nokido-agent"] = comptes.get("nokido-agent", 0) + 1
                        continue
                    for prefixe, tirage in TIRAGES_PAR_JOB.items():
                        if nom.startswith(prefixe):
                            for p, n in tirage.items():
                                comptes[p] = comptes.get(p, 0) + n
                    if nom.startswith("Parcours paquet") and run.get("event") == "workflow_dispatch":
                        try:
                            m = _SPEC.search(journal(api, job.get("id"), jeton))
                        except Exception:  # noqa: BLE001 -- muet-ok : la spec illisible est COMPTEE dans inconnus
                            m = None
                        if m is None:
                            inconnus += 1
                        elif "nokido-agent" in m.group(1) and not m.group(1).endswith(".whl"):
                            comptes["nokido-agent"] = comptes.get("nokido-agent", 0) + 1
                runs[rid] = {"jour": (run.get("created_at") or "")[:10], "workflow": wf, "comptes": comptes,
                             "inconnus": inconnus}
            if len(lot) < 100:
                break
    return runs, manques


def collecter(depot: str, jeton: str | None, jeton_actions: str | None, readme: str = "",
              deja: set | None = None) -> dict:
    api = "https://api.github.com/repos/" + depot
    jour = _dt.date.today().isoformat()
    r: dict = {"date": jour, "manques": {}}
    if jeton:
        for cle, chemin in (("vues", "/traffic/views"), ("clones", "/traffic/clones")):
            d, err = _essayer(api + chemin, jeton)
            if err:
                r["manques"][cle] = err
            else:
                serie = d.get("views") or d.get("clones") or []
                r[cle] = {x["timestamp"][:10]: [x["count"], x["uniques"]] for x in serie}
    else:
        r["manques"]["trafic"] = "pas de jeton STATS_TOKEN : trafic NON mesure"
    meta, err = _essayer(api, jeton_actions)
    if err:
        r["manques"]["depot"] = err
    else:
        r["etoiles"] = meta.get("stargazers_count")
    runs, err = _essayer("%s/actions/workflows/%s/runs?per_page=100&created=>=%s" % (
        api, WORKFLOW_INSTALL, (_dt.date.today() - _dt.timedelta(days=14)).isoformat()), jeton_actions)
    if err:
        r["manques"]["runs_ci"] = err
    else:
        par_jour: dict = {}
        for run in runs.get("workflow_runs", []):
            j = run["created_at"][:10]
            par_jour[j] = par_jour.get(j, 0) + 1
        r["runs_ci"] = par_jour
    r["pypi_30j"], r["pypi_jours"] = {}, {}
    for p in PAQUETS:
        d, err = _essayer("https://pypistats.org/api/packages/%s/recent" % p)
        if err:
            r["manques"]["pypi:" + p] = err
        else:
            r["pypi_30j"][p] = (d.get("data") or {}).get("last_month")
        # Serie JOURNALIERE hors miroirs, ventilee par version de Python DECLAREE : pip et uv la declarent, les robots
        # (scanners, indexeurs) non. Mesure du 15/10 : nokido-agent 2 036 « hors miroirs » dont 1 976 sans Python
        # declare -- 60 installations reelles. Archivee jour par jour : cumul global au-dela des 180 j gardes.
        d, err = _essayer("https://pypistats.org/api/packages/%s/python_major?mirrors=false" % p)
        donnees = (d or {}).get("data") if not err else None
        if err or not isinstance(donnees, list):
            r["manques"]["pypi_global:" + p] = err or "reponse sans serie journaliere"
        else:
            r["pypi_jours"][p], r.setdefault("pypi_robots", {})[p] = {}, {}
            for x in donnees:
                if not x.get("date"):
                    continue
                cible = r["pypi_robots"][p] if x.get("category") in (None, "null") else r["pypi_jours"][p]
                cible[x["date"]] = cible.get(x["date"], 0) + int(x.get("downloads") or 0)
    rel, err = _essayer(api + "/releases?per_page=100", jeton_actions)
    if err or not isinstance(rel, list):
        r["manques"]["releases"] = err or "reponse sans liste de releases"
    else:
        r["releases"] = {"total": sum(a.get("download_count", 0) for x in rel for a in x.get("assets") or []),
                         "n": len(rel)}
    r["ci_runs"], manques_ci = tirages_ci(api, jeton_actions, deja or set())
    r["manques"].update(manques_ci)
    m = _TAMPON.search(readme or "")
    if m:
        champs = dict(kv.split("=", 1) for kv in m.group("champs").split() if "=" in kv)
        r["organisme"] = {"sha": m.group("sha"), "date": m.group("date"), **champs}
    return r


def fusionner(archive: dict, releve: dict) -> dict:
    """Archive par JOUR : la serie de 14 jours de chaque releve met a jour ses jours, le plus recent fait foi."""
    a = {"jours": dict(archive.get("jours") or {}), "dernier": releve}
    for cle in ("vues", "clones"):
        for jour, (n, u) in (releve.get(cle) or {}).items():
            a["jours"].setdefault(jour, {})[cle] = [n, u]
    for jour, n in (releve.get("runs_ci") or {}).items():
        a["jours"].setdefault(jour, {})["runs_ci"] = n
    for cle_releve, cle_jour in (("pypi_jours", "pypi"), ("pypi_robots", "pypi_robots")):
        for p, serie in (releve.get(cle_releve) or {}).items():
            for jour, n in serie.items():
                a["jours"].setdefault(jour, {}).setdefault(cle_jour, {})[p] = n
    a["ci_runs"] = {**(archive.get("ci_runs") or {}), **(releve.get("ci_runs") or {})}
    return a


def global_pypi(archive: dict) -> dict:
    """Cumul GLOBAL hors miroirs, nos CI deduites. Un run de CI n'est deduit que s'il tombe dans la periode couverte
    par la serie du paquet (sinon on retirerait un telechargement jamais compte). Une deduction superieure au total
    n'est pas ecretee en silence : elle est rendue dans `incoherences`."""
    jours = archive.get("jours") or {}
    tot, depuis = {}, {}
    for j in sorted(jours):
        for p, n in (jours[j].get("pypi") or {}).items():
            tot[p] = tot.get(p, 0) + int(n)
            depuis.setdefault(p, j)
    ci, inconnus, pack = {}, 0, 0
    for run in (archive.get("ci_runs") or {}).values():
        inconnus += run.get("inconnus", 0)
        for p, n in (run.get("comptes") or {}).items():
            if p == "pack":
                pack += n
            elif p in depuis and run.get("jour", "") >= depuis[p]:
                ci[p] = ci.get(p, 0) + n
    reels = {p: tot[p] - ci.get(p, 0) for p in tot}
    robots = sum(int(n) for j in jours.values() for n in (j.get("pypi_robots") or {}).values())
    return {"depuis": min(depuis.values()) if depuis else None, "total": sum(tot.values()) if tot else None,
            "robots": robots,
            "ci": sum(ci.values()), "reel": sum(reels.values()) if tot else None,
            "par_paquet": {p: {"total": tot[p], "ci": ci.get(p, 0), "reel": reels[p]} for p in tot},
            "pack_ci": pack, "inconnus": inconnus, "incoherences": [p for p, v in reels.items() if v < 0]}


def resume(archive: dict, fenetre: int | None = None) -> dict:
    """Cumul sur TOUTE l'archive par defaut (owner 15/10 : « des stats globales, pas juste 14 ou 30 jours »)."""
    jours = sorted(archive.get("jours", {}))
    jours = jours[-fenetre:] if fenetre else jours
    somme = lambda cle, i: sum((archive["jours"][j].get(cle) or [0, 0])[i] for j in jours)  # noqa: E731
    dernier = archive.get("dernier") or {}
    trafic_mesure = "trafic" not in (dernier.get("manques") or {})
    return {
        "vues": somme("vues", 0) if trafic_mesure else None,
        "visiteurs": somme("vues", 1) if trafic_mesure else None,
        "clones": somme("clones", 0) if trafic_mesure else None,
        "runs_ci": sum(archive["jours"][j].get("runs_ci", 0) for j in jours),
        "pypi_30j": sum(v for v in (dernier.get("pypi_30j") or {}).values() if isinstance(v, int)),
        "etoiles": dernier.get("etoiles"),
        "organisme": dernier.get("organisme"),
        "date": dernier.get("date"),
        "pypi_global": global_pypi(archive),
        "releases_total": (dernier.get("releases") or {}).get("total"),
        "trafic_depuis": next((j for j in sorted(archive.get("jours", {})) if archive["jours"][j].get("vues")), None),
    }


def rendre_svg(s: dict) -> str:
    def n(v):
        return "n/d" if v is None else "{:,}".format(v).replace(",", " ")
    g = s.get("pypi_global") or {}
    pp = g.get("par_paquet") or {}
    ligne1 = ("PyPI depuis le %s : %s installations réelles (pip/uv ; nos CI déduites : −%s ; "
              "%s robots et scanners exclus)" % (g.get("depuis") or "n/d", n(g.get("reel")), n(g.get("ci")),
                                                 n(g.get("robots"))))
    detail = " · ".join("%s %s" % (p, n((pp.get(p) or {}).get("reel"))) for p in PAQUETS)
    rel = s.get("releases_total")
    rel_reel = None if rel is None else rel - (g.get("pack_ci") or 0)
    ligne2 = "%s · releases GitHub %s (nos CI déduites : −%s) · ★ %s" % (
        detail, n(rel_reel), n(g.get("pack_ci")), n(s["etoiles"]))
    trafic = ("depuis le %s" % s["trafic_depuis"]) if s.get("trafic_depuis") else "non mesuré (jeton)"
    org = s.get("organisme") or {}
    ligne3 = "Trafic %s : %s vues · %s visiteurs · %s clones (dont runs CI : %s) · %s modules · %s fragments RAG" % (
        trafic, n(s["vues"]), n(s["visiteurs"]), n(s["clones"]), n(s["runs_ci"]), org.get("modules", "n/d"),
        org.get("rag_chunks", "n/d"))
    reserve = []
    if g.get("inconnus"):
        reserve.append("%s job(s) CI à spec illisible non déduits" % g["inconnus"])
    if g.get("incoherences"):
        reserve.append("déduction > total pour %s" % ", ".join(g["incoherences"]))
    reserve.append("installations locales non déduites")
    ligne4 = "relevé du %s — %s" % (s.get("date") or "", " ; ".join(reserve))
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    lignes = "".join('<text x="12" y="%d" font-family="Segoe UI,Helvetica,Arial,sans-serif" font-size="12" '
                     'fill="%s">%s</text>' % (20 + 19 * i, coul, esc(t))
                     for i, (t, coul) in enumerate(((ligne1, "#24292f"), (ligne2, "#24292f"), (ligne3, "#57606a"),
                                                   (ligne4, "#8c959f"))))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="820" height="90" role="img" '
            'aria-label="Statistiques publiques de Nokido">'
            '<rect width="820" height="90" rx="6" fill="#f6f8fa" stroke="#d0d7de"/>%s</svg>' % lignes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--depot", default="Nokido-labs/nokido")
    ap.add_argument("--sortie", required=True, help="dossier de la branche stats (archive.json, stats.svg)")
    ap.add_argument("--readme", default="README.md", help="README dont on relit le tampon STATS")
    a = ap.parse_args(argv)
    sortie = Path(a.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    try:
        readme = Path(a.readme).read_text(encoding="utf-8", errors="replace")
    except OSError:
        readme = ""
    fichier = sortie / "archive.json"
    try:
        archive = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        archive = {}
    # Les runs deja comptes ne sont plus relus : l'archive porte leur deduction (les journaux expirent a 90 j).
    releve = collecter(a.depot, _jeton("STATS_TOKEN"), _jeton("GITHUB_TOKEN"), readme,
                       deja=set((archive.get("ci_runs") or {}).keys()))
    archive = fusionner(archive, releve)
    fichier.write_text(json.dumps(archive, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (sortie / "stats.svg").write_text(rendre_svg(resume(archive)), encoding="utf-8")
    for cle, cause in sorted(releve["manques"].items()):
        print("[stats] NON MESURE %s : %s" % (cle, cause))
    print("[stats] archive : %d jour(s) ; carte : %s" % (len(archive["jours"]), sortie / "stats.svg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
