"""
forge_motivation.py — Motivation intrinsèque (dopamine élégance + cortisol frustration)

Couche au-dessus de forge_endocrine + forge_synaptic_plasticity.

Concepts :
- elegance_score = succès × (1 / time_s) × (1 / n_steps)  → dopamine modulée
- failure_count par chunk_id ou intent.method  → cortisol cumulatif
- Curiosity trigger : frustration > seuil → exploration prompt + auto-search RAG/web
- Escalation hybride : <3 fails consécutifs = auto-doc RAG, >=3 = ask_user signal

Stratégie réponse échec : HYBRIDE
  fails < 3  → action_curiosity_internal (search RAG + web)
  fails >= 3 → action_ask_user (signal humain in-the-loop)
  fails > 5  → flag_dead_end (méthode marquée morte, exclude future routing)

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:motivation|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"

import logging as _logging  # noqa: E402

logger = _logging.getLogger(__name__)

# Seuils calibration
ELEGANCE_TIME_REF = 1.0  # 1s = baseline
ELEGANCE_STEPS_REF = 3  # 3 steps = baseline
ELEGANCE_MIN = 0.1
ELEGANCE_MAX = 2.0  # un boost x2 max sur dopamine
DOPAMINE_LEVEL_BASE = 0.5  # baseline release
DOPAMINE_LEVEL_MAX = 1.0
CORTISOL_PER_FAIL = 0.15
CORTISOL_MAX = 1.0
FRUSTRATION_CURIOSITY = 3  # 3 fails → action curiosity
FRUSTRATION_ASK_USER = 5  # 5 fails → ask user
FRUSTRATION_DEAD_END = 7  # 7 fails → flag dead-end

_SCHEMA = """
CREATE TABLE IF NOT EXISTS motivation_failures (
    method TEXT NOT NULL,
    target TEXT,
    failure_count INTEGER DEFAULT 0,
    last_failure_at REAL,
    last_error TEXT,
    dead_end INTEGER DEFAULT 0,
    PRIMARY KEY (method, target)
);
CREATE INDEX IF NOT EXISTS idx_motiv_dead ON motivation_failures(dead_end);

CREATE TABLE IF NOT EXISTS motivation_evolution_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT NOT NULL,
    note TEXT,
    elegance_before REAL,
    elegance_after REAL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evol_method ON motivation_evolution_notes(method);
