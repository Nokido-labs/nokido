# -*- coding: utf-8 -*-
"""Patcheur one-shot : l'accuse M2M n'ecrase plus la reponse complete d'une tache.

DEFAUT MESURE (2026-07-26)
--------------------------
`tools/forge_task_executor.py` ecrit d'abord la reponse complete de l'agent dans
`tasks.result` (jusqu'a 8000 chars) via `_mark_done`, PUIS emet son accuse M2M
(`task action=result`) dont le champ `detail` est volontairement court -- le
protocole impose des champs courts, le detail allant au tableau noir.

Le handler du registre (`app/forge_mcp_registry.py`, ~L5081) faisait :

    UPDATE tasks SET status='done', result=?, ...      -- result = l'ACCUSE

c'est-a-dire qu'il ecrasait la REPONSE par l'ACCUSE. Mesure : un avis de 1555
caracteres reduit a 313, coupe en pleine phrase ("### 1. MOTIVATION DU VERDICT
& PREUVES EX"). L'avis n'a survecu que dans le postal (`mail`), d'ou il a fallu
le repecher a la main.

L'enveloppe M2M est un ACCUSE DE RECEPTION : elle part de toute facon a
l'emetteur (notification) et dans `agent_messages`. Elle n'a pas a remplacer le
livrable. Correctif : on conserve le contenu le plus substantiel.

Ce fichier est un patcheur ONE-SHOT parce que `forge_mcp_registry.py` est
CRITICAL_FILE : `governed_edit` le refuse (garde legitime), et le chemin prevu
est un script REVU puis lance en compte privilegie. Idempotent : relance = no-op.

Le changement ne prend effet qu'au PROCHAIN demarrage du hub -- aucun restart
n'est declenche ici.
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

AVANT = """        conn = self._task_db()
        row = conn.execute("SELECT job_id,from_agent,description FROM tasks WHERE id=?", (tid,)).fetchone()
        conn.execute("UPDATE tasks SET status='done',result=?,updated_at=? WHERE id=?", (result_text, now, tid))
"""

APRES = '''        conn = self._task_db()
        row = conn.execute(
            "SELECT job_id,from_agent,description,result FROM tasks WHERE id=?", (tid,)
        ).fetchone()
        # NE PAS ECRASER UN RESULTAT PLUS RICHE PAR L'ENVELOPPE M2M.
        # Mesure 2026-07-26 : l'executor ecrit d'abord la reponse complete de
        # l'agent (jusqu'a 8000 chars), PUIS emet son accuse M2M -- dont le champ
        # `detail` est volontairement court (180 chars). Cet UPDATE ecrasait la
        # reponse par l'accuse : 1555 caracteres d'avis reduits a 313, coupes en
        # pleine phrase, recuperables seulement dans le postal.
        # L'enveloppe est un ACCUSE DE RECEPTION, pas le livrable : elle part de
        # toute facon a l'emetteur (notification plus bas) et dans agent_messages.
        _prev = (row[3] if row and len(row) > 3 else "") or ""
        _keep = result_text if len(result_text or "") >= len(_prev) else _prev
        conn.execute("UPDATE tasks SET status='done',result=?,updated_at=? WHERE id=?", (_keep, now, tid))
'''


def main() -> int:
    if not CIBLE.exists():
        print("CIBLE ABSENTE: %s" % CIBLE)
        return 2
    src = CIBLE.read_text(encoding="utf-8")

    if "_keep = result_text if len(result_text" in src:
        print("DEJA APPLIQUE - no-op")
        return 0
    if src.count(AVANT) != 1:
        # Fail-loud : ne jamais patcher a l'aveugle un fichier critique.
        print("MOTIF INTROUVABLE OU AMBIGU (occurrences=%d) - AUCUNE ECRITURE"
              % src.count(AVANT))
        return 3

    neuf = src.replace(AVANT, APRES, 1)
    try:
        ast.parse(neuf)
    except SyntaxError as exc:
        print("AST KO apres patch (%s) - AUCUNE ECRITURE" % exc)
        return 4

    sauvegarde = CIBLE.with_suffix(".py.bak_clobber")
    sauvegarde.write_text(src, encoding="utf-8")
    CIBLE.write_text(neuf, encoding="utf-8")
    print("PATCH APPLIQUE : %s (sauvegarde %s)" % (CIBLE.name, sauvegarde.name))
    print("Effet au PROCHAIN demarrage du hub ; aucun restart declenche ici.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
