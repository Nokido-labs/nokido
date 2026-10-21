"""Page arbre d'evolution de la roadmap (item SSoT roadmap_p1_arbre_evolution_ui_web_20261017).

Owner : « un visu total de la roadmap dans l'ui web, sous forme d'arbre d'evolution, multi-partite ». Ce module ne LIT
rien : il met en forme le document que rend deja `tools/forge_roadmap_keeper.arbre()` ({genere_le, total, par_etat,
items:[{cle, etat, priorite, reste}]}). Graphe vis-network : racine -> une branche par priorite -> un noeud par item,
colore par etat. Aucun item n'est perdu (un etat inattendu garde une couleur de repli) et une troncature se DIT.
Anti-dup : la page est `graph_viz.html` (deja vis-network vendorise, jamais de CDN) dans sa vue `roadmap` ; on y
injecte le graphe, on n'ecrit pas une seconde page.
"""
from __future__ import annotations

__FORGE_COLOR__ = "interface/ui_roadmap : arbre d'evolution de la roadmap sur la page graph_viz (vis-network)"

import json
from pathlib import Path

ICI = Path(__file__).resolve().parent
GABARIT = ICI / "graph_viz.html"
VIS_JS = ICI / "static" / "vis-network.min.js"
SRC_VIS = ' src="/static/vis-network.min.js">'
ANCRE = "function nodeDef("
TITRE_MAX = 200

COULEURS = {"CLOS": "#2e7d32", "PARTIEL": "#f9a825", "DECISION_OWNER": "#c62828", "OWNER_PLANIFIE": "#6a1b9a",
            "GELE": "#607d8b", "SANS_MARQUEUR": "#9e9e9e"}
COULEUR_INCONNUE = "#ff00ff"          # un etat neuf reste VISIBLE, jamais range avec les sains
PRIORITES = ("P0", "P1", "P2")


def _prio(p) -> str:
    p = str(p or "").upper()
    return p if p in PRIORITES else "sans"


def _titre(item: dict) -> str:
    reste = str(item.get("reste") or "")
    if len(reste) > TITRE_MAX:
        reste = "%s... [tronque : %d car. sur %d]" % (reste[:TITRE_MAX], TITRE_MAX, len(reste))
    return "%s [%s]\n%s" % (item.get("cle") or "?", item.get("etat") or "?", reste)


_EN_VOL = ("running", "claimed", "assigned")


def porteurs_en_vol(cles, db=None) -> dict:
    """{cle: agent} des items cites par une tache EN VOL de tasks.db (lecture seule) ; base illisible -> {}."""
    import sqlite3
    db = Path(db) if db is not None else ICI.parents[1] / "sandbox" / "tasks.db"
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        try:
            taches = con.execute("SELECT agent, description FROM tasks WHERE status IN (?,?,?)", _EN_VOL).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - porteurs inconnus : la page s'affiche sans, elle ne ment pas
        return {}
    out = {}
    for cle in cles:
        for agent, desc in taches:
            if cle and cle in str(desc or ""):
                out[cle] = str(agent or "?").upper()
                break
    return out


def _dependances(items: list) -> tuple:
    """({cle: {items qu'elle debloque}}, nb de cycles casses) depuis les citations (`cite`) -- graphe SANS cycle :
    une arete qui fermerait un cycle (citations mutuelles) est ecartee et comptee."""
    cles = {str(it.get("cle")) for it in items}
    adj = {c: set() for c in cles}

    def atteint(depart: str, cible: str) -> bool:
        pile, vus = [depart], set()
        while pile:
            x = pile.pop()
            if x == cible:
                return True
            if x not in vus:
                vus.add(x)
                pile.extend(adj[x])
        return False

    cassees = 0
    for it in sorted(items, key=lambda i: str(i.get("cle"))):
        a = str(it.get("cle"))
        for b in sorted(set(it.get("cite") or []) & cles):
            if b == a:
                continue
            if atteint(a, b):
                cassees += 1
                continue
            adj[b].add(a)
    return adj, cassees


def graphe(arbre: dict, porteurs: dict | None = None) -> dict:
    """{nodes, edges, hierarchie, cycles_casses} vis-network depuis le document de `arbre()`. Pur.

    Vraie hierarchie de RESOLUTION (owner 19/10) : arete « debloque » de l'item cite vers l'item qui le cite ; seul un
    item SANS prerequis pend sous sa priorite. `porteurs` = {cle: agent} (multi-partite)."""
    porteurs = porteurs or {}
    items = list((arbre or {}).get("items") or [])
    adj, cassees = _dependances(items)
    prerequis = {c: set() for c in adj}
    for b, cibles in adj.items():
        for a in cibles:
            prerequis[a].add(b)
    nodes = [{"id": "roadmap", "label": "roadmap", "groupe": "racine", "shape": "box"}]
    edges = []
    for p in PRIORITES + ("sans",):
        nodes.append({"id": "prio:" + p, "label": p, "groupe": "priorite", "shape": "ellipse"})
        edges.append({"from": "roadmap", "to": "prio:" + p})
    for item in items:
        cle = str(item.get("cle") or "?")
        etat = str(item.get("etat") or "SANS_MARQUEUR")
        nid = "item:" + cle
        n_debloque = len(adj.get(cle, ()))
        noeud = {"id": nid, "label": cle[:40], "groupe": "item", "etat": etat, "debloque": n_debloque,
                 "color": COULEURS.get(etat, COULEUR_INCONNUE), "title": _titre(item)}
        if n_debloque:
            noeud["label"] += "\n> debloque %d" % n_debloque
        porteur = porteurs.get(item.get("cle"))
        if porteur:
            noeud["porteur"] = porteur
            noeud["label"] += "\n[%s]" % porteur
        nodes.append(noeud)
        if not prerequis.get(cle):
            edges.append({"from": "prio:" + _prio(item.get("priorite")), "to": nid})
    for b in sorted(adj):
        for a in sorted(adj[b]):
            edges.append({"from": "item:" + b, "to": "item:" + a, "arrows": "to", "title": "debloque"})
    return {"nodes": nodes, "edges": edges, "hierarchie": True, "cycles_casses": cassees}


def page_html(g: dict, vis_js: str | None = None, gabarit: str | None = None) -> str:
    """graph_viz.html avec le graphe injecte (const ROADMAP_GRAPHE, vue roadmap) ; `vis_js` embarque la lib a la
    place de son src (page autonome). Gabarit sans ancre -> ValueError : une page muette ne se rend pas en silence."""
    page = gabarit if gabarit is not None else GABARIT.read_text(encoding="utf-8")
    if ANCRE not in page:
        raise ValueError("gabarit graph_viz.html sans ancre %r : vue roadmap impossible" % ANCRE)
    donnees = json.dumps(g, ensure_ascii=False).replace("</", "<\\/")
    page = page.replace(ANCRE, "const ROADMAP_GRAPHE = %s;\n%s" % (donnees, ANCRE), 1)
    if vis_js and SRC_VIS in page:
        page = page.replace(SRC_VIS, ">" + vis_js.replace("</", "<\\/"), 1)
    return page


def ecrire_page(arbre: dict, chemin) -> Path:
    """Ecrit la page AUTONOME (lib embarquee) pour `arbre` ; rend le chemin ecrit."""
    cible = Path(chemin)
    cible.parent.mkdir(parents=True, exist_ok=True)
    vis = VIS_JS.read_text(encoding="utf-8", errors="replace")
    cible.write_text(page_html(graphe(arbre), vis_js=vis), encoding="utf-8")
    return cible
