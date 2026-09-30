"""
forge_graph_explorer.py — Nokido Graph Explorer GUI
=====================================================
Application web locale pour l'exploration interactive de graphes.

Lancement :
    python app/forge_graph_explorer.py
    → http://localhost:7474

Fonctionnalités GUI :
    ├─ CHARGEMENT  : CSV, JSON, matrice, générateurs intégrés
    ├─ VISUALISATION : Cytoscape.js — zoom/pan/sélection/drag nœuds
    ├─ LAYOUTS     : spring / circular / cose / breadthfirst / concentric
    ├─ ANALYSE     : centralité, communautés, stats, chemins
    ├─ GNN         : embed, node classify, link predict (async)
    ├─ FILTRES     : par degré, par communauté, par score
    └─ EXPORT      : PNG, JSON Cytoscape, GEXF, rapport
"""

from __future__ import annotations

import asyncio
import io
import json

# DEAD_IMPORT removed: import os
import sys
import threading

# DEAD_IMPORT removed: import time
# DEAD_IMPORT removed: import traceback
import webbrowser
from pathlib import Path
from typing import Any, Optional

# ── Ajout du répertoire app au path ──────────────────────────────────────────
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import networkx as nx

# DEAD_IMPORT removed: import numpy as np
import uvicorn
import os as _os
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from nokido_agent.app.forge_graph_studio import GraphStudio

# ══════════════════════════════════════════════════════════════════════════════
# APP FASTAPI
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Nokido Graph Explorer", version="1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://127.0.0.1", "http://localhost"], allow_methods=["*"], allow_headers=["*"]
)

_GRAPH_TOKEN = _os.environ.get("FORGE_MCP_TOKEN", "")


@app.middleware("http")
async def _bearer_auth(request: Request, call_next):
    # `scope["path"]`, jamais le `url.path` de la requete : sous Starlette 0.52.1 un en-tete
    # `Host: x/ping?x=` faisait lire `/ping` (exempte) pour une requete vers une route
    # protegee — contournement MESURE le 2026-09-24 (CVE-2026-48710).
    if request.scope["path"] in ("/ping", "/"):
        return await call_next(request)
    if _GRAPH_TOKEN:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != _GRAPH_TOKEN:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)


# Charte UI commune (palette netcfg-agent) — servie depuis app/web_hub/static
from fastapi.staticfiles import StaticFiles  # noqa: E402

_LAFORGE_STATIC = _APP_DIR / "web_hub" / "static"
if _LAFORGE_STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_LAFORGE_STATIC)), name="static")

# State global (une session = un graphe actif)
_state: dict[str, Any] = {
    "gs": None,  # GraphStudio actif
    "name": "",
    "analysis": {},  # résultats d'analyse mis en cache
    "gnn_task": None,  # tâche GNN en cours
}


# ══════════════════════════════════════════════════════════════════════════════
# SÉRIALISATION graphe → Cytoscape.js
# ══════════════════════════════════════════════════════════════════════════════


def _gs_to_cyto(gs: GraphStudio) -> dict:
    """Convertit GraphStudio → format éléments Cytoscape.js."""
    G = gs.G
    cent = gs._centrality.get("pagerank", {})
    comm_map: dict = {}
    if gs._communities:
        for i, c in enumerate(gs._communities):
            for node in c:
                comm_map[node] = i

    max_cent = max(cent.values(), default=1e-8)
    nodes = []
    for n in G.nodes():
        data = G.nodes[n]
        c_val = cent.get(n, 0.0)
        nodes.append(
            {
                "data": {
                    "id": str(n),
                    "label": str(data.get("label", n)),
                    "degree": G.degree(n),
                    "centrality": round(c_val / max_cent, 4),
                    "community": comm_map.get(n, 0),
                    **{k: str(v) for k, v in data.items()},
                }
            }
        )

    edges = []
    for i, (u, v, d) in enumerate(G.edges(data=True)):
        # On serialise tous les attributs en string (coherent avec nodes)
        # pour que le frontend puisse colorier par 'type' et afficher
        # la 'description' au hover.
        edge_data = {
            "id": f"e{i}",
            "source": str(u),
            "target": str(v),
            "weight": d.get("weight", 1.0),
        }
        for k, v2 in d.items():
            if k == "weight":
                continue
            edge_data[k] = str(v2) if not isinstance(v2, (str, int, float, bool)) else v2
        edges.append({"data": edge_data})
    return {"nodes": nodes, "edges": edges}


# ══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/ping")
def ping():
    """Health endpoint pour le hub web (Nokido)."""
    return "pong"


@app.get("/api/status")
def status():
    """Statut du graphe actif.

    Defensif : chaque champ stats() est isole pour qu'une exception
    sur une metrique particuliere (ex: average_clustering qui leve
    NetworkXNotImplemented sur un MultiGraph) ne casse PAS la reponse
    entiere. Le frontend recoit toujours les champs principaux
    (n_nodes, n_edges, loaded=true) meme si certaines metriques
    optionnelles sont marquees None.
    """
    gs = _state["gs"]
    if gs is None:
        return {"loaded": False}

    # Champs de base : toujours disponibles depuis gs directement.
    result = {
        "loaded": True,
        "name": gs.name,
        "n_nodes": gs.n,
        "n_edges": gs.m,
        "is_multigraph": gs.G.is_multigraph(),
        "analysis_keys": list(_state["analysis"].keys()),
    }

    # Champs issus de stats() : encapsules pour tolerer les cas pathologiques.
    # Sur un MultiGraph, average_clustering leve NetworkXNotImplemented ;
    # sur un graphe disconnecte, diameter leve NetworkXError.
    try:
        st = gs.stats()
        result.update(
            {
                "density": round(st.density, 4),
                "directed": st.is_directed,
                "connected": st.is_connected,
                "components": st.n_components,
                "avg_degree": round(st.avg_degree, 2),
                "diameter": st.diameter,
            }
        )
    except Exception as e:
        # On log mais on renvoie quand meme une reponse valide au frontend
        print(f"[Graph Explorer] stats() partiellement KO: {type(e).__name__}: {e}")
        # Metriques pouvant etre calculees individuellement, tolerantes
        import networkx as nx

        G = gs.G
        try:
            result["density"] = round(nx.density(G), 4)
        except Exception:
            result["density"] = None
        result["directed"] = G.is_directed()
        try:
            result["connected"] = nx.is_connected(G) if not G.is_directed() else nx.is_weakly_connected(G)
        except Exception:
            result["connected"] = None
        try:
            if G.is_directed():
                result["components"] = nx.number_weakly_connected_components(G)
            else:
                result["components"] = nx.number_connected_components(G)
        except Exception:
            result["components"] = None
        try:
            result["avg_degree"] = round(sum(dict(G.degree()).values()) / max(1, G.number_of_nodes()), 2)
        except Exception:
            result["avg_degree"] = None
        # diameter : non calcule (requiert graphe connexe + non-multigraph)
        result["diameter"] = None
        result["stats_warning"] = str(e)[:200]

    return result


@app.get("/api/graph")
def get_graph():
    if _state["gs"] is None:
        raise HTTPException(404, "Aucun graphe chargé")
    return JSONResponse(_gs_to_cyto(_state["gs"]))


