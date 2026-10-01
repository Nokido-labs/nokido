#!/usr/bin/env python3
"""forge_ci_stop_hook.py — Stop hook : surface le verdict CI de la branche en fin de tour.

Exigence owner 2026-07-29 : ne plus JAMAIS laisser passer une CI GitHub rouge apres un
push (angle mort mesure plusieurs fois). A chaque Stop, on regarde le DERNIER run de la
branche courante ; si echec -> on CRIE (le stdout du hook est injecte dans le contexte du
tour suivant) ; sinon -> quasi silencieux. Cache l'etat {HEAD, done, conclusion} pour ne
pas re-crier ni re-appeler l'API quand rien n'a bouge — mais tant qu'aucun verdict TERMINAL
n'existe POUR ce HEAD, on re-verifie au tour suivant (on ne rate pas la transition
in_progress -> failure). Best-effort absolu : toute erreur -> exit 0 muet, un hook Stop ne
doit JAMAIS bloquer la fin de tour. Reutilise forge_ci_check.check (API GitHub via coffre).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "sandbox" / "ci_stop_hook_state.json"
REPO = os.environ.get("NOKIDO_CI_REPO", "Nokido-labs/nokido-private")


def _git(*args):
    try:
        out = subprocess.run(["git", "-C", str(ROOT), *args],
                             capture_output=True, text=True, timeout=5,
                             encoding="utf-8", errors="replace")
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _save(head, done, concl):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"head": head, "done": bool(done), "concl": concl},
                                    ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _via_gh(branch: str) -> dict:
    """Repli quand le coffre DPAPI est hors de portee du contexte du hook.

    Mesure 2026-08-12 (owner : « tu devrais les attraper en fin de gitactions,
    ce n'est JAMAIS le cas ») : `forge_ci_check.check` rend
    {ok:false, error:'GITHUB_TOKEN introuvable (coffre DPAPI)'} SANS clef `runs`.
    Le hook tombait alors dans la branche `not runs`, n'y parlait qu'au PREMIER
    passage, et restait muet pour toujours -- signature laissee dans le cache :
    {"done": false, "concl": ""}. La CI pouvait virer au rouge sans un mot.
    `gh` est authentifie INDEPENDAMMENT du coffre : deuxieme voie, pas la meme
    dependance, donc une panne du coffre ne rend plus le garde aveugle.
    """
    try:
        p = subprocess.run(
            ["gh", "run", "list", "-R", REPO, "-b", branch, "-L", "1",
             "--json", "headSha,status,conclusion,url"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace")
        if p.returncode != 0:
            return {}
        arr = json.loads(p.stdout or "[]")
    except Exception:
        return {}
    if not arr:
        return {}
    w = arr[0]
    return {"ok": True, "via": "gh", "runs": [{
        "head": (w.get("headSha") or "")[:8],
        "status": w.get("status"),
        "conclusion": w.get("conclusion"),
        "url": w.get("url"),
    }]}


def main():
    head_full = _git("rev-parse", "HEAD")
    head = head_full[:12]
    if not head:
        return 0
    # Un run CI n'existe que pour un HEAD POUSSE. Tant que HEAD local n'est sur
    # AUCUNE branche distante, aucun appel API n'a de sens. C'etait le cout
    # mesure (7,2 s x 1709 tours = 3,4 h le 2026-08-16) : sur un HEAD non pousse,
    # `runs` restait vide -> `done=False` -> l'API etait re-interrogee a CHAQUE
    # tour. `git branch -r --contains` est local (~50 ms) et sans reseau ; s'il
    # rend vide, on sort sans appeler GitHub. best-effort : si git echoue, on
    # continue le chemin normal (le tour suivant retentera).
    if head_full and _git("rev-parse", "--verify", "-q", head_full + "^{commit}"):
        remotes = _git("branch", "-r", "--contains", head_full)
        if remotes == "":
            return 0
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    first_seen = st.get("head") != head
    # Deja tranche (verdict terminal) pour ce HEAD -> rien a dire, PAS d'appel API.
    if not first_seen and st.get("done"):
        return 0

    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "alpha"
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_ci_check import check
        v = check(REPO, branch, 1) or {}
    except Exception as e:  # pas de reseau/coffre : ne bloque pas
        if first_seen:
            print("[ci-guard] verif CI impossible (%s) — verifier a la main" % type(e).__name__,
                  flush=True)
        return 0

    runs = v.get("runs") or []
    if not runs:
        # Voie principale aveugle -> on tente gh AVANT de conclure quoi que ce soit.
        v = _via_gh(branch) or v
        runs = v.get("runs") or []
    if not runs:
        _save(head, False, "")
        # PAS de `first_seen` ici. Un capteur qui ne voit rien doit le redire a
        # CHAQUE tour tant qu'aucun verdict n'existe pour ce HEAD : se taire apres
        # une seule plainte, c'est exactement ce qui a laisse passer des CI rouges.
        print("[ci-guard] ⚠ CI ILLISIBLE (%s) — aucun verdict pour %s. "
              "Verifier a la main : gh run list -R %s"
              % (v.get("error") or v.get("runs_error") or "?", head, REPO), flush=True)
        return 0

    last = runs[0]
    concl = (last.get("conclusion") or "").lower()
    status = (last.get("status") or "").lower()
    rsha = last.get("head") or ""
    url = last.get("url") or ""
    matches = bool(rsha) and head[:len(rsha)] == rsha
    terminal = concl in ("success", "failure")
    _save(head, terminal and matches, concl)

    if matches and concl == "failure":
        run_id = url.rstrip("/").rsplit("/", 1)[-1] if url else "<id>"
        print("[ci-guard] ⛔ CI ROUGE %s@%s -> %s" % (REPO, rsha, url), flush=True)
        print("[ci-guard] Le dernier run a ECHOUE. Diag: gh run view --log-failed %s -R %s. "
              "NE PAS declarer livre tant que ce n'est pas vert." % (run_id, REPO), flush=True)
    elif matches and concl == "success":
        pass  # vert et a jour : silencieux
    elif not matches:
        if first_seen:
            print("[ci-guard] run pour HEAD %s pas encore visible (dernier connu: %s %s) — "
                  "je re-verifie au prochain tour." % (head, rsha, status or concl), flush=True)
    else:  # matches, en cours
        if first_seen:
            print("[ci-guard] CI en cours pour %s (%s) — verdict au prochain tour." % (rsha, status),
                  flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # un hook Stop ne doit JAMAIS bloquer la fin de tour
