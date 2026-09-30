"""
forge_active_inference.py — Friston Free Energy Principle (FEP) simplifié

Théorie : le cerveau minimise la surprise (free energy variationnelle).
Surprise = écart entre prédiction interne et observation.

Application Nokido :
- Generative model = P(outcome | method, target) appris depuis historique
- Predict outcome AVANT exec (success_proba, time_estimate, elegance_estimate)
- Observation = résultat réel
- Surprise = divergence prediction vs réalité (KL approx)
- Active Inference = choisir intent qui MINIMISE expected free energy

Free Energy F ≈ -log P(o|m) + KL[q(s) || p(s|m)]
Approx pratique : F = surprise + complexity_cost

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:active_inference|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"

EPS = 1e-9
SURPRISE_THRESHOLD_HIGH = 2.0  # surprise élevée → trigger learning update
COMPLEXITY_PENALTY = 0.1

# ═══════════════════════════════════════════════════════════════════════════
# SIGNAUX DU CORPS — attendu CONDITIONNÉ AU CONTEXTE (2026-07-29)
# ═══════════════════════════════════════════════════════════════════════════
# L'API (method, target) ci-dessus prédit le résultat d'une ACTION. Les capteurs du
# corps posent une autre question : « cette valeur est-elle normale ICI, MAINTENANT ? »
#
# Défaut mesuré le 29-07 : organ_pulse jugeait « 19/29 daemons sans heartbeat » sur un
# SEUIL ABSOLU (>= 5 => embolie), sans savoir que le superviseur venait de démarrer
# 70 secondes plus tôt. Or 19 stale à T+70 s d'un boot est l'ATTENDU, pas une
# pathologie. Le verdict a armé le cortisol, le cortisol a fait refuser 471 spawns,
# et les spawns refusés ont maintenu les daemons stale. Un seuil ne connaît pas la
# phase du système ; un attendu APPRIS, si.
#
# Modèle : moyenne/variance incrémentales (Welford) par couple (signal, contexte).
# Surprise gaussienne 0.5*z², homogène au terme temporel de compute_surprise().
SIGNAL_MIN_OBS = 5  # en deçà le modèle est immature : l'appelant garde SA règle
SIGNAL_STD_FLOOR = 0.5  # plancher d'écart-type : évite un z infini sur série plate

_SIGNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS active_inference_signals (
    signal TEXT NOT NULL,
    context TEXT NOT NULL,
    n INTEGER DEFAULT 0,
    mean REAL DEFAULT 0.0,
    m2 REAL DEFAULT 0.0,
    last_updated REAL,
    PRIMARY KEY (signal, context)
);
"""


def _ensure_signal_schema(conn) -> None:
    conn.executescript(_SIGNAL_SCHEMA)


def predict_signal(signal: str, context: str) -> Dict[str, Any]:
    """Attendu appris pour ce signal DANS CE CONTEXTE. n=0 => aucune connaissance."""
    row = None
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_signal_schema(conn)
        row = conn.execute(
            "SELECT n, mean, m2 FROM active_inference_signals WHERE signal=? AND context=?",
            (signal, context),
        ).fetchone()
        conn.close()
    except Exception:  # noqa: BLE001 — pas de modèle lisible = pas de connaissance
        row = None
    if not row or row[0] < 1:
        return {"n": 0, "mean": 0.0, "std": 0.0, "mature": False}
    n, mean, m2 = row[0], row[1], row[2]
    var = (m2 / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": mean, "std": math.sqrt(max(var, 0.0)),
            "mature": n >= SIGNAL_MIN_OBS}


def signal_z(signal: str, context: str, value: float):
    """Écart normalisé observation/attendu. None si le modèle est immature.

    None n'est PAS zéro : il dit « je ne sais pas encore », et l'appelant doit alors
    retomber sur sa propre règle plutôt que de conclure à la normalité.
    """
    p = predict_signal(signal, context)
    if not p["mature"]:
        return None
    return (value - p["mean"]) / max(p["std"], SIGNAL_STD_FLOOR)


