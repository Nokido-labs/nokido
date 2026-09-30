"""forge_pluripotent_workers.py — Cellules souches logicielles différenciables.

Mapping bio↔code :
- Cellule souche      = PluripotentWorker (générique, ne sait rien de spécifique)
- Différenciation     = adopt_role(role) selon signaux endocriniens / queue
- Lignée cellulaire   = mode (ingest, watch, enrich, monitor)
- Apoptose            = self-terminate quand son rôle n'a plus de demande
- Microenvironnement  = signaux endocrines (TSH, LEPTIN, ADRENALINE, etc.)

PROBLÈME RÉEL ADRESSÉ
=====================
Aujourd'hui : 4 daemons fixes (biblio_worker, rss_watcher, skill_enricher,
hebbian_linker) avec leur boilerplate dupliqué (heartbeat, state, cycle, CLI).
Chaque nouveau besoin = nouveau module → duplication code + maintenance.

Cellule souche : 1 worker générique qui se différencie selon les signaux.
- Aucune demande TSH → reste en G0 (idle)
- TSH > 0.4 → différencie en "rag_warmer"
- LEPTIN > 0.5 → différencie en "mailbox_purger"
- HORMONE custom via release() → adopte rôle correspondant

ROLES INITIAUX (catalogue extensible)
======================================
- "rag_warmer"        : si TSH_VECTORIZATION > 0.4 → run forge_rag_warmup
- "mailbox_purger"    : si LEPTIN_MAILBOX_FULL > 0.5 → run forge_renal_clearance --apply
                                                       ciblé agent_messages
- "watch_refresher"   : si nouvelle entry biblio_raw queued → kick biblio_worker run
- "antibody_curator"  : si > 5 nouveaux antibodies → archive + alert
- "G0_idle"           : aucun signal pertinent

Une seule instance peut adopter UN rôle à la fois. Pour multiples rôles
simultanés → spawn multiples PluripotentWorker.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"

DEFAULT_INTERVAL_S = int(os.environ.get("LAFORGE_PLURI_INTERVAL_S", "180"))


@dataclass
class Role:
    name: str
    trigger_hormone: str  # quelle hormone active ce rôle
    trigger_threshold: float  # niveau minimum
    half_life_role_s: int  # combien de temps reste différencié sans renouveau signal
    action: Callable[[], dict]  # fonction à exécuter


def _read_hormone(name: str) -> float:
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_endocrine import read as hormone_read

        return hormone_read(name)
    except Exception:
        return 0.0


def _observer_signal(signal: str) -> None:
    """CONSTATE la lecture d'une hormone par la differenciation.

    MESURE 2026-09-20 :

        TSH_VECTORIZATION      EMIS 1 (n=4 181)   LU 0   TRANSDUIT 0   valeur 0.843
        INSULIN_VECTORIZATION  EMIS 1 (n=33 273)  LU 1   TRANSDUIT 1   valeur 0.833

    Le seuil du role `rag_warmer` vaut 0.1 : le corps emettait donc une demande
    huit fois au-dessus du seuil, et rien ne permettait de savoir si quelqu'un la
    lisait. L'unique lecture d'INSULIN, elle, datait de 52,6 JOURS (trophisme 0.0)
    par un recepteur -- `forge_rag_warmup.warmup_rag` -- dont le lien a ete retire
    d'ici le 2026-07-05, pour un motif JUSTE (il figeait le tick ~90 s sans
    vectoriser). Le recepteur reel est desormais cette differenciation.

    Sans cette declaration, « personne ne lit » et « le worker n'a pas tourne »
    sont indistinguables -- et accuser le premier est le faux positif qui fait
    desarmer un garde.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_signal_coupling import observe_signal as _obs

        _obs(signal, consumer="forge_pluripotent_workers.perceive_environment")
    except Exception:  # noqa: BLE001 - muet-ok : un capteur de couplage ne doit
        pass          # JAMAIS casser la regulation qu'il observe.


