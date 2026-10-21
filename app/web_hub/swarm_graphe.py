"""Vue /swarm/graphe : qui travaille sur quoi (item SSoT p1_swarm_en_direct_graphique_2026-10-14).

Mesure 19/10 03:04 : le miroir sandbox/reflexion.jsonl vit mais ne porte ni task_* ni job_* -- le bus ne voit pas le
travail des executeurs. Premiere marche, sans attendre le bus : lecture SEULE de tasks.db, graphe agents -> taches
(en vol et recentes), couleur par statut. Anti-dup : le rendu est celui de l'arbre roadmap (roadmap_arbre.page_html
sur graph_viz.html, vis-network vendorise) ; ce module ne fait que le graphe.
"""
from __future__ import annotations

__FORGE_COLOR__ = "interface/ui_swarm : graphe agents -> taches de l'essaim (tasks.db, vis-network)"

from pathlib import Path

ICI = Path(__file__).resolve().parent
BORNE = 60
COULEURS = {"running": "#1565c0", "claimed": "#1565c0", "assigned": "#1565c0", "pending": "#9e9e9e",
            "done": "#2e7d32", "failed": "#c62828", "error": "#c62828"}
COULEUR_INCONNUE = "#ff00ff"      # un statut neuf reste VISIBLE


def lire_taches(db=None, limite: int = 200):
    """[(id, agent, statut, description)] des taches les plus recentes, en lecture seule ; base illisible -> None."""
    import sqlite3
    db = Path(db) if db is not None else ICI.parents[1] / "sandbox" / "tasks.db"
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        try:
            return con.execute("SELECT id, agent, status, substr(description, 1, 300) FROM tasks "
                               "ORDER BY rowid DESC LIMIT ?", (int(limite),)).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - illisible n'est pas vide : None, et la page le dit
        return None


def graphe_taches(lignes, borne: int = BORNE) -> dict:
    """{nodes, edges, libelle, ecartees} : un noeud par agent, un par tache (au plus `borne`, l'ecart est DIT)."""
    lignes = list(lignes or [])
    gardees = lignes[:borne]
    nodes, edges, agents = [], [], set()
    for tid, agent, statut, desc in gardees:
        agent = str(agent or "?").upper()
        if agent not in agents:
            agents.add(agent)
            nodes.append({"id": "agent:" + agent, "label": agent, "groupe": "agent", "shape": "box"})
        statut = str(statut or "?")
        nid = "tache:" + str(tid)
        nodes.append({"id": nid, "label": str(tid)[:22], "groupe": "item", "statut": statut,
                      "color": COULEURS.get(statut, COULEUR_INCONNUE),
                      "title": "%s [%s]\n%s" % (tid, statut, str(desc or "")[:200])})
        edges.append({"from": "agent:" + agent, "to": nid})
    return {"nodes": nodes, "edges": edges, "libelle": "taches", "ecartees": max(0, len(lignes) - len(gardees))}
