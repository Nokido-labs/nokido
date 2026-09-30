# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/budget-requetes"
PATCH : la porte non gardee du meme danger, et l'effecteur jamais arme.

CE QUI EST TOMBE, ET POURQUOI
=============================
Le 2026-09-03 le hub est mort sur `query action=schema table=rag_fts`. Journal :
`[loop-lag] event loop bloque 19760 ms` puis `19948 ms`. Cause exacte, lue dans le
code et non deduite : la branche `schema` fait `SELECT COUNT(*)` sur CHAQUE table
de la base — dont `rag_fts` et `rag_chunks` sur `embeddings.db` (22,8 Go, ~2 M
lignes). C'est le balayage meme que le garde de la voie `sql=` REFUSE, en citant
« un GROUP BY sur rag_chunks a fait tomber le hub deux fois le 2026-08-23 ».

Le garde etait bon ; sa PORTEE etait fausse. Il est pose apres le `return` de la
branche schema, donc `action=schema` empruntait la porte non gardee du meme
danger. Meme famille que le gate lifecycle qui testait `act == "stop"` alors qu'un
restart contient l'arret qu'il refuse.

TROIS VOLETS
============
1. BUDGET SUR `schema` : meme `set_progress_handler` que la voie `sql=`. Il abandonne
   la requete DANS la VM SQLite, quel que soit le plan choisi — plus fiable qu'un
   `interrupt()` depuis un autre thread, et deja eprouve ici.
2. FIN DES `COUNT(*)` NON BORNES : `MAX(rowid)` est instantane (index) la ou
   `COUNT(*)` balaye. La sortie CHANGE de sens, donc elle le DIT : la cle devient
   `rows_max_rowid` avec une note. Une borne annoncee vaut mieux qu'un compte exact
   qui tue le service — et un compte qu'on ne peut pas obtenir n'est pas un compte.
3. WATCHDOG ARME : `forge_loop_sentinel.start_kill_watchdog` existe, avec son thread
   OS et sa grace suspend/resume, et n'etait appele NULLE PART — le hub n'importait
   que `start`, l'observateur. Un capteur sans effecteur explique les WARNING a
   19 760 ms. Seuil a 15 s (le defaut de 60 s n'aurait pas tire sur ce gel).

Harnais REUTILISE : `forge_patch_muted_paths.campagne()`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_patch_muted_paths import appliquer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "app" / "forge_mcp_registry.py"
HUB = ROOT / "tools" / "nokido_hub.py"

SENT_REG = "budget schema (porte non gardee du 2026-09-03)"
BLOCS_REGISTRY = [
    (r'''            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
                if not _tbl:
                    tbls = {}
                    for _n in names:
                        try:
                            tbls[_n] = conn.execute(f'SELECT COUNT(*) FROM "{_n}"').fetchone()[0]
                        except Exception:
                            tbls[_n] = None
                    conn.close()
                    return json.dumps({"db": str(db_path), "tables": tbls}, indent=2, ensure_ascii=False)''',

     r'''            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
                # budget schema (porte non gardee du 2026-09-03) : `timeout=10` est
                # un delai d'attente de VERROU, pas une borne sur le travail du
                # moteur. Sans progress handler, un COUNT sur une table de 22 Go
                # gele l'event loop du hub — mesure : 19 760 ms, puis la chute.
                _budget_s = float(os.environ.get("LAFORGE_QUERY_BUDGET_S", "20"))
                _echeance = time.monotonic() + _budget_s
                conn.set_progress_handler(
                    lambda: 1 if time.monotonic() > _echeance else 0, 20000)
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
                if not _tbl:
                    tbls = {}
                    for _n in names:
                        # MAX(rowid) : instantane (index) la ou COUNT(*) BALAYE. La
                        # valeur change de sens — c'est une BORNE SUPERIEURE, les
                        # suppressions ne rendent pas leur rowid — donc la sortie le
                        # dit au lieu de laisser croire a un compte exact.
                        try:
                            _v = conn.execute(f'SELECT MAX(rowid) FROM "{_n}"').fetchone()[0]
                            tbls[_n] = int(_v) if _v is not None else 0
                        except Exception:
                            tbls[_n] = None   # illisible : PAS zero
                    conn.close()
                    return json.dumps({"db": str(db_path), "tables": tbls,
                                       "note": "valeurs = MAX(rowid), BORNE SUPERIEURE "
                                               "et non COUNT(*) : un balayage sur une "
                                               "grosse table gele le hub (2026-09-03). "
                                               "null = table non comptable ou illisible."},
                                      indent=2, ensure_ascii=False)'''),

    (r'''                n_rows = conn.execute(f'SELECT COUNT(*) FROM "{_tbl}"').fetchone()[0]''',
     r'''                # idem : borne, pas compte — voir la note renvoyee au client.
                _mx = conn.execute(f'SELECT MAX(rowid) FROM "{_tbl}"').fetchone()[0]
                n_rows = int(_mx) if _mx is not None else 0'''),

    (r'''                return json.dumps({"db": str(db_path), "table": _tbl, "rows": n_rows,
                                   "columns": cols, "sample": sample},
                                  indent=2, ensure_ascii=False, default=str)''',
     r'''                return json.dumps({"db": str(db_path), "table": _tbl,
                                   "rows_max_rowid": n_rows,
                                   "note": "rows_max_rowid = BORNE SUPERIEURE "
                                           "(MAX(rowid)), pas un COUNT(*)",
                                   "columns": cols, "sample": sample},
                                  indent=2, ensure_ascii=False, default=str)'''),
]

SENT_HUB = "start_kill_watchdog"
BLOCS_HUB = [
    (r'''        from forge_loop_sentinel import start as _loop_sentinel_start''',
     r'''        from forge_loop_sentinel import start as _loop_sentinel_start
        from forge_loop_sentinel import start_kill_watchdog as _loop_kill_start'''),
    (r'''        _loop_sentinel_start(threshold_ms=300)''',
     r'''        _loop_sentinel_start(threshold_ms=300)
        # EFFECTEUR, enfin arme. `start_kill_watchdog` existait — thread OS dedie,
        # grace suspend/resume, opt-out LAFORGE_LOOP_KILL_S=0 — et n'etait appele
        # NULLE PART : le hub n'importait que l'observateur. D'ou des WARNING a
        # 19 760 ms sans que rien n'agisse. Seuil a 15 s : le defaut de 60 s
        # n'aurait pas tire sur le gel du 2026-09-03. Un process supervise qu'on
        # tue proprement est respawne ; un hub gele emporte toutes les surfaces.
        _loop_kill_start(kill_after_s=float(os.environ.get("LAFORGE_LOOP_KILL_S", "15")))'''),
]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv
    rc = appliquer(REGISTRY, SENT_REG, BLOCS_REGISTRY, apply=apply,
                   suffixe="budget-schema")
    if rc != 0:
        return rc
    return appliquer(HUB, SENT_HUB, BLOCS_HUB, apply=apply, suffixe="loop-kill",
                     note_finale="Le hub doit etre REDEMARRE pour charger ce code.")


if __name__ == "__main__":
    sys.exit(main())