def _transduire_signal(signal: str) -> None:
    """CONSTATE l'EFFET, au site de l'effet -- seule preuve qu'une voie transduit.

    Patron copie de `forge_rag_warmup.warmup_rag` (eprouve sur TSH/INSULIN depuis
    le 2026-08-05) et deja repris dans `forge_llama_keeper._piliers_on_demand` :
    `_observer` au site de la LECTURE, `_transduire` au site de l'EFFET. On ne
    l'appelle QUE sur une action REUSSIE -- une action en echec ou un maintien en
    G0 ne sont pas des effets, et les compter ferait declarer COUPLEE une voie qui
    n'agit jamais (`attempt != success`).
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_signal_coupling import transduce_signal as _tr

        _tr(signal, consumer="forge_pluripotent_workers.differentiate")
    except Exception:  # noqa: BLE001 - muet-ok, meme raison
        pass


# ============================================================================
# ACTIONS (ce que fait chaque rôle quand activé)
# ============================================================================


def _action_rag_warmer() -> dict:
    """Hépatocyte vectorisateur : draine un lot BORNÉ du backlog embed NULL via :8099
    (forge_embed_backfill_cool, repointé du brain_worker :5557 mort) = fait BAISSER
    TSH_VECTORIZATION à chaque tick. C'est le métabolisme autonome CONTINU du corps
    (le bulk 645k = run_job séparé one-shot). 2026-07-05 : ex-appel warmup_rag/
    index_app_dir (indexation code sur DB 38G) RETIRÉ d'ici — il figeait le tick ~90s
    ET n'embarquait rien (embedding=NULL, pas de vectorisation) ; l'indexation du code
    reste couverte par le hook POST_COMMIT + le warmup au boot. Borné à 300 pour rester
    sous le timeout de tick (_safe_call 90s)."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_embed_backfill_cool import backfill  # type: ignore

        res = backfill(limit=300, batch_size=32, sleep_between=0.0, cpu_max=92, ram_max=90)
        return {
            "role": "rag_warmer",
            "ok": True,
            "embed_drained": res.get("success", 0),
            "processed": res.get("processed", 0),
        }
    except Exception as e:
        return {"role": "rag_warmer", "ok": False, "err": f"{type(e).__name__}: {e}"}


def _action_mailbox_purger() -> dict:
    """Différencié en cellule rénale : purge ciblée agent_messages anciens lus."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_renal_clearance import filter_table, FiltrationRule, _conn

        rule = FiltrationRule(
            table="agent_messages",
            age_column="created_at",
            max_age_days=30,
            protect_where="status = 'unread'",
        )
        conn = _conn()
        from nokido_agent.app.forge_renal_clearance import _ensure_schema  # type: ignore

        # _ensure_schema is renal-specific, on skip
        from dataclasses import asdict

        result = filter_table(conn, rule, dry_run=False)
        conn.close()
        return {"role": "mailbox_purger", "ok": True, "result": asdict(result)}
    except Exception as e:
        return {"role": "mailbox_purger", "ok": False, "err": f"{type(e).__name__}: {e}"}


def _action_watch_refresher() -> dict:
    """Différencié en macrophage de surveillance : kick biblio_worker."""
    # Plutôt que invoke direct, on touche un fichier signal que biblio_worker peut lire
    sig = SANDBOX / "kick_biblio_worker.signal"
    SANDBOX.mkdir(parents=True, exist_ok=True)
    sig.write_text(datetime.now().isoformat(), encoding="utf-8")
    return {"role": "watch_refresher", "ok": True, "signal_file": str(sig)}


def _action_antibody_curator() -> dict:
    """Différencié en cellule plasmatique : archive antibodies stables."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_immune_adaptive import _conn as imm_conn, _ensure_schema

        conn = imm_conn()
        _ensure_schema(conn)
        # Archive : antibodies non vus depuis 60j et count >= 3 → mark "archived" en kind
        n = conn.execute(
            "UPDATE immune_antibodies SET kind = kind || ':archived' "
            "WHERE last_seen < datetime('now', '-60 days') AND count >= 3 "
            "AND kind NOT LIKE '%:archived'"
        ).rowcount
        conn.commit()
        conn.close()
        return {"role": "antibody_curator", "ok": True, "archived": n}
    except Exception as e:
        return {"role": "antibody_curator", "ok": False, "err": f"{type(e).__name__}: {e}"}