# ── Chargement ────────────────────────────────────────────────────────────────


@app.post("/api/load/generator")
async def load_generator(payload: dict):
    """Charge un graphe généré."""
    kind = payload.get("kind", "karate_club")
    params = payload.get("params", {})
    try:
        generators = {
            "karate_club": lambda: GraphStudio.karate_club(),
            "les_miserables": lambda: GraphStudio.les_miserables(),
            "florentine": lambda: GraphStudio.florentine_families(),
            "erdos_renyi": lambda: GraphStudio.erdos_renyi(params.get("n", 50), params.get("p", 0.15)),
            "barabasi_albert": lambda: GraphStudio.barabasi_albert(params.get("n", 100), params.get("m", 2)),
            "watts_strogatz": lambda: GraphStudio.watts_strogatz(
                params.get("n", 80), params.get("k", 6), params.get("p", 0.1)
            ),
            "grid": lambda: GraphStudio.grid(params.get("rows", 5), params.get("cols", 5)),
            "tree": lambda: GraphStudio.tree(params.get("depth", 3), params.get("branching", 2)),
            "complete": lambda: GraphStudio.complete(params.get("n", 10)),
        }
        if kind not in generators:
            raise ValueError(f"Générateur inconnu: {kind}")
        gs = generators[kind]()
        _state["gs"] = gs
        _state["name"] = gs.name
        _state["analysis"] = {}
        return {"ok": True, "name": gs.name, "n": gs.n, "m": gs.m}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/load/json")
async def load_json_data(payload: dict):
    """Charge un graphe depuis JSON (node_link format ou adjacency)."""
    try:
        data = payload.get("data", {})
        name = payload.get("name", "imported_graph")
        gs = GraphStudio.from_dict(data, name=name)
        _state["gs"] = gs
        _state["analysis"] = {}
        return {"ok": True, "name": name, "n": gs.n, "m": gs.m}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/load/file")
async def load_file(file: UploadFile = File(...)):
    """Upload et chargement d'un fichier CSV/JSON."""
    try:
        content = await file.read()
        name = Path(file.filename).stem
        suffix = Path(file.filename).suffix.lower()
        print(f"[Graph Explorer] Upload: {file.filename} ({len(content)} bytes)")

        if suffix == ".json":
            try:
                data = json.loads(content.decode("utf-8", errors="replace"))
                print(
                    f"[Graph Explorer] JSON decode success, keys: {list(data.keys()) if isinstance(data, dict) else 'list'}"
                )
                gs = GraphStudio.from_dict(data, name=name)
                print(f"[Graph Explorer] GraphStudio loaded: n={gs.n}, m={gs.m}")
            except Exception as je:
                print(f"[Graph Explorer] JSON Error: {je}")
                raise ValueError(f"Erreur lecture JSON: {je}")

        elif suffix == ".csv":
            import io as _io
            import pandas as pd

            df = pd.read_csv(_io.BytesIO(content))
            # Détecter colonnes src/dst
            src_col = next(
                (c for c in df.columns if c.lower() in ("src", "source", "from", "node1", "u")), df.columns[0]
            )
            dst_col = next((c for c in df.columns if c.lower() in ("dst", "target", "to", "node2", "v")), df.columns[1])
            G = nx.Graph()
            for _, row in df.iterrows():
                G.add_edge(row[src_col], row[dst_col])
            gs = GraphStudio.from_nx(G, name=name)

        elif suffix in (".gexf", ".gml"):
            tmp_path = _APP_DIR.parent / f"tmp_upload{suffix}"
            tmp_path.write_bytes(content)
            G = nx.read_gexf(str(tmp_path)) if suffix == ".gexf" else nx.read_gml(str(tmp_path))
            gs = GraphStudio.from_nx(G, name=name)
            tmp_path.unlink(missing_ok=True)

        else:
            raise ValueError(f"Format non supporté: {suffix}")

        _state["gs"] = gs
        _state["analysis"] = {}
        return {"ok": True, "name": name, "n": gs.n, "m": gs.m}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Analyse ───────────────────────────────────────────────────────────────────


@app.post("/api/analyse/centrality")
async def run_centrality(payload: dict):
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    metrics = payload.get("metrics", ["degree", "pagerank"])
    result = gs.centrality(metrics)
    # Top-10 par métrique
    tops = {m: sorted(c.items(), key=lambda x: -x[1])[:10] for m, c in result.items()}
    _state["analysis"]["centrality"] = result
    return {"ok": True, "top": tops, "metrics": metrics}


@app.post("/api/analyse/communities")
async def run_communities(payload: dict):
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    method = payload.get("method", "louvain")
    k = payload.get("k", 4)
    comms = gs.communities(method, k=k)
    _state["analysis"]["communities"] = comms
    summary = [{"id": i, "size": len(c), "nodes": list(c)[:20]} for i, c in enumerate(comms)]
    modularity = None
    try:
        Gu = gs.G.to_undirected() if gs.G.is_directed() else gs.G
        modularity = round(nx.community.modularity(Gu, comms), 4)
    except Exception:
        pass
    return {"ok": True, "n_communities": len(comms), "method": method, "modularity": modularity, "communities": summary}


@app.post("/api/analyse/paths")
async def run_paths(payload: dict):
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    src = payload.get("src")
    dst = payload.get("dst")
    k = payload.get("k", 3)
    # Convertir au bon type (int si possible)
    try:
        src = int(src)
    except (ValueError, TypeError):
        pass
    try:
        dst = int(dst)
    except (ValueError, TypeError):
        pass
    result = gs.paths(src, dst, k=k)
    return {"ok": True, **result}


@app.get("/api/analyse/spectral")
async def run_spectral():
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    result = gs.spectral(k=15)
    _state["analysis"]["spectral"] = result
    return {"ok": True, **result}


@app.get("/api/analyse/motifs")
async def run_motifs():
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    result = gs.motifs()
    return {"ok": True, **result}


@app.get("/api/analyse/clustering")
async def run_clustering():
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    result = gs.clustering()
    return {
        "ok": True,
        "global_clustering": round(result["global"], 4),
        "transitivity": round(result["transitivity"], 4),
    }


# ── GNN ───────────────────────────────────────────────────────────────────────


