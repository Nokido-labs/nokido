"""forge_sft_export.py — exporte un golden-dataset SFT (chat JSONL) depuis les trajectoires
GAGNANTES, pour fine-tuner un modèle de base (le 7b expert de tes projets).

Sources :
  - swebench : instances RÉSOLUES (eval results[].resolved=True) → (problem_statement → model_patch).
    Golden code-gen pairs. NB: l'eval local est flaky (erreurs d'env) → peu de résolus tant que
    l'eval n'est pas durci ; le set croît avec les runs cloud forts.
  - goap     : traces succès (execution_traces.db) → (state_text → action_json). Action-selection,
    mince mais réel (croît avec la boucle self-play).

Format chat-SFT standard (transformers/trl/axolotl) :
  {"messages":[{"role":"user","content":...},{"role":"assistant","content":...}],"source":...,"id":...}

Lance : python tools/forge_sft_export.py --out RAG/sft/golden.jsonl --sources swebench,goap
"""

from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

from nokido_agent.app.forge_benchmark_adapter import swebench_dir  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# SWE-bench vit HORS de RAG/ depuis le 2026-09-27 : meme resolveur que les runners.
SWE = swebench_dir()
TRACES = ROOT / "RAG" / "execution_traces.db"


def _problem_statements() -> dict:
    out: dict[str, str] = {}
    for f in glob.glob(str(SWE / "swebench_*_*.jsonl")):
        try:
            for line in open(f, encoding="utf-8", errors="replace"):
                d = json.loads(line)
                if d.get("instance_id") and d.get("problem_statement"):
                    out[d["instance_id"]] = d["problem_statement"]
        except Exception:  # noqa: BLE001
            pass
    return out


def harvest_swebench() -> list[dict]:
    """Instances RÉSOLUES → (problem → patch). Golden code-gen."""
    problems = _problem_statements()
    resolved: set[str] = set()
    for f in glob.glob(str(SWE / "eval_*.json")):
        try:
            j = json.load(open(f, encoding="utf-8", errors="replace"))
            for r in (j.get("results") or []):
                if isinstance(r, dict) and r.get("resolved"):
                    resolved.add(r.get("instance_id"))
        except Exception:  # noqa: BLE001
            pass
    patch: dict[str, str] = {}
    for f in glob.glob(str(SWE / "predictions*.jsonl")):
        try:
            for line in open(f, encoding="utf-8", errors="replace"):
                d = json.loads(line)
                if d.get("instance_id") and d.get("model_patch"):
                    patch.setdefault(d["instance_id"], d["model_patch"])
        except Exception:  # noqa: BLE001
            pass
    pairs = []
    for iid in resolved:
        if iid in problems and iid in patch:
            pairs.append({
                "messages": [
                    {"role": "user",
                     "content": f"Résous ce ticket. Renvoie UNIQUEMENT un patch unified diff.\n\n{problems[iid][:6000]}"},
                    {"role": "assistant", "content": patch[iid]},
                ],
                "source": "swebench_resolved", "id": iid,
            })
    return pairs


def harvest_goap() -> list[dict]:
    """Traces GOAP succès → (state_text → action_json). Action-selection."""
    if not TRACES.exists():
        return []
    pairs = []
    try:
        con = sqlite3.connect(f"file:{TRACES}?mode=ro", uri=True)  # read-only (sandbox OK)
        for sid, aj in con.execute(
            "SELECT id, action_json FROM traces WHERE success=1 AND task_type='goap'"):
            try:
                a = json.loads(aj)
            except Exception:  # noqa: BLE001
                continue
            pairs.append({
                "messages": [
                    {"role": "user", "content": "Prochaine action GOAP ? Donne l'outil + ses arguments en JSON."},
                    {"role": "assistant", "content": json.dumps(a, ensure_ascii=False)},
                ],
                "source": "goap_success", "id": sid,
            })
        con.close()
    except Exception:  # noqa: BLE001
        pass
    return pairs


