"""
forge_graph_engine.py — Nokido Graph Engine v1
================================================
Convertit les artefacts Nokido en graphes exploitables par le GNN.

Trois types de graphes produits :
    1. AST Graph     — code Python → graphe syntaxique (nœuds=AST nodes, arêtes=parent/child)
    2. Network Graph — state.json pentest → graphe réseau IP (nœuds=hôtes, arêtes=services)
    3. Knowledge Graph — RAG embeddings.db → graphe entités-relations (triplets)

Tous les graphes sont exportés en format torch_geometric.data.Data
pour être consommés directement par forge_gnn.py.
"""

from __future__ import annotations

import ast as _ast
import json
import re
import sqlite3
from pathlib import Path

import torch
from torch_geometric.data import Data

# ══════════════════════════════════════════════════════════════════════════════
# 1. AST GRAPH — code Python → graphe syntaxique
# ══════════════════════════════════════════════════════════════════════════════

# Mapping type de nœud AST → index numérique (feature)
_AST_NODE_TYPES = [
    "Module",
    "FunctionDef",
    "AsyncFunctionDef",
    "ClassDef",
    "Return",
    "Delete",
    "Assign",
    "AugAssign",
    "AnnAssign",
    "For",
    "AsyncFor",
    "While",
    "If",
    "With",
    "AsyncWith",
    "Raise",
    "Try",
    "Assert",
    "Import",
    "ImportFrom",
    "Global",
    "Nonlocal",
    "Expr",
    "Pass",
    "Break",
    "Continue",
    "Call",
    "Attribute",
    "Subscript",
    "Name",
    "Constant",
    "List",
    "Tuple",
    "Dict",
    "Set",
    "BinOp",
    "UnaryOp",
    "BoolOp",
    "Compare",
    "IfExp",
    "Lambda",
    "Yield",
    "YieldFrom",
    "Await",
    "JoinedStr",
    "FormattedValue",
    "Starred",
    "keyword",
    "arg",
    "arguments",
    "Other",
]
_AST_TYPE_INDEX = {t: i for i, t in enumerate(_AST_NODE_TYPES)}
_N_AST_TYPES = len(_AST_NODE_TYPES)


def _ast_node_feature(node: _ast.AST) -> list[float]:
    """One-hot encoding du type de nœud + métadonnées."""
    feat = [0.0] * _N_AST_TYPES
    idx = _AST_TYPE_INDEX.get(type(node).__name__, _AST_TYPE_INDEX["Other"])
    feat[idx] = 1.0
    # Métadonnées : ligne, colonne (normalisées)
    line = getattr(node, "lineno", 0) / 1000.0
    col = getattr(node, "col_offset", 0) / 200.0
    return feat + [line, col]


def code_to_graph(source: str, label: int | None = None) -> Data:
    """
    Convertit du code Python en graphe PyG.

    Args:
        source : code source Python
        label  : étiquette du graphe (0=clean, 1=vuln, etc.) pour l'entraînement GNN

    Returns:
        torch_geometric.data.Data avec :
            x          : [N, n_features] features des nœuds
            edge_index : [2, E] arêtes parent→enfant AST
            y          : [1] label (si fourni)
    """
    try:
        tree = _ast.parse(source)
    except SyntaxError:
        # Graphe vide en cas d'erreur syntaxique
        return Data(
            x=torch.zeros(1, _N_AST_TYPES + 2), edge_index=torch.zeros(2, 0, dtype=torch.long)
        )

    # Numérotation DFS des nœuds
    node_list: list[_ast.AST] = []
    node_id: dict[int, int] = {}  # id(node) → index

    def _visit(node: _ast.AST):
        idx = len(node_list)
        node_list.append(node)
        node_id[id(node)] = idx
        for child in _ast.iter_child_nodes(node):
            _visit(child)

    _visit(tree)

    # Features
    x = torch.tensor([_ast_node_feature(n) for n in node_list], dtype=torch.float32)

    # Arêtes parent → enfants
    src, dst = [], []
    for node in node_list:
        p_idx = node_id[id(node)]
        for child in _ast.iter_child_nodes(node):
            c_idx = node_id[id(child)]
            src.append(p_idx)
            dst.append(c_idx)
            # Arête bidirectionnelle
            src.append(c_idx)
            dst.append(p_idx)

    if src:
        edge_index = torch.tensor([src, dst], dtype=torch.long)
    else:
        edge_index = torch.zeros(2, 0, dtype=torch.long)

    data = Data(x=x, edge_index=edge_index)
    if label is not None:
        data.y = torch.tensor([label], dtype=torch.long)
    data.num_nodes = len(node_list)
    return data


