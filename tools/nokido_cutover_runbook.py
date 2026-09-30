"""nokido_cutover_runbook.py — genere docs/cutover_runbook.md (mermaid inclus).

POURQUOI UN GENERATEUR ET PAS UN DOCUMENT. Un runbook ecrit a la main vieillit en
silence : il dira « 33 services » longtemps apres qu'il y en ait 30. Celui-ci se
REGENERE depuis les mesures (registre, superviseur, disque, graphe d'imports), donc il
ne peut pas mentir plus vieux que sa derniere execution, qui est datee dedans.

CE QU'IL ASSEMBLE, en reutilisant l'existant plutot qu'en le recalculant :
  * `nokido_cutover_owner.preflight()` — surfaces a reecrire + verification des chemins ;
  * `nokido_nssm_path_audit` — la mesure NSSM (rédaction des secrets comprise) ;
  * `proxy_deno/core/services.toml` — ce que le SUPERVISEUR gouverne, pour distinguer un
    service vivant d'un reliquat NSSM ;
  * un graphe d'imports AST — le rayon de souffle par module.

POURQUOI LE GRAPHE EST RECALCULE ICI. `forge_graph_linker.get_impacted_by_change` est la
primitive prevue pour ca, mais mesure le 2026-08-11 : ses aretes structurelles ne visent
que 247 noeuds et AUCUNE carte de module. Pour un module de app/ ou tools/ elle rend donc
`[]` — indistinguable de « aucun impact ». Tant que cette couverture n'existe pas, un
runbook qui s'y fierait afficherait un rayon de souffle nul et rassurant. Le graphe AST,
lui, est complet et deterministe. A rebrancher sur le linker le jour ou il couvrira les
modules.

LECTURE SEULE. N'ecrit que docs/cutover_runbook.md.

CLI :
    LAFORGE_PYTHON tools/nokido_cutover_runbook.py
    LAFORGE_PYTHON tools/nokido_cutover_runbook.py --sortie docs/cutover_runbook.md
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/rename : genere docs/cutover_runbook.md"

import argparse
import ast
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.tools import nokido_cutover_owner as owner       # noqa: E402  (chemin ajoute juste au-dessus)


def _graphe_imports() -> tuple[dict, dict, int]:
    """Graphe d'imports INTERNES. Rend (imports, importe_par, nb_aretes)."""
    fichiers = [p for p in list(ROOT.glob("app/**/*.py")) + list(ROOT.glob("tools/**/*.py"))
                if "_attic" not in p.parts and "bench_fixtures" not in p.parts]
    mods = {p.stem for p in fichiers}
    imports: dict[str, set[str]] = defaultdict(set)
    for p in fichiers:
        try:
            arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(arbre):
            cible = None
            if isinstance(n, ast.Import):
                for a in n.names:
                    base = a.name.split(".")[0]
                    if base in mods and base != p.stem:
                        imports[p.stem].add(base)
                continue
            if isinstance(n, ast.ImportFrom) and n.module:
                cible = n.module.split(".")[0]
            if cible and cible in mods and cible != p.stem:
                imports[p.stem].add(cible)
    inverse: dict[str, set[str]] = defaultdict(set)
    for m, deps in imports.items():
        for d in deps:
            inverse[d].add(m)
    return imports, inverse, sum(len(v) for v in imports.values())


def _superviseur() -> list[str]:
    toml = ROOT / "proxy_deno" / "core" / "services.toml"
    if not toml.is_file():
        return []
    return re.findall(r'name\s*=\s*"([^"]+)"', toml.read_text(encoding="utf-8", errors="replace"))


def _norm(x: str) -> str:
    """Nom comparable ENTRE EPOQUES de nommage.

    Mesure 2026-08-11 : sans retirer le prefixe de marque, l'intersection superviseur /
    NSSM tombait a 1 et le diagramme concluait « 31 services que personne ne redemarre ».
    Artefact : le superviseur declare les memes organes sous le prefixe courant, le
    registre les porte encore sous l'ancien. Prefixe retire -> 28 doublons d'epoque et
    seulement 4 services reellement sans equivalent.
    """
    return re.sub(r"^(laforge|nokido)", "", x.lower().replace("-", "").replace("_", ""))


def _lib(x: str) -> str:
    """Libelle mermaid sur : un guillemet parasite (il y en a dans le registre) casse
    le noeud, et le diagramme entier cesse de s'afficher."""
    return re.sub(r'[\"`\[\]{}|]', "", str(x)).strip()


