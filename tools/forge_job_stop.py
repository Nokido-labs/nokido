"""
tools/forge_job_stop.py — arret PROPRE d'un job detache lance par `run action=run_job`.

Manque comble le 2026-07-25 : `job_status` sait lire l'etat d'un job, rien ne savait
l'ARRETER. Depuis le bac a sable, `taskkill` rend « Acces refuse » (le job tourne sous
un autre compte), donc le seul recours etait d'attendre la fin d'un travail qu'on
savait nuisible.

GARDES (l'arret d'un processus est irreversible, il ne se devine pas) :
  - le pid doit correspondre a un job REFERENCE dans le repertoire des jobs, ou porter
    une ligne de commande qui pointe vers un script de jobs -> on ne tue jamais un pid
    arbitraire sur la foi d'un numero ;
  - dry-run par defaut : sans `--kill`, on IMPRIME ce qu'on ferait ;
  - l'arbre est arrete (children puis parent) : un crawl laisse sinon des orphelins.

Usage : run action=trusted_script path=tools/forge_job_stop.py script_args="<pid> --kill"
"""
from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/keeper : arret propre d'un job detache"  # organe declare le 2026-09-06 (audit de raccordement)

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Le projet s'appelait LAFORGE avant Nokido, et cette liste n'avait pas suivi : le hub
# ecrit dans `C:/tmp/nokido_jobs` (admin_run_job) et le bac a sable dans
# `sandbox/jobs`, alors que le garde ne connaissait que `laforge_jobs`. Consequence
# mesuree le 2026-07-30 : `_looks_like_job` REFUSAIT tout job lance aujourd'hui, donc
# le seul outil d'arret ne pouvait rien arreter. Meme classe que le `glob("*Nokido*")`
# de forge_conv_indexer : un filtre par NOM ignore les noms d'avant et ceux d'apres.
import os as _os

_ENV_JOBS = _os.environ.get("LAFORGE_JOBS_DIR", "")
JOB_DIRS = (
    *((Path(_ENV_JOBS),) if _ENV_JOBS else ()),
    Path(r"C:\tmp\nokido_jobs"),
    Path(r"C:\tmp\laforge_jobs"),
    ROOT / "sandbox" / "jobs",
    Path(r"C:\tmp"),
)


def _looks_like_job(proc) -> tuple[bool, str]:
    """Le processus est-il bien un job detache Nokido ? Retour (verdict, raison)."""
    try:
        cmd = " ".join(proc.cmdline())
    except Exception as e:  # noqa: BLE001
        return False, f"ligne de commande illisible ({type(e).__name__})"
    low = cmd.lower()
    if "python" not in low:
        return False, "ce n'est pas un processus python"
    for d in JOB_DIRS:
        if str(d).lower().replace("\\", "/") in low.replace("\\", "/"):
            return True, f"script sous {d}"
    if "_wrap.py" in low or "laforge_jobs" in low:
        return True, "wrapper de job"
    return False, f"ne pointe vers aucun repertoire de jobs : {cmd[:120]}"


def _arreter_arbre(proc, kill: bool) -> dict:
    """Arrete l'arbre (enfants PUIS parent) et rend le RESULTAT PAR PID.

    Jamais un « ok » global : sur ce poste un arret peut etre refuse par les droits
    (compte different) et le silence ferait croire a un succes. Chaque pid porte son
    verdict.
    """
    import psutil

    try:
        tree = proc.children(recursive=True)
    except Exception as e:  # noqa: BLE001
        tree = []
        detail = [{"pid": proc.pid, "note": f"enfants illisibles ({type(e).__name__})"}]
    else:
        detail = []
    if not kill:
        return {"ok": False, "dry_run": True, "pid": proc.pid,
                "enfants": [c.pid for c in tree], "detail": detail}

    resultats: list[dict] = []
    for ch in list(tree) + [proc]:
        etat = "?"
        try:
            ch.terminate()
            try:
                ch.wait(timeout=5)
                etat = "arrete"
            except Exception:  # noqa: BLE001
                ch.kill()
                etat = "tue (force)"
        except psutil.NoSuchProcess:
            etat = "deja mort"
        except psutil.AccessDenied:
            etat = "ACCES REFUSE (compte different)"
        except Exception as e:  # noqa: BLE001
            etat = f"echec {type(e).__name__}"
        resultats.append({"pid": ch.pid, "etat": etat})
    vivants = [r for r in resultats if "REFUSE" in r["etat"] or r["etat"].startswith("echec")]
    return {"ok": not vivants, "dry_run": False, "pid": proc.pid,
            "resultats": resultats, "non_arretes": vivants, "detail": detail}


