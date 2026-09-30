"""Step 6 epistemic: dashboard route Vega-Lite.

Routes :
  GET  /epistemic/<topic>             -> page HTML avec Vega-Lite charts
  GET  /epistemic/api/trajectory      -> JSON trajectoires claims dans le temps
  GET  /epistemic/api/conflicts       -> JSON top conflits non resolus
  GET  /epistemic/api/heatmap/<topic> -> JSON heatmap predicats consensus/conflit

Pour mount dans FastAPI principal (app/web_hub/app.py) :
    from app.web_hub.epistemic import router as epistemic_router
    app.include_router(epistemic_router, prefix="/epistemic")
"""

from __future__ import annotations
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

try:
    from fastapi import APIRouter, HTTPException, Query, Request
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError:
    APIRouter = None


class SchemaAbsent(RuntimeError):
    """Le schema epistemique n'est pas installe dans CETTE base.

    Distinct d'un resultat vide : « zero conflit » est une DONNEE, « la table des
    claims n'existe pas » est une INDISPONIBILITE. Les confondre a fait rendre 500
    a quatre routes des que la base etait neuve (mesure CI 2026-08-26).
    """

    def __init__(self, tables):
        self.tables = list(tables)
        super().__init__("tables absentes : " + ", ".join(self.tables))


class BaseIllisible(RuntimeError):
    """La base elle-meme ne s'ouvre pas (absente, verrouillee, droits)."""


def _conn():
    # `mode=ro` : une base ABSENTE leve au lieu d'etre CREEE vide par sqlite —
    # sinon la route fabrique un embeddings.db fantome puis accuse ses tables.
    try:
        c = sqlite3.connect(
            "file:%s?mode=ro" % DB.as_posix(), uri=True, timeout=30)
    except sqlite3.Error as exc:
        raise BaseIllisible(str(exc)) from exc
    c.row_factory = sqlite3.Row
    return c


def _exiger(c, *tables: str) -> None:
    """Leve SchemaAbsent en NOMMANT ce qui manque — jamais un 500 opaque."""
    presentes = {
        r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    }
    manque = [t for t in tables if t not in presentes]
    if manque:
        raise SchemaAbsent(manque)


# --- DB queries ---


# Candidats lexicaux retenus avant le tri par poids epistemique (borne DITE, pas un silence).
CANDIDATS_LEXICAUX = 2000


def _expression_fts(topic: str) -> str:
    """Termes du sujet en expression FTS5 sure (mots cites, OR) ; vide si aucun mot."""
    mots = re.findall(r"\w+", topic or "", flags=re.UNICODE)[:8]
    return " OR ".join('"%s"' % m for m in mots)


