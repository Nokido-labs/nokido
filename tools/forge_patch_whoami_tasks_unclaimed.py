# -*- coding: utf-8 -*-
"""Patcheur one-shot : whoami signale les taches DEPOSEES mais jamais RECLAMEES.

DEFAUT MESURE (2026-07-26)
--------------------------
Une tache adressee a un CLI interactif lui est RESERVEE : l'executor autonome
l'exclut volontairement (`_INTERACTIVE_CLIS` dans forge_task_executor), et elle
attend d'etre reclamee par la surface visee. Si cette surface ne tourne pas, la
tache dort **sans que rien ne le signale**.

Mesure : 16 taches ANTIGRAVITY en attente, decouvertes par l'owner, qui a du
faire traiter le lot a la main. Le RAG porte la meme plainte, deja qualifiee
d'« oubli recurrent du drainage/poll de l'inbox d'ANTIGRAVITY » -- recurrente,
donc jamais instrumentee. La regle interne le disait pourtant : « deposer une
tache => verifier que le drain tourne, sinon elle reste pending sans que
personne ne le signale ». Cette verification reposait sur l'humain.

C'est EXACTEMENT l'angle mort que le point 7 du meme digest corrige pour
l'infra : « sinon whoami reste aveugle a une infra cassee tant qu'aucun
job/chain n'est en file ». Le digest voyait les jobs et les chains, pas la FILE.

`forge_mcp_registry.py` est CRITICAL_FILE : `governed_edit` le refuse (garde
legitime), le chemin prevu est un script REVU puis lance en compte privilegie.
Idempotent : relance = no-op. Effet au PROCHAIN demarrage du hub ; aucun restart
n'est declenche ici.
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

AVANT = """            _health_actions = whoami_health_actions(_degraded)

            out = {
"""

APRES = '''            _health_actions = whoami_health_actions(_degraded)

            # 8. Taches DEPOSEES mais jamais RECLAMEES (2026-07-26). Une tache
            # adressee a un CLI interactif lui est RESERVEE : l'executor autonome
            # l'exclut volontairement (_INTERACTIVE_CLIS) et elle attend une
            # reclamation. Si la surface visee ne tourne pas, la tache dort sans
            # que RIEN ne le signale -- mesure : 16 taches ANTIGRAVITY decouvertes
            # par l'owner, traitees a la main. Meme angle mort que le point 7
            # ci-dessus, applique a la FILE et non plus a l'infra.
            _unclaimed = []
            try:
                import sqlite3 as _sq3

                _tdb = _P(__file__).resolve().parent.parent / "sandbox" / "tasks.db"
                _c8 = _sq3.connect("file:%s?mode=ro" % _tdb.as_posix(), uri=True, timeout=2.0)
                try:
                    _unclaimed = [
                        {"agent": _a, "n": _n, "plus_ancienne": _old}
                        for _a, _n, _old in _c8.execute(
                            "SELECT agent, COUNT(*), MIN(created_at) FROM tasks "
                            "WHERE status='pending' GROUP BY agent ORDER BY COUNT(*) DESC"
                        )
                    ]
                finally:
                    _c8.close()
            except Exception:
                _unclaimed = []
            for _u8 in _unclaimed:
                _health_actions = [{
                    "cmd": "task action=claim agent=%s  (ou reveiller sa surface)" % _u8["agent"],
                    "why": "%s tache(s) pending pour %s, la plus ancienne %s -- personne ne draine"
                           % (_u8["n"], _u8["agent"], _u8["plus_ancienne"]),
                }] + _health_actions

            out = {
'''

AVANT2 = '''                "biblio_unverified": [{"id": b["id"][:12], "title": b["title"][:60]} for b in _biblio],
'''

APRES2 = '''                "biblio_unverified": [{"id": b["id"][:12], "title": b["title"][:60]} for b in _biblio],
                "tasks_unclaimed": _unclaimed,
'''


def main() -> int:
    if not CIBLE.exists():
        print("CIBLE ABSENTE: %s" % CIBLE)
        return 2
    src = CIBLE.read_text(encoding="utf-8")

    if "tasks_unclaimed" in src:
        print("DEJA APPLIQUE - no-op")
        return 0
    for motif, nom in ((AVANT, "ancrage digest"), (AVANT2, "ancrage biblio")):
        if src.count(motif) != 1:
            print("MOTIF %s INTROUVABLE OU AMBIGU (occurrences=%d) - AUCUNE ECRITURE"
                  % (nom, src.count(motif)))
            return 3

    neuf = src.replace(AVANT, APRES, 1).replace(AVANT2, APRES2, 1)
    try:
        ast.parse(neuf)
    except SyntaxError as exc:
        print("AST KO apres patch (%s) - AUCUNE ECRITURE" % exc)
        return 4

    CIBLE.with_suffix(".py.bak_unclaimed").write_text(src, encoding="utf-8")
    CIBLE.write_text(neuf, encoding="utf-8")
    print("PATCH APPLIQUE : %s" % CIBLE.name)
    print("Effet au PROCHAIN demarrage du hub ; aucun restart declenche ici.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
