# -*- coding: utf-8 -*-
"""NR -- un test qui lance le garde d'impulsion redirige AUSSI son journal hors du vrai sandbox.

Mesure du 18/10 (decision owner a venir : basculer le garde en mode refuser apres mesure du bruit) :
sandbox/workspace/gate_journal.jsonl portait 636 lignes dont 68 datees de 2027 (horloge simulee d'un test), 34 sur
la fixture `job_abc123` et 51 en mode `refuser` alors que le garde tourne en `observer`. Cause :
tests/nr/test_gate_rafale_et_polling_nr.py redirige l'etat, la horloge et les jobs, mais pas NOKIDO_GATE_JOURNAL --
chaque passage de la suite ecrit dans le journal REEL et fausse la mesure qui doit decider de la bascule.
Meme famille que les drapeaux *.wanted des NR (2ee65b530) : un instrument ne lit pas ses propres tests.

Contrat (lecture statique) : tout test qui lance tools/hook_capability_gate.py en posant NOKIDO_GATE_ETAT pose
aussi NOKIDO_GATE_JOURNAL.
"""
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def test_chaque_test_du_garde_redirige_son_journal():
    fautifs = []
    for p in sorted((RACINE / "tests").rglob("*.py")):
        if p.name == Path(__file__).name:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        if "hook_capability_gate" in t and "NOKIDO_GATE_ETAT" in t and "NOKIDO_GATE_JOURNAL" not in t:
            fautifs.append(str(p.relative_to(RACINE)))
    assert not fautifs, fautifs