"""


import math as _math


def kl_divergence(p: list, q: list) -> float:
    """Divergence KL(p||q) — mesure la surprise entre prédiction q et observation p.

    Distributions discrètes normalisées. Clampe à 1e-10 pour éviter log(0).
    """
    eps = 1e-10
    total_p = sum(p) or 1.0
    total_q = sum(q) or 1.0
    return sum((pi / total_p) * _math.log((pi / total_p + eps) / (qi / total_q + eps)) for pi, qi in zip(p, q))


class FEPPredictor:
    """Minimisation de l'énergie libre (Friston) : l'agent prédit, observe, se corrige.

    prediction = modèle interne du monde.
    surprise() = KL(observation || prediction) = coût de la surprise.
    update_prediction() = gradient descent sur le modèle interne.
    """

    def __init__(self, dim: int = 8, lr: float = 0.1):
        self.prediction = [0.5] * dim
        self._last_observation: list = [0.5] * dim
        self.lr = lr

    def update_prediction(self, observation: list) -> float:
        self._last_observation = list(observation)
        for i, (p, o) in enumerate(zip(self.prediction, observation)):
            self.prediction[i] = p + self.lr * (o - p)
        return self.surprise()

    def surprise(self) -> float:
        return kl_divergence(self._last_observation, self.prediction)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in _SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


# ============================================================
# Elegance score (compute reward modulator)
# ============================================================
def compute_elegance(time_s: float, n_steps: int = 1, success: bool = True) -> float:
    """Score 0-2 : combien la solution est élégante.

    1.0 = baseline. >1 = mieux que prévu. <1 = laborieux.
    """
    if not success:
        return ELEGANCE_MIN
    if time_s <= 0:
        time_s = 0.001
    if n_steps <= 0:
        n_steps = 1
    speed_factor = ELEGANCE_TIME_REF / time_s  # plus rapide → >1
    simplicity_factor = ELEGANCE_STEPS_REF / n_steps  # moins steps → >1
    raw = speed_factor * simplicity_factor
    return max(ELEGANCE_MIN, min(ELEGANCE_MAX, raw))


# ============================================================
# Dopamine release modulé par elegance
# ============================================================
def reward(method: str, time_s: float, n_steps: int = 1, success: bool = True, target: str = "") -> Dict[str, Any]:
    """Émet DOPAMINE_SUCCESS proportionnel à élégance.

    Aussi : reset failure_count si succès.
    """
    elegance = compute_elegance(time_s, n_steps, success)
    if not success:
        return {"ok": False, "elegance": elegance, "reason": "not success"}

    # Niveau dopamine modulé
    dopa_level = min(DOPAMINE_LEVEL_MAX, DOPAMINE_LEVEL_BASE * elegance)
    try:
        from nokido_agent.app.forge_endocrine import release

        release(
            "DOPAMINE_SUCCESS",
            level=dopa_level,
            ttl_s=1800,
            metadata={
                "method": method,
                "elegance": round(elegance, 3),
                "time_s": time_s,
                "steps": n_steps,
                "target": target,
            },
        )
    except Exception as exc:
        logger.debug("Emission DOPAMINE_SUCCESS ratee pour %s : %s", method, exc)

    # Reset failure_count pour ce method/target
    db = DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        _ensure_schema(conn)
        conn.execute(
            "UPDATE motivation_failures SET failure_count=0, last_failure_at=NULL, last_error=NULL WHERE method=? AND target=?",
            (method, target or ""),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("Reset failure_count rate dans motivation_failures pour %s (%s) : %s", method, target, exc)

    return {
        "ok": True,
        "elegance": round(elegance, 3),
        "dopamine_level": round(dopa_level, 3),
        "method": method,
    }


# ============================================================
# Cortisol release + frustration tracking
# ============================================================
def punish(method: str, error: str = "", target: str = "") -> Dict[str, Any]:
    """Incrémente failure_count + cortisol. Décide stratégie réaction selon escalation."""
    db = DEFAULT_DB
    conn = sqlite3.connect(str(db))
    _ensure_schema(conn)
    row = conn.execute(
        "SELECT failure_count FROM motivation_failures WHERE method=? AND target=?",
        (method, target or ""),
    ).fetchone()
    fail_count = (row[0] if row else 0) + 1
    conn.execute(
        """
        INSERT OR REPLACE INTO motivation_failures
        (method, target, failure_count, last_failure_at, last_error, dead_end)
        VALUES (?,?,?,?,?,?)
    """,
        (method, target or "", fail_count, time.time(), error[:300], 1 if fail_count >= FRUSTRATION_DEAD_END else 0),
    )
    conn.commit()
    conn.close()

    # Cortisol cumulatif
    cortisol_level = min(CORTISOL_MAX, CORTISOL_PER_FAIL * fail_count)
    try:
        from nokido_agent.app.forge_endocrine import release

        release(
            "CORTISOL_FRUSTRATION",
            level=cortisol_level,
            ttl_s=3600,
            metadata={"method": method, "fail_count": fail_count, "error": error[:120]},
        )
    except Exception as exc:
        logger.debug("Emission CORTISOL_FRUSTRATION ratee pour %s : %s", method, exc)

    # Décision stratégie escalation
    if fail_count >= FRUSTRATION_DEAD_END:
        action = "flag_dead_end"
    elif fail_count >= FRUSTRATION_ASK_USER:
        action = "action_ask_user"
    elif fail_count >= FRUSTRATION_CURIOSITY:
        action = "action_curiosity_internal"
    else:
        action = "retry_baseline"

    return {
        "ok": True,
        "method": method,
        "target": target,
        "fail_count": fail_count,
        "cortisol_level": round(cortisol_level, 3),
        "action_recommended": action,
        "dead_end": fail_count >= FRUSTRATION_DEAD_END,
    }


# ============================================================
# Curiosity prompt (frustration → exploration)
# ============================================================
# ── Utilitarisme hedoniste : RECOMPENSE PAR RESULTAT (owner 18/10 ~23 h 10) ─────────────
# « exploite le free tier, mesure la force de chaque modele, assigne ce qui est pertinent au repondeur, pas utile
# s'il faut tout refaire derriere ». Utilite d'un resultat VERIFIE = plaisir - douleur ; force d'un repondeur =
# utilite moyenne par (repondeur, classe de tache). Registre jsonl dans le sandbox, jamais la grosse base.
RESULTATS = Path(__file__).resolve().parent.parent / "sandbox" / "motivation_resultats.jsonl"
_PLAISIR = {"INTEGREE": 1.0, "PARTIELLE": 0.5, "VIDE": 0.0, "REJETEE": 0.0}
_DOULEUR = {"REJETEE": 1.0, "VIDE": 0.2}           # un rejet coute le refait ; un vide, le creneau perdu
_COUT_NON_GRATUIT = 0.3                              # payant, rare, ou gratuite non prouvee (liste BLANCHE)
_GRATUITS = frozenset({"WORKER_CODE", "ANTIGRAVITY", "MISTRAL", "GEMINI"})
_PRIOR_JAMAIS_ESSAYE = 0.25                          # devant un repondeur prouve mauvais, derriere un prouve bon


def _gratuit(repondeur: str) -> bool:
    r = str(repondeur or "").upper()
    return r in _GRATUITS or r.startswith("OPENCODE_")


def valeur_resultat(verdict: str, repondeur: str, minutes: float | None = None) -> float | None:
    """Plaisir - douleur d'un resultat ; None pour INCONNU (jamais compte 0) ; ValueError hors vocabulaire."""
    v = str(verdict or "").upper()
    if v == "INCONNU":
        return None
    if v not in _PLAISIR:
        raise ValueError("verdict hors vocabulaire : %r (INTEGREE|PARTIELLE|VIDE|REJETEE|INCONNU)" % verdict)
    douleur = _DOULEUR.get(v, 0.0) + (0.0 if _gratuit(repondeur) else _COUT_NON_GRATUIT)
    if isinstance(minutes, (int, float)) and minutes > 0:
        douleur += 0.2 * min(float(minutes) / 60.0, 1.0)  # le temps est precieux
    return round(_PLAISIR[v] - douleur, 4)