def observe_signal(signal: str, context: str, value: float) -> Dict[str, Any]:
    """Met à jour l'attendu (Welford) et rend la surprise de CETTE valeur.

    La surprise est calculée AVANT la mise à jour : on mesure l'écart au modèle qui
    avait cours, pas à un modèle déjà corrigé par l'observation qu'on juge.
    """
    before = predict_signal(signal, context)
    z = signal_z(signal, context, value)
    surprise = round(0.5 * z * z, 4) if z is not None else None
    n = before["n"] + 1
    delta = value - before["mean"]
    mean = before["mean"] + delta / n

    def _op(conn):
        _ensure_signal_schema(conn)
        row = conn.execute(
            "SELECT m2 FROM active_inference_signals WHERE signal=? AND context=?",
            (signal, context)).fetchone()
        m2 = (row[0] if row else 0.0) + delta * (value - mean)
        conn.execute(
            "INSERT INTO active_inference_signals (signal, context, n, mean, m2, last_updated) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(signal, context) DO UPDATE SET "
            "n=excluded.n, mean=excluded.mean, m2=excluded.m2, "
            "last_updated=excluded.last_updated",
            (signal, context, n, mean, m2, time.time()))
        return m2

    try:
        # write_retry : reprise avec recul + jitter sur verrou (gotcha DB is locked)
        from nokido_agent.app.forge_db_path import write_retry
        write_retry(_op)
    except Exception as e:  # noqa: BLE001 — un capteur ne casse jamais sur sa trace
        return {"ok": False, "error": str(e)[:120], "z": z, "surprise": surprise}
    return {"ok": True, "signal": signal, "context": context, "value": value,
            "n": n, "mean": round(mean, 3),
            "z": (round(z, 3) if z is not None else None),
            "surprise": surprise, "mature_before": before["mature"]}  # cost rajout complexité au generative model

_SCHEMA = """
CREATE TABLE IF NOT EXISTS active_inference_priors (
    method TEXT NOT NULL,
    target_class TEXT,
    n_observations INTEGER DEFAULT 0,
    p_success REAL DEFAULT 0.5,
    mean_time_s REAL DEFAULT 1.0,
    var_time_s REAL DEFAULT 1.0,
    mean_elegance REAL DEFAULT 1.0,
    var_elegance REAL DEFAULT 0.5,
    last_updated REAL,
    PRIMARY KEY (method, target_class)
);
CREATE TABLE IF NOT EXISTS active_inference_surprises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT,
    target_class TEXT,
    predicted_p_success REAL,
    actual_success INTEGER,
    predicted_time_s REAL,
    actual_time_s REAL,
    predicted_elegance REAL,
    actual_elegance REAL,
    surprise REAL,
    free_energy REAL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_surprise_ts ON active_inference_surprises(ts);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in _SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


def _target_class(target: str) -> str:
    """Réduit target en classe (IPv4, URL, query, etc.) pour généralisation."""
    if not target:
        return "_none_"
    t = target.lower()
    if ":" in t:
        parts = t.split(":")
        if parts[-1] in ("strategic", "tactical", "technical"):
            return f"short_term_{parts[-1]}"
    if any(c.isdigit() for c in t.split(".")[0:1]) and t.count(".") == 3:
        return "ipv4"
    if t.startswith(("http://", "https://")):
        return "url"
    if "/" in t and t.count("/") > 2:
        return "path"
    if len(t) > 80:
        return "long_text"
    if t.startswith("agt_"):
        return "agent_id"
    return "short_term"


# ============================================================
# Generative model : load priors (P(outcome|method, target_class))
# ============================================================
def get_prior(method: str, target: str = "") -> Dict[str, float]:
    """Récupère les priors apprises pour cette méthode+classe target."""
    cls = _target_class(target)
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT n_observations, p_success, mean_time_s, var_time_s, mean_elegance, var_elegance "
            "FROM active_inference_priors WHERE method=? AND target_class=?",
            (method, cls),
        ).fetchone()
        conn.close()
        if row:
            return {
                "n": row[0],
                "p_success": row[1],
                "mean_time_s": row[2],
                "var_time_s": row[3],
                "mean_elegance": row[4],
                "var_elegance": row[5],
                "target_class": cls,
            }
    except Exception:
        pass
    # Default uniforme : aucune connaissance
    return {
        "n": 0,
        "p_success": 0.5,
        "mean_time_s": 1.0,
        "var_time_s": 1.0,
        "mean_elegance": 1.0,
        "var_elegance": 0.5,
        "target_class": cls,
    }


def predict(method: str, target: str = "") -> Dict[str, Any]:
    """Prediction AVANT exec — qu'attend-on de cet intent ?"""
    p = get_prior(method, target)
    return {
        "method": method,
        "target_class": p["target_class"],
        "predicted_p_success": p["p_success"],
        "predicted_time_s": p["mean_time_s"],
        "predicted_elegance": p["mean_elegance"],
        "confidence": min(1.0, p["n"] / 20.0),  # confiance proportionnelle à n_obs
        "n_observations": p["n"],
    }


