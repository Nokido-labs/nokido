"""tools/forge_ami_strategist.py - coordinateur AMI subtasks via swarm.

STRATEGIST role : pour chaque subtask (A/C/D/E enrichissement AMI),
1. Read relevant files (context).
2. Cloud LLM (hub `ask` groq/cerebras) genere un draft (patch ou fichier).
3. Sauve draft dans drafts/<id>.py.
4. Juge local (forge_scorecard.evaluate_code via Ollama laforge-qwen) note
   le draft : Scorecard {state, grade, confidence, critique}.
5. Decision :
   - OPTIMAL  >= 0.9  -> ok=True, pret a merger
   - PARTIAL  >= 0.4  -> 1 retry avec critique embed dans prompt
   - REJECTED < 0.4   -> ban cloud provider, retry sur backup
6. Rapport JSON sortie : drafts/<id>.json (verdict + scorecard).

Politique tokens : 1 file de contexte max par subtask, 2 retries max,
provider fallback cerebras -> groq -> github. Pas de cloud sans demande.

Usage :
  LAFORGE_PYTHON tools/forge_ami_strategist.py [--subtask A|C|D|E|all]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_agent_credential import jeton_hub  # noqa: E402
from nokido_agent.app.forge_scorecard import (  # noqa: E402
    QualityGrade,
    Scorecard,
    evaluate_code,
    evaluate_patch,
    evaluate_symbolic,
)

try:
    from nokido_agent.app.forge_dspy_router import signature_call as _signature_call  # noqa: E402

    _DSPY_AVAILABLE = True
except ImportError:
    _DSPY_AVAILABLE = False
    _signature_call = None  # type: ignore

DRAFTS_DIR = ROOT / "_strategist_drafts"
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

HUB_URL = "http://127.0.0.1:8766/mcp"
PROVIDER_CHAIN = ["cerebras", "groq", "github"]  # cerebras = better JSON-follow


# === Subtasks definition ======================================================


@dataclass
class Subtask:
    sid: str
    goal: str
    rationale: str
    context_files: list[str]
    target_file: str
    constraints: list[str] = field(default_factory=list)
    provider_chain: list[str] = field(default_factory=lambda: list(PROVIDER_CHAIN))


SUBTASKS = [
    Subtask(
        sid="A",
        goal=(
            "Instrumenter forge_mcp_registry.handle_task_result pour ecrire une "
            "transition execution_traces a la completion de chaque tache. "
            "Utiliser forge_mpc._insert_self_play_trace avec state_emb=embedding "
            "(description+result via forge_state_encoder.encode_state quand "
            "disponible, sinon hash 384D), action_desc=task.description, "
            "cost_before=1.0, cost_after=(1.0 - scorecard.confidence_score), "
            "success=(scorecard.grade IN OPTIMAL/PARTIAL). Try/except non-fatal."
        ),
        rationale=(
            "Actuel : 96% des traces sont task_type=monitoring, state_text="
            "tasks:unknown. Le offline_trainer apprend du bruit. En cablant "
            "handle_task_result on capture les VRAIES transitions agentiques."
        ),
        context_files=["app/forge_mcp_registry.py", "app/forge_mpc.py"],
        target_file="app/forge_mcp_registry.py",
        constraints=[
            "modif minimale - injecter un bloc apres le scorecard hook existant",
            "non-fatal : echec encode_state -> embedding hash fallback",
            "ne pas casser le retour de handle_task_result",
        ],
    ),
    Subtask(
        sid="C",
        goal=(
            "Refactor forge_actor.mcts_propose en VRAI MCTS : (a) Expansion "
            "recursive depth jusqu'a max_depth=3, (b) Backpropagation visite+"
            "value vers tous les ancestors (Node.update apres rollout), (c) UCT"
            " selection a chaque niveau (pas seulement leaf). Preserver "
            "signature publique."
        ),
        rationale=(
            "Actuel : 32 children depth=1 + best-pick = Monte-Carlo sampling, "
            "pas AlphaZero. Pas de backprop -> pas d'apprentissage de la "
            "strategie de search. Pas de tree profond -> horizon=1."
        ),
        context_files=["app/forge_actor.py"],
        target_file="app/forge_actor.py",
        constraints=[
            "garder signature mcts_propose(state_emb, goal_emb, n_simulations, noise_std)",
            "preserver decode_action_emb + propose_action_emb dependencies",
            "ajouter max_depth parametre default=3",
        ],
    ),
    Subtask(
        sid="D",
        goal=(
            "Ajouter epistemic gate dans forge_mpc.run_mpc_loop : avant chaque "
            "step calculer epistemic_cost (MC k>=5) ; si > threshold "
            "(default 0.7) declarer step 'uncertain' et publier un message "
            "agent_messages a Claude/Gemini pour demander clarification au lieu"
            " d'agir. Retourner MPCResult avec un flag uncertain_steps."
        ),
        rationale=(
            "Actuel : MPC execute meme quand le world_model n'a aucune idee. "
            "Epistemic cost calcule mais pas utilise comme gate."
        ),
        context_files=["app/forge_mpc.py", "app/forge_cost_net.py"],
        target_file="app/forge_mpc.py",
        constraints=[
            "non-bloquant : si pas de hub disponible, skip silencieux",
            "epistemic_threshold parametrable via env LAFORGE_EPISTEMIC_THRESHOLD",
        ],
    ),
    Subtask(
        sid="SB1",
        goal=(
            "SWE-bench Stage 1 - repomap + dep-graph cross-fichier. Etendre "
            "forge_warpgrep v1 (mono-fichier BM25 + AST) en v2 qui construit "
            "une table symboles {module: {func/class: (file, line)}} sur tous "
            "les .py du repo cible (clone shallow), resoud les from-imports, "
            "expose callers_of(symbol)/callees_of(symbol) <=2 sauts. "
            "Le runner SWE-bench injecte les voisins du sous-graphe dans le "
            "contexte Coder."
        ),
        rationale=(
            "Locate buggy file = facile, mais le Coder a besoin du contexte "
            "cross-fichier (callers d'une fonction dont la signature change). "
            "Scale AI : scaffolding +14-25 pts au-dessus du modele nu."
        ),
        context_files=["tools/forge_warpgrep.py", "app/forge_graph_universal.py"],
        target_file="tools/forge_warpgrep.py",
        constraints=[
            "API publique : ajouter `class CrossFileGraph` + 2 methodes",
            "Reutiliser ast.parse, networkx (deja import dans graph_universal)",
            "cap 300 LOC ajoutees (sinon split module separe)",
        ],
    ),
    Subtask(
        sid="SB2",
        goal=(
            "SWE-bench Stage 2 - skeleton pruning Coder. _coder_context du "
            "runner envoie le fichier ENTIER (cap 30k). Remplacer par "
            "_skeleton_file (corps des methodes masques par `...`) + "
            "_zoom_functions (code complet des seules fonctions touchees par "
            "le sous-graphe ou matchant keywords distille). Reduction -50 a "
            "-70% du prompt = focus modele <70B."
        ),
        rationale=(
            "Le Coder reste focus sur la zone bug + APIs voisines. Les autres "
            "methodes du fichier = bruit qui dilue l'attention. Briques deja "
            "presentes dans le runner mais pas activees dans _coder_context."
        ),
        context_files=["tools/forge_swebench_runner.py"],
        target_file="tools/forge_swebench_runner.py",
        constraints=[
            "Ne pas casser le retour de _coder_context",
            "Skeleton format compatible avec parsers ast existants",
            "Si keywords vides -> tomber sur fichier entier (fallback)",
        ],
    ),
    Subtask(
        sid="E",
        goal=(
            "Cabler forge_skill_curator dans forge_offline_trainer cycle : "
            "apres training, scanner execution_traces pour patterns "
            "(action_desc, task_type) avec >=3 successes -> extraire route "
            "comme 'skill' indexee dans RAG (domain='curated_skills'). "
            "Idempotent : skill_hash deja present = skip."
        ),
        rationale=(
            "forge_skill_curator existe mais pas appelle. Sans curation, les "
            "solutions reussies restent enfouies dans traces."
        ),
        context_files=["tools/forge_offline_trainer.py", "app/forge_skill_curator.py"],
        target_file="tools/forge_offline_trainer.py",
        constraints=[
            "wire dans main cycle apres save_models",
            "non-bloquant : skill_curator absent -> skip",
        ],
    ),
]


# === Hub ask wrapper ==========================================================


def hub_ask(
    provider: str, message: str, token: str, max_tokens: int = 4096, timeout_s: int = 90
) -> dict:
    """Appel hub tools/call ask provider=...

    Retourne {ok, text, raw_error}."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ask",
                "arguments": {
                    "provider": provider,
                    "message": message,
                    "max_tokens": max_tokens,
                    "rag_context": False,
                },
            },
        }
    ).encode()
    req = urllib.request.Request(
        HUB_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Agent-Name": "STRATEGIST",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            data = json.loads(r.read())
        text = data.get("result", {}).get("content", [{}])[0].get("text", "")
        # Hub ask retourne un JSON envelope {"ok", "text", "thread_id", ...}
        # serialise comme string. Le vrai contenu LLM est dans .text de l envelope.
        try:
            inner = json.loads(text)
            if isinstance(inner, dict) and "text" in inner:
                text = inner["text"]
                if inner.get("ok") is False:
                    return {
                        "ok": False,
                        "text": text,
                        "raw_error": inner.get("error", "provider error"),
                    }
        except (json.JSONDecodeError, TypeError):
            pass
        return {"ok": True, "text": text}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "text": "", "raw_error": str(e)}