def _mermaid_surfaces(r: dict, n_sup: int) -> str:
    svc, cfg = r["services"], r["configs"]
    t = r["taches"]
    n_t = len(t.get("items", [])) if t.get("etat") == "OK" else "? (non conclusif)"
    return f"""```mermaid
flowchart TD
    subgraph DEDANS["Dans le depot — deja insensible au nom (phase 0)"]
        CODE["code app/ + tools/<br/>racine derivee de __file__"]
        RUNTIME["etat runtime<br/>domaines RAG, fichier d'environnement"]
    end
    subgraph DEHORS["Hors du depot — ce que le cutover doit rebrancher"]
        NSSM["services NSSM<br/>{len(svc['items'])} concernes / {svc['enumeres']} enumeres"]
        TASK["taches planifiees<br/>{n_t} concernee(s)"]
        CFG["configs clientes<br/>{len(cfg['items'])} fichier(s)"]
        SUPER["superrepo<br/>.gitmodules + index + .git/modules"]
    end
    DOSSIER(["renommage du dossier<br/>{r['ancien']} -> {r['nouveau']}"])
    DOSSIER --> CODE
    DOSSIER --> NSSM
    DOSSIER --> TASK
    DOSSIER --> CFG
    DOSSIER --> SUPER
    DOSSIER --> RUNTIME
    CODE -. "aucune action: derive" .-> OK1[/"rien a faire"/]
    RUNTIME -. "outil dedie" .-> MIG["nokido_cutover_migrate.py --apply"]
    NSSM --> VER{{"verification des chemins<br/>OK / ABSENT / ILLISIBLE"}}
    TASK --> VER
    CFG --> VER
    SUPER --> VER
    VER -->|"un seul ABSENT"| STOP["arret: on ne renomme pas"]
    VER -->|"tout OK"| GO["cutover applique"]
```"""


def _mermaid_gouvernance(r: dict, sup: list[str]) -> str:
    nssm = [it["service"] for it in r["services"]["items"]]
    sup_norm = {_norm(s) for s in sup}
    doubles = [s for s in nssm if _norm(s) in sup_norm]      # meme organe, deux epoques
    reliquats = [s for s in nssm if _norm(s) not in sup_norm]
    ex_rel = "<br/>".join(_lib(x) for x in reliquats[:8]) + ("<br/>..." if len(reliquats) > 8 else "")
    ex_dbl = "<br/>".join(_lib(x) for x in doubles[:8]) + ("<br/>..." if len(doubles) > 8 else "")
    return f"""```mermaid
flowchart LR
    SUP["superviseur Deno<br/>{len(sup)} services declares"]
    NSSM["registre NSSM<br/>{len(nssm)} services nommant le depot"]
    D["MEME organe des deux cotes<br/>{len(doubles)} entrees NSSM doublonnees<br/>{ex_dbl or '(aucune)'}"]
    R["NSSM sans equivalent<br/>{len(reliquats)}<br/>{ex_rel or '(aucun)'}"]
    SUP --> D
    NSSM --> D
    NSSM --> R
    D -. "l entree NSSM est une survivance" .-> Q1(["le superviseur porte l organe<br/>sous le nom courant"])
    R -. "a instruire" .-> Q2(["ni le superviseur ni personne<br/>ne les redemarre"])
```

Comparaison faite **prefixe de marque retire** : le superviseur declare les organes sous
le nom courant, le registre les porte sous l'ancien. Sans cette normalisation
l'intersection tombe a 1 et le diagramme accuse a tort une trentaine d'orphelins."""


def _mermaid_morts(r: dict) -> str:
    morts = r["refs_mortes_AVANT"]
    if not morts:
        return "_Aucune reference morte : le cutover peut etre applique._"
    lignes = ["```mermaid", "flowchart TD", '    T["references DEJA mortes AVANT le cutover"]']
    for i, m in enumerate(morts[:14]):
        svc = m.split(":")[0]
        cible = m.split(": ", 1)[1].split(" (")[0] if ": " in m else "?"
        lignes.append(f'    T --> M{i}["{_lib(svc)}<br/>-> {_lib(Path(cible).name)}"]')
    lignes.append("```")
    return "\n".join(lignes)


def _rayon(inverse: dict, cibles: list[str], n: int = 10) -> str:
    """Modules les plus exposes parmi les cibles: qui les importe, au 1er et 2e rang."""
    classe = []
    for m in cibles:
        d1 = inverse.get(m, set())
        d2 = (set().union(*[inverse.get(x, set()) for x in d1]) - d1 - {m}) if d1 else set()
        classe.append((len(d1) + len(d2), m, sorted(d1), len(d2)))
    classe.sort(reverse=True)
    out = ["| module | importe par | 2e rang | importateurs directs |", "|---|---:|---:|---|"]
    for _, m, d1, n2 in classe[:n]:
        out.append(f"| `{m}` | {len(d1)} | {n2} | {', '.join('`' + x + '`' for x in d1[:5]) or '—'} |")
    return "\n".join(out)