def file_to_graph(path: str | Path, label: int | None = None) -> Data:
    """Charge un fichier Python et le convertit en graphe AST."""
    source = Path(path).read_text(encoding="utf-8", errors="ignore")
    data = code_to_graph(source, label)
    data.source_file = str(path)
    return data


# ══════════════════════════════════════════════════════════════════════════════
# 2. NETWORK GRAPH — state.json → graphe IP
# ══════════════════════════════════════════════════════════════════════════════

# Features réseau : type, risk, nb_ports, nb_vulns
_NET_TYPES = ["host", "iot", "infra", "mobile", "offline", "unknown"]
_NET_RISKS = ["none", "low", "medium", "high", "critical"]
_NET_TYPE_IDX = {t: i for i, t in enumerate(_NET_TYPES)}
_NET_RISK_IDX = {r: i for i, r in enumerate(_NET_RISKS)}


def _net_node_feature(node: dict) -> list[float]:
    """Feature vector pour un nœud réseau."""
    type_oh = [0.0] * len(_NET_TYPES)
    risk_oh = [0.0] * len(_NET_RISKS)
    t = node.get("type", "unknown")
    r = node.get("risk", "none")
    type_oh[_NET_TYPE_IDX.get(t, _NET_TYPE_IDX["unknown"])] = 1.0
    risk_oh[_NET_RISK_IDX.get(r, _NET_RISK_IDX["none"])] = 1.0
    nb_ports = len(node.get("ports", [])) / 20.0
    nb_vulns = len(node.get("vulns", [])) / 10.0
    return type_oh + risk_oh + [nb_ports, nb_vulns]


_NET_FEAT_DIM = len(_NET_TYPES) + len(_NET_RISKS) + 2  # 13


def network_to_graph(state_path: str | Path) -> tuple[Data, dict]:
    """
    Convertit state.json pentest en graphe PyG.

    Stratégie d'arêtes :
        - Tous les hôtes actifs sont connectés à la gateway (infra)
        - Les IoT avec ports ouverts partagent une arête (même sous-réseau /24)
        - Les hôtes avec vulns partagent une arête de risque mutuel

    Returns:
        (data, ip_index)
        data     : graphe PyG
        ip_index : {ip: node_idx} pour retrouver les nœuds
    """
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    nodes = {k: v for k, v in state.get("nodes", {}).items() if k != "meta"}

    # Filtrer les nœuds IP valides
    valid = {
        ip: n
        for ip, n in nodes.items()
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip)
        and n.get("risk", "none") != "none"
        or n.get("type") in ("infra", "host")
    }
    # Inclure tous les nœuds non-fantômes
    valid = {
        ip: n
        for ip, n in nodes.items()
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) and n.get("type", "unknown") != "offline"
    }

    ip_list = sorted(valid.keys())
    ip_index = {ip: i for i, ip in enumerate(ip_list)}

    # Features
    x = torch.tensor([_net_node_feature(valid[ip]) for ip in ip_list], dtype=torch.float32)

    # Gateway
    gateway_ip = next((ip for ip, n in valid.items() if n.get("type") == "infra"), None)

    src, dst = [], []

    # Arêtes gateway → tous
    if gateway_ip:
        gw_idx = ip_index[gateway_ip]
        for ip, idx in ip_index.items():
            if ip != gateway_ip:
                src += [gw_idx, idx]
                dst += [idx, gw_idx]

    # Arêtes IoT avec ports ouverts (risque de pivot)
    iot_with_ports = [
        ip for ip in ip_list if valid[ip].get("type") == "iot" and valid[ip].get("ports")
    ]
    for i in range(len(iot_with_ports)):
        for j in range(i + 1, len(iot_with_ports)):
            a, b = ip_index[iot_with_ports[i]], ip_index[iot_with_ports[j]]
            src += [a, b]
            dst += [b, a]

    # Arêtes vulnérabilités communes
    vuln_hosts = [ip for ip in ip_list if valid[ip].get("vulns")]
    for i in range(len(vuln_hosts)):
        for j in range(i + 1, len(vuln_hosts)):
            a, b = ip_index[vuln_hosts[i]], ip_index[vuln_hosts[j]]
            src += [a, b]
            dst += [b, a]

    if src:
        edge_index = torch.tensor([src, dst], dtype=torch.long)
    else:
        edge_index = torch.zeros(2, 0, dtype=torch.long)

    # Labels : risk comme classification (none=0 low=1 medium=2 high=3)
    risk_to_label = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 3}
    y = torch.tensor(
        [risk_to_label.get(valid[ip].get("risk", "none"), 0) for ip in ip_list], dtype=torch.long
    )

    data = Data(x=x, edge_index=edge_index, y=y)
    data.num_nodes = len(ip_list)
    data.ip_list = ip_list
    return data, ip_index