def _topic_chunks(topic: str, limit: int = 50) -> list[dict]:
    """Chunks actifs du sujet, par poids epistemique decroissant.

    Mesure 2026-09-24 : l'ancienne forme (`text LIKE '%sujet%'` + `active IS NULL OR
    active = 1`) parcourait TOUTES les lignes actives de rag_chunks (45 Go) par l'index
    non selectif `active`, a chaque chargement de la page, dans un handler synchrone.
    Desormais : l'index lexical MAINTENU (`rag_fts`, celui que les ecrivains nourrissent
    -- `rag_chunks_fts` ne l'est pas, mesure du 23/08) choisit les CANDIDATS_LEXICAUX
    plus pertinents, puis on trie par poids. Ce qui change, et c'est dit : correspondance
    par MOTS (plus par sous-chaine), sur le texte seulement (`domain` et `role_hint` ne
    sont pas indexes dans `rag_fts`).
    """
    expr = _expression_fts(topic)
    if not expr:
        return []
    c = _conn()
    try:
        _exiger(c, "rag_chunks", "rag_fts")
        cur = c.execute(
            """
            SELECT c.id AS id, c.text AS text, c.source AS source, c.ingested_at AS ingested_at,
                   c.epistemic_weight AS epistemic_weight, c.domain AS domain, c.version AS version
            FROM (SELECT chunk_id FROM rag_fts WHERE rag_fts MATCH ? ORDER BY rank LIMIT ?) f
            CROSS JOIN rag_chunks c ON c.id = f.chunk_id
            WHERE COALESCE(c.active, 1) = 1
            ORDER BY c.epistemic_weight DESC NULLS LAST
            LIMIT ?
        """,
            (expr, CANDIDATS_LEXICAUX, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        c.close()


def _conflicts_top(limit: int = 20) -> list[dict]:
    """Top claims avec le plus de refutations.

    `CROSS JOIN` impose chunk_claims (169 lignes, mesure 24/09) en boucle EXTERNE et
    rag_chunks par cle. Avec `JOIN` + `active IS NULL OR active = 1`, le planificateur
    partait de rag_chunks par l'index non selectif `active` : toutes les lignes actives
    lues pour en joindre 169. `COALESCE(c.active, 1) = 1` garde le meme sens
    (NULL = jamais retire) sans offrir cet index. Cliquet : test_chemin_chaud_sans_balayage_nr.
    """
    c = _conn()
    try:
        _exiger(c, "chunk_claims", "rag_chunks", "claim_reevaluations")
        cur = c.execute(
            """
            SELECT cc.chunk_id, cc.text, c.epistemic_weight, c.source,
                   COUNT(re.newer_claim_id) AS n_refutations
            FROM chunk_claims cc
            CROSS JOIN rag_chunks c ON c.id = cc.chunk_id
            LEFT JOIN claim_reevaluations re ON re.older_claim_id = cc.id
                                            AND re.reevaluation_type IN ('contradicts','supersedes')
            WHERE COALESCE(c.active, 1) = 1
            GROUP BY cc.id
            HAVING n_refutations > 0
            ORDER BY n_refutations DESC, c.epistemic_weight ASC
            LIMIT ?
        """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        c.close()


def _heatmap_predicates(topic: str, limit_predicates: int = 30) -> list[dict]:
    """Heatmap : predicate -> (n_chunks, avg_weight, n_refutations).

    Meme forme que `_conflicts_top` (CROSS JOIN depuis chunk_claims) : le LIKE ne porte
    plus que sur les lignes jointes aux revendications, jamais sur toute la base.
    """
    c = _conn()
    try:
        _exiger(c, "chunk_claims", "rag_chunks")
        rows = c.execute(
            """
            SELECT cc.predicates, c.epistemic_weight, cc.id AS claim_id
            FROM chunk_claims cc
            CROSS JOIN rag_chunks c ON c.id = cc.chunk_id
            WHERE COALESCE(c.active, 1) = 1
              AND (c.role_hint LIKE ? OR c.text LIKE ?)
        """,
            (f"%{topic}%", f"%{topic}%"),
        ).fetchall()

        pred_stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "w_sum": 0.0, "claim_ids": []})
        for r in rows:
            try:
                preds = json.loads(r["predicates"] or "[]")
            except json.JSONDecodeError:
                continue
            for p in preds:
                pred_stats[p]["n"] += 1
                pred_stats[p]["w_sum"] += float(r["epistemic_weight"] or 0.5)
                pred_stats[p]["claim_ids"].append(r["claim_id"])

        result = []
        for pred, stats in pred_stats.items():
            avg_w = stats["w_sum"] / stats["n"] if stats["n"] else 0
            result.append(
                {
                    "predicate": pred,
                    "n_chunks": stats["n"],
                    "avg_weight": round(avg_w, 3),
                }
            )
        result.sort(key=lambda x: x["n_chunks"], reverse=True)
        return result[:limit_predicates]
    finally:
        c.close()


# --- Vega-Lite specs ---


def _vega_trajectory_spec(data: list[dict]) -> dict:
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": "Trajectoire epistemic_weight des claims dans le temps",
        "data": {"values": data},
        "mark": {"type": "circle", "size": 80, "opacity": 0.7},
        "encoding": {
            "x": {"field": "ingested_at", "type": "temporal", "title": "Date d ingestion"},
            "y": {
                "field": "epistemic_weight",
                "type": "quantitative",
                "title": "Poids epistemique",
                "scale": {"domain": [0, 1]},
            },
            "color": {"field": "domain", "type": "nominal"},
            "tooltip": [
                {"field": "text", "type": "nominal", "title": "Claim"},
                {"field": "source", "type": "nominal"},
                {"field": "epistemic_weight", "type": "quantitative", "format": ".3f"},
            ],
        },
        "width": 800,
        "height": 400,
    }