def stop_job(job_id: str, kill: bool = False, force: bool = False) -> dict:
    """Arrete un job par son ID. API appelable par le HUB, qui est leur ancetre.

    BLOCKER comble le 2026-07-30 (il etait au blackboard depuis le 25-07) : « aucun
    compte client ne peut arreter un processus qu'il a fait naitre — il manque un
    job_kill cote hub ». Les comptes clients echouent en effet (AccessDenied mesure 4
    fois), mais le hub a CREE le job : c'est a lui de savoir l'arreter.

    Le pid enregistre est celui du WRAPPER, pas du worker (gotcha 2026-07-25) : on
    arrete donc l'ARBRE, sinon le travail continue sous un chef mort.
    """
    import json as _json

    import psutil

    rec = None
    for d in JOB_DIRS:
        p = d / f"{job_id}.json"
        try:
            if p.is_file():
                rec = _json.loads(p.read_text(encoding="utf-8", errors="replace"))
                break
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"fiche illisible ({type(e).__name__})",
                    "job_id": job_id}
    if rec is None:
        return {"ok": False, "error": "job_id inconnu dans les repertoires de jobs",
                "job_id": job_id, "cherche_dans": [str(d) for d in JOB_DIRS]}
    pid = rec.get("pid")
    if not pid:
        return {"ok": False, "error": "fiche sans pid", "job_id": job_id}
    try:
        proc = psutil.Process(int(pid))
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "job_id": job_id, "pid": pid,
                "note": f"process absent ({type(e).__name__}) — job deja termine"}
    ok, why = _looks_like_job(proc)
    if not ok and force and (proc.name() or "").lower().startswith("python"):
        ok, why = True, f"{why} -- accepte par --force (identifie via la fiche du job)"
    if not ok:
        return {"ok": False, "job_id": job_id, "pid": pid, "refus": why,
                "note": "on n'arrete pas un pid qu'on n'a pas identifie"}
    out = _arreter_arbre(proc, kill)
    out.update({"job_id": job_id, "identifie": why})
    return out


def main() -> int:
    args = [a for a in sys.argv[1:]]
    kill = "--kill" in args
    # --force : dernier recours, quand la ligne de commande est ILLISIBLE (le job
    # tourne sous un compte que meme LaForgeTrusted n'inspecte pas -> AccessDenied) et
    # que l'identification vient d'AILLEURS : `job_status` du hub a rendu ce pid pour
    # ce job_id, et l'arret a ete demande explicitement. On exige quand meme que la
    # cible soit un python.exe : la porte est etroite, pas ouverte.
    force = "--force" in args
    pids = [a for a in args if a.isdigit()]
    if not pids:
        print("usage: forge_job_stop.py <pid> [<pid>...] [--kill]")
        return 1

    import psutil

    for spid in pids:
        pid = int(spid)
        try:
            proc = psutil.Process(pid)
        except Exception as e:  # noqa: BLE001
            print(f"pid {pid} : introuvable ({type(e).__name__})")
            continue
        ok, why = _looks_like_job(proc)
        if not ok and force and (proc.name() or "").lower().startswith("python"):
            ok, why = True, f"{why} -- accepte par --force (identifie via le hub)"
        print(f"pid {pid} ({proc.name()}) -> {'JOB' if ok else 'REFUS'} : {why}")
        if not ok:
            print("  aucun arret : on ne tue pas un processus qu'on n'a pas identifie"
                  " (--force si l'identification vient du hub)")
            continue
        try:
            tree = proc.children(recursive=True)
        except Exception:  # noqa: BLE001
            tree = []
        print(f"  arbre : {len(tree)} enfant(s)")
        if not kill:
            print("  DRY-RUN : ajouter --kill pour arreter")
            continue
        for ch in tree:
            try:
                ch.terminate()
            except Exception:  # noqa: BLE001
                pass
        # `wait_procs` leve AccessDenied quand le job tourne sous un compte que ce
        # compte-ci n'ouvre pas (mesure 2026-07-25 : sandbox-online vu de
        # LaForgeTrusted). Sans ce garde, l'exception coupait la fonction AVANT
        # l'arret du PARENT -- on tuait les enfants et on laissait le chef.
        try:
            psutil.wait_procs(tree, timeout=5)
        except Exception as e:  # noqa: BLE001
            print(f"  attente des enfants impossible ({type(e).__name__}) — on continue")
        for ch in tree:
            try:
                if ch.is_running():
                    ch.kill()
            except Exception:  # noqa: BLE001
                pass
        try:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:  # noqa: BLE001
                proc.kill()
            print(f"  ARRETE (pid {pid} + {len(tree)} enfant(s))")
        except Exception as e:  # noqa: BLE001
            print(f"  ECHEC : {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
