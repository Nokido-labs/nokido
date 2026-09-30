"""Patch CRITICAL_FILE : point d'observation d'autorisation sur :8766 (SHADOW).

__FORGE_COLOR__ = "immunitaire/maintenance-gouvernee"

Insere `_AuthzShadowMW` dans `tools/nokido_hub.py`. Le middleware OBSERVE et ne
refuse RIEN : il appelle le chemin d'identite EXISTANT (`_resolve_ring`), calcule
la decision qu'un enforcement rendrait, resout l'appelant quand ca compte, et
journalise. Toute la logique vit dans `app/forge_authz_shadow.py` -- le fichier
critique ne recoit que le branchement.

Ordre des middlewares : Starlette execute le DERNIER ajoute en PREMIER, donc
l'ajouter apres les autres le place le plus en amont, et il voit les requetes
avant le pressure-relief.

Usage :
    run action=trusted_script path=tools/forge_patch_authz_shadow.py
    run action=trusted_script path=tools/forge_patch_authz_shadow.py script_args="--apply"
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIBLE = ROOT / "app" / ".." / "tools" / "nokido_hub.py"
CIBLE = (ROOT / "tools" / "nokido_hub.py").resolve()

ANCRE = "    app.add_middleware(_PressureReliefMW)\n"

REMPLACEMENT = '''    app.add_middleware(_PressureReliefMW)

    # -- OBSERVATION D'AUTORISATION (SHADOW) -------------------------------
    # Mesure du 2026-09-02 : sur 81 routes declarees, 41 sondables en GET, dont
    # 32 repondent 200 SANS jeton (3 sensibles). `:8766` n'a aucun middleware
    # d'authentification -- l'identite n'est resolue que dans les handlers qui
    # pensent a le faire. Avant d'armer un refus, il faut savoir QUI appelle :
    # `/api/resource/should_spawn` est appelee par le superviseur lui-meme, et
    # la refuser a l'aveugle couperait la regulation du corps.
    #
    # Ce middleware ne refuse RIEN. Il reutilise `_resolve_ring` (donc le
    # CapabilityToken puis `forge_videur`) : aucun second systeme d'identite.
    class _AuthzShadowMW(BaseHTTPMiddleware):
        """Journalise la decision qu'un enforcement RENDRAIT. Ne bloque jamais."""

        echecs = 0          # un observateur muet qui se croit actif est pire que rien

        async def dispatch(self, request, call_next):
            try:
                import forge_authz_shadow as _az

                if _az.actif():
                    try:
                        _ring, _agent = _resolve_ring(request)
                    except Exception as _re:      # identite illisible != identite absente
                        _ring, _agent = -1, "resolve_error:%s" % type(_re).__name__
                    _auth = request.headers.get("Authorization", "")
                    # `via` ne recopie JAMAIS le jeton : seulement sa FORME.
                    _via = "bearer" if _auth.lower().startswith("bearer ") else (
                        "header_agent" if request.headers.get("LaForge-Agent-Name")
                        or request.headers.get("X-Agent-Name") else "anonyme")
                    _verdict = _az.decider(request.scope["path"], _ring, _agent, _via)
                    # Resolution PID seulement quand ca compte : `net_connections`
                    # coute cher, et une route servie sans question n'a rien a
                    # apprendre. Les DENY/UNKNOWN sont exactement les appelants
                    # qu'il faut nommer avant d'armer quoi que ce soit.
                    if _verdict["decision"] == "SHADOW_ALLOW":
                        _qui = {"pid": None, "process": None, "parent_pid": None,
                                "service": None,
                                "raison": "non resolu : decision ALLOW, PID inutile ici"}
                    else:
                        _qui = _az.resoudre_appelant(
                            request.client.port if request.client else None)
                    if not _az.observer(_az.trace_de(
                            request.scope["path"], request.method, _ring, _agent,
                            _via, _qui, verdict=_verdict)):
                        type(self).echecs += 1
            except Exception:  # muet-ok : une OBSERVATION ne casse jamais une requete ; `echecs` porte le compte
                type(self).echecs += 1
            return await call_next(request)

    app.add_middleware(_AuthzShadowMW)
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    a = ap.parse_args()

    if not CIBLE.exists():
        print("ABSENT : %s" % CIBLE)
        return 2
    src = CIBLE.read_text(encoding="utf-8")

    if "_AuthzShadowMW" in src:
        print("DEJA PATCHE. Rien a faire.")
        return 0

    n = src.count(ANCRE)
    if n != 1:
        print("ANCRE TROUVEE %d FOIS (attendu 1) -- refus d'ecrire." % n)
        return 3

    neuf = src.replace(ANCRE, REMPLACEMENT, 1)
    try:
        compile(neuf, str(CIBLE), "exec")
    except SyntaxError as e:
        print("AST INVALIDE apres patch (%s) -- refus d'ecrire." % e)
        return 4

    # Le middleware reference trois noms du module. S'ils manquent, l'erreur
    # n'apparaitrait qu'a la premiere requete, c'est-a-dire en production.
    for nom in ("BaseHTTPMiddleware", "def _resolve_ring"):
        if nom not in neuf:
            print("SYMBOLE MANQUANT dans le module : %r -- refus." % nom)
            return 6

    print("ancre unique OK | AST OK | symboles presents | delta = +%d octets"
          % (len(neuf) - len(src)))
    if not a.apply:
        print("DRY-RUN : rien ecrit. Relancer avec --apply.")
        return 0

    fd, tmp = tempfile.mkstemp(dir=str(CIBLE.parent), suffix=".patchtmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(neuf)
        os.replace(tmp, str(CIBLE))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:  # muet-ok : nettoyage best-effort, l'erreur reelle est relancee
            pass
        raise

    relu = CIBLE.read_text(encoding="utf-8")
    ok = "_AuthzShadowMW" in relu and len(relu) == len(neuf)
    print("ECRIT | relecture disque : %s" % ("identique" if ok else "DIVERGENTE"))
    print("SHADOW arme par defaut ; LAFORGE_AUTHZ_SHADOW=0 pour l'eteindre.")
    print("Effet au PROCHAIN redemarrage du hub.")
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
