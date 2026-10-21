"""NR -- le daemon POST_COMMIT peut indexer les commits en RAG (2026-10-18, GO owner).

Mesure du 18/10 (logs/supervisor/NokidoMCP.log) : « GATE DENY tool=rag agent=POST_COMMIT: ring 4 <= requis 3 »,
299 refus le 15/10 (journal ouvert a 16:58), 955 le 16/10, 816 le 17/10 -- l'indexation des commits, qui donne aux
agents la conscience partagee de ce qui vient d'etre fait (RULES_SHARED : « le daemon POST_COMMIT indexe en RAG »),
etait refusee presque systematiquement. POST_COMMIT a deja SA propre identite (actor POST_COMMIT) : seul son ring
est en cause. Meme remede que RSS_WATCHER le 13/10 (owner, GO a) : ring 3 = le minimum pour indexer, SANS relever
SERVICES (qui ouvrirait l'ecriture au RAG a tout organe empruntant ce badge commun).
"""
from __future__ import annotations

import json
from pathlib import Path

REGISTRE = Path(__file__).resolve().parents[2] / "config" / "agent_identities.json"


def _identites() -> dict:
    def trouver(o):
        if isinstance(o, dict):
            if "SERVICES" in o and isinstance(o["SERVICES"], dict):
                return o
            for v in o.values():
                r = trouver(v)
                if r is not None:
                    return r
        return None

    return trouver(json.loads(REGISTRE.read_text(encoding="utf-8")))


def test_post_commit_au_ring_3_sans_relever_services():
    reg = _identites()
    assert reg["POST_COMMIT"]["ring"] == 3, "ring 4 : rag (requis 3) refuse l'indexation de chaque commit"
    assert reg["SERVICES"]["ring"] == 4, "relever SERVICES ouvrirait le RAG a tout organe qui l'emprunte"