# === Prompt building ==========================================================


def build_prompt(st: Subtask, mode: str = "patch", ctx_cap: int = 3500) -> str:
    """Build prompt with file context + goal + constraints.
    mode=patch : rendu = fragment de fonction (cap 2000 chars). ctx 1 fichier.
    mode=fullfile : rendu = fichier complet rewrite. ctx tous les context_files."""
    parts = [
        "Tu es un agent INGENIEUR PYTHON Nokido specialise.",
        f"OBJECTIF : {st.goal}",
        f"FICHIER CIBLE : {st.target_file}",
        f"POURQUOI : {st.rationale}",
        "",
        "CONTRAINTES :",
    ]
    for c in st.constraints:
        parts.append(f"  - {c}")
    parts.append("")
    files_to_include = st.context_files if mode == "fullfile" else st.context_files[:1]
    parts.append(f"CONTEXTE ({len(files_to_include)} fichier(s), cap {ctx_cap}b/file) :")
    for cf in files_to_include:
        p = ROOT / cf
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        if len(body) > ctx_cap:
            half = ctx_cap // 2
            body = body[:half] + "\n\n# ... [troncated] ...\n\n" + body[-half:]
        parts.append(f"\n=== {cf} ===")
        parts.append(body)
    parts.append("")
    if mode == "fullfile":
        parts.append(
            "RENDU ATTENDU - STRICT :\n"
            "Un SEUL bloc ```python (avec ouverture ET cloture explicites) "
            "contenant le CONTENU COMPLET du fichier cible (rewrite integral). "
            "Conserve TOUS les imports, classes et fonctions existants non "
            "touches. Annote les zones modifiees par # STRATEGIST <sid>. "
            "PAS de texte explicatif autour du bloc."
        )
    else:
        parts.append(
            "RENDU ATTENDU - STRICT :\n"
            "Un SEUL bloc ```python (ouverture ET cloture) contenant "
            "UNIQUEMENT la/les FONCTION(S) MODIFIEE(S) ou AJOUTEE(S). "
            "Garde les imports si nouveaux. Cap 2000 caracteres. Pas de texte "
            "explicatif autour du bloc."
        )
    return "\n".join(parts)


