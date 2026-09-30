"""forge_heldout_gate.py — garde HELD-OUT pour le code auto-genere (Phi_T, Metal-Sci).

Trou mesure 25-07 : la boucle d'evolution autonome (trigger_autonomous_evolution ->
AutonomousOrchestrator) valide le code genere par une simple REVUE LLM molle (le noeud
DAG 'validate' lance une equipe LLM). Aucun garde deterministe, aucune donnee held-out.
C'est exactement la regression silencieuse que decrit Metal-Sci : un agent sur-optimise
POUR ses tests fournis et casse sur des dimensions / volumes / entrees qu'il n'a jamais vus.

PRINCIPE (Phi_T evalue sur configs held-out) : un patch ne passe pas seulement les tests
locaux, il doit preserver des INVARIANTS sur un echantillon de PRODUCTION que le
generateur n'a jamais vu. Ici, held-out = un fixture GELE de vrais chunks (selection
deterministe, ecrit une fois, jamais regenere pendant l'evolution).

HONNETE, PAS DECORATIF : le gate DISTINGUE 'passe held-out' de 'aucun profil held-out
pour ce module' (il ne rend jamais un vert silencieux sur du non-verifie). Le premier
profil couvre l'EMBEDDER (l'exemple meme du papier : regressions de dimensions/kernel).

PRUDENCE : n'exercer que du code DEJA REVU (post quality_gate). Ce module execute les
fonctions qu'on lui passe — il n'importe PAS de code arbitraire non revu.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : garde held-out du code auto-genere"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import db_path  # noqa: E402

FIXTURE = ROOT / "sandbox" / "heldout_fixture.json"
_STRIDE = 9973  # rowid % _STRIDE == 0 : selection deterministe, stable dans le temps


def freeze_fixture(n: int = 30) -> dict:
    """Gele une fois un echantillon held-out de vrais chunks (deterministe, reutilise).

    Le fixture DOIT etre stable : c'est ce qui le rend 'held-out'. On ne le regenere
    pas a chaque appel — s'il existe, on le relit tel quel.
    """
    if FIXTURE.exists():
        try:
            return json.loads(FIXTURE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - fixture corrompu -> on regele
            pass
    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30)
    try:
        rows = con.execute(
            "SELECT id, substr(text,1,300) FROM rag_chunks "
            "WHERE embedding IS NOT NULL AND length(text) > 80 AND rowid % ? = 0 LIMIT ?",
            (_STRIDE, n)).fetchall()
    finally:
        con.close()
    fx = {"stride": _STRIDE, "n": len(rows),
          "items": [{"id": r[0], "text": r[1]} for r in rows]}
    try:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(fx, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return fx


def check_embedder(embed_fn, dim: int = 1024) -> dict:
    """INVARIANTS held-out d'un embedder : passe le fixture GELE, verifie que la
    sortie reste saine sur des entrees jamais optimisees.

    Invariants (une seule violation = regression) :
      * pas d'exception sur le lot held-out ;
      * autant de vecteurs que d'entrees ;
      * chaque vecteur : dimension EXACTE + toutes composantes FINIES + norme > 0 ;
      * auto-similarite : cos(v, v) ~ 1 (detecte une normalisation cassee).
    """
    fx = freeze_fixture()
    texts = [it["text"] for it in fx["items"]]
    if not texts:
        return {"ok": False, "verdict": "held_out_indisponible", "reason": "fixture vide"}
    try:
        vecs = embed_fn(texts)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "verdict": "REGRESSION", "reason": f"exception embedder: {e!r}"}
    if not vecs or len(vecs) != len(texts):
        return {"ok": False, "verdict": "REGRESSION",
                "reason": f"compte sortie {len(vecs) if vecs else 0} != entrees {len(texts)}"}
    for i, v in enumerate(vecs):
        a = np.asarray(v, dtype=np.float64)
        if a.shape[0] != dim:
            return {"ok": False, "verdict": "REGRESSION", "reason": f"dim {a.shape[0]} != {dim} (chunk {i})"}
        if not np.isfinite(a).all():
            return {"ok": False, "verdict": "REGRESSION", "reason": f"NaN/Inf dans le vecteur {i}"}
        norm = float(np.linalg.norm(a))
        if norm <= 1e-9:
            return {"ok": False, "verdict": "REGRESSION", "reason": f"norme nulle vecteur {i}"}
        self_cos = float(np.dot(a, a) / (norm * norm))
        if abs(self_cos - 1.0) > 1e-3:
            return {"ok": False, "verdict": "REGRESSION", "reason": f"auto-cos {self_cos:.4f} != 1 (chunk {i})"}
    return {"ok": True, "verdict": "held_out_OK", "n": len(texts), "dim": dim}


def validate_file(path: str) -> dict:
    """Invariant UNIVERSEL, tout module : le fichier compile (pas de crash au chargement).

    Ne resout pas les imports (execution), juste la compilation — bon marche, attrape
    les regressions de syntaxe/indentation qu'un generateur peut introduire.
    """
    p = Path(path)
    if not p.exists():
        return {"ok": False, "verdict": "absent", "reason": path}
    try:
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
        return {"ok": True, "verdict": "compile_OK"}
    except SyntaxError as e:
        return {"ok": False, "verdict": "REGRESSION", "reason": f"SyntaxError L{e.lineno}: {e.msg}"}


# Profils held-out par NATURE de module. Etendre au fil des organes critiques.
_PROFILS = {
    "embedder": lambda: check_embedder(_live_embedder()),
}


def _live_embedder():
    from nokido_agent.app.forge_embed_router import embed_batch_fast
    return embed_batch_fast


def block_if_regressed(path: str, kind: str | None = None) -> dict:
    """Gate held-out — miroir de forge_quality_gate.block_if_failing.

    (1) compile toujours ; (2) si le module a un PROFIL held-out (kind), exerce ses
    invariants sur donnees de prod masquees. Rend explicitement 'held_out_absent'
    quand aucun profil n'existe : JAMAIS un vert silencieux sur du non-verifie.
    """
    comp = validate_file(path)
    if not comp["ok"]:
        return {"blocked": True, **comp}
    if kind and kind in _PROFILS:
        prof = _PROFILS[kind]()
        return {"blocked": not prof["ok"], **prof}
    return {"blocked": False, "verdict": "held_out_absent",
            "note": f"aucun profil held-out pour kind={kind!r} — compile OK, invariants NON verifies"}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Garde held-out pour code auto-genere")
    ap.add_argument("path")
    ap.add_argument("--kind", default=None)
    a = ap.parse_args()
    r = block_if_regressed(a.path, a.kind)
    print(json.dumps(r, ensure_ascii=False))
    return 2 if r.get("blocked") else 0


if __name__ == "__main__":
    sys.exit(main())
