"""tools/forge_veille_rejeu.py — rejoue les veilles qui n'ont RIEN rapatrie.

P0 roadmap. Perimetre etabli par la mesure du 31-07, et volontairement ETROIT :
sur les 32 veilles a n_stored=0, VINGT-CINQ portent deja 1116 chunks dans
rag_chunks — les rejouer ne rendrait rien. Seules les SEPT qui n'ont rien
rapatrie du tout (n_ingested=0 ET n_stored=0) sont de vrais trous.

Pourquoi ce script existe alors que la delegation etait censee le faire : la
tache confiee a l'agent autonome a ete marquee `done` en moins de 20 s sur un
accuse de reception (« Consignes bien recues »), sans qu'aucune veille ne bouge.
Un resultat sans effet mesurable ne vaut pas execution — on refait le travail
ici, et on VERIFIE l'effet apres coup au lieu de croire un statut.

Le rejeu passe par forge_watch_agent.create_job (chemin existant, jamais
reimplemente) puis laisse la chaine faire son travail. Le rapport final relit
watch_jobs et compare AVANT/APRES par veille.

Usage : run action=run_job script=tools/forge_veille_rejeu.py online=true
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/veille : rejoue les veilles qui n'ont rien rapatrie"  # organe declare le 2026-09-06 (audit de raccordement)

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Les 7 veilles sans aucun rapatriement (mesure 31-07).
CIBLES = [
    "wj_88e5d77124", "wj_b3e99bf1d0", "wj_ffa79e641c", "wj_93c31fd075",
    "wj_fe5f00dd0c", "wj_f00a86d6f8", "wj_ecf1a5196e",
]

# wj_88e5d77124 est une DERIVE SEMANTIQUE connue et documentee : le theme
# « crawlforge » a ramene du Minecraft Forge. Si elle rederive, c'est un defaut
# de REQUETE (terme de marque contenant un mot polysemique), pas une panne de
# retention — le rapport doit le dire au lieu de le compter comme un echec.
DERIVE_CONNUE = {"wj_88e5d77124": "terme de marque polysemique (crawlforge -> Minecraft Forge)"}


def _etat(conn, ids: list) -> dict:
    q = ",".join("?" * len(ids))
    return {r[0]: {"theme": r[1], "status": r[2], "n_ing": r[3] or 0, "n_sto": r[4] or 0}
            for r in conn.execute(
                f"SELECT id, theme, status, n_ingested, n_stored FROM watch_jobs "
                f"WHERE id IN ({q})", ids)}


def main() -> int:
    from nokido_agent.app.forge_db_path import db_path
    import sqlite3

    conn = sqlite3.connect(db_path(), timeout=60)
    avant = _etat(conn, CIBLES)
    print(f"[rejeu] {len(avant)} veilles ciblees", flush=True)

    try:
        from nokido_agent.app.forge_watch_agent import create_job
    except Exception as e:
        print(f"ARRET : forge_watch_agent.create_job indisponible ({type(e).__name__}: {e})")
        return 2

    lances = {}
    for wid, info in avant.items():
        theme = info["theme"]
        note = DERIVE_CONNUE.get(wid)
        if note:
            print(f"[rejeu] {wid} — derive connue : {note}", flush=True)
        try:
            res = create_job(theme=theme, idea_id=f"rejeu_{wid}", agent="CLAUDE_REJEU_P0")
            neuf = res.get("job_id") if isinstance(res, dict) else res
            lances[wid] = neuf
            print(f"[rejeu] {wid} -> nouveau job {neuf} | {theme[:70]}", flush=True)
        except Exception as e:
            # Un echec de LANCEMENT se dit : sans cela, une veille manquante dans le
            # rapport final serait indiscernable d'une veille qui n'a rien trouve.
            lances[wid] = None
            print(f"[rejeu] {wid} ECHEC DE LANCEMENT {type(e).__name__}: {str(e)[:120]}", flush=True)

    lances_ok = [v for v in lances.values() if v]
    print(f"[rejeu] {len(lances_ok)}/{len(CIBLES)} jobs lances — attente de la chaine", flush=True)

    # La chaine est asynchrone : on observe jusqu'a stabilisation, avec un plafond.
    # On ne conclut PAS d'une lecture unique (un job en cours rendrait 0 a tort).
    deadline = time.time() + 1800
    derniers = {}
    while time.time() < deadline and lances_ok:
        time.sleep(60)
        etat = _etat(conn, lances_ok)
        finis = [j for j, v in etat.items() if str(v["status"]).startswith(("completed", "done"))]
        print(f"[rejeu] {len(finis)}/{len(lances_ok)} termines", flush=True)
        derniers = etat
        if len(finis) == len(lances_ok):
            break

    print("\n=== RAPPORT PAR VEILLE (avant -> apres) ===", flush=True)
    rendu = 0
    for wid, neuf in lances.items():
        a = avant[wid]
        if not neuf:
            print(f"{wid} : NON RELANCEE (echec de lancement) | {a['theme'][:60]}")
            continue
        b = derniers.get(neuf) or _etat(conn, [neuf]).get(neuf) or {}
        ing, sto = b.get("n_ing", 0), b.get("n_sto", 0)
        rendu += ing
        note = f" [{DERIVE_CONNUE[wid]}]" if wid in DERIVE_CONNUE else ""
        print(f"{wid} -> {neuf} : status={b.get('status')} n_ingested={ing} "
              f"n_stored={sto}{note}")
        print(f"    (avant : {a['status']} ing={a['n_ing']} sto={a['n_sto']})")
    print(f"\nTOTAL chunks rapatries par le rejeu : {rendu}")
    print("Lecture : n_stored compte la table BIBLIOGRAPHIQUE, pas le RAG — "
          "un n_ingested>0 avec n_stored=0 signifie que le corpus est arrive "
          "mais n'a pas ete promu en biblio (defaut connu, seuil de pertinence).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
