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
import urllib.request
from pathlib import Path

PAQUETS = ("nokido-agent", "netcfg-agent", "netcfg-agent-mcp")
WORKFLOW_INSTALL = "installation-complete.yml"
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


def collecter(depot: str, jeton: str | None, jeton_actions: str | None, readme: str = "") -> dict:
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
    r["pypi_30j"] = {}
    for p in PAQUETS:
        d, err = _essayer("https://pypistats.org/api/packages/%s/recent" % p)
        if err:
            r["manques"]["pypi:" + p] = err
        else:
            r["pypi_30j"][p] = (d.get("data") or {}).get("last_month")
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
    return a


def resume(archive: dict, fenetre: int = 14) -> dict:
    jours = sorted(archive.get("jours", {}))[-fenetre:]
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
    }


def rendre_svg(s: dict) -> str:
    def n(v):
        return "n/d" if v is None else "{:,}".format(v).replace(",", " ")
    ligne1 = "14 j : %s vues · %s visiteurs · %s clones (dont runs CI : %s)" % (
        n(s["vues"]), n(s["visiteurs"]), n(s["clones"]), n(s["runs_ci"]))
    org = s.get("organisme") or {}
    ligne2 = "PyPI 30 j : %s téléchargements · ★ %s · %s modules · %s fragments RAG" % (
        n(s["pypi_30j"]), n(s["etoiles"]), org.get("modules", "n/d"), org.get("rag_chunks", "n/d"))
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="54" role="img" '
            'aria-label="Statistiques publiques de Nokido">'
            '<rect width="640" height="54" rx="6" fill="#f6f8fa" stroke="#d0d7de"/>'
            '<text x="12" y="22" font-family="Segoe UI,Helvetica,Arial,sans-serif" font-size="12" '
            'fill="#24292f">%s</text>'
            '<text x="12" y="42" font-family="Segoe UI,Helvetica,Arial,sans-serif" font-size="12" '
            'fill="#57606a">%s — %s</text></svg>' % (esc(ligne1), esc(ligne2), esc(s.get("date") or "")))


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
    releve = collecter(a.depot, _jeton("STATS_TOKEN"), _jeton("GITHUB_TOKEN"), readme)
    fichier = sortie / "archive.json"
    try:
        archive = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        archive = {}
    archive = fusionner(archive, releve)
    fichier.write_text(json.dumps(archive, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (sortie / "stats.svg").write_text(rendre_svg(resume(archive)), encoding="utf-8")
    for cle, cause in sorted(releve["manques"].items()):
        print("[stats] NON MESURE %s : %s" % (cle, cause))
    print("[stats] archive : %d jour(s) ; carte : %s" % (len(archive["jours"]), sortie / "stats.svg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
