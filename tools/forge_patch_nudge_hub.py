# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "regulation/reveil-embedding"
PATCH : le reveil d'embedding du hub verifie qu'on l'ecoute.

`tools/nokido_hub.py` est CRITICAL_FILE — `governed_edit` le refuse, d'ou ce script
git-tracke lance en `trusted_script`. Il reutilise le harnais de
`forge_patch_muted_paths.appliquer()` : sentinelle d'idempotence, ancre devant
apparaitre EXACTEMENT une fois sinon abandon, `compile()` avant ecriture, sauvegarde
horodatee, relecture verifiee, dry-run par defaut.

LE DEFAUT (mesure 2026-08-05)
=============================
`_zmq_nudge` poussait un reveil fire-and-forget vers `:5557` apres chaque INSERT de
chunk. Ce port est FERME depuis juin. Et surtout — mesure, pas supposition — **un
PUSH ZMQ vers un port ferme est ACCEPTE sans exception** : le `except: pass` ne se
declenchait jamais, le hub croyait avoir reveille l'embedder, et les chunks inseres
restaient sans vecteur. C'est l'un des chemins qui a laisse s'accumuler 278 512
chunks non vectorises.

Le remede n'est pas de journaliser une erreur qui ne se produit pas : c'est de
verifier la presence d'un PAIR avant de croire au reveil. `forge_nudge_embed` le
fait, et rend un etat exploitable au lieu d'un silence.

    LAFORGE_PYTHON tools/forge_patch_nudge_hub.py            # dry-run
    LAFORGE_PYTHON tools/forge_patch_nudge_hub.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_patch_muted_paths import appliquer  # noqa: E402

CIBLE = ROOT / "tools" / "nokido_hub.py"
SENTINELLE = "forge_nudge_embed"

BLOCS = [
    (r'''    """Fire-and-forget PUSH to brain_worker:5557 — wake embed daemon after INSERT."""
    try:
        import msgpack as _mp
        import zmq as _zmq

        ctx = _zmq.Context.instance()
        s = ctx.socket(_zmq.PUSH)
        s.setsockopt(_zmq.LINGER, 0)
        s.connect("tcp://localhost:5557")
        try:
            from forge_trace_context import get_trace_id

            _tid = get_trace_id()
        except Exception:
            _tid = "system"
        s.send(_mp.packb({"cmd": "nudge", "n": n, "trace_id": _tid}, use_bin_type=True), _zmq.NOBLOCK)
        s.close()
    except Exception:
        pass''',
     r'''    """Reveille le daemon d'embedding apres INSERT — en VERIFIANT qu'on est ecoute.

    L'ancienne version poussait en fire-and-forget sur :5557. Mesure du 2026-08-05 :
    ce port est ferme depuis juin, et un PUSH ZMQ vers un port ferme est ACCEPTE sans
    exception — donc le `except: pass` ne se declenchait JAMAIS et le hub croyait
    avoir reveille l'embedder. Les chunks inseres restaient sans vecteur, en silence.
    """
    try:
        from forge_nudge_embed import nudge_embed

        _tid = "system"
        try:
            from forge_trace_context import get_trace_id

            _tid = get_trace_id()
        except Exception:  # muet-ok : sans trace_id on garde "system", pas de perte
            pass
        nudge_embed(n, source="nokido_hub",
                    payload={"cmd": "nudge", "n": n, "trace_id": _tid})
    except Exception as _e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.hub").warning(
            "[hub] reveil d'embedding impossible (%s: %s) | consequence: les chunks "
            "qui viennent d'etre inseres resteront sans vecteur jusqu'au prochain "
            "passage du drain", type(_e).__name__, str(_e)[:90])'''),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reveil d'embedding verifie, cote hub")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    return appliquer(CIBLE, SENTINELLE, BLOCS, a.apply, suffixe="nudge",
                     note_finale="Effet au prochain REDEMARRAGE du hub.")


if __name__ == "__main__":
    raise SystemExit(main())
