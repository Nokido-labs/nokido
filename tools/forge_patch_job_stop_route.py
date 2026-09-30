#!/usr/bin/env python
"""forge_patch_job_stop_route.py — expose l'arret d'un job sur le hub.

LE BLOCKER (au blackboard depuis le 2026-07-25, ferme ici le 2026-07-30)
    « aucun compte client ne peut arreter un processus qu'il a fait naitre (run_job, et
    WMI depuis le 26-07) — il manque un job_kill cote hub ou superviseur ».
    Mesure : 4 formes d'arret refusees depuis les comptes clients (psutil.terminate,
    taskkill, taskkill /F, Stop-Process -Force), `LaForgeTrusted` n'ayant AUCUN
    privilege Windows. Or c'est le HUB qui cree les jobs : l'arret appartient a
    l'ancetre, pas au demandeur.

CE QUE LA ROUTE FAIT
    POST /admin/job/{job_id}/stop   body {"kill": bool, "force": bool}
      - `kill` absent ou faux -> DRY-RUN : rend le pid et l'arbre, n'arrete rien.
        Un arret est irreversible, il se demande explicitement.
      - arrete l'ARBRE (enfants puis parent) : le pid enregistre est celui du WRAPPER,
        pas du worker (gotcha 2026-07-25), donc tuer le seul parent laisserait le
        travail continuer sous un chef mort.
      - rend le verdict PAR PID (arrete / tue force / deja mort / ACCES REFUSE) et un
        code 409 si quelque chose n'a pas pu etre arrete : jamais un `ok` global qui
        masquerait un refus de droits.

POURQUOI UN SCRIPT
    `tools/nokido_hub.py` est CRITICAL_FILE : `governed_edit` le refuse. Chemin prevu :
    script COMMITTE puis lance en `trusted_script`. Idempotent, verifie ses ancres et
    l'AST, et n'ecrit RIEN s'il doute.
"""

from __future__ import annotations

__FORGE_COLOR__ = "locomoteur-orchestration"

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "tools" / "nokido_hub.py"

ANCRE_HANDLER = "    async def admin_job_status(request):"
HANDLER = '''    async def admin_job_stop(request):
        """Arrete un job detache. Le hub est leur ANCETRE, lui seul y arrive.

        BLOCKER ouvert le 2026-07-25 : aucun compte client ne peut arreter un
        processus qu'il a fait naitre (4 formes refusees, LaForgeTrusted n'ayant aucun
        privilege Windows). Le hub a CREE le job -> l'arret appartient ici.
        `kill` faux par defaut : un arret est irreversible, il se demande.
        """
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        job_id = str(request.path_params.get("job_id", ""))
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            import sys as _s

            _tools = str(ROOT / "tools")
            if _tools not in _s.path:
                _s.path.insert(0, _tools)
            from forge_job_stop import stop_job
        except Exception as e:
            return JSONResponse(
                {"ok": False, "error": f"forge_job_stop indisponible: {str(e)[:140]}"},
                status_code=500,
            )
        res = stop_job(
            job_id,
            kill=bool(body.get("kill", False)),
            force=bool(body.get("force", False)),
        )
        logger.info(
            "admin_job_stop %s kill=%s -> ok=%s", job_id, body.get("kill"), res.get("ok")
        )
        # 409 quand un pid a resiste : le code HTTP doit dire la verite, pas rassurer.
        _code = 200 if (res.get("ok") or res.get("dry_run")) else 409
        return JSONResponse(res, status_code=_code)

'''

ANCRE_ROUTE = '        Route("/admin/job/{job_id}", admin_job_status, methods=["GET"]),'
ROUTE = (ANCRE_ROUTE + "\n"
         '        Route("/admin/job/{job_id}/stop", admin_job_stop, methods=["POST"]),')


def main() -> int:
    if not CIBLE.exists():
        print(f"[patch] cible absente: {CIBLE}")
        return 1
    src = CIBLE.read_text(encoding="utf-8")
    if "admin_job_stop" in src:
        print("[patch] deja applique — rien a faire (idempotent)")
        return 0
    if ANCRE_HANDLER not in src:
        print("[patch] ANCRE HANDLER introuvable — ABANDON, rien n'est ecrit")
        return 2
    if ANCRE_ROUTE not in src:
        print("[patch] ANCRE ROUTE introuvable — ABANDON, rien n'est ecrit")
        return 2
    out = src.replace(ANCRE_HANDLER, HANDLER + ANCRE_HANDLER, 1)
    out = out.replace(ANCRE_ROUTE, ROUTE, 1)
    try:
        ast.parse(out, filename=str(CIBLE))
    except SyntaxError as e:
        print(f"[patch] AST CASSE apres patch ({e}) — ABANDON, rien n'est ecrit")
        return 3
    CIBLE.write_text(out, encoding="utf-8")
    print(f"[patch] applique: +{len(out) - len(src)} octets, AST OK")
    print("[patch] route: POST /admin/job/{job_id}/stop  body {\"kill\": true}")
    print("[patch] BLOCKER du 25-07 ferme : l'arret d'un job appartient au hub,")
    print("        qui l'a cree, et non au compte client qui l'a demande.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