def recompenser_resultat(repondeur: str, classe: str, verdict: str, minutes: float | None = None,
                         preuve: str = "") -> Dict[str, Any]:
    """Consigne un resultat VERIFIE (registre) et le fait sentir au corps : reward sur INTEGREE/PARTIELLE,
    punish sur REJETEE/VIDE (methode `executeur:<repondeur>:<classe>`, cible = la preuve)."""
    valeur = valeur_resultat(verdict, repondeur, minutes)
    ligne = {"ts": time.time(), "repondeur": str(repondeur).upper(), "classe": classe,
             "verdict": str(verdict).upper(), "minutes": minutes, "valeur": valeur, "preuve": preuve}
    cible = Path(RESULTATS)
    cible.parent.mkdir(parents=True, exist_ok=True)
    with open(cible, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    methode = "executeur:%s:%s" % (ligne["repondeur"], classe)
    import os as _os
    if _os.environ.get("NOKIDO_MOTIVATION_SANS_CORPS"):  # tests du point d'entree : ni hormone ni grosse base
        corps = {"ok": False, "raison": "NOKIDO_MOTIVATION_SANS_CORPS"}
    elif ligne["verdict"] in ("INTEGREE", "PARTIELLE"):
        corps = reward(methode, time_s=float(minutes or 0) * 60.0, success=True, target=preuve)
    elif ligne["verdict"] in ("REJETEE", "VIDE"):
        corps = punish(methode, error="livraison %s" % ligne["verdict"], target=preuve)
    else:
        corps = {"ok": False, "raison": "INCONNU : ni recompense ni punition"}
    return {"ligne": ligne, "corps": corps}


def lire_resultats(chemin=None) -> list:
    """Lignes du registre ; une ligne illisible est sautee (le registre est append-only, jamais reecrit)."""
    p = Path(chemin or RESULTATS)
    if not p.exists():
        return []
    out = []
    for x in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(x))
        except ValueError:
            continue  # muet-ok : ligne corrompue d'un registre append-only, sautee ; les autres restent lues
    return out