def _vega_heatmap_spec(data: list[dict]) -> dict:
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": "Heatmap predicats : volume vs consensus epistemique",
        "data": {"values": data},
        "mark": {"type": "rect", "tooltip": True},
        "encoding": {
            "x": {"field": "n_chunks", "type": "quantitative", "title": "Nombre de chunks", "bin": True},
            "y": {"field": "avg_weight", "type": "quantitative", "title": "Poids moyen", "bin": True},
            "color": {
                "aggregate": "count",
                "type": "quantitative",
                "scale": {"scheme": "viridis"},
                "title": "Predicats",
            },
            "tooltip": [
                {"field": "predicate", "type": "nominal"},
                {"field": "n_chunks", "type": "quantitative"},
                {"field": "avg_weight", "type": "quantitative", "format": ".3f"},
            ],
        },
        "width": 600,
        "height": 400,
    }


# --- HTML dashboard ---

HTML_TEMPLATE = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Epistemic Dashboard - {topic}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 1100px; margin: 30px auto; padding: 20px; }}
  h1 {{ color: #2c3e50; }}
  h2 {{ color: #34495e; border-bottom: 2px solid #ecf0f1; padding-bottom: 5px; }}
  .stat {{ display: inline-block; padding: 10px 20px; background: #ecf0f1; border-radius: 6px; margin: 5px; }}
  .stat-value {{ font-size: 24px; font-weight: bold; color: #27ae60; }}
  .stat-label {{ font-size: 12px; color: #7f8c8d; }}
  .conflict {{ background: #fff5e6; padding: 10px; margin: 5px 0; border-left: 4px solid #e67e22; }}
  pre {{ background: #2c3e50; color: #ecf0f1; padding: 10px; overflow: auto; }}
  .controls {{ background: #f8f9fa; padding: 15px; border-radius: 6px; margin: 20px 0; }}
  .controls label {{ display: block; margin: 5px 0; }}
  .controls input[type=range] {{ width: 200px; vertical-align: middle; }}
  #chart-trajectory, #chart-heatmap {{ margin: 20px 0; }}
</style>
<script src="/static/vega.min.js"></script>
<script src="/static/vega-lite.min.js"></script>
<script src="/static/vega-embed.min.js"></script>
</head>
<body>
<h1>Epistemic Dashboard - {topic}</h1>

<h2>Vue d ensemble</h2>
<div>
  <div class="stat"><div class="stat-value">{n_chunks}</div><div class="stat-label">chunks actifs</div></div>
  <div class="stat"><div class="stat-value">{avg_weight:.2f}</div><div class="stat-label">poids moyen</div></div>
  <div class="stat"><div class="stat-value">{n_conflicts}</div><div class="stat-label">conflits detectes</div></div>
</div>

<h2>Tuning interactif (coefficients alpha/beta/gamma/delta/epsilon)</h2>
<div class="controls">
  <label>alpha (trust): <input type="range" id="alpha" data-testid="epistemic-coef-alpha" min="0" max="1" step="0.05" value="0.3"> <span id="v-alpha">0.30</span></label>
  <label>beta (recency): <input type="range" id="beta" data-testid="epistemic-coef-beta" min="0" max="1" step="0.05" value="0.25"> <span id="v-beta">0.25</span></label>
  <label>gamma (citations): <input type="range" id="gamma" data-testid="epistemic-coef-gamma" min="0" max="1" step="0.05" value="0.15"> <span id="v-gamma">0.15</span></label>
  <label>delta (peer-review): <input type="range" id="delta" data-testid="epistemic-coef-delta" min="0" max="1" step="0.05" value="0.20"> <span id="v-delta">0.20</span></label>
  <label>epsilon (refutation penalty): <input type="range" id="epsilon" data-testid="epistemic-coef-epsilon" min="0" max="1" step="0.05" value="0.10"> <span id="v-epsilon">0.10</span></label>
  <button onclick="recalc()" data-testid="epistemic-recalc">Recalc preview</button>
</div>

<h2>Trajectoire</h2>
<div id="chart-trajectory"></div>

<h2>Heatmap predicats</h2>
<div id="chart-heatmap"></div>

<h2>Top conflits non resolus</h2>
<div id="conflicts">{conflicts_html}</div>

<script>
const TRAJ_SPEC = {traj_spec};
const HEAT_SPEC = {heat_spec};
vegaEmbed('#chart-trajectory', TRAJ_SPEC);
vegaEmbed('#chart-heatmap', HEAT_SPEC);

['alpha','beta','gamma','delta','epsilon'].forEach(id => {{
  const el = document.getElementById(id);
  el.addEventListener('input', () => {{
    document.getElementById('v-' + id).textContent = parseFloat(el.value).toFixed(2);
  }});
}});

function recalc() {{
  const alpha = parseFloat(document.getElementById('alpha').value);
  const beta = parseFloat(document.getElementById('beta').value);
  const gamma = parseFloat(document.getElementById('gamma').value);
  const delta = parseFloat(document.getElementById('delta').value);
  const epsilon = parseFloat(document.getElementById('epsilon').value);
  
  fetch('./api/recalc', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ alpha, beta, gamma, delta, epsilon, topic: '{topic}' }})
  }})
  .then(r => r.json())
  .then(res => {{
    if (res.ok) {{
      vegaEmbed('#chart-trajectory', res.trajectory_spec);
      vegaEmbed('#chart-heatmap', res.heatmap_spec);
    }} else {{
      console.error(res.error);
    }}
  }})
  .catch(e => console.error(e));
}}
</script>
</body></html>"""


_INDISPO = (
    "<!doctype html><meta charset='utf-8'><title>Epistemic — indisponible</title>"
    "<body style='font:15px system-ui;padding:2rem;background:#111;color:#ddd'>"
    "<h1>Tableau epistemique indisponible</h1><p>{raison}</p>"
    "<p><small>Ce n'est pas « aucun conflit » : la source de ces chiffres n'est pas "
    "lisible ici. Rien n'est affiche plutot qu'un zero trompeur.</small></p>")


def _render_html(topic: str) -> str:
    try:
        chunks = _topic_chunks(topic, limit=100)
        conflicts = [
            c for c in _conflicts_top(20)
            if topic.lower() in (c.get("text") or "").lower()][:5]
    except SchemaAbsent as exc:
        return _INDISPO.format(
            raison="Schema epistemique absent de cette base : %s. La base existe, "
                   "ces tables n'y ont jamais ete creees." % ", ".join(exc.tables))
    except BaseIllisible as exc:
        return _INDISPO.format(raison="Base RAG illisible : %s" % exc)

    trajectory_data = [
        {
            "ingested_at": c["ingested_at"],
            "epistemic_weight": c["epistemic_weight"] or 0.5,
            "domain": c.get("domain") or "?",
            "source": c.get("source") or "?",
            "text": (c.get("text") or "")[:200],
        }
        for c in chunks
        if c.get("ingested_at")
    ]

    try:
        heatmap_data = _heatmap_predicates(topic)
    except (SchemaAbsent, BaseIllisible):
        heatmap_data = []

    n_chunks = len(chunks)
    avg_w = (sum((c["epistemic_weight"] or 0.5) for c in chunks) / n_chunks) if chunks else 0
    n_conflicts = len(conflicts)

    conflicts_html = (
        "".join(
            f'<div class="conflict"><strong>{c.get("text", "")[:160]}</strong>'
            f"<br><small>Source: {c.get('source', '?')} - Refutations: {c.get('n_refutations', 0)}"
            f" - Poids: {(c.get('epistemic_weight') or 0):.3f}</small></div>"
            for c in conflicts
        )
        or "<em>Aucun conflit detecte pour ce topic.</em>"
    )

    return HTML_TEMPLATE.format(
        topic=topic,
        n_chunks=n_chunks,
        avg_weight=avg_w,
        n_conflicts=n_conflicts,
        traj_spec=json.dumps(_vega_trajectory_spec(trajectory_data)),
        heat_spec=json.dumps(_vega_heatmap_spec(heatmap_data)),
        conflicts_html=conflicts_html,
    )


# --- FastAPI router ---

if APIRouter is not None:
    router = APIRouter(tags=["epistemic"])

    @router.get("/{topic}", response_class=HTMLResponse)
    def dashboard(topic: str):
        return _render_html(topic)

    def _servir(fn, *a, **kw):
        """503 NOMME quand la source manque — jamais un 500 anonyme."""
        try:
            return JSONResponse(fn(*a, **kw))
        except SchemaAbsent as exc:
            raise HTTPException(
                status_code=503,
                detail={"raison": "schema_epistemique_absent",
                        "tables_manquantes": exc.tables,
                        "note": "indisponible, PAS un resultat vide"}) from exc
        except BaseIllisible as exc:
            raise HTTPException(
                status_code=503,
                detail={"raison": "base_rag_illisible", "erreur": str(exc)}) from exc

    @router.get("/api/trajectory")
    def api_trajectory(topic: str = Query(...), limit: int = 100):
        return _servir(_topic_chunks, topic, limit=limit)

    @router.get("/api/conflicts")
    def api_conflicts(limit: int = 20):
        return _servir(_conflicts_top, limit=limit)

    @router.get("/api/heatmap/{topic}")
    def api_heatmap(topic: str):
        return _servir(_heatmap_predicates, topic)

    @router.post("/api/recalc")
    async def api_recalc(request: Request):
        try:
            body = await request.json()
            alpha = float(body.get("alpha", 0.3))
            beta = float(body.get("beta", 0.25))
            gamma = float(body.get("gamma", 0.15))
            delta = float(body.get("delta", 0.20))
            epsilon = float(body.get("epsilon", 0.10))
            topic = body.get("topic", "")
            
            chunks = _topic_chunks(topic, limit=100)
            
            trajectory_data = []
            for c in chunks:
                if not c.get("ingested_at"):
                    continue
                orig_w = c["epistemic_weight"] or 0.5
                w = orig_w * (alpha * 1.5 + beta * 0.8 + gamma * 1.2 + delta * 1.0 - epsilon * 0.5)
                w = max(0.0, min(1.0, w))
                
                trajectory_data.append({
                    "ingested_at": c["ingested_at"],
                    "epistemic_weight": round(w, 3),
                    "domain": c.get("domain") or "?",
                    "source": c.get("source") or "?",
                    "text": (c.get("text") or "")[:200],
                })
                
            heatmap_data = _heatmap_predicates(topic)
            scaled_heatmap = []
            for h in heatmap_data:
                orig_h_w = h["avg_weight"]
                h_w = orig_h_w * (alpha * 1.5 + beta * 0.8 + gamma * 1.2 + delta * 1.0 - epsilon * 0.5)
                h_w = max(0.0, min(1.0, h_w))
                scaled_heatmap.append({
                    "predicate": h["predicate"],
                    "n_chunks": h["n_chunks"],
                    "avg_weight": round(h_w, 3)
                })
                
            return JSONResponse({
                "ok": True,
                "trajectory_spec": _vega_trajectory_spec(trajectory_data),
                "heatmap_spec": _vega_heatmap_spec(scaled_heatmap)
            })
        except SchemaAbsent as exc:
            return JSONResponse(
                {"ok": False, "raison": "schema_epistemique_absent",
                 "tables_manquantes": exc.tables}, status_code=503)
        except BaseIllisible as exc:
            return JSONResponse(
                {"ok": False, "raison": "base_rag_illisible", "erreur": str(exc)},
                status_code=503)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# --- CLI test (no FastAPI required) ---


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="Topic to render")
    ap.add_argument("-o", "--output", help="Write HTML to file (default stdout)")
    args = ap.parse_args()
    html = _render_html(args.topic)
    if args.output:
        Path(args.output).write_text(html, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(html)


if __name__ == "__main__":
    main()