# === Code extraction ==========================================================

_CODE_BLOCK_PY = re.compile(r"```(?:python|py)\s*\n(.*?)(?:```|$)", re.DOTALL)
_CODE_BLOCK_ANY = re.compile(r"```\s*\n(.*?)(?:```|$)", re.DOTALL)


def extract_first_block(text: str) -> str | None:
    """Extraction tolerante : ```python, ```py, ``` seul. Accepte les
    blocs sans fence de cloture (truncation hub 4000b)."""
    m = _CODE_BLOCK_PY.search(text)
    if m:
        return m.group(1).strip()
    m = _CODE_BLOCK_ANY.search(text)
    if m:
        body = m.group(1).strip()
        # heuristique : sanity check qu il y a au moins une signature Python
        if re.search(r"\b(def |class |import |from )", body):
            return body
    return None


# === Strategist driver ========================================================


def _dspy_draft(st: Subtask, provider: str, token: str, ctx_cap: int, max_tokens: int) -> dict:
    """Draft via dspy CodePatchProposal Signature - rendu JSON strict.
    Retourne {ok, code, fields, raw_error}."""
    if not _DSPY_AVAILABLE:
        return {"ok": False, "code": None, "raw_error": "dspy non installe (forge_dspy_router)"}
    # build context = 1 fichier cible cap
    ctx_parts = []
    for cf in st.context_files[:1]:
        p = ROOT / cf
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        if len(body) > ctx_cap:
            half = ctx_cap // 2
            body = body[:half] + "\n\n# ... [troncated] ...\n\n" + body[-half:]
        ctx_parts.append(f"=== {cf} ===\n{body}")
    constraints_str = " ; ".join(st.constraints)
    inputs = {
        "goal": st.goal,
        "file_context": "\n\n".join(ctx_parts),
        "constraints": constraints_str,
    }
    rep = _signature_call(
        "CodePatchProposal", inputs, provider, token, max_tokens=max_tokens, timeout_s=180
    )
    if not rep.get("ok"):
        return {
            "ok": False,
            "code": None,
            "raw_error": rep.get("error", "?"),
            "raw": rep.get("raw", ""),
        }
    fields = rep.get("fields", {})
    code = fields.get("code", "")
    return {
        "ok": bool(code),
        "code": code,
        "fields": fields,
        "raw_error": None if code else "field 'code' vide",
    }


