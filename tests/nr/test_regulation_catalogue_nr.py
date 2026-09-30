"""NR — le catalogue de regulation ne doit jamais survivre a son code.

Le 2026-08-14, `tools/forge_regulation_loops.py` declarait encore
`Loop(name="docker.release", source="tools/forge_docker_keeper.py")` six
semaines apres que `3aec1500` en eut supprime l'implementation. Rien n'a
signale le trou : un catalogue orphelin ne se tait pas, il RASSURE. Toute
inspection de la regulation y lisait que Docker se relachait.

Ce test est le seul endroit ou la promesse de `Loop` — « chaque valeur vient
d'une CONSTANTE du code cite par `source` » — devient opposable.

Il echoue de deux facons, volontairement distinctes :
  * une Loop dont le fichier source a disparu ;
  * une Loop dont le symbole cite est absent de ce fichier.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_chaque_loop_a_une_implementation():
    """Aucune Loop ne doit citer une source sans preuve dedans."""
    from forge_regulation_loops import verifier_implementations

    anomalies = verifier_implementations()
    detail = "\n".join(
        f"  - {a['loop']} -> {a['source']} : {a['defaut']}"
        + (f" (cherche '{a['cherche']}')" if a.get("cherche") else "")
        for a in anomalies
    )
    assert not anomalies, (
        f"{len(anomalies)} boucle(s) declaree(s) sans code derriere :\n{detail}\n"
        "Soit l'implementation a ete supprimee (regression), soit la source ne "
        "cite pas le bon symbole (convention : 'chemin.py:SYMBOLE')."
    )


def test_le_garde_detecte_vraiment_une_source_absente(tmp_path):
    """Un garde qui ne peut pas echouer ne garde rien.

    On lui donne une racine vide : tous les fichiers cites y sont absents, donc
    il DOIT crier. Sans cette contre-epreuve, un `verifier_implementations` qui
    renverrait `[]` par accident (boucle jamais entree, exception avalee)
    passerait pour sain — exactement le faux-vert que ce module combat.
    """
    from forge_regulation_loops import LOOPS, verifier_implementations

    anomalies = verifier_implementations(racine=tmp_path)
    assert anomalies, "le garde n'a rien signale sur une racine vide"
    assert all(a["defaut"] == "SOURCE_ABSENTE" for a in anomalies)
    # Chaque boucle citant au moins un .py doit etre remontee.
    attendues = {b.name for b in LOOPS if ".py" in b.source}
    assert {a["loop"] for a in anomalies} == attendues


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
