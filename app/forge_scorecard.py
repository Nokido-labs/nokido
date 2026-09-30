"""app/forge_scorecard.py - bulletin d'evaluation multidimensionnel.

Contrat de retour unifie pour les agents Nokido. Remplace les booleens
ok/ko et codes HTTP par un objet Scorecard a 4 axes :

  1. ExecutionState  - axe technique (COMPLETED / TIMEOUT / CRASHED)
  2. QualityGrade    - axe metier (OPTIMAL / PARTIAL / REJECTED / UNRATED)
  3. confidence_score - 0.0 a 1.0
  4. metrics          - duration_ms, tokens_used, memory_peak_mb
     payload         - le resultat brut (code, texte, ...)
     critique        - feedback narratif pour l'agent suivant

Combine 2 sources d'evaluation :
  - QualityGate (forge_quality_gate.py)   - deterministe (AST + pylint + coverage + TODO)
  - LLM-judge   (Ollama local)            - semantique (Exactitude/Clarte/Securite)

Strategie de combinaison : AND-min - la confiance finale = min(det, sem).
Le determinisme veto en cas de bug syntaxique, le juge LLM raffine la
notation quand le code compile.

Loop GOAP en aval :
  OPTIMAL  (>= 0.9) - tache close, on passe au suivant
  PARTIAL  (>= 0.4) - tache derivee 'refine' a l'Editeur, garde le payload
  REJECTED (< 0.4)  - annulation + ban_approach + nouvelle tentative
  UNRATED           - juge non lance, fallback sur le determinisme seul

Le module est volontairement standalone : zero dependance hub/registry
pour pouvoir l'invoquer depuis n'importe quel agent (silo, swarm,
edge-WASM, sandbox). Le juge LLM tape directement Ollama via urllib.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# === Enums ====================================================================


class ExecutionState(str, Enum):
    COMPLETED = "COMPLETED"  # process termine sans crash
    TIMEOUT = "TIMEOUT"  # depasse la deadline
    CRASHED = "CRASHED"  # exception non rattrapee / OOM / API down


class QualityGrade(str, Enum):
    OPTIMAL = "OPTIMAL"  # >= 0.9
    PARTIAL = "PARTIAL"  # 0.4 <= x < 0.9
    REJECTED = "REJECTED"  # < 0.4
    UNRATED = "UNRATED"  # juge non lance


# === Dataclasses ==============================================================


@dataclass
class ScoreMetrics:
    duration_ms: float = 0.0
    tokens_used: int = 0
    memory_peak_mb: float = 0.0


@dataclass
class Scorecard:
    state: ExecutionState = ExecutionState.COMPLETED
    grade: QualityGrade = QualityGrade.UNRATED
    confidence_score: float = 0.0
    metrics: ScoreMetrics = field(default_factory=ScoreMetrics)
    payload: Any = None
    critique: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        d["grade"] = self.grade.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)

    @classmethod
    def crashed(cls, reason: str, payload: Any = None) -> "Scorecard":
        return cls(
            state=ExecutionState.CRASHED,
            grade=QualityGrade.REJECTED,
            confidence_score=0.0,
            payload=payload,
            critique=reason,
        )

    @classmethod
    def timeout(cls, deadline_s: float, payload: Any = None) -> "Scorecard":
        return cls(
            state=ExecutionState.TIMEOUT,
            grade=QualityGrade.REJECTED,
            confidence_score=0.0,
            payload=payload,
            critique=f"timeout {deadline_s:.1f}s",
        )


# === Grade derivation =========================================================


def grade_from_score(score: float) -> QualityGrade:
    """Map [0.0, 1.0] vers QualityGrade. Seuils 0.4 / 0.9."""
    if score >= 0.9:
        return QualityGrade.OPTIMAL
    if score >= 0.4:
        return QualityGrade.PARTIAL
    return QualityGrade.REJECTED


# Statuts qui DECLARENT un echec dans un `task_result` M2M ({intent, status_code, ...}).
_STATUTS_ECHEC = {"FAILED", "FAILURE", "ERROR", "ERR", "KO", "CRASHED", "REFUSED",
                  "DENIED", "ABORTED", "TIMEOUT"}


def scorecard_de_resultat(result_text: str, erreurs_gate: list) -> Scorecard:
    """Scorecard DETERMINISTE d'un resultat de tache (contrat de `handle_task_result`).

    DEFAUT CORRIGE (2026-09-24, veille lot_B_33) : le registre notait TOUT resultat
    `COMPLETED`, et `OPTIMAL 1.0 — all checks pass` des que `gate_check_result` ne
    rendait aucune erreur. Or ce controle n'inspecte que les blocs ```python : un
    resultat sans code — ou un `ERR_INTERNAL` — passait « all checks pass » alors
    qu'AUCUN controle n'avait tourne. Mesure : une tache AGY refusee par le verrou
    workdir notee `OPTIMAL / 1.0`.

    Lecture par EXPRESSIONS et non par `json.loads` : le registre tronque le
    resultat a 2000 caracteres, et un JSON coupe doit encore dire son echec.
    """
    import re as _re

    texte = result_text or ""
    m_int = _re.search(r'"intent(?:_code)?"\s*:\s*"([A-Za-z_]+)"', texte)
    m_st = _re.search(r'"status(?:_code)?"\s*:\s*"([A-Za-z_]+)"', texte)
    intent = (m_int.group(1) if m_int else "").upper()
    statut = (m_st.group(1) if m_st else "").upper()
    if intent == "ERR_TIMEOUT" or statut == "TIMEOUT":
        return Scorecard(state=ExecutionState.TIMEOUT, grade=QualityGrade.REJECTED,
                         confidence_score=0.0,
                         critique="echec DECLARE par le resultat : intent=%s status_code=%s"
                                  % (intent or "-", statut or "-"))
    if intent.startswith("ERR_") or statut in _STATUTS_ECHEC:
        return Scorecard.crashed("echec DECLARE par le resultat : intent=%s status_code=%s"
                                 % (intent or "-", statut or "-"))
    if erreurs_gate:
        score = 0.5 if len(erreurs_gate) == 1 else 0.2
        return Scorecard(state=ExecutionState.COMPLETED, grade=grade_from_score(score),
                         confidence_score=score,
                         critique="det: " + "; ".join(str(e) for e in erreurs_gate[:5]))
    blocs = [b for b in _re.findall(r"```python(.*?)```", texte, _re.DOTALL) if b.strip()]
    if not blocs:
        # Aucun controle n'a tourne : le silence d'une source n'est pas un succes.
        return Scorecard(state=ExecutionState.COMPLETED, grade=QualityGrade.UNRATED,
                         confidence_score=0.0,
                         critique="det: aucun bloc de code a verifier — non note")
    return Scorecard(state=ExecutionState.COMPLETED, grade=QualityGrade.OPTIMAL,
                     confidence_score=1.0,
                     critique="det: %d bloc(s) python verifie(s), aucune erreur" % len(blocs))


# === Evaluation pipeline ======================================================


def evaluate_code(
    file_path: str,
    task_desc: str = "",
    judge_model: str = "laforge-qwen",
    judge_timeout: int = 60,
    ollama_url: str = "http://127.0.0.1:11434",
) -> Scorecard:
    """Pipeline complet : QualityGate (deterministe) + LLM-judge (semantique).

    file_path : code Python a noter (chemin absolu).
    task_desc : description de la tache initiale (alimente le juge LLM).
                Si vide, le juge est saute et la note = score deterministe.
    """
    sc = Scorecard()
    t0 = time.monotonic()

    # Phase 1 : deterministic gate (forge_quality_gate)
    det_score, det_critique = _run_quality_gate(file_path)
    if det_score < 0.0:  # gate crashed (return -1)
        sc = Scorecard.crashed(f"quality_gate crash: {det_critique}")
        sc.metrics.duration_ms = (time.monotonic() - t0) * 1000
        return sc

    # Phase 2 : LLM judge (skippe si pas de task_desc)
    if task_desc:
        sem_score, sem_critique = _llm_judge(file_path, task_desc, judge_model, judge_timeout, ollama_url)
    else:
        sem_score, sem_critique = 1.0, "judge skipped (no task_desc)"

    # Phase 3 : combine - AND-min (les deux doivent passer)
    sc.confidence_score = min(det_score, sem_score)
    sc.grade = grade_from_score(sc.confidence_score)
    sc.critique = f"det: {det_critique} | sem: {sem_critique}"
    sc.metrics.duration_ms = (time.monotonic() - t0) * 1000
    return sc


def _run_quality_gate(file_path: str) -> tuple[float, str]:
    """QualityGate -> score [0.0, 1.0]. Retourne (-1.0, exc) en cas de crash."""
    try:
        from nokido_agent.app.forge_quality_gate import QualityGate

        gate = QualityGate().check(file_path)
        if gate.ok:
            return 1.0, "all checks pass"
        # echec partiel : 1 erreur = 0.5, 2+ erreurs = 0.2
        score = 0.5 if len(gate.errors) == 1 else 0.2
        return score, "; ".join(gate.errors)
    except Exception as e:  # noqa: BLE001
        return -1.0, str(e)


def _llm_judge(file_path: str, task_desc: str, model: str, timeout: int, ollama_url: str) -> tuple[float, str]:
    """LLM-as-judge via Ollama local. Parse JSON {score, critique}.
    Echec -> (0.5, raison) - on tombe sur neutre plutot que zero pour
    eviter qu'un Ollama down ne bloque le pipeline."""
    try:
        code = Path(file_path).read_text(encoding="utf-8", errors="replace")[:8000]
    except OSError as e:
        return 0.0, f"file unreadable: {e}"

    prompt = (
        f"Tu es Evaluateur Qualite. Tache initiale : {task_desc}\n\n"
        f"Code rendu :\n```python\n{code}\n```\n\n"
        "Note de 0.0 a 1.0 selon : Exactitude (40%) / Clarte (30%) / Securite (30%).\n"
        "Reponds UNIQUEMENT en JSON valide : "
        '{"score": float, "critique": str}'
    )

    try:
        import urllib.request as _ur

        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            }
        ).encode()
        req = _ur.Request(f"{ollama_url}/api/generate", data=body, headers={"Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        resp_text = data.get("response", "")
        parsed = json.loads(resp_text)
        score = float(parsed.get("score", 0.0))
        critique = str(parsed.get("critique", ""))[:500]
        return max(0.0, min(1.0, score)), critique
    except Exception as e:  # noqa: BLE001
        return 0.5, f"judge error ({e}) - neutral fallback"


def _mccabe_complexity(tree) -> int:
    """McCabe cyclomatic complexity sur un ast.Module entier.
    Compte les branchements decisionnels : if/elif, for, while, try/except,
    boolean ops, comprehensions. +1 par fonction (entry point)."""
    import ast as _ast

    cc = 1
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            cc += 1
        elif isinstance(
            node, (_ast.If, _ast.For, _ast.AsyncFor, _ast.While, _ast.ExceptHandler, _ast.With, _ast.AsyncWith)
        ):
            cc += 1
        elif isinstance(node, _ast.BoolOp):
            cc += len(node.values) - 1
        elif isinstance(node, (_ast.ListComp, _ast.SetComp, _ast.DictComp, _ast.GeneratorExp)):
            cc += 1
    return cc


_CRITICAL_NODES_FALLBACK = frozenset(
    {
        "forge_rag_engine",
        "forge_semantic_firewall",
        "forge_mcp_registry",
        "forge_orchestrator",
        "forge_llm_router",
        "forge_handoff",
        "forge_world_model",
        "forge_actor",
        "forge_mpc",
        "forge_scorecard",
        "forge_self_correction",
        "nokido_hub",
    }
)

_critical_cache: frozenset[str] | None = None


def _build_module_dep_graph():
    """Scan app/*.py, construit un graph dirige module->module via from-imports.
    Retourne UniversalGraph ou None si build echoue."""
    import ast as _ast

    try:
        from nokido_agent.app.forge_graph_universal import UniversalGraph, GraphNode, GraphEdge
    except ImportError:
        return None
    app_dir = Path(__file__).resolve().parent
    if not app_dir.is_dir():
        return None
    g = UniversalGraph(name="nokido_deps", directed=True)
    mod_names: set[str] = set()
    edges: list[tuple[str, str]] = []
    for py in app_dir.glob("forge_*.py"):
        mod = py.stem
        mod_names.add(mod)
        try:
            tree = _ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ImportFrom) and node.module:
                target = node.module.split(".")[0]
                if target.startswith("forge_") or target == "nokido_hub":
                    edges.append((mod, target))
                    mod_names.add(target)
    for m in mod_names:
        g.add_node(GraphNode(id=m, label=m, domain="code"))
    for src, dst in edges:
        g.add_edge(GraphEdge(src=src, dst=dst, relation="imports"))
    return g


def _critical_nodes(top_n: int = 20) -> frozenset[str]:
    """Top-N noeuds central degree-centrality du dep graph Nokido. Cache TTL session.
    Fallback sur set hardcoded si forge_graph_universal indispo ou crash."""
    global _critical_cache
    if _critical_cache is not None:
        return _critical_cache
    try:
        g = _build_module_dep_graph()
        if g is None:
            _critical_cache = _CRITICAL_NODES_FALLBACK
            return _critical_cache
        # top_central_nodes(n, metric='degree') -> list[(node, score)]
        top = g.top_central_nodes(n=top_n, metric="degree")
        nodes = {nid for nid, _ in top}
        # union avec fallback pour ne JAMAIS perdre les nodes connus pivot
        _critical_cache = frozenset(nodes | _CRITICAL_NODES_FALLBACK)
    except Exception:  # noqa: BLE001
        _critical_cache = _CRITICAL_NODES_FALLBACK
    return _critical_cache


def _graph_critical_break(broken_imports: list[str]) -> int:
    """Compte combien de modules casses sont CRITIQUES dans le dep graph Nokido.
    Critique = top degree-centrality des forge_*.py + fallback set hardcoded."""
    crit = _critical_nodes()
    return sum(1 for m in broken_imports if m in crit)


def evaluate_symbolic(file_path: str, target_file: str | None = None, token_budget: int = 4000) -> Scorecard:
    """JUDGE SYMBOLIQUE - ZERO LLM. Marcus / Friston-style governance.

    Axes deterministes (somme = confidence_score, cap 1.0) :
      - AST validity        : 0.20 si parse OK, 0.0 sinon (veto)
      - pylint E/F          : (score/10) * 0.20 (errors+fatals only)
      - LOC budget          : 0.15 (lineaire 200 -> 500, 0 au-dessus)
      - dep graph impact    : 0.15 si pas d'import casse, -0.05 par noeud
                              CRITIQUE casse (forge_rag_engine, ...).
      - McCabe complexity   : 0.15 si cc <= 20 ; lineaire jusqu a 60 (0)
      - Token budget        : 0.15 si len/4 <= token_budget, sinon 0

    Aucun appel a un LLM. Permet d arbitrer sans biais rhetorique cloud.
    Si AST fail -> Scorecard.crashed (veto immediat).
    """
    import ast
    import subprocess
    import sys

    sc = Scorecard()
    t0 = time.monotonic()

    src_path = Path(file_path)
    try:
        text = src_path.read_text(encoding="utf-8")
    except OSError as e:
        return Scorecard.crashed(f"file unreadable: {e}")

    # AXE 1 : AST validity (veto si fail)
    try:
        tree = ast.parse(text)
        ast_score = 0.20
        ast_note = "OK"
    except SyntaxError as e:
        sc = Scorecard.crashed(f"AST error: {e}")
        sc.metrics.duration_ms = (time.monotonic() - t0) * 1000
        return sc

    # AXE 2 : pylint E/F only (errors + fatals)
    pylint_score = 0.0
    pylint_note = "skipped"
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pylint", "--score=y", "--disable=all", "--enable=E,F", str(src_path)],
            capture_output=True,
            text=True,
            timeout=20,
        errors="replace")
        import re as _re

        m = _re.search(r"rated at (-?\d+\.?\d*)/10", r.stdout)
        if m:
            score10 = max(0.0, float(m.group(1)))
            pylint_score = min(score10 / 10.0 * 0.20, 0.20)
            pylint_note = f"{score10:.1f}/10"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # AXE 3 : LOC budget (penalise gros fichiers)
    loc = len([ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")])
    if loc <= 200:
        loc_score = 0.15
    elif loc >= 500:
        loc_score = 0.0
    else:
        loc_score = 0.15 * (1.0 - (loc - 200) / 300.0)
    loc_note = f"{loc} LOC"

    # AXE 4 : dep graph impact - resoud imports + pondere noeuds critiques
    import importlib.util

    imports = []
    broken: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            for n in node.names:
                imports.append(n.name)
    for mod in imports:
        top = mod.split(".")[0]
        if top in ("__future__",):
            continue
        try:
            if importlib.util.find_spec(top) is None:
                broken.append(top)
        except Exception:  # noqa: BLE001
            broken.append(top)
    critical_broken = _graph_critical_break(broken)
    dep_score = max(0.0, 0.15 - 0.05 * critical_broken) if not broken else 0.0
    dep_note = "OK" if not broken else f"broken={broken[:3]} critical={critical_broken}"

    # AXE 5 : McCabe cyclomatic complexity
    cc = _mccabe_complexity(tree)
    if cc <= 20:
        mccabe_score = 0.15
    elif cc >= 60:
        mccabe_score = 0.0
    else:
        mccabe_score = 0.15 * (1.0 - (cc - 20) / 40.0)
    mccabe_note = f"cc={cc}"

    # AXE 6 : token estimate (approx OpenAI = len/4)
    tok_est = max(1, len(text) // 4)
    tok_score = 0.15 if tok_est <= token_budget else 0.0
    tok_note = f"{tok_est} tok (budget {token_budget})"

    confidence = ast_score + pylint_score + loc_score + dep_score + mccabe_score + tok_score
    confidence = min(confidence, 1.0)
    sc.confidence_score = confidence
    sc.grade = grade_from_score(confidence)
    sc.critique = (
        f"ast={ast_note}({ast_score:.2f}) "
        f"pylint={pylint_note}({pylint_score:.2f}) "
        f"loc={loc_note}({loc_score:.2f}) "
        f"dep={dep_note}({dep_score:.2f}) "
        f"mccabe={mccabe_note}({mccabe_score:.2f}) "
        f"tokens={tok_note}({tok_score:.2f})"
    )
    sc.metrics.duration_ms = (time.monotonic() - t0) * 1000
    sc.metrics.tokens_used = tok_est
    return sc


def evaluate_patch(
    file_path: str,
    task_desc: str,
    judge_model: str = "laforge-qwen",
    judge_timeout: int = 60,
    ollama_url: str = "http://127.0.0.1:11434",
) -> Scorecard:
    """Pipeline allege pour les FRAGMENTS de code (patches, fonctions isolees).
    Skip pylint (toujours 0 sur fragments sans imports/module) et coverage.
    Garde AST validity + LLM-judge semantique.

    Strategie :
      - AST parse fail -> CRASHED grade REJECTED
      - AST OK + LLM-judge -> grade selon sem_score uniquement
    """
    import ast

    sc = Scorecard()
    t0 = time.monotonic()
    try:
        ast.parse(Path(file_path).read_text(encoding="utf-8"))
    except SyntaxError as e:
        sc = Scorecard.crashed(f"AST error: {e}")
        sc.metrics.duration_ms = (time.monotonic() - t0) * 1000
        return sc
    except OSError as e:
        sc = Scorecard.crashed(f"file unreadable: {e}")
        return sc
    sem_score, sem_critique = (1.0, "judge skipped (no task_desc)")
    if task_desc:
        sem_score, sem_critique = _llm_judge(file_path, task_desc, judge_model, judge_timeout, ollama_url)
    sc.confidence_score = sem_score
    sc.grade = grade_from_score(sem_score)
    sc.critique = f"patch_ast: OK | sem: {sem_critique}"
    sc.metrics.duration_ms = (time.monotonic() - t0) * 1000
    return sc


# === Persistence helper =======================================================


def store_for_task(scorecard: Scorecard, task_id: str, db_path: str = "") -> bool:
    """Persiste la Scorecard dans la colonne tasks.scorecard_json. Ajoute la
    colonne si absente (migration soft, non destructive)."""
    if not db_path:
        from pathlib import Path as _P

        db_path = str(_P(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
    try:
        import sqlite3

        conn = sqlite3.connect(db_path, timeout=10)
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN scorecard_json TEXT")
        except sqlite3.OperationalError:
            pass  # column exists
        conn.execute("UPDATE tasks SET scorecard_json=? WHERE id=?", (scorecard.to_json(), task_id))
        conn.commit()
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


# === Refine task derivation ===================================================


def create_refine_task(
    original_task_id: str,
    scorecard: Scorecard,
    original_description: str = "",
    target_agent: str = "EDITOR",
    hub_url: str = "http://127.0.0.1:8766",
    hub_token: str = "",
    timeout_s: int = 15,
) -> dict:
    """Cree une tache derivee 'refine' a partir d'une Scorecard PARTIAL.

    Le hub recoit un task.assign vers target_agent avec :
      - description = critique + extrait de la tache initiale + grade actuel.
      - from_agent  = "scorecard_router" (tracable dans agent_messages).

    Returns : {"ok": bool, "task_id": str | None, "raw": <hub response text>}.
    Echec reseau ou hub down -> ok=False + erreur dans raw, sans lever.
    """
    import urllib.request

    desc = (
        f"[REFINE] tache originale={original_task_id} "
        f"grade={scorecard.grade.value} "
        f"confidence={scorecard.confidence_score:.2f}\n\n"
        f"Critique du juge :\n{scorecard.critique}\n\n"
        f"Contexte original (extrait) :\n{(original_description or '')[:1000]}\n\n"
        "Consigne : applique un patch minimal pour adresser la critique tout "
        "en preservant les parties qui fonctionnent. Ne pas re-generer "
        "from-scratch."
    )
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "task",
                "arguments": {
                    "action": "assign",
                    "agent": target_agent,
                    "description": desc,
                    "from_agent": "scorecard_router",
                    "intent": "refine",
                },
            },
        }
    ).encode()
    headers = {"Content-Type": "application/json", "X-Agent-Name": "SCORECARD_ROUTER"}
    if hub_token:
        headers["Authorization"] = f"Bearer {hub_token}"
    req = urllib.request.Request(f"{hub_url}/mcp", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            data = json.loads(r.read())
        text = data.get("result", {}).get("content", [{}])[0].get("text", "")
        # Hub returns json text "{...task_id: ...}" or plain ack
        new_tid = None
        try:
            parsed = json.loads(text)
            new_tid = parsed.get("task_id") or parsed.get("id")
        except (json.JSONDecodeError, AttributeError):
            pass
        return {"ok": True, "task_id": new_tid, "raw": text}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "task_id": None, "raw": f"err: {e}"}


# === GOAP routing helper ======================================================


def next_action_for(scorecard: Scorecard) -> str:
    """Mappage QualityGrade -> action GOAP suivante.
    Used by forge_goap_hub_bridge to derive the next planner step."""
    if scorecard.grade == QualityGrade.OPTIMAL:
        return "close"
    if scorecard.grade == QualityGrade.PARTIAL:
        return "refine"  # task derivee a l'Editeur, garde le payload
    if scorecard.grade == QualityGrade.REJECTED:
        return "ban_and_retry"
    return "judge"  # UNRATED -> declenche le juge LLM