def construire(sortie: Path) -> Path:
    r = owner.preflight()
    sup = _superviseur()
    _, inverse, aretes = _graphe_imports()
    touches = sorted({p.stem for p in list(ROOT.glob("app/*.py")) + list(ROOT.glob("tools/*.py"))
                      if p.stem in inverse}, key=lambda m: -len(inverse[m]))[:12]
    svc, cfg = r["services"], r["configs"]
    t = r["taches"]
    horodatage = time.strftime("%Y-%m-%d %H:%M")

    doc = f"""# Runbook de cutover — renommage du dossier `{r['ancien']}` vers `{r['nouveau']}`

> Genere par `tools/nokido_cutover_runbook.py` le {horodatage}. **Ne pas editer a la main** :
> regenerer. Les nombres ci-dessous sont des MESURES, pas des estimations.

## Ce que le cutover doit rebrancher

{_mermaid_surfaces(r, len(sup))}

Le code du depot n'est **pas** concerne : la phase 0 lui a fait deriver sa racine de
`__file__`. Ce qui casse au renommage, c'est ce qui vit **dehors** et le nomme en dur.

| surface | mesure | denominateur |
|---|---:|---|
| services NSSM | {len(svc['items'])} | {svc['enumeres']} services enumeres, {svc['sans_params']} non-NSSM, **{svc['illisibles']} illisibles** |
| taches planifiees | {len(t.get('items', [])) if t.get('etat') == 'OK' else t.get('etat', 'ILLISIBLE')} | {t.get('lignes_vues', '?')} ligne(s) enumerees{(' — ' + t['motif']) if t.get('motif') else ''} |
| configs clientes | {len(cfg['items'])} | profil scanne `{cfg.get('profil_scanne', '?')}` · {len(cfg['absents'])} absente(s), **{len(cfg['illisibles'])} illisible(s)** |
| chemins verifies | {r['refs_verifiees']} | {r['refs_illisibles']} illisible(s), **{len(r['refs_mortes_AVANT'])} deja mort(s)** |

`ILLISIBLE` n'est pas `ABSENT` : un compte qui n'a pas le droit de statuer ne prouve
rien. Toute ligne illisible ci-dessus doit etre relue depuis la **console owner** avant
de conclure.

## Qui gouverne quoi (et ce que personne ne gouverne)

{_mermaid_gouvernance(r, sup)}

Un service NSSM que le superviseur ne declare pas ne sera **redemarre par personne**.
Avant de le reecrire, trancher : reliquat a supprimer, ou secours manuel a garder ?

## Ce qui est deja casse AVANT le cutover

{_mermaid_morts(r)}

Ces references ne sont **pas** un effet du renommage : elles sont mortes maintenant. Le
script refuse `--apply` tant qu'elles sont la — sinon le cutover porterait leur chapeau.

Deux precautions avant de conclure sur une reference absente : un binaire peut avoir ete
produit **ailleurs** (repertoire de sortie redirige, installation dans le profil), et le
profil de l'owner est **illisible** depuis un compte de service — ou `exists()` rend
`False` pour un dossier qui existe. Trancher en **console owner**, pas ici.

## Rayon de souffle du code (graphe d'imports, {aretes} aretes internes)

{_rayon(inverse, touches)}

## Marche a suivre

```bash
# 1. Mesurer, sans rien ecrire (n'exige pas l'elevation)
LAFORGE_PYTHON tools/nokido_cutover_owner.py

# 2. Voir chaque reecriture et sa cible verifiee
LAFORGE_PYTHON tools/nokido_cutover_owner.py --plan

# 3. Purger les references deja mortes (sinon --apply refuse)

# 4. Appliquer, en console ELEVEE
LAFORGE_PYTHON tools/nokido_cutover_owner.py --apply --confirm RENOMMER

# 5. Revalider apres coup
LAFORGE_PYTHON tools/nokido_cutover_owner.py --verify

# 6. En cas de doute, revenir en arriere
LAFORGE_PYTHON tools/nokido_cutover_owner.py --rollback sandbox/cutover_<horodatage>
```

`--apply` fait, dans cet ordre : arret des services, renommage du dossier, reecriture des
references (registre, taches, configs), alignement du superrepo, migration de l'etat
runtime par `nokido_cutover_migrate.py`, verification, redemarrage. Un instantane complet
est ecrit **avant** la premiere ecriture ; c'est lui que rejoue `--rollback`.

## Ce que le script ne fait PAS, volontairement

- Il ne touche pas aux **noms de services, de comptes, de variables d'environnement ni au
  fichier d'environnement** : le nom du dossier en est aussi le prefixe, et la reecriture
  est contrainte au **segment de chemin** pour cette raison exacte.
- Il n'imprime **jamais** la valeur d'une variable d'environnement de service : plusieurs
  portent des jetons en clair. Seuls les noms apparaissent.
- Il ne reimporte pas automatiquement les taches planifiees au rollback : l'XML d'origine
  est dans l'instantane, la reimportation se fait a la main et se verifie.
"""
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(doc, encoding="utf-8")
    return sortie


def _main() -> int:
    ap = argparse.ArgumentParser(description="Genere le runbook de cutover")
    ap.add_argument("--sortie", default=str(ROOT / "docs" / "cutover_runbook.md"))
    a = ap.parse_args()
    p = construire(Path(a.sortie))
    print(f"[runbook] ecrit : {p} ({p.stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