def harvest_humaneval(he_train_max: int | None = None) -> list[dict]:
    """HumanEval PASS → (prompt → code_body). Code-gen FIABLE : eval déterministe subprocess
    (zéro flakiness vs Docker SWE-bench). he_train_max=N → ne garde QUE les task HumanEval/<N
    (split TRAIN ; les >=N restent HELD-OUT pour forge_sft_eval = pas de leakage)."""
    HE = ROOT / "RAG" / "humaneval"
    pairs = []
    for f in glob.glob(str(HE / "humaneval_*.json")):
        try:
            j = json.load(open(f, encoding="utf-8", errors="replace"))
            for r in (j.get("results") or []):
                if isinstance(r, dict) and r.get("pass") and r.get("prompt") and r.get("code_body"):
                    if he_train_max is not None:
                        try:
                            if int(str(r.get("task_id", "")).split("/")[-1]) >= he_train_max:
                                continue  # held-out → exclu du train
                        except Exception:  # noqa: BLE001
                            pass
                    pairs.append({
                        "messages": [
                            {"role": "user",
                             "content": f"Complète cette fonction Python. Renvoie UNIQUEMENT le corps (indenté).\n\n{r['prompt']}"},
                            {"role": "assistant", "content": r["code_body"]},
                        ],
                        "source": "humaneval_pass", "id": r.get("task_id"),
                    })
        except Exception:  # noqa: BLE001
            pass
    return pairs


def harvest_mbpp(limit: int | None = None) -> list[dict]:
    """MBPP — ~974 problèmes (texte → fonction complète) via HF datasets. Les solutions de
    référence sont CORRECTES par construction (≠ l'eval HumanEval → 0 leakage). Sert de
    scale data (134→~1k) + diversité anti-forgetting. Réseau requis (run sous user) ;
    skip propre si offline/sandbox. Instruction = fonction COMPLÈTE (≠ corps HumanEval)."""
    try:
        from datasets import load_dataset
    except Exception as e:  # noqa: BLE001
        print(f"[sft] mbpp skip (datasets indispo: {e})")
        return []
    rows: list[dict] = []
    for cfg in ("full", "sanitized", None):
        try:
            ds = load_dataset("mbpp", cfg) if cfg else load_dataset("mbpp")
        except Exception:  # noqa: BLE001
            continue
        for split in ds:  # train/test/validation/prompt
            for r in ds[split]:
                text = r.get("text") or r.get("prompt")
                code = r.get("code")
                if not text or not code:
                    continue
                rows.append({
                    "messages": [
                        {"role": "user",
                         "content": f"Écris une fonction Python complète pour : {text}\nRenvoie UNIQUEMENT le code de la fonction."},
                        {"role": "assistant", "content": code},
                    ],
                    "source": "mbpp", "id": f"mbpp/{r.get('task_id')}",
                })
        break  # une config a marché
    if not rows:
        print("[sft] mbpp skip (download échoué — offline ? lancer sous user avec réseau)")
    return rows[:limit] if limit else rows


def _git(args: list[str]) -> str:
    """git dans le dépôt. Rend une chaîne VIDE si git est injoignable — et le DIT.

    Un extracteur qui rend « 0 paire » pour « rien à moissonner » ET pour « je n'ai pas
    pu regarder » fabrique un silence rassurant (RULES_SHARED : vrai · faux · illisible).
    """
    try:
        r = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(ROOT), "--no-pager", *args],
            capture_output=True, text=True, errors="replace", timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[git_history] git INJOIGNABLE ({type(exc).__name__}) — 0 paire, PAS « rien à moissonner »")
        return ""
    if r.returncode != 0:
        print(f"[git_history] git rc={r.returncode} : {(r.stderr or '')[:200]}")
        return ""
    return r.stdout or ""


