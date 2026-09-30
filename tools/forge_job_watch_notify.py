"""forge_job_watch_notify.py — Facteur de fin de job : observe un job deporte et
notifie automatiquement les clients DANS LA BOUCLE a sa terminaison.

Decouple : tourne en run_job a cote du job cible (aucun kill/relaunch requis).
Observe `progress.json` (ecrit par le job) : quand phase=='done' -> emet via
forge_job_notify.notify_subscribers vers chaque abonne (agt_claude, agt_gemini, ...)
dans le canal agent_messages que leurs inbox-hooks pollent. Detecte aussi le stall
(progress fige) et notifie un resultat partiel pour ne jamais laisser la boucle muette.

Usage :
    LAFORGE_PYTHON tools/forge_job_watch_notify.py \
        --progress C:/tmp/audit_deep/progress.json \
        --refined  C:/tmp/audit_deep/refined.jsonl \
        --report   C:/tmp/audit_deep/AUDIT_DEEP_REPORT.md \
        --job audit_swarm_deep --to agt_claude,agt_gemini
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from nokido_agent.tools.forge_job_notify import notify_subscribers  # noqa: E402


def _resoudre(chemin):
    """Ancre un chemin RELATIF sur le depot, pas sur le repertoire courant.

    MESURE 2026-09-08 : le repertoire de travail d'un job detache est
    `<depot>/sandbox/workspace`, PAS la racine. Or la forme imposee par le garde de
    capacites est relative (`--rc sandbox/jobs/<job>.rc`) : elle se resolvait donc
    ailleurs, `_lire_rc` rendait None, et le veilleur lisait cette absence comme
    « le job tourne encore ». Il a attendu 35 min apres la fin de sa cible, avec pour
    seul journal sa ligne de demarrage, en tenant sa lane -- donc en empechant tout
    autre veilleur d'etre poste. Un echec MUET dans l'outil meme qui existe pour ne
    pas poller.
    """
    if not chemin:
        return chemin
    p = Path(chemin)
    return str(p if p.is_absolute() else (ROOT / p))


def _load(path: str) -> dict:
    try:
        return json.loads(Path(_resoudre(path)).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _count_verdicts(refined: str) -> dict:
    real = fp = unc = total = 0
    sev: dict[str, int] = {}
    tops = []
    p = Path(refined)
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
            except Exception:
                continue
            total += 1
            v = d.get("final", {}).get("verdict")
            if v == "real":
                real += 1
                s = str(d["final"].get("severity", "medium")).lower()
                sev[s] = sev.get(s, 0) + 1
                if s in ("critical", "high") and len(tops) < 5:
                    tops.append(f"[{s}] {d['finding'].get('file')}: {d['finding'].get('title','?')[:55]}")
            elif v == "false_positive":
                fp += 1
            else:
                unc += 1
    sevtxt = ", ".join(f"{k}:{sev[k]}" for k in ("critical", "high", "medium", "low", "info") if sev.get(k))
    return {"total": total, "real": real, "fp": fp, "unc": unc, "sevtxt": sevtxt, "tops": tops}


def _summary(stage: str, args) -> str:
    """Resume de fin. Deux formes, selon ce que le job a REELLEMENT produit.

    Le module ne savait resumer qu'un audit swarm (`--refined` obligatoire). Or le job le
    plus surveille de ce depot est la CI locale, qui ne produit ni `refined.jsonl` ni
    rapport : le facteur etait donc inutilisable la ou il aurait le plus servi. Mesure du
    2026-09-06 : une soiree entiere de CI suivies par polling manuel -- exactement le
    defaut que `forge_job_progress` consignait deja le 2026-09-03, « suivi a l'aveugle
    alors qu'un champ prevu pour ca existait ».
    """
    tetes = {"done": "job terminé", "stall": "job figé (résultat PARTIEL)",
             "rc": "job terminé"}
    head = tetes.get(stage, stage)
    if not args.refined:
        rc = _lire_rc(args.rc)
        etat = "VERT (rc=0)" if rc == "0" else (f"ROUGE (rc={rc})" if rc else "rc INCONNU")
        prog = _load(args.progress)
        etape = prog.get("etape") or prog.get("phase") or "?"
        return f"{head} [{args.job}] : {etat}. Dernière étape : {etape}."
    v = _count_verdicts(args.refined)
    body = (f"{head}. Findings raffinés={v['total']} | REELS={v['real']} "
            f"({v['sevtxt'] or '—'}) | faux-positifs={v['fp']} | incertains={v['unc']}. "
            f"Rapport: {args.report}")
    if v["tops"]:
        body += " TOP: " + " ; ".join(v["tops"])
    return body


def _lire_rc(chemin):
    """Le `.rc` est le TEMOIN EXTERNE de fin : absent tant que le job tourne.

    RULES_SHARED le dit deja pour la surveillance : « condition sur un signal que le log
    ne peut pas imiter -- le fichier .rc du job (absent tant qu'il tourne) ». Un resume
    fonde sur le log seul se ferait tromper par un job qui imprime le mot « termine ».
    Trois etats : la valeur, None si absent, None si illisible -- jamais une invention.
    """
    chemin = _resoudre(chemin)
    if not chemin or not os.path.exists(chemin):
        return None
    try:
        return open(chemin, encoding="utf-8", errors="replace").read().strip()
    except OSError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--progress", required=True)
    ap.add_argument("--refined", default=None,
                    help="audit swarm seulement ; absent = resume generique (rc + etape)")
    ap.add_argument("--report", default=None)
    ap.add_argument("--rc", default=None,
                    help="fichier .rc du job : TEMOIN EXTERNE de fin, absent tant que le "
                         "job tourne. Sans lui, seul `phase=done` du progress termine la "
                         "surveillance -- ce qu'un job de CI n'ecrit jamais.")
    ap.add_argument("--job", default="job")
    ap.add_argument("--to", required=True)
    ap.add_argument("--poll", type=int, default=120)
    ap.add_argument("--stall-secs", type=int, default=4 * 3600)
    ap.add_argument("--max-secs", type=int, default=6 * 24 * 3600)
    a = ap.parse_args()
    subs = [x.strip() for x in a.to.split(",") if x.strip()]

    # ANCRAGE AVANT TOUTE ATTENTE. Les chemins sont resolus une fois, puis ANNONCES en
    # absolu : une porte annoncee est une porte verifiable, et un veilleur poste devant
    # la mauvaise se voit a la premiere ligne de son journal au lieu de se lire comme
    # une attente normale pendant six jours.
    a.progress = _resoudre(a.progress)
    a.rc = _resoudre(a.rc)
    a.refined = _resoudre(a.refined)
    a.report = _resoudre(a.report)

    t0 = time.time()
    last_sig = None
    last_change = time.time()
    print(f"[watch] start job={a.job} -> {subs} poll={a.poll}s", flush=True)
    print(f"[watch] porte progress = {a.progress} (present={os.path.exists(a.progress)})",
          flush=True)
    print(f"[watch] porte rc       = {a.rc} (present="
          f"{os.path.exists(a.rc) if a.rc else 'AUCUN rc fourni'})", flush=True)

    while True:
        if time.time() - t0 > a.max_secs:
            notify_subscribers(a.job, subs, _summary("stall", a) + " [watch: max-secs atteint]",
                               method="audit.timeout")
            print("[watch] max-secs -> notified timeout, exit", flush=True)
            return

        prog = _load(a.progress)
        phase = prog.get("phase")
        if phase == "done":
            out = notify_subscribers(a.job, subs, _summary("done", a), method="audit.done")
            print(f"[watch] DONE -> notified {out.get('delivered')} err={out.get('errors')}", flush=True)
            return
        # FIN PAR LE TEMOIN EXTERNE. Un job de CI n'ecrit jamais `phase=done` : il depose
        # son `.rc`. Sans cette branche, le facteur attendait un signal que ce job-la
        # n'emet pas -- un guetteur poste devant la mauvaise porte.
        if a.rc and _lire_rc(a.rc) is not None:
            out = notify_subscribers(a.job, subs, _summary("rc", a), method="job.done")
            print(f"[watch] RC -> notified {out.get('delivered')} err={out.get('errors')}",
                  flush=True)
            return

        # stall detection : signature = (phase, refined size, progress mtime)
        try:
            taille = (os.path.getsize(a.refined)
                      if a.refined and os.path.exists(a.refined) else 0)
            sig = (phase, prog.get("etape"), taille,
                   os.path.getmtime(a.progress) if os.path.exists(a.progress) else 0)
        except OSError:
            sig = None
        if sig != last_sig:
            last_sig = sig
            last_change = time.time()
        elif time.time() - last_change > a.stall_secs:
            notify_subscribers(a.job, subs, _summary("stall", a) + " [watch: progress figé]",
                               method="audit.stall")
            print("[watch] STALL -> notified partial, exit", flush=True)
            return

        time.sleep(a.poll)


if __name__ == "__main__":
    main()