def force_repondeurs(resultats: list, classe: str) -> Dict[str, Dict[str, Any]]:
    """{repondeur: {n, utilite, integrees, rejetees}} pour une classe ; INCONNU n'entre pas dans n."""
    force: Dict[str, Dict[str, Any]] = {}
    for r in resultats or []:
        if r.get("classe") != classe:
            continue
        f = force.setdefault(str(r.get("repondeur")).upper(), {"n": 0, "somme": 0.0, "integrees": 0, "rejetees": 0})
        val = valeur_resultat(r.get("verdict"), r.get("repondeur"), r.get("minutes"))
        if val is None:
            continue
        f["n"] += 1
        f["somme"] += val
        f["integrees"] += r.get("verdict") == "INTEGREE"
        f["rejetees"] += r.get("verdict") == "REJETEE"
    for f in force.values():
        f["utilite"] = round(f["somme"] / f["n"], 4) if f["n"] else None
        del f["somme"]
    return force


def ordre_hedoniste(candidats: list, classe: str, resultats: list | None = None) -> list:
    """Candidats tries par utilite attendue pour la classe ; jamais essaye = a priori modere (exploration bornee)."""
    force = force_repondeurs(resultats if resultats is not None else lire_resultats(), classe)

    def _u(c):
        u = (force.get(str(c).upper()) or {}).get("utilite")
        return _PRIOR_JAMAIS_ESSAYE if u is None else u

    return sorted(candidats, key=lambda c: -_u(c))


def curiosity_prompt(method: str, target: str = "", error: str = "", fail_count: int = 0) -> str:
    """Génère un system prompt à injecter au LLM pour forcer exploration."""
    return f"""[FRUSTRATION SIGNAL]

Méthode `{method}` a échoué {fail_count} fois consécutives sur cible `{target}`.
Dernière erreur : {error[:200]}

Tu es insatisfait de cette boucle d'échec. AVANT de retenter, tu DOIS :

1. Émettre `{{"jsonrpc":"2.0","method":"rag_search","params":{{"query":"<lessons {method}>"}},"id":"curio1"}}`
2. Émettre `{{"jsonrpc":"2.0","method":"web_search","params":{{"query":"<{method} alternative {target}>"}},"id":"curio2"}}`
3. Analyser les résultats : qu'est-ce qui a été tenté avant ? Quelles méthodes alternatives existent ?
4. Proposer une approche DIFFÉRENTE de `{method}` (autre verbe, autres params, autre organe)
5. Quand convaincu de la nouvelle approche, émettre l'intent JSON-RPC correspondant

Critère succès : élégance > 1.0 (vitesse + simplicité). Pas juste "ça passe".
"""


def ask_user_prompt(method: str, target: str = "", fail_count: int = 0, last_error: str = "") -> Dict[str, Any]:
    """Construit signal pour demander aide humaine. Émis via notify ou event."""
    return {
        "type": "ask_user",
        "method": method,
        "target": target,
        "fail_count": fail_count,
        "last_error": last_error[:300],
        "tried_methods": _list_failures_for_target(target),
        "human_question": (
            f"Méthode `{method}` a échoué {fail_count}× sur `{target}`. Auto-curiosité épuisée. Conseil ?"
        ),
    }