# ============================================================
# Surprise computation (-log p(observation))
# ============================================================
def compute_surprise(predicted: Dict[str, Any], observed: Dict[str, Any]) -> float:
    """Surprise scalaire = écart prediction vs observation.

    Approx : KL discret success + dist normalisée time/elegance.
    """
    # Surprise sur succès binaire
    p_succ_pred = predicted.get("predicted_p_success", 0.5)
    actual_succ = 1.0 if observed.get("success") else 0.0
    if actual_succ > 0.5:
        s_succ = -math.log(max(p_succ_pred, EPS))
    else:
        s_succ = -math.log(max(1.0 - p_succ_pred, EPS))

    # Surprise sur temps (gaussienne approx)
    pt = predicted.get("predicted_time_s", 1.0)
    at = observed.get("actual_time_s", pt)
    var_t = max(0.1, pt * 0.5)  # var par défaut 50% du mean
    s_time = ((at - pt) ** 2) / (2 * var_t)

    # Surprise sur élégance
    pe = predicted.get("predicted_elegance", 1.0)
    ae = observed.get("actual_elegance", pe)
    s_eleg = ((ae - pe) ** 2) / (2 * 0.3)

    surprise = s_succ + 0.5 * s_time + 0.5 * s_eleg
    return round(surprise, 4)


def epistemic_value(surprise: float, n_observations: int = 0) -> float:
    """Valeur épistémique (gain d'information) — pile AMI, brief Gemini #11.

    L'inférence active ne doit pas seulement RÉAGIR à la surprise post-hoc : elle doit
    VOULOIR réduire l'ambiguïté du modèle du monde. Valeur élevée quand le modèle est
    AMBIGU (peu d'observations = `1/(1+n)`) ET/OU la surprise est haute (le modèle se
    trompe = opportunité d'apprentissage à ne pas perdre). Usages :
    - prioriser une action d'observation peu coûteuse AVANT une action coûteuse
      (minimiser l'énergie libre ATTENDUE en réduisant l'ambiguïté d'abord) ;
    - pondérer l'apprentissage (anchor) sur les outcomes surprenants/nouveaux.
    """
    ambiguity = 1.0 / (1.0 + max(0, n_observations))
    return round(ambiguity * (1.0 + max(0.0, surprise)), 4)


def compute_free_energy(predicted: Dict[str, Any], observed: Dict[str, Any], complexity: float = 1.0) -> float:
    """Free Energy F = surprise + complexity_cost.

    Approximation simplifiée du F variationnel de Friston.
    """
    surprise = compute_surprise(predicted, observed)
    return round(surprise + COMPLEXITY_PENALTY * complexity, 4)