# ============================================================================
# CATALOGUE DES RÔLES
# ============================================================================

ROLE_CATALOG: list[Role] = [
    Role(
        name="rag_warmer",
        trigger_hormone="TSH_VECTORIZATION",
        trigger_threshold=0.1,
        half_life_role_s=3600,
        action=_action_rag_warmer,
    ),
    Role(
        name="mailbox_purger",
        trigger_hormone="LEPTIN_MAILBOX_FULL",
        trigger_threshold=0.5,
        half_life_role_s=3600,
        action=_action_mailbox_purger,
    ),
    Role(
        name="watch_refresher",
        trigger_hormone="DOPAMINE_SUCCESS",
        trigger_threshold=0.3,
        half_life_role_s=1800,
        action=_action_watch_refresher,
    ),
    Role(
        name="antibody_curator",
        trigger_hormone="CORTISOL_QUOTA_CLOUD",
        trigger_threshold=0.5,
        half_life_role_s=7200,
        action=_action_antibody_curator,
    ),
]


@dataclass
class PluripotentWorker:
    name: str = "stem_worker_0"
    current_role: str = "G0_idle"
    differentiated_at: str = ""
    actions_taken: list[dict] = field(default_factory=list)

    def perceive_environment(self) -> Role | None:
        """Lit les hormones et choisit le rôle avec le plus fort signal au-dessus du seuil."""
        candidates = []
        for role in ROLE_CATALOG:
            level = _read_hormone(role.trigger_hormone)
            # DECLARER TOUTE hormone CONSULTEE, pas seulement celle qui gagne :
            # une hormone lue puis ecartee a bien ete LUE. Ne declarer que la
            # gagnante ferait passer pour « jamais lues » les trois autres.
            try:
                _observer_signal(role.trigger_hormone)
            except Exception:  # noqa: BLE001 - l'instrumentation ne casse jamais
                pass           # la differenciation qu'elle observe.
            if level >= role.trigger_threshold:
                candidates.append((level, role))
        if not candidates:
            return None
        # Prend le plus fort
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]

    def differentiate(self, role: Role) -> dict:
        self.current_role = role.name
        self.differentiated_at = datetime.now().isoformat()
        result = role.action()
        # SEUL chemin qui a REELLEMENT agi. Une action en echec n'est pas un effet :
        # c'est la meme regle que `ok=False` cote keeper, et elle evite de declarer
        # COUPLEE une hormone dont la voie ne produit rien.
        if isinstance(result, dict) and result.get("ok"):
            try:
                _transduire_signal(role.trigger_hormone)
            except Exception:  # noqa: BLE001 - idem : jamais casser l'action
                pass
        self.actions_taken.append(
            {
                "ts": datetime.now().isoformat(),
                "role": role.name,
                "trigger": role.trigger_hormone,
                "result": result,
            }
        )
        # Cap historique
        self.actions_taken = self.actions_taken[-50:]
        return result

    def cycle(self) -> dict:
        role = self.perceive_environment()
        if role is None:
            self.current_role = "G0_idle"
            return {"role": "G0_idle", "action": None, "ts": datetime.now().isoformat()}
        return self.differentiate(role)


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido pluripotent workers")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--name", default="stem_worker_0")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    args = ap.parse_args()

    if not args.once and not args.daemon:
        ap.error("--once ou --daemon requis")

    worker = PluripotentWorker(name=args.name)

    while True:
        out = worker.cycle()
        print(
            f"[pluri:{worker.name}] role={worker.current_role} action_ok="
            f"{(out.get('result') or out).get('ok', '—') if isinstance(out, dict) else '—'}",
            flush=True,
        )
        if isinstance(out, dict) and out.get("err"):
            print(f"  err: {out['err']}", flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