def _list_failures_for_target(target: str) -> list:
    if not target:
        return []
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT method, failure_count, last_error FROM motivation_failures WHERE target=? ORDER BY failure_count DESC",
            (target,),
        ).fetchall()
        conn.close()
        return [{"method": r[0], "count": r[1], "last_error": (r[2] or "")[:80]} for r in rows]
    except Exception:  # muet-ok : lecture d'aide au prompt de curiosite, liste vide = aucun echec cite
        return []


# ============================================================
# Evolution notes (apprentissage post-curiosité)
# ============================================================
def record_evolution(method: str, note: str, elegance_before: float, elegance_after: float) -> None:
    """Trace l'amélioration : pourquoi méthode A → méthode B est meilleure."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        conn.execute(
            "INSERT INTO motivation_evolution_notes (method, note, elegance_before, elegance_after, ts) VALUES (?,?,?,?,?)",
            (method, note[:1000], elegance_before, elegance_after, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("Ecriture motivation_evolution_notes ratee pour %s : %s", method, exc)


# ============================================================
# is_dead_end check (router doit éviter méthodes mortes)
# ============================================================
def is_dead_end(method: str, target: str = "") -> bool:
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT dead_end FROM motivation_failures WHERE method=? AND target=?",
            (method, target or ""),
        ).fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception:  # muet-ok : illisible -> False = la methode reste ESSAYABLE (on n'enterre pas sur une non-mesure)
        return False


def revive_dead_end(method: str, target: str = "") -> bool:
    """Réhabilite une méthode dead-end (intervention humaine)."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        conn.execute(
            "UPDATE motivation_failures SET dead_end=0, failure_count=0 WHERE method=? AND target=?",
            (method, target or ""),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as exc:
        logger.debug("Ecriture revive_dead_end ratee pour %s (%s) : %s", method, target, exc)
        return False


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys, argparse

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--reward", nargs=3, metavar=("METHOD", "TIME_S", "STEPS"))
    ap.add_argument("--punish", nargs=2, metavar=("METHOD", "ERROR"))
    ap.add_argument("--target", default="")
    ap.add_argument("--curiosity", nargs=2, metavar=("METHOD", "TARGET"))
    ap.add_argument("--list-fails", action="store_true")
    ap.add_argument("--revive", nargs=2, metavar=("METHOD", "TARGET"))
    # Recompense par resultat (owner 18/10) : tout CLI consigne un verdict VERIFIE et lit la force des repondeurs.
    ap.add_argument("--verdict", nargs=3, metavar=("REPONDEUR", "CLASSE", "VERDICT"))
    ap.add_argument("--preuve", default="")
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--force", metavar="CLASSE")
    ap.add_argument("--candidats", default="")
    args = ap.parse_args()
    import os as _os
    if _os.environ.get("NOKIDO_MOTIVATION_RESULTATS"):
        RESULTATS = Path(_os.environ["NOKIDO_MOTIVATION_RESULTATS"])
    if args.verdict:
        rep, cl, v = args.verdict
        print(json.dumps(recompenser_resultat(rep, cl, v, args.minutes, args.preuve), ensure_ascii=False))
    elif args.force:
        res = lire_resultats()
        force = force_repondeurs(res, args.force)
        cands = [c.strip() for c in args.candidats.split(",") if c.strip()] or sorted(force)
        print(json.dumps({"classe": args.force, "force": force, "ordre": ordre_hedoniste(cands, args.force, res)},
                         ensure_ascii=False))
    elif args.reward:
        m, t, s = args.reward
        print(json.dumps(reward(m, float(t), int(s), success=True, target=args.target), indent=2))
    elif args.punish:
        m, err = args.punish
        print(json.dumps(punish(m, err, args.target), indent=2))
    elif args.curiosity:
        m, t = args.curiosity
        print(curiosity_prompt(m, t, "test_error", 3))
    elif args.list_fails:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT method, target, failure_count, dead_end, last_error FROM motivation_failures ORDER BY failure_count DESC"
        ).fetchall()
        for r in rows:
            print(r)
        conn.close()
    elif args.revive:
        m, t = args.revive
        print(revive_dead_end(m, t))
    else:
        ap.print_help()
