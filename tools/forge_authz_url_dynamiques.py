"""Cherche les appels au hub dont l'URL est CONSTRUITE a l'execution.

__FORGE_COLOR__ = "immunitaire/angle-mort-des-appelants"

Finding M2M #2 (2026-09-02) : une route peut recevoir du trafic sans apparaitre
dans aucun code source sous forme de chaine litterale. `_appelants` de
`forge_route_authz_audit` fait un `motif in source` -- il est donc AVEUGLE a :

  - l'interpolation      : f"/api/{domaine}/{action}", `/api/${x}/y`
  - la concatenation     : base + "/api/" + nom
  - la configuration     : URL lue dans un .toml, une base, un payload de job
  - l'inference LLM      : un agent qui derive l'URL d'une doc d'API

Ce module ne remplace pas l'inventaire : il MESURE SON ANGLE MORT. Sa sortie
n'est pas « voici les appelants cachés » mais « voici les endroits ou un
appelant PEUT se cacher ». Un fichier liste ici ne prouve rien contre lui ; sa
valeur est de dire combien d'endroits echappent structurellement au grep, pour
qu'on cesse de lire « aucun appelant trouve » comme « personne n'appelle ».

Deporte en job : le balayage disque depasse le cap des appels hub (mesure : 120 s
insuffisants).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SORTIE = ROOT / "sandbox" / "authz_url_dynamiques.json"

# Exclusions elargies apres mesure : la premiere version a tourne 36 min sans
# finir. Le cout n'est pas le nombre de fichiers mais leur TAILLE -- `sandbox/`
# et `RAG/` portent des JSON de plusieurs centaines de Mo qui n'ont aucun
# appelant HTTP a reveler. Un balayage qui ne finit jamais ne mesure rien.
EXCLUS = ("_attic", "archaeology_clones", "mutation_wt", "node_modules",
          ".git", "eval_repos", "site-packages", "__pycache__",
          "sandbox", "RAG", "logs", "nokido_persist", "venv", ".venv",
          "dist", "build", "coverage", "htmlcov")
EXTS = (".py", ".ts", ".js", ".html", ".toml", ".json")

# Au-dela, le fichier est ECARTE et COMPTE comme tel : un minifie de 3 Mo ou un
# dump JSON ne contient pas d'appelant lisible, mais l'ecarter en silence
# surestimerait la couverture.
TAILLE_MAX = 2 * 1024 * 1024

# Fichiers qui NOMMENT ces motifs sans en etre : les instruments eux-memes.
_OBSERVATEURS = frozenset({
    "forge_authz_url_dynamiques.py",
    "forge_route_authz_audit.py",
    "forge_authz_matrice.py",
})

# Chaque motif nomme CE QU'IL ATTRAPE. Un motif sans nom produit un compteur
# qu'on ne sait plus interpreter trois semaines plus tard.
MOTIFS = {
    "port_puis_variable": re.compile(r"8766[\"'`]?\s*(?:\+|,|\))\s*\w"),
    "f_string_api": re.compile(r"""f["'][^"'\n]*/api/\{"""),
    "template_ts": re.compile(r"`[^`\n]*/(?:api|mcp|admin|ingest)/\$\{"""),
    "concat_chemin": re.compile(r"""\+\s*["']/(?:api|mcp|admin|ingest|forge)/"""),
    "join_url": re.compile(r"urljoin\s*\(|posixpath\.join\s*\([^)]*api"),
    "base_url_var": re.compile(r"(?:HUB_URL|BASE_URL|hub_url|base_url)\s*[+%]|"
                               r"\{(?:HUB_URL|hub_url|base|base_url)\}"),
    "route_depuis_config": re.compile(r"""(?:route|endpoint|path)\s*=\s*(?:cfg|config|os\.environ|"""
                                      r"""json\.loads|\w+\[["'])"""),
}


def balayer() -> dict:
    t0 = time.time()
    hits: dict = {k: [] for k in MOTIFS}
    lus = illisibles = trop_gros = 0
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUS]
        if any(x in base for x in EXCLUS):
            continue
        for f in files:
            if not f.endswith(EXTS):
                continue
            if f in _OBSERVATEURS:
                # TROISIEME occurrence du meme defaut le 2026-09-02 : ce fichier
                # DECRIT les motifs qu'il cherche, donc il se trouve lui-meme.
                # Les deux seuls hits `f_string_api` et `template_ts` du premier
                # balayage etaient les exemples de cette docstring. Un instrument
                # qui se compte parmi ses mesures fabrique ce qu'il rapporte.
                continue
            p = Path(base) / f
            try:
                if p.stat().st_size > TAILLE_MAX:
                    trop_gros += 1
                    continue
                src = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                # « je n'ai pas pu lire » n'est PAS « rien trouve » : sans ce
                # compteur, la couverture serait surestimee en silence.
                illisibles += 1
                continue
            lus += 1
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            for nom, pat in MOTIFS.items():
                for m in pat.finditer(src):
                    ligne = src.count("\n", 0, m.start()) + 1
                    extrait = src[max(0, m.start() - 45):m.start() + 70]
                    hits[nom].append({
                        "fichier": rel, "ligne": ligne,
                        "extrait": " ".join(extrait.split())[:120],
                    })
    total = sum(len(v) for v in hits.values())
    return {
        "fichiers_lus": lus,
        "fichiers_illisibles": illisibles,
        "fichiers_trop_gros": trop_gros,
        "total_sites": total,
        "par_motif": {k: len(v) for k, v in hits.items()},
        "hits": hits,
        "duree_s": round(time.time() - t0, 1),
        "avertissement": (
            "Ces sites ne sont PAS des appelants prouves : ce sont des endroits "
            "ou une URL peut etre construite, donc ou un appelant echappe au "
            "grep litteral. Leur nombre borne la confiance qu'on peut accorder "
            "a « aucun appelant trouve dans le depot »."
        ),
    }


def main() -> int:
    r = balayer()
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print("fichiers lus      : %d  (illisibles : %d, ecartes car >2 Mo : %d)"
          % (r["fichiers_lus"], r["fichiers_illisibles"], r["fichiers_trop_gros"]))
    print("sites dynamiques  : %d en %s s" % (r["total_sites"], r["duree_s"]))
    print("par motif         : %s" % r["par_motif"])
    for nom, items in r["hits"].items():
        if not items:
            continue
        print("\n-- %s (%d) --" % (nom, len(items)))
        for h in items[:8]:
            print("   %-42s:%-5d %s" % (h["fichier"][:42], h["ligne"], h["extrait"][:70]))
        if len(items) > 8:
            print("   ... %d autres (voir %s)" % (len(items) - 8, SORTIE.name))
    print("\necrit : %s" % SORTIE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