# ============================================================
# Online learning : update generative model (Bayesian moment update)
# ============================================================
def observe(
    method: str, target: str = "", success: bool = True, time_s: float = 1.0, elegance: float = 1.0
) -> Dict[str, Any]:
    """Update generative model avec nouvelle observation.

    Running mean/var via Welford-like incremental update.
    Calcule + persist surprise + free_energy.
    """
    cls = _target_class(target)
    pred = predict(method, target)
    observed = {
        "success": success,
        "actual_time_s": time_s,
        "actual_elegance": elegance,
    }
    surprise = compute_surprise(pred, observed)
    fe = compute_free_energy(pred, observed)

    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT n_observations, p_success, mean_time_s, var_time_s, mean_elegance, var_elegance "
            "FROM active_inference_priors WHERE method=? AND target_class=?",
            (method, cls),
        ).fetchone()
        if row:
            n, p_s, mt, vt, me, ve = row
            n2 = n + 1
            p_s2 = (p_s * n + (1.0 if success else 0.0)) / n2
            # Welford running mean+var
            delta_t = time_s - mt
            mt2 = mt + delta_t / n2
            vt2 = (vt * n + delta_t * (time_s - mt2)) / n2 if n2 > 0 else vt
            delta_e = elegance - me
            me2 = me + delta_e / n2
            ve2 = (ve * n + delta_e * (elegance - me2)) / n2 if n2 > 0 else ve
        else:
            n2 = 1
            p_s2 = 1.0 if success else 0.0
            mt2 = time_s
            vt2 = 0.0
            me2 = elegance
            ve2 = 0.0

        conn.execute(
            """
            INSERT OR REPLACE INTO active_inference_priors
            (method, target_class, n_observations, p_success, mean_time_s, var_time_s,
             mean_elegance, var_elegance, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?)
        """,
            (method, cls, n2, p_s2, mt2, max(0.01, vt2), me2, max(0.01, ve2), time.time()),
        )

        conn.execute(
            """
            INSERT INTO active_inference_surprises
            (method, target_class, predicted_p_success, actual_success,
             predicted_time_s, actual_time_s, predicted_elegance, actual_elegance,
             surprise, free_energy, ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                method,
                cls,
                pred["predicted_p_success"],
                1 if success else 0,
                pred["predicted_time_s"],
                time_s,
                pred["predicted_elegance"],
                elegance,
                surprise,
                fe,
                time.time(),
            ),
        )

        conn.commit()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "method": method,
        "target_class": cls,
        "predicted": pred,
        "observed": observed,
        "surprise": surprise,
        "free_energy": fe,
        "high_surprise": surprise >= SURPRISE_THRESHOLD_HIGH,
    }


# ============================================================
# Active Inference : choose action minimizing expected free energy
# ============================================================
def expected_free_energy(method: str, target: str = "", complexity: float = 1.0) -> float:
    """E[F] = E[surprise] + complexity_cost — utilisé pour ranger options."""
    p = get_prior(method, target)
    # E[surprise] ~ -log(p_success) si on attend succès
    expected_surprise = -math.log(max(p["p_success"], EPS))
    # Pénalité variance (incertitude = info à acquérir, pas forcément bad)
    var_penalty = 0.1 * (p["var_time_s"] + p["var_elegance"])
    return round(expected_surprise + COMPLEXITY_PENALTY * complexity - var_penalty, 4)


def rank_methods(candidate_methods: List[str], target: str = "") -> List[Dict[str, Any]]:
    """Range candidats par expected free energy croissant (meilleur en premier).

    Active Inference principle : choisir action min E[F].
    """
    out = []
    for m in candidate_methods:
        ef = expected_free_energy(m, target)
        p = get_prior(m, target)
        out.append(
            {
                "method": m,
                "expected_free_energy": ef,
                "p_success": p["p_success"],
                "n_obs": p["n"],
                "confidence": min(1.0, p["n"] / 20.0),
            }
        )
    out.sort(key=lambda x: x["expected_free_energy"])
    return out


def recent_surprise(window_s: float = 604800.0, last_n: int = 20) -> Dict[str, Any]:
    """Surprise moyenne des `last_n` dernieres observations, sans remonter
    au-dela de `window_s`.

    Distinct de stats()["avg_surprise"], qui moyenne toute l'histoire : mesure
    2026-07-24, all-time=1.31 contre 0.21 sur 30 jours. La moyenne all-time est
    dominee par l'archeologie et ferait croire a un modele mauvais alors qu'il
    est bien calibre depuis.

    Fenetre par COMPTAGE et non par duree seule : le debit d'observations varie
    de plusieurs ordres de grandeur (~0.6/jour au repos). Une fenetre purement
    horaire ne collecte jamais rien et fige le signal a zero — un regulateur
    branche dessus serait decoratif. Le plafond `window_s` garde malgre tout la
    dimension temporelle en ecartant les observations perimees.
    """
    cutoff = time.time() - max(60.0, float(window_s))
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT surprise FROM active_inference_surprises WHERE ts>=? "
            "ORDER BY ts DESC LIMIT ?",
            (cutoff, max(1, int(last_n))),
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e), "n": 0, "mean_surprise": 0.0, "ratio": 0.0}
    vals = [float(r[0]) for r in rows if r[0] is not None]
    n = len(vals)
    mean = (sum(vals) / n) if n else 0.0
    return {
        "ok": True,
        "n": n,
        "window_s": float(window_s),
        "last_n": int(last_n),
        "mean_surprise": round(mean, 4),
        "ratio": round(mean / SURPRISE_THRESHOLD_HIGH, 4) if n else 0.0,
    }


def stats() -> Dict[str, Any]:
    conn = sqlite3.connect(str(DEFAULT_DB))
    _ensure_schema(conn)
    n_priors = conn.execute("SELECT COUNT(*) FROM active_inference_priors").fetchone()[0]
    n_obs = conn.execute("SELECT COUNT(*) FROM active_inference_surprises").fetchone()[0]
    avg_surp = conn.execute("SELECT AVG(surprise) FROM active_inference_surprises").fetchone()[0]
    high_surp_count = conn.execute(
        "SELECT COUNT(*) FROM active_inference_surprises WHERE surprise>=?", (SURPRISE_THRESHOLD_HIGH,)
    ).fetchone()[0]
    top = conn.execute(
        "SELECT method, target_class, n_observations, p_success FROM active_inference_priors "
        "ORDER BY n_observations DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "n_priors": n_priors,
        "n_observations": n_obs,
        "avg_surprise": round(avg_surp or 0, 4),
        "high_surprise_events": high_surp_count,
        "top_observed": [{"method": r[0], "target_class": r[1], "n": r[2], "p_success": round(r[3], 3)} for r in top],
    }


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys, argparse

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--predict", nargs="+", metavar=("METHOD", "[TARGET]"))
    ap.add_argument("--observe", nargs=4, metavar=("METHOD", "TARGET", "SUCCESS", "TIME_S"))
    ap.add_argument("--rank", nargs="+", metavar="METHODS")
    ap.add_argument("--target", default="")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.predict:
        m = args.predict[0]
        t = args.predict[1] if len(args.predict) > 1 else ""
        print(json.dumps(predict(m, t), indent=2))
    elif args.observe:
        m, t, s, ts = args.observe
        r = observe(m, t, s in ("1", "true"), float(ts), 1.0)
        print(json.dumps(r, indent=2))
    elif args.rank:
        print(json.dumps(rank_methods(args.rank, args.target), indent=2))
    elif args.stats:
        print(json.dumps(stats(), indent=2))
    else:
        ap.print_help()