# ══════════════════════════════════════════════════════════════════════════════
# 3. KNOWLEDGE GRAPH — RAG → triplets entités-relations
# ══════════════════════════════════════════════════════════════════════════════


def rag_to_graph(rag_db: str | Path, min_chunks: int = 3) -> tuple[Data, dict]:
    """
    Construit un graphe de connaissances depuis embeddings.db.

    Nœuds  : sources uniques (fichiers, domaines, skills)
    Arêtes : co-occurrence de tokens dans les chunks RAG

    Returns:
        (data, node_labels) pour visualisation
    """
    db_path = Path(rag_db)
    if not db_path.exists():
        # Graphe vide
        return Data(x=torch.zeros(1, 8), edge_index=torch.zeros(2, 0, dtype=torch.long)), {}

    with sqlite3.connect(str(db_path)) as conn:
        try:
            rows = conn.execute("SELECT source, domain, text FROM rag_chunks LIMIT 500").fetchall()
        except Exception:
            return Data(x=torch.zeros(1, 8), edge_index=torch.zeros(2, 0, dtype=torch.long)), {}

    if len(rows) < min_chunks:
        return Data(x=torch.zeros(1, 8), edge_index=torch.zeros(2, 0, dtype=torch.long)), {}

    # Nœuds = sources uniques
    sources = sorted(set(r[0] for r in rows if r[0]))
    domains = sorted(set(r[1] for r in rows if r[1]))
    all_nodes = sources + [d for d in domains if d not in sources]
    node_idx = {n: i for i, n in enumerate(all_nodes)}
    N = len(all_nodes)

    # Features : [is_source, is_domain, nb_chunks, avg_text_len]
    chunk_count = dict.fromkeys(all_nodes, 0)
    text_len_sum = dict.fromkeys(all_nodes, 0.0)
    for source, domain, text in rows:
        if source in chunk_count:
            chunk_count[source] += 1
            text_len_sum[source] += len(text or "")
        if domain and domain in chunk_count:
            chunk_count[domain] += 1

    x_list = []
    for n in all_nodes:
        is_src = 1.0 if n in sources else 0.0
        is_dom = 1.0 if n in domains else 0.0
        cnt = chunk_count[n] / 50.0
        avglen = (text_len_sum[n] / max(1, chunk_count[n])) / 1000.0
        x_list.append([is_src, is_dom, cnt, avglen, 0.0, 0.0, 0.0, 0.0])
    x = torch.tensor(x_list, dtype=torch.float32)

    # Arêtes : source ↔ domain (même chunk)
    src, dst = [], []
    for source, domain, _ in rows:
        if source and domain and source in node_idx and domain in node_idx:
            a, b = node_idx[source], node_idx[domain]
            if a != b:
                src += [a, b]
                dst += [b, a]

    if src:
        edge_index = torch.tensor([src, dst], dtype=torch.long)
    else:
        edge_index = torch.zeros(2, 0, dtype=torch.long)

    data = Data(x=x, edge_index=edge_index)
    data.num_nodes = N
    return data, {i: n for n, i in node_idx.items()}


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════


def graph_summary(data: Data, name: str = "Graph") -> str:
    n = data.num_nodes or (data.x.shape[0] if data.x is not None else 0)
    e = data.edge_index.shape[1] if data.edge_index is not None else 0
    f = data.x.shape[1] if data.x is not None else 0
    has_y = data.y is not None
    return f"{name}: nodes={n} edges={e} feat_dim={f} labeled={'yes' if has_y else 'no'}"