def harvest_git_commits(limit: int = 600, max_files: int = 3, max_diff: int = 12000) -> list[dict]:
    """Historique RÉEL du dépôt → (intention → patch). Ground truth que personne n'a inventé.

    Pourquoi ici et pas dans un module neuf : le golden dataset a déjà son point d'entrée
    (ce fichier), son format (`messages`/`source`/`id`) et ses consommateurs
    (`forge_sft_train`, `forge_benchmark_runner`). Ce qui manquait n'était pas un outil,
    c'était une SOURCE — mesuré le 02/08 : 3 973 commits, dont 966 `fix(` et 1 379 `feat(`,
    chacun portant son « pourquoi » dans le corps et son patch exact en face.

    Filtres DÉTERMINISTES d'abord ; un juge LLM ne sert qu'à départager la zone grise, et
    coûte cent fois plus cher que ces quatre tests :
      · commit conventionnel `fix(` / `feat(`, jamais un merge (son diff n'enseigne rien) ;
      · corps non vide, signatures d'agent retirées — sans le pourquoi, la paire n'apprend
        qu'un diff sans intention ;
      · au plus `max_files` fichiers touchés = atomicité (un commit qui mélange un fix, un
        bump et un renommage ne laisse apprendre aucune relation cause→effet) ;
      · diff sous `max_diff` caractères — ÉCARTÉ, jamais tronqué : un patch coupé est un
        patch faux, et le modèle apprendrait à en produire.

    Biais assumé, à connaître avant d'entraîner : le corps d'un commit Nokido décrit souvent
    la mesure ET le remède. La paire est donc plus facile qu'un ticket réel, où le remède est
    inconnu. Pour une évaluation sévère, réduire `--git-body` : le sujet seul se rapproche
    d'un énoncé de problème.
    """
    RS, US = "\x1e", "\x1f"
    brut = _git(["log", f"-{limit}", "--no-merges", "--grep=^fix(", "--grep=^feat(",
                 f"--pretty=format:%H{US}%s{US}%b{RS}"])
    if not brut:
        return []
    pairs: list[dict] = []
    vus: set[str] = set()
    ecartes = {"corps_pauvre": 0, "trop_de_fichiers": 0, "diff_trop_gros": 0, "patch_vide": 0, "doublon": 0}
    for enr in brut.split(RS):
        if not enr.strip():
            continue
        parts = enr.strip("\n").split(US)
        if len(parts) < 3:
            continue
        sha, sujet, corps = parts[0].strip(), parts[1].strip(), US.join(parts[2:]).strip()
        corps = "\n".join(
            ln for ln in corps.splitlines()
            if not ln.strip().startswith(("LaForge-Agent-", "Co-Authored-By:", "Untested-Ack:"))
        ).strip()
        if len(corps) < 40:
            ecartes["corps_pauvre"] += 1
            continue
        patch = _git(["show", sha, "--format=", "--patch", "--unified=3"])
        if not patch.strip():
            ecartes["patch_vide"] += 1
            continue
        n_files = patch.count("\ndiff --git ") + (1 if patch.startswith("diff --git ") else 0)
        if n_files > max_files:
            ecartes["trop_de_fichiers"] += 1
            continue
        if len(patch) > max_diff:
            ecartes["diff_trop_gros"] += 1
            continue
        if sujet.lower() in vus:
            ecartes["doublon"] += 1
            continue
        vus.add(sujet.lower())
        pairs.append({
            "messages": [
                {"role": "user",
                 "content": "Dépôt Nokido. Applique ce changement. Renvoie UNIQUEMENT un patch "
                            f"unified diff.\n\n{sujet}\n\n{corps[:1500]}"},
                {"role": "assistant", "content": patch},
            ],
            "source": "git_history", "id": sha[:12],
        })
    print(json.dumps({"git_history": {"retenues": len(pairs), "ecartees": ecartes}}, ensure_ascii=False))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "RAG" / "sft" / "golden.jsonl"))
    ap.add_argument("--sources", default="humaneval,mbpp,swebench,goap,git")
    ap.add_argument("--git-limit", type=int, default=600,
                    help="commits fix(/feat( examinés pour la source `git` (historique du dépôt)")
    ap.add_argument("--git-max-files", type=int, default=3,
                    help="atomicité : au-delà, le commit mélange trop de choses pour enseigner")
    ap.add_argument("--he-train-max", type=int, default=None,
                    help="split : ne garde que HumanEval/<N pour le train (>=N = held-out eval)")
    args = ap.parse_args()
    srcs = {s.strip() for s in args.sources.split(",")}

    pairs = []
    if "humaneval" in srcs:
        pairs += harvest_humaneval(he_train_max=args.he_train_max)
    if "mbpp" in srcs:
        pairs += harvest_mbpp()
    if "swebench" in srcs:
        pairs += harvest_swebench()
    if "goap" in srcs:
        pairs += harvest_goap()
    if "git" in srcs:
        pairs += harvest_git_commits(limit=args.git_limit, max_files=args.git_max_files)

    seen, uniq = set(), []
    for p in pairs:
        k = (p["source"], p["id"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for p in uniq:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(json.dumps({"total": len(uniq), "by_source": dict(Counter(p["source"] for p in uniq)),
                      "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