@app.post("/api/gnn/embed")
async def gnn_embed(payload: dict):
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    dim = payload.get("dim", 32)
    epochs = payload.get("epochs", 100)
    n_layers = payload.get("layers", 2)
    try:
        loop = asyncio.get_event_loop()
        emb = await loop.run_in_executor(None, lambda: gs.gnn_embed(hidden=dim, n_layers=n_layers, epochs=epochs))
        _state["analysis"]["gnn_emb"] = emb
        # t-SNE 2D pour visualisation
        try:
            from sklearn.manifold import TSNE

            tsne = TSNE(n_components=2, random_state=42, perplexity=min(30, gs.n // 3 + 1))
            emb2d = tsne.fit_transform(emb).tolist()
        except Exception:
            emb2d = emb[:, :2].tolist()
        nodes = list(gs.G.nodes())
        return {
            "ok": True,
            "dim": dim,
            "n_nodes": gs.n,
            "embeddings_2d": {str(nodes[i]): emb2d[i] for i in range(len(nodes))},
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/gnn/classify")
async def gnn_classify(payload: dict):
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    if not gs._nl:
        raise HTTPException(400, "Labels requis pour la classification")
    hidden = payload.get("hidden", 32)
    epochs = payload.get("epochs", 200)
    n_layers = payload.get("layers", 2)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: gs.gnn_node_classify(hidden=hidden, n_layers=n_layers, epochs=epochs)
        )
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/gnn/link_predict")
async def gnn_link_predict(payload: dict):
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    hidden = payload.get("hidden", 32)
    epochs = payload.get("epochs", 100)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: gs.gnn_link_predict(hidden=hidden, epochs=epochs))
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/gnn/node2vec")
async def gnn_node2vec(payload: dict):
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    dim = payload.get("dim", 64)
    walk_len = payload.get("walk_length", 30)
    num_walks = payload.get("num_walks", 100)
    try:
        loop = asyncio.get_event_loop()
        emb = await loop.run_in_executor(
            None, lambda: gs.node2vec(dim=dim, walk_length=walk_len, num_walks=num_walks, workers=1)
        )
        try:
            from sklearn.manifold import TSNE

            tsne = TSNE(n_components=2, random_state=42, perplexity=min(30, gs.n // 3 + 1))
            emb2d = tsne.fit_transform(emb).tolist()
        except Exception:
            emb2d = emb[:, :2].tolist()
        nodes = list(gs.G.nodes())
        return {"ok": True, "dim": dim, "embeddings_2d": {str(nodes[i]): emb2d[i] for i in range(len(nodes))}}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Export ────────────────────────────────────────────────────────────────────


@app.get("/api/export/gexf")
async def export_gexf():
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    buf = io.BytesIO()
    nx.write_gexf(gs.G, buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{gs.name}.gexf"'},
    )


@app.get("/api/export/json")
async def export_json():
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    data = nx.node_link_data(gs.G)
    return JSONResponse(data)


@app.get("/api/export/report")
async def export_report():
    gs = _state["gs"]
    if gs is None:
        raise HTTPException(404, "Aucun graphe")
    rep = gs.report()
    return JSONResponse(rep)


# ══════════════════════════════════════════════════════════════════════════════
# HTML FRONTEND
# ══════════════════════════════════════════════════════════════════════════════

_HTML = r"""
<!DOCTYPE html>
<html lang="fr" class="dark" data-theme="dark"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Graph Explorer — Nokido</title>
<link rel="stylesheet" href="/static/nokido.css">
<script src="/static/tailwind.min.js"></script>
<script src="/static/lucide.min.js"></script>
<script src="/static/cytoscape.min.js"></script>
<style>
  /* Adopte palette netcfg via /static/nokido.css en plus de Tailwind. */
  body { background: var(--bg-0, #0f172a); font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }
  #cy { width: 100%; height: 100%; background: var(--bg-0, #0f172a); }
  details[open] > summary .chev { transform: rotate(180deg); }
  summary::-webkit-details-marker { display: none; }
  summary { list-style: none; cursor: pointer; }
  .panel-body.collapsed { display: none; }  /* compat si toggle() ancienne version appelle */
  /* Scroll propre dans sidebar */
  .scroll-y { overflow-y:auto; scrollbar-width:thin; scrollbar-color:#334155 #0f172a; }
  .scroll-y::-webkit-scrollbar { width:6px; }
  .scroll-y::-webkit-scrollbar-thumb { background:#334155; border-radius:3px; }
  /* Inputs/selects : Tailwind dark compatible */
  .lf-input {
    width:100%; max-width:100%; box-sizing:border-box;
    background:#0f172a; border:1px solid #334155; color:#e2e8f0;
    padding:6px 8px; border-radius:6px; font-size:12px;
  }
  .lf-input:focus { outline:none; border-color:#3b82f6; }
</style>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen h-screen overflow-hidden">

<!-- Header unifie (aligne avec /ctf/) -->
<header class="border-b border-slate-800 px-6 py-3 flex items-center gap-4 bg-slate-950/50">
  <a href="/" class="text-slate-400 hover:text-slate-200 text-sm">&larr; Hub</a>
  <h1 class="text-xl font-bold text-blue-400 flex items-center gap-2">
    <i data-lucide="share-2" class="h-5 w-5"></i> Graph Explorer
  </h1>
  <span id="toolbar-label" class="text-xs text-slate-500 font-mono">no graph loaded</span>
  <div class="ml-auto flex items-center gap-2">
    <button onclick="fitGraph()" class="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300" title="Fit">
      <i data-lucide="maximize" class="h-3.5 w-3.5 inline"></i> Fit
    </button>
    <button onclick="resetView()" class="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300" title="Reset">
      <i data-lucide="rotate-ccw" class="h-3.5 w-3.5 inline"></i> Reset
    </button>
  </div>
</header>

<!-- Layout principal : sidebar + canvas -->
<div class="flex" style="height: calc(100vh - 57px)">

  <!-- SIDEBAR -->
  <aside class="w-[340px] shrink-0 border-r border-slate-800 bg-slate-950/40 scroll-y flex flex-col">
    <div class="p-4 space-y-3">

      <!-- CHARGER -->
      <details open class="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
        <summary class="px-3 py-2 flex items-center justify-between bg-slate-800/70 hover:bg-slate-800 text-xs uppercase tracking-wide text-blue-400 font-semibold">
          <span class="flex items-center gap-2"><i data-lucide="folder-input" class="h-3.5 w-3.5"></i> Charger un graphe</span>
          <i data-lucide="chevron-down" class="chev h-3.5 w-3.5 transition-transform"></i>
        </summary>
        <div class="p-3 space-y-3">
          <div>
            <label class="text-[11px] text-slate-400 block mb-1">Générateur</label>
            <select id="gen-kind" class="lf-input">
              <option value="karate_club">Karate Club (Zachary)</option>
              <option value="les_miserables">Les Misérables</option>
              <option value="florentine">Familles Florentines</option>
              <option value="erdos_renyi">Erdős–Rényi</option>
              <option value="barabasi_albert">Barabási–Albert</option>
              <option value="watts_strogatz">Watts–Strogatz</option>
              <option value="grid">Grille</option>
              <option value="tree">Arbre</option>
              <option value="complete">Graphe Complet</option>
            </select>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="text-[11px] text-slate-400 block mb-1">N nœuds</label>
              <input type="number" id="p-n" value="50" min="5" max="2000" class="lf-input">
            </div>
            <div>
              <label class="text-[11px] text-slate-400 block mb-1">Param</label>
              <input type="number" id="p-p" value="0.15" step="0.05" min="0.01" max="1" class="lf-input">
            </div>
          </div>
          <button onclick="loadGenerator()" class="w-full py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold flex items-center justify-center gap-2">
            <i data-lucide="sparkles" class="h-4 w-4"></i> Générer
          </button>

          <div class="border-t border-slate-700 pt-3 space-y-2">
            <label class="text-[11px] text-slate-400 block">Fichier (.csv .json .gexf .gml)</label>
            <input type="file" id="file-input" accept=".csv,.json,.gexf,.gml" onchange="loadFile()" class="lf-input text-[11px]">
          </div>

          <div class="border-t border-slate-700 pt-3 space-y-2">
            <label class="text-[11px] text-slate-400 block">JSON direct</label>
            <textarea id="json-input" rows="3" placeholder='{"nodes":[...],"links":[...]}' class="lf-input font-mono text-[10px] resize-y"></textarea>
            <button onclick="loadJSON()" class="w-full py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold">Charger JSON</button>
          </div>
        </div>
      </details>

      <!-- STATS -->
      <details open class="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
        <summary class="px-3 py-2 flex items-center justify-between bg-slate-800/70 hover:bg-slate-800 text-xs uppercase tracking-wide text-blue-400 font-semibold">
          <span class="flex items-center gap-2"><i data-lucide="bar-chart-3" class="h-3.5 w-3.5"></i> Statistiques</span>
          <i data-lucide="chevron-down" class="chev h-3.5 w-3.5 transition-transform"></i>
        </summary>
        <div class="p-3">
          <div class="grid grid-cols-3 gap-2 text-center">
            <div class="bg-slate-900/60 rounded p-2"><div id="s-n" class="text-lg font-bold text-blue-400">—</div><div class="text-[10px] text-slate-500 uppercase">Nœuds</div></div>
            <div class="bg-slate-900/60 rounded p-2"><div id="s-m" class="text-lg font-bold text-blue-400">—</div><div class="text-[10px] text-slate-500 uppercase">Arêtes</div></div>
            <div class="bg-slate-900/60 rounded p-2"><div id="s-d" class="text-lg font-bold text-blue-400">—</div><div class="text-[10px] text-slate-500 uppercase">Densité</div></div>
            <div class="bg-slate-900/60 rounded p-2"><div id="s-diam" class="text-lg font-bold text-blue-400">—</div><div class="text-[10px] text-slate-500 uppercase">Diamètre</div></div>
            <div class="bg-slate-900/60 rounded p-2"><div id="s-deg" class="text-lg font-bold text-blue-400">—</div><div class="text-[10px] text-slate-500 uppercase">Degré moy.</div></div>
            <div class="bg-slate-900/60 rounded p-2"><div id="s-comp" class="text-lg font-bold text-blue-400">—</div><div class="text-[10px] text-slate-500 uppercase">Compos.</div></div>
          </div>
        </div>
      </details>

      <!-- ANALYSE -->
      <details open class="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
        <summary class="px-3 py-2 flex items-center justify-between bg-slate-800/70 hover:bg-slate-800 text-xs uppercase tracking-wide text-blue-400 font-semibold">
          <span class="flex items-center gap-2"><i data-lucide="search" class="h-3.5 w-3.5"></i> Analyse</span>
          <i data-lucide="chevron-down" class="chev h-3.5 w-3.5 transition-transform"></i>
        </summary>
        <div class="p-3 space-y-2">
          <div>
            <label class="text-[11px] text-slate-400 block mb-1">Centralités</label>
            <select id="cent-metrics" multiple size="4" class="lf-input">
              <option value="degree" selected>Degree</option>
              <option value="pagerank" selected>PageRank</option>
              <option value="betweenness">Betweenness</option>
              <option value="closeness">Closeness</option>
              <option value="eigenvector">Eigenvector</option>
              <option value="katz">Katz</option>
            </select>
          </div>
          <button onclick="runCentrality()" class="w-full py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold">Calculer centralité</button>

          <div class="grid grid-cols-2 gap-2 pt-1">
            <select id="comm-method" class="lf-input">
              <option value="louvain" selected>Louvain</option>
              <option value="greedy">Greedy</option>
              <option value="label_prop">Label Prop</option>
              <option value="girvan_newman">Girvan-Newman</option>
              <option value="kmeans">K-Means</option>
            </select>
            <input type="number" id="comm-k" value="4" min="2" max="20" class="lf-input">
          </div>
          <button onclick="runCommunities()" class="w-full py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold">Détecter communautés</button>

          <div class="grid grid-cols-2 gap-2 pt-1">
            <input type="text" id="path-src" placeholder="Source" class="lf-input">
            <input type="text" id="path-dst" placeholder="Cible" class="lf-input">
          </div>
          <button onclick="runPaths()" class="w-full py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold">Trouver chemin</button>

          <div class="grid grid-cols-2 gap-2 pt-1">
            <button onclick="runSpectral()" class="py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold">Spectral</button>
            <button onclick="runMotifs()" class="py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold">Motifs</button>
          </div>
        </div>
      </details>

      <!-- GNN -->
      <details class="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
        <summary class="px-3 py-2 flex items-center justify-between bg-slate-800/70 hover:bg-slate-800 text-xs uppercase tracking-wide text-purple-400 font-semibold">
          <span class="flex items-center gap-2"><i data-lucide="brain-circuit" class="h-3.5 w-3.5"></i> GNN</span>
          <i data-lucide="chevron-down" class="chev h-3.5 w-3.5 transition-transform"></i>
        </summary>
        <div class="p-3 space-y-2">
          <div class="grid grid-cols-2 gap-2">
            <div><label class="text-[11px] text-slate-400 block mb-1">Dim</label><input type="number" id="gnn-h" value="32" min="8" max="128" class="lf-input"></div>
            <div><label class="text-[11px] text-slate-400 block mb-1">Epochs</label><input type="number" id="gnn-ep" value="100" min="10" max="500" class="lf-input"></div>
          </div>
          <button onclick="runGNNEmbed()" class="w-full py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold">Embedding (autoencoder)</button>
          <button onclick="runNode2Vec()" class="w-full py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold">Node2Vec</button>
          <button onclick="runGNNClassify()" class="w-full py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold">Classify nœuds</button>
          <button onclick="runLinkPredict()" class="w-full py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold">Link prediction</button>
        </div>
      </details>

      <!-- VISUALISATION -->
      <details open class="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
        <summary class="px-3 py-2 flex items-center justify-between bg-slate-800/70 hover:bg-slate-800 text-xs uppercase tracking-wide text-blue-400 font-semibold">
          <span class="flex items-center gap-2"><i data-lucide="palette" class="h-3.5 w-3.5"></i> Visualisation</span>
          <i data-lucide="chevron-down" class="chev h-3.5 w-3.5 transition-transform"></i>
        </summary>
        <div class="p-3 space-y-2">
          <div>
            <label class="text-[11px] text-slate-400 block mb-1">Layout</label>
            <select id="layout-sel" class="lf-input">
              <option value="cose" selected>CoSE (force)</option>
              <option value="circle">Circle</option>
              <option value="concentric">Concentric</option>
              <option value="breadthfirst">Breadth-first</option>
              <option value="grid">Grid</option>
              <option value="random">Random</option>
            </select>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="text-[11px] text-slate-400 block mb-1">Couleur</label>
              <select id="color-by" class="lf-input">
                <option value="community">Communauté</option>
                <option value="centrality">Centralité</option>
                <option value="degree">Degré</option>
              </select>
            </div>
            <div>
              <label class="text-[11px] text-slate-400 block mb-1">Taille</label>
              <select id="size-by" class="lf-input">
                <option value="degree">Degré</option>
                <option value="centrality">Centralité</option>
                <option value="uniform">Uniforme</option>
              </select>
            </div>
          </div>
        </div>
      </details>

      <!-- EXPORT -->
      <details class="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
        <summary class="px-3 py-2 flex items-center justify-between bg-slate-800/70 hover:bg-slate-800 text-xs uppercase tracking-wide text-blue-400 font-semibold">
          <span class="flex items-center gap-2"><i data-lucide="download" class="h-3.5 w-3.5"></i> Export</span>
          <i data-lucide="chevron-down" class="chev h-3.5 w-3.5 transition-transform"></i>
        </summary>
        <div class="p-3 grid grid-cols-2 gap-2">
          <button onclick="exportPNG()" class="py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-xs font-semibold">PNG</button>
          <button onclick="exportJSON()" class="py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-xs font-semibold">JSON</button>
          <button onclick="exportGEXF()" class="py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-xs font-semibold">GEXF</button>
          <button onclick="exportReport()" class="py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-xs font-semibold">Rapport</button>
        </div>
      </details>

      <!-- RESULTATS -->
      <details open class="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
        <summary class="px-3 py-2 flex items-center justify-between bg-slate-800/70 hover:bg-slate-800 text-xs uppercase tracking-wide text-blue-400 font-semibold">
          <span class="flex items-center gap-2"><i data-lucide="clipboard-list" class="h-3.5 w-3.5"></i> Résultats</span>
          <i data-lucide="chevron-down" class="chev h-3.5 w-3.5 transition-transform"></i>
        </summary>
        <div class="p-3">
          <div id="results" class="text-xs text-slate-400 font-mono max-h-72 overflow-y-auto whitespace-pre-wrap">Chargez un graphe pour commencer…</div>
          <div id="legend-body" class="mt-2 text-[10px] text-slate-500"></div>
        </div>
      </details>

    </div>
  </aside>

  <!-- CANVAS -->
  <main class="flex-1 relative">
    <div id="cy"></div>
    <!-- Loader overlay -->
    <div id="loader" class="hidden absolute inset-0 bg-slate-950/70 flex items-center justify-center">
      <div class="bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 shadow-lg flex items-center gap-3">
        <i data-lucide="loader-2" class="h-4 w-4 text-blue-400 animate-spin"></i>
        <div id="loader-msg" class="text-sm text-slate-200">Chargement…</div>
      </div>
    </div>
    <!-- Info panel nodes -->
    <div id="info-panel" class="hidden absolute top-3 right-3 w-72 max-h-[50vh] bg-slate-900/95 border border-slate-700 rounded-lg shadow-2xl scroll-y">
      <div class="flex items-center justify-between px-3 py-2 border-b border-slate-700">
        <span id="info-title" class="text-sm font-semibold text-blue-400">Info</span>
        <button onclick="toggleInfo()" class="text-slate-400 hover:text-slate-200 text-xs">✕</button>
      </div>
      <div id="info-body" class="p-3 text-xs text-slate-300 font-mono"></div>
    </div>
  </main>
</div>

<script>lucide.createIcons();</script>
<script>

// ── Init Cytoscape ────────────────────────────────────────────────────────────
const PALETTE = [
  '#58a6ff','#3fb950','#f85149','#d2a8ff','#ffa657',
  '#79c0ff','#56d364','#ff7b72','#f0883e','#a5f3fc',
  '#ec4899','#84cc16','#f59e0b','#06b6d4','#8b5cf6',
  '#ef4444','#22c55e','#3b82f6','#a855f7','#14b8a6'
];

// Palette de couleurs par type de noeud (match partiel insensible a la casse)
const TYPE_COLORS = {
  'domain controller': '#f59e0b',  // Orange DC = cle de voute
  'sql server':        '#8b5cf6',  // Violet DB
  'linux':             '#10b981',  // Vert linux
  'windows':           '#3b82f6',  // Bleu windows
  'backup':            '#ec4899',  // Rose backup
  'iot':               '#ef4444',  // Rouge IoT (entree exposee)
  'router':            '#ef4444',
  'arm':               '#ef4444',
  'squid':             '#6b7280',  // Gris proxy
  'proxy':             '#6b7280',
};
function nodeColor(ele) {
  const t = String(ele.data('type') || '').toLowerCase();
  for (const [key, color] of Object.entries(TYPE_COLORS)) {
    if (t.includes(key)) return color;
  }
  return '#58a6ff';  // Defaut
}

// Palette par type d'arete (relation entre machines)
const EDGE_COLORS = {
  'pivot':                  '#ef4444',  // Rouge = chemin d'attaque
  'exploit':                '#ef4444',
  'privilege':              '#f59e0b',  // Orange = escalade
  'credential':             '#8b5cf6',  // Violet = credential reuse
  'trust':                  '#3b82f6',  // Bleu = trust inter-service
  'admin':                  '#10b981',  // Vert = admin legitime
  'network':                '#6b7280',  // Gris = connexion reseau basique
};
function edgeColor(ele) {
  const t = String(ele.data('type') || '').toLowerCase();
  for (const [key, color] of Object.entries(EDGE_COLORS)) {
    if (t.includes(key)) return color;
  }
  return 'rgba(255,255,255,.35)';
}

let cy = cytoscape({
  container: document.getElementById('cy'),
  style: [
    { selector:'node', style:{
        'background-color': nodeColor,
        'label':'data(label)',
        'color':'#fff',
        'font-size':'11px',
        'font-weight':'600',
        'text-valign':'bottom',
        'text-halign':'center',
        'text-margin-y': 6,
        'text-outline-width': 2,
        'text-outline-color': '#0f172a',
        'width': 'mapData(degree, 0, 10, 32, 56)',
        'height': 'mapData(degree, 0, 10, 32, 56)',
        'border-width':2,
        'border-color':'rgba(255,255,255,.25)',
        'transition-property':'background-color,width,height,border-width',
        'transition-duration':'0.2s',
    }},
    { selector:'node:selected', style:{
        'border-color':'#facc15','border-width':4,
    }},
    { selector:'node.hover', style:{
        'border-color':'#fff','border-width':3,
    }},
    { selector:'edge', style:{
        'width': 2,
        'line-color': edgeColor,
        'target-arrow-color': edgeColor,
        'target-arrow-shape':'triangle',
        'arrow-scale': 1.2,
        'curve-style':'bezier',
        'label':'data(type)',
        'font-size':'8px',
        'color':'rgba(255,255,255,.55)',
        'text-background-color':'#0f172a',
        'text-background-opacity': 0.7,
        'text-background-padding': 2,
        'text-rotation':'autorotate',
    }},
    { selector:'edge:selected', style:{
        'width': 4, 'color':'#facc15',
    }},
    { selector:'.highlighted', style:{
        'background-color':'#facc15',
        'line-color':'#facc15',
        'target-arrow-color':'#facc15',
        'width':4,
        'z-index': 99,
    }},
  ],
  layout: { name:'cose', animate:true, animationDuration: 600,
            idealEdgeLength: 140, nodeOverlap: 20, nodeRepulsion: 8000,
            gravity: 0.25, numIter: 1500, padding: 50,
            randomize: true },
  userZoomingEnabled:true,
  userPanningEnabled:true,
  boxSelectionEnabled:true,
  wheelSensitivity: 0.3,
});

// Tooltip hover : affiche les metadonnees du noeud
(function setupTooltip() {
  const tip = document.createElement('div');
  tip.id = 'cy-tip';
  tip.style.cssText = 'position:fixed;z-index:9999;background:#1e293b;color:#e2e8f0;' +
    'padding:8px 12px;border-radius:6px;font-size:12px;pointer-events:none;' +
    'box-shadow:0 4px 12px rgba(0,0,0,.5);display:none;max-width:280px;' +
    'border:1px solid rgba(255,255,255,.1);line-height:1.4;';
  document.body.appendChild(tip);
  cy.on('mouseover', 'node', (e) => {
    const d = e.target.data();
    let html = '<div style="font-weight:600;color:#fff;margin-bottom:4px">' +
      (d.label || d.id) + '</div>';
    if (d.type) html += '<div>Type: <span style="color:#94a3b8">' +
      d.type + '</span></div>';
    if (d.services && d.services !== '[]')
      html += '<div>Services: <span style="color:#94a3b8">' +
      d.services + '</span></div>';
    if (d.vulns && d.vulns !== '[]')
      html += '<div style="color:#fca5a5">Vulns: ' + d.vulns + '</div>';
    html += '<div style="color:#475569;margin-top:4px;font-size:10px">' +
      'degree=' + (d.degree || 0) + ' id=' + d.id + '</div>';
    tip.innerHTML = html;
    tip.style.display = 'block';
  });
  cy.on('mousemove', 'node', (e) => {
    tip.style.left = (e.originalEvent.clientX + 14) + 'px';
    tip.style.top  = (e.originalEvent.clientY + 14) + 'px';
  });
  cy.on('mouseout', 'node', () => { tip.style.display = 'none'; });
  cy.on('mouseover', 'edge', (e) => {
    const d = e.target.data();
    let html = '<div style="font-weight:600;color:#fff">' +
      (d.type || 'edge') + '</div>';
    html += '<div style="color:#94a3b8">' + d.source + ' -> ' + d.target + '</div>';
    if (d.description) html += '<div style="color:#94a3b8;margin-top:4px">' +
      d.description + '</div>';
    tip.innerHTML = html;
    tip.style.display = 'block';
  });
  cy.on('mousemove', 'edge', (e) => {
    tip.style.left = (e.originalEvent.clientX + 14) + 'px';
    tip.style.top  = (e.originalEvent.clientY + 14) + 'px';
  });
  cy.on('mouseout', 'edge', () => { tip.style.display = 'none'; });
})();

cy.on('tap','node', e => showNodeInfo(e.target));
cy.on('tap', e => { if(e.target === cy) hideNodeInfo(); });

// ── Utils ─────────────────────────────────────────────────────────────────────
const log = (msg, color='#e6edf3') => {
  const el = document.getElementById('results');
  el.innerHTML += `<span style="color:${color}">${msg}\n</span>`;
  el.scrollTop = el.scrollHeight;
};
const clearLog = () => document.getElementById('results').innerHTML = '';
const load = (msg='') => {
  document.getElementById('loader').style.display='flex';
  document.getElementById('loader-msg').textContent = msg || 'Traitement...';
};
const unload = () => document.getElementById('loader').style.display='none';
const toggle = el => {
  const body = el.nextElementSibling;
  const arrow = el.querySelector('span');
  body.classList.toggle('collapsed');
  arrow.textContent = body.classList.contains('collapsed') ? '▶' : '▼';
};

async function api(method, endpoint, body={}) {
  // Calcul du base path pour supporter le proxying (ex: /graph/)
  const base = window.location.pathname.endsWith('/') ? window.location.pathname : window.location.pathname + '/';
  const url = base + endpoint.replace(/^\.\//, '');
  
  const opts = {method, headers:{'Accept':'application/json'}};
  if(method==='POST') {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  
  console.log(`[API] ${method} ${url}`);
  const r = await fetch(url, opts);
  if(!r.ok) {
    let msg = r.statusText;
    try { const e = await r.json(); msg = e.detail || msg; } catch(err) {}
    throw new Error(msg);
  }
  return r.json();
}

async function fetchBlob(endpoint) {
  const base = window.location.pathname.endsWith('/') ? window.location.pathname : window.location.pathname + '/';
  const url = base + endpoint.replace(/^\.\//, '');
  const r = await fetch(url);
  if(!r.ok) throw new Error(`Download failed: ${r.statusText}`);
  return r.blob();
}

// ── Update stats ──────────────────────────────────────────────────────────────
async function refreshStats() {
  try {
    const s = await api('GET','./api/status');
    if(!s.loaded) return;
    document.getElementById('s-n').textContent    = s.n_nodes;
    document.getElementById('s-m').textContent    = s.n_edges;
    document.getElementById('s-d').textContent    = s.density;
    document.getElementById('s-diam').textContent = s.diameter ?? '—';
    document.getElementById('s-deg').textContent  = s.avg_degree;
    document.getElementById('s-comp').textContent = s.components;
    document.getElementById('toolbar-label').textContent = `⬡ ${s.name}  (n=${s.n_nodes}, m=${s.n_edges})`;
  } catch(e) {}
}

// ── Render graph ──────────────────────────────────────────────────────────────
async function renderGraph() {
  load('Rendu du graphe…');
  try {
    const data = await api('GET','./api/graph');
    cy.elements().remove();
    cy.add(data.nodes.map(n => ({group:'nodes', data:n.data})));
    cy.add(data.edges.map(e => ({group:'edges', data:e.data})));
    applyLayout();
    recolorNodes();
    resizeNodes();
    await refreshStats();
    log(`✅ Graphe rendu : ${data.nodes.length} nœuds, ${data.edges.length} arêtes`,'#3fb950');
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

// ── Load generators ───────────────────────────────────────────────────────────
async function loadGenerator() {
  const kind = document.getElementById('gen-kind').value;
  const n = parseInt(document.getElementById('p-n').value)||50;
  const p = parseFloat(document.getElementById('p-p').value)||0.15;
  const params = {n, p, m:Math.max(1,Math.round(p*5)), k:4, rows:n>10?5:3, cols:5, depth:3, branching:2};
  load(`Génération ${kind}…`);
  try {
    const r = await api('POST','./api/load/generator',{kind,params});
    clearLog(); log(`✅ ${r.name} — n=${r.n} m=${r.m}`,'#3fb950');
    await renderGraph();
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); unload(); }
}

async function loadFile() {
  const file = document.getElementById('file-input').files[0];
  if(!file) return;
  load(`Chargement ${file.name}…`);
  try {
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch('./api/load/file',{method:'POST',body:fd});
    if(!r.ok){ const e=await r.json(); throw new Error(e.detail); }
    const data = await r.json();
    clearLog(); log(`✅ ${data.name} — n=${data.n} m=${data.m}`,'#3fb950');
    await renderGraph();
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); unload(); }
}

async function loadJSON() {
  const raw = document.getElementById('json-input').value.trim();
  if(!raw) return;
  try {
    const data = JSON.parse(raw);
    load('Chargement JSON…');
    const r = await api('POST','./api/load/json',{data,name:'imported'});
    clearLog(); log(`✅ ${r.name} — n=${r.n} m=${r.m}`,'#3fb950');
    await renderGraph();
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); unload(); }
}

// ── Analyse ───────────────────────────────────────────────────────────────────
async function runCentrality() {
  const sel = document.getElementById('cent-metrics');
  const metrics = [...sel.selectedOptions].map(o=>o.value);
  load('Calcul centralité…');
  try {
    const r = await api('POST','./api/analyse/centrality',{metrics});
    log(`📊 Centralité (${metrics.join(', ')}):`, '#58a6ff');
    for(const [m,top] of Object.entries(r.top)){
      log(`  ${m}: ${top.slice(0,5).map(([n,v])=>`${n}(${v.toFixed(3)})`).join(' ')}`);
    }
    resizeNodes(); recolorNodes();
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

async function runCommunities() {
  const method = document.getElementById('comm-method').value;
  const k = parseInt(document.getElementById('comm-k').value)||4;
  load('Détection communautés…');
  try {
    const r = await api('POST','./api/analyse/communities',{method,k});
    log(`🏘 ${r.n_communities} communautés (${method}) — modularité: ${r.modularity??'—'}`,'#58a6ff');
    r.communities.forEach(c => log(`  Comm.${c.id}: ${c.size} nœuds — ${c.nodes.slice(0,8).join(',')}${c.size>8?'…':''}`));
    recolorNodes();
    updateLegend(r.communities);
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

async function runPaths() {
  const src = document.getElementById('path-src').value.trim();
  const dst = document.getElementById('path-dst').value.trim();
  if(!src||!dst){ log('❌ Source et destination requises','#f85149'); return; }
  load('Calcul chemin…');
  try {
    const r = await api('POST','./api/analyse/paths',{src,dst,k:3});
    if(r.shortest && r.shortest.length){
      log(`🛤 ${src}→${dst}: longueur=${r.length} chemin=${r.shortest.join('→')}`,'#58a6ff');
      // Highlight path
      cy.elements().removeClass('highlighted');
      r.shortest.forEach(n => {
        cy.getElementById(String(n)).addClass('highlighted');
      });
      for(let i=0;i<r.shortest.length-1;i++){
        cy.edges(`[source="${r.shortest[i]}"][target="${r.shortest[i+1]}"]`).addClass('highlighted');
        cy.edges(`[source="${r.shortest[i+1]}"][target="${r.shortest[i]}"]`).addClass('highlighted');
      }
    } else {
      log(`⚠️ Aucun chemin entre ${src} et ${dst}`,'#f85149');
    }
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

async function runSpectral() {
  load('Analyse spectrale…');
  try {
    const r = await api('GET','./api/analyse/spectral');
    log(`🌊 Spectral — Fiedler: ${r.fiedler_value.toFixed(4)} | gap: ${r.spectral_gap.toFixed(4)} | radius: ${r.spectral_radius.toFixed(2)}`,'#58a6ff');
    log(`  λ: ${r.eigenvalues.slice(0,6).map(v=>v.toFixed(3)).join(', ')}…`);
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

async function runMotifs() {
  load('Comptage motifs…');
  try {
    const r = await api('GET','./api/analyse/motifs');
    log(`△ Motifs — triangles: ${r.triangles} | cliques: ${r.n_cliques} | max_clique: ${r.max_clique_size}`,'#58a6ff');
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

// ── GNN ───────────────────────────────────────────────────────────────────────
async function runGNNEmbed() {
  const hidden = parseInt(document.getElementById('gnn-h').value)||32;
  const epochs = parseInt(document.getElementById('gnn-ep').value)||100;
  load(`GNN Embedding (${epochs} epochs)…`);
  try {
    const r = await api('POST','./api/gnn/embed',{dim:hidden,epochs,layers:2});
    log(`🧠 GNN Embed: ${r.n_nodes} nœuds, dim=${r.dim}`,'#d2a8ff');
    // Repositionner nœuds selon t-SNE
    applyEmbeddingLayout(r.embeddings_2d);
    log('  Positionnement t-SNE appliqué');
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

async function runNode2Vec() {
  const epochs = parseInt(document.getElementById('gnn-ep').value)||100;
  load('Node2Vec (random walks)…');
  try {
    const r = await api('POST','./api/gnn/node2vec',{dim:32,walk_length:30,num_walks:Math.min(200,epochs*2)});
    log(`🔀 Node2Vec: ${Object.keys(r.embeddings_2d).length} nœuds`,'#d2a8ff');
    applyEmbeddingLayout(r.embeddings_2d);
    log('  Positionnement t-SNE Node2Vec appliqué');
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

async function runGNNClassify() {
  const hidden = parseInt(document.getElementById('gnn-h').value)||32;
  const epochs = parseInt(document.getElementById('gnn-ep').value)||200;
  load(`GNN Node Classify (${epochs} epochs)…`);
  try {
    const r = await api('POST','./api/gnn/classify',{hidden,epochs,layers:2});
    log(`🎯 Classify: acc=${(r.accuracy*100).toFixed(1)}% | n_classes=${r.n_classes}`,'#3fb950');
    // Colorier selon prédictions
    cy.nodes().forEach(n => {
      const pred = r.predictions[n.id()];
      if(pred !== undefined){
        n.data('gnn_class', pred);
        n.style('background-color', PALETTE[pred % PALETTE.length]);
      }
    });
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

async function runLinkPredict() {
  const hidden = parseInt(document.getElementById('gnn-h').value)||32;
  const epochs = parseInt(document.getElementById('gnn-ep').value)||100;
  load('Link Prediction…');
  try {
    const r = await api('POST','./api/gnn/link_predict',{hidden,epochs});
    log(`🔗 Top liens manquants (loss=${r.final_loss}):`,'#d2a8ff');
    r.top_missing_links.slice(0,5).forEach(l =>
      log(`  ${l.src} ↔ ${l.dst}: ${l.score}`)
    );
  } catch(e) { log(`❌ ${e.message}`,'#f85149'); }
  finally { unload(); }
}

// ── Layout et rendu ───────────────────────────────────────────────────────────
function applyLayout() {
  const name = document.getElementById('layout-sel').value;
  cy.layout({
    name,
    animate:true, animationDuration:400,
    padding:40,
    nodeDimensionsIncludeLabels:true,
    ...(name==='cose'?{gravity:1, numIter:2000, initialTemp:200}:{}),
    ...(name==='concentric'?{concentric: n=>n.data('degree'), levelWidth:()=>2}:{}),
  }).run();
}

function applyEmbeddingLayout(emb2d) {
  // Normaliser les coordonnées t-SNE vers l'espace Cytoscape
  const vals = Object.values(emb2d);
  const xs = vals.map(v=>v[0]), ys = vals.map(v=>v[1]);
  const xMin=Math.min(...xs), xMax=Math.max(...xs);
  const yMin=Math.min(...ys), yMax=Math.max(...ys);
  const W = cy.width()*0.8, H = cy.height()*0.8;
  const pos = {};
  for(const [nid,[x,y]] of Object.entries(emb2d)){
    pos[nid] = {
      x: ((x-xMin)/(xMax-xMin+1e-8))*W - W/2,
      y: ((y-yMin)/(yMax-yMin+1e-8))*H - H/2,
    };
  }
  cy.nodes().forEach(n => {
    const p = pos[n.id()];
    if(p) n.position(p);
  });
  cy.fit(cy.elements(), 40);
}

function recolorNodes() {
  const by = document.getElementById('color-by').value;
  cy.nodes().forEach(n => {
    const d = n.data();
    if(by==='community'){
      const c = parseInt(d.community)||0;
      n.style('background-color', PALETTE[c%PALETTE.length]);
    } else if(by==='degree'){
      const maxDeg = Math.max(...cy.nodes().map(nn=>nn.data('degree')||1));
      const t = (d.degree||0)/maxDeg;
      n.style('background-color', interpolateColor('#161b22','#58a6ff',t));
    } else if(by==='centrality'){
      const t = parseFloat(d.centrality)||0;
      n.style('background-color', interpolateColor('#161b22','#f85149',t));
    } else {
      n.style('background-color', PALETTE[0]);
    }
  });
}

function resizeNodes() {
  const by = document.getElementById('size-by').value;
  cy.nodes().forEach(n => {
    const d = n.data();
    if(by==='uniform'){
      n.style({width:28,height:28});
    } else if(by==='degree'){
      const maxDeg = Math.max(...cy.nodes().map(nn=>nn.data('degree')||1),1);
      const sz = 18 + 32*(d.degree||0)/maxDeg;
      n.style({width:sz,height:sz});
    } else if(by==='centrality'){
      const sz = 16 + 36*(parseFloat(d.centrality)||0);
      n.style({width:sz,height:sz});
    }
  });
}

function interpolateColor(c1,c2,t){
  const h=s=>parseInt(s.slice(1),16);
  const r1=h(c1)>>16,g1=(h(c1)>>8)&0xff,b1=h(c1)&0xff;
  const r2=h(c2)>>16,g2=(h(c2)>>8)&0xff,b2=h(c2)&0xff;
  const r=Math.round(r1+(r2-r1)*t).toString(16).padStart(2,'0');
  const g=Math.round(g1+(g2-g1)*t).toString(16).padStart(2,'0');
  const b=Math.round(b1+(b2-b1)*t).toString(16).padStart(2,'0');
  return `#${r}${g}${b}`;
}

function updateLegend(comms) {
  const body = document.getElementById('legend-body');
  body.innerHTML = comms.slice(0,8).map(c=>
    `<div><span class="leg-dot" style="background:${PALETTE[c.id%20]}"></span>Comm.${c.id} (${c.size})</div>`
  ).join('');
}

function fitGraph()  { cy.fit(cy.elements(), 40); }
function resetView() { cy.reset(); }
function toggleInfo(){ const p=document.getElementById('info-panel'); p.style.display=p.style.display==='none'||!p.style.display?'block':'none'; }

function showNodeInfo(node) {
  const d = node.data();
  const el = document.getElementById('info-panel');
  el.style.display = 'block';
  document.getElementById('info-title').textContent = `Nœud: ${d.id}`;
  const rows = Object.entries(d)
    .filter(([k])=>!['id'].includes(k))
    .map(([k,v])=>`<b style="color:#e6edf3">${k}</b>: ${v}`)
    .join('<br>');
  document.getElementById('info-body').innerHTML = rows || 'Aucune donnée';
}
function hideNodeInfo() { document.getElementById('info-panel').style.display='none'; }

// ── Export ────────────────────────────────────────────────────────────────────
async function exportGEXF() {
  const r = await fetch('./api/export/gexf');
  const blob = await r.blob();
  const a = document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='graph.gexf'; a.click();
}
async function exportJSON() {
  const r = await fetch('./api/export/json');
  const data = await r.json();
  const a = document.createElement('a'); a.href='data:application/json,'+encodeURIComponent(JSON.stringify(data)); a.download='graph.json'; a.click();
}
async function exportReport() {
  const r = await fetch('./api/export/report');
  const data = await r.json();
  const a = document.createElement('a'); a.href='data:application/json,'+encodeURIComponent(JSON.stringify(data,null,2)); a.download='graph_report.json'; a.click();
}
function exportPNG() {
  const png = cy.png({scale:2,full:true});
  const a = document.createElement('a'); a.href=png; a.download='graph.png'; a.click();
}

// ── Init ──────────────────────────────────────────────────────────────────────
(async()=>{
  await refreshStats();
  const s = await api('GET','./api/status').catch(()=>({loaded:false}));
  if(s.loaded) await renderGraph();
})();

</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_HTML)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/api/orchestration")
def get_orchestration_graph():
    """Graphe temps-réel des échanges inter-agents (agent_messages + agent_tasks)."""
    import sqlite3, os
    from pathlib import Path

    DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
    nodes = {}
    edges = []
    try:
        conn = sqlite3.connect(str(DB), timeout=3)
        # Agents connus depuis agent_messages (base M2M, interrupteur sandbox/m2m.switch ;
        # `conn` reste la base du RAG pour les autres tables)
        from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
        _m2m = sqlite3.connect(_m2m_path(), timeout=3)
        rows = _m2m.execute(
            "SELECT from_agent, to_agent, method, status, created_at "
            "FROM agent_messages ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        _m2m.close()
        for from_a, to_a, method, status, ts in rows:
            for ag in (from_a, to_a):
                if ag not in nodes:
                    color = (
                        "#1D9E75"
                        if "claude" in ag
                        else "#378ADD"
                        if "gemini" in ag
                        else "#EF9F27"
                        if "ollama" in ag
                        else "#D85A30"
                        if "groq" in ag
                        else "#888780"
                    )
                    nodes[ag] = {"id": ag, "label": ag, "color": color, "type": "agent"}
            edges.append({"source": from_a, "target": to_a, "label": method, "status": status, "ts": ts})
        # Tâches actives (non-stale)
        tasks = conn.execute(
            "SELECT id, executor, status, title FROM agent_tasks WHERE status NOT IN ('stale','done') LIMIT 50"
        ).fetchall()
        for tid, exec_a, tstatus, title in tasks:
            task_id = f"task:{tid[:8]}"
            color = "#F09595" if tstatus == "pending" else "#C0DD97"
            nodes[task_id] = {"id": task_id, "label": (title or tid)[:30], "color": color, "type": "task"}
            if exec_a and exec_a in nodes:
                edges.append({"source": exec_a, "target": task_id, "label": tstatus, "status": tstatus, "ts": ""})
        conn.close()
    except Exception as e:
        return JSONResponse({"error": str(e), "nodes": [], "edges": []})

    # Format Cytoscape.js
    cyto_nodes = [
        {"data": {"id": n["id"], "label": n["label"], "color": n["color"], "type": n["type"]}} for n in nodes.values()
    ]
    cyto_edges = [
        {
            "data": {
                "id": f"e{i}",
                "source": e["source"],
                "target": e["target"],
                "label": e["label"],
                "status": e["status"],
            }
        }
        for i, e in enumerate(edges)
    ]
    return JSONResponse(
        {"nodes": cyto_nodes, "edges": cyto_edges, "counts": {"agents": len(nodes), "messages": len(edges)}}
    )


def main(host: str = "127.0.0.1", port: int = 7474, open_browser: bool = True):
    print("\n⬡  Nokido Graph Explorer")
    print(f"   → http://{host}:{port}\n")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7474)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    main(args.host, args.port, not args.no_browser)