def run_subtask(
    st: Subtask,
    token: str,
    max_retries: int = 2,
    mode: str = "patch",
    auto_refine: bool = False,
    judge: str = "symbolic",
    drafter: str = "raw",
) -> dict:
    """Boucle cloud-draft / judge-local / refine.
    mode=fullfile|patch : taille rendu attendu.
    judge=symbolic|sem|both : symbolic=AST+dep+pylint+LOC+tokens (zero LLM,
    gouvernance Marcus) ; sem=LLM-judge qwen ; both=symbolic + sem.
    drafter=raw|dspy : raw=hub_ask texte libre + regex (legacy) ;
    dspy=signature_call JSON-schema strict (Marcus governance step 2).
    auto_refine=True -> sur PARTIAL final, dispatche create_refine_task EDITOR."""
    log = []
    last_critique = ""
    is_full = mode == "fullfile"
    max_tok = 16384 if is_full else 8192
    ctx_cap = 8000 if is_full else 3500
    best_attempt: dict | None = None  # garde la meilleure tentative
    for attempt in range(1, max_retries + 1):
        provider = st.provider_chain[(attempt - 1) % len(st.provider_chain)]
        print(f"\n[{st.sid}] attempt={attempt} provider={provider} mode={mode} drafter={drafter}")
        t0 = time.monotonic()
        if drafter == "dspy":
            # Signature CodePatchProposal -> rendu JSON {code, rationale, risk, ...}
            rep = _dspy_draft(st, provider, token, ctx_cap, max_tok)
            dt = time.monotonic() - t0
            log.append(
                {
                    "attempt": attempt,
                    "provider": provider,
                    "ask_ms": int(dt * 1000),
                    "drafter": "dspy",
                    "ok": rep["ok"],
                    "raw_error": rep.get("raw_error"),
                }
            )
            if not rep["ok"]:
                print(f"  [dspy] FAIL : {rep.get('raw_error', '?')[:200]}")
                last_critique = f"dspy schema fail: {rep.get('raw_error', '')}"
                continue
            code = rep["code"]
            # save dspy fields for debug
            raw_path = DRAFTS_DIR / f"{st.sid}_attempt{attempt}_dspy.json"
            raw_path.write_text(
                json.dumps(rep.get("fields", {}), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            _rat = (
                str(rep["fields"].get("rationale", ""))[:80]
                .encode("ascii", "replace")
                .decode("ascii")
            )
            _risk = (
                str(rep["fields"].get("risk_level", "?")).encode("ascii", "replace").decode("ascii")
            )
            print(f"  [dspy] OK rationale={_rat} risk={_risk}")
        else:
            # Legacy raw drafter
            prompt = build_prompt(st, mode=mode, ctx_cap=ctx_cap)
            if last_critique:
                prompt += (
                    "\n\nIMPORTANT - PRECEDENT JUGEMENT LOCAL :\n"
                    f"{last_critique}\n"
                    "Corrige les problemes ci-dessus dans cette nouvelle version."
                )
            rep = hub_ask(provider, prompt, token, max_tokens=max_tok, timeout_s=180)
            dt = time.monotonic() - t0
            log.append(
                {
                    "attempt": attempt,
                    "provider": provider,
                    "ask_ms": int(dt * 1000),
                    "drafter": "raw",
                    "ok": rep["ok"],
                    "raw_error": rep.get("raw_error"),
                }
            )
            if not rep["ok"]:
                print(f"  [ask] FAIL : {rep.get('raw_error', '?')[:200]}")
                continue
            raw_path = DRAFTS_DIR / f"{st.sid}_attempt{attempt}_raw.txt"
            raw_path.write_text(rep["text"], encoding="utf-8")
            code = extract_first_block(rep["text"])
            if not code:
                print(
                    f"  [ask] OK mais aucun bloc code (len resp={len(rep['text'])}) "
                    f"-> raw save {raw_path.name}"
                )
                last_critique = (
                    "Le rendu n avait pas de bloc ```python valide. "
                    "STRICT : ouvre par ```python et ferme par ``` exactement."
                )
                continue
        draft_path = DRAFTS_DIR / f"{st.sid}_attempt{attempt}.py"
        draft_path.write_text(code, encoding="utf-8")
        print(f"  [draft] {draft_path}  ({len(code)}b)")
        # juge selon strategie demandee :
        # symbolic = zero LLM (Marcus governance, default)
        # sem      = LLM-judge qwen (legacy)
        # both     = min(symbolic, sem)
        try:
            if judge == "symbolic":
                sc = evaluate_symbolic(str(draft_path))
            elif judge == "sem":
                judge_fn = evaluate_code if is_full else evaluate_patch
                sc = judge_fn(
                    str(draft_path), task_desc=st.goal, judge_model="laforge-qwen", judge_timeout=90
                )
            else:  # both
                sc_sym = evaluate_symbolic(str(draft_path))
                judge_fn = evaluate_code if is_full else evaluate_patch
                sc_sem = judge_fn(
                    str(draft_path), task_desc=st.goal, judge_model="laforge-qwen", judge_timeout=90
                )
                sc = sc_sym if sc_sym.confidence_score <= sc_sem.confidence_score else sc_sem
                sc.critique = f"sym: {sc_sym.critique} || sem: {sc_sem.critique}"
        except Exception as e:  # noqa: BLE001
            print(f"  [judge] ERR : {e}")
            log[-1]["judge_error"] = str(e)
            continue
        print(f"  [judge] grade={sc.grade.value}  conf={sc.confidence_score:.2f}")
        print(f"          critique: {sc.critique[:200]}")
        log[-1].update(
            {
                "draft_path": str(draft_path),
                "scorecard": sc.to_dict(),
            }
        )
        # Retient la meilleure tentative (plus haut confidence_score)
        if (
            best_attempt is None
            or sc.confidence_score > best_attempt["scorecard"]["confidence_score"]
        ):
            best_attempt = log[-1]
        if sc.grade == QualityGrade.OPTIMAL:
            return {
                "sid": st.sid,
                "status": "OPTIMAL",
                "attempts": log,
                "final_draft": str(draft_path),
                "scorecard": sc.to_dict(),
                "refine_task_id": None,
            }
        last_critique = sc.critique
    # epuise sans OPTIMAL : utilise best_attempt (pas la derniere qui peut etre pire)
    if best_attempt is None:
        return {
            "sid": st.sid,
            "status": "FAIL",
            "attempts": log,
            "final_draft": None,
            "scorecard": None,
            "refine_task_id": None,
        }
    final_grade = best_attempt["scorecard"]["grade"]
    result = {
        "sid": st.sid,
        "status": final_grade,
        "attempts": log,
        "final_draft": best_attempt["draft_path"],
        "scorecard": best_attempt["scorecard"],
        "refine_task_id": None,
    }
    # auto_refine : sur PARTIAL final + scorecard dispo, dispatch refine
    if auto_refine and final_grade == "PARTIAL" and result["scorecard"]:
        try:
            # Import local des classes encore non importees au module level
            # (QualityGrade/Scorecard sont deja module level - on n importe que
            # le delta pour eviter shadow UnboundLocalError sur QualityGrade).
            from nokido_agent.app.forge_scorecard import (
                ExecutionState as _ES,
            )
            from nokido_agent.app.forge_scorecard import (
                ScoreMetrics as _SM,
            )
            from nokido_agent.app.forge_scorecard import (
                create_refine_task as _crt,
            )

            sc_d = result["scorecard"]
            sc_obj = Scorecard(
                state=_ES(sc_d.get("state", "COMPLETED")),
                grade=QualityGrade(sc_d.get("grade", "UNRATED")),
                confidence_score=float(sc_d.get("confidence_score", 0.0)),
                metrics=_SM(**(sc_d.get("metrics") or {})),
                payload=result["final_draft"],
                critique=str(sc_d.get("critique", "")),
            )
            ref = _crt(
                original_task_id=f"strategist_{st.sid}",
                scorecard=sc_obj,
                original_description=st.goal,
                target_agent="EDITOR",
                hub_token=token,
            )
            result["refine_task_id"] = ref.get("task_id")
            print(
                f"  [refine] dispatched to EDITOR -> task_id={result['refine_task_id']} ok={ref.get('ok')}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [refine] FAIL : {e}")
            result["refine_error"] = str(e)
    return result


# === Main =====================================================================


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subtask", default="all", help="A | C | D | E | all (defaut all)")
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument(
        "--mode",
        choices=["patch", "fullfile"],
        default="patch",
        help="patch = fragment de fonction ; fullfile = rewrite complet",
    )
    ap.add_argument(
        "--auto-refine",
        action="store_true",
        help="sur PARTIAL final, dispatch create_refine_task EDITOR",
    )
    ap.add_argument(
        "--judge",
        choices=["symbolic", "sem", "both"],
        default="symbolic",
        help="symbolic = AST/dep/pylint/LOC/tokens zero LLM "
        "(defaut, gouvernance Marcus) ; sem = LLM-judge "
        "qwen ; both = min des deux",
    )
    ap.add_argument(
        "--drafter",
        choices=["raw", "dspy"],
        default="raw",
        help="raw = hub_ask texte libre + regex (legacy) ; "
        "dspy = signature_call JSON-schema strict "
        "(Marcus governance step 2)",
    )
    args = ap.parse_args()

    # 2b-6 (2026-09-28) : le jeton de l'identite annoncee (X-Agent-Name: STRATEGIST), propre
    # sinon le maitre en transition dite -- plus le maitre lu en direct au coffre machine.
    token = jeton_hub("STRATEGIST") or ""
    if not token:
        print("ERR : aucun jeton pour STRATEGIST (ni propre, ni maitre en transition)")
        return 1

    selected = (
        [st for st in SUBTASKS if st.sid == args.subtask.upper()]
        if args.subtask.lower() != "all"
        else SUBTASKS
    )
    if not selected:
        print(f"ERR : subtask '{args.subtask}' inconnu (A/C/D/E/all)")
        return 1

    print(
        f"[strategist] {len(selected)} subtask(s) : {[st.sid for st in selected]} "
        f"mode={args.mode} judge={args.judge} drafter={args.drafter} "
        f"auto_refine={args.auto_refine}"
    )
    results = []
    for st in selected:
        r = run_subtask(
            st,
            token,
            max_retries=args.max_retries,
            mode=args.mode,
            auto_refine=args.auto_refine,
            judge=args.judge,
            drafter=args.drafter,
        )
        results.append(r)
        (DRAFTS_DIR / f"{st.sid}_report.json").write_text(
            json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print("\n=== STRATEGIST REPORT ===")
    for r in results:
        refine_str = f" refine_id={r.get('refine_task_id')}" if r.get("refine_task_id") else ""
        print(f"  [{r['sid']}] {r['status']}  -> {r.get('final_draft')}{refine_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
