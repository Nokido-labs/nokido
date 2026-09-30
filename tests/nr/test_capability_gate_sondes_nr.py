# -*- coding: utf-8 -*-
"""NR — le gate de capacites attrape les sondes fausses SANS crier a faux.

Origine : 2026-08-30, dix erreurs du MEME motif en une journee — sonder la forme
qu'on IMAGINE au lieu de lire ce que le systeme DECLARE. A chaque fois la
declaration existait (services.toml, docker-compose, RULES_SHARED, un SKILL.md).
L'owner : « faut vraiment que tu fasses un point sur tes sondes ».

Une note ne suffit pas — c'est le constat du 29-30/07 : 485 memoires existaient et
l'enquete a quand meme ete refaite. Ce hook EXECUTE la lecon.

Ces tests tiennent les deux bouts. Un garde qui rate le piege ne sert a rien ; un
garde qui crie a faux se fait desarmer, et c'est la mort d'un garde — d'ou le
resserrage mesure de la regle `run_job`, qui produisait 1 faux positif sur 4 avant
correction le jour meme.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import hook_capability_gate as G  # noqa: E402

# Commandes ORDINAIRES : le gate doit rester MUET dessus.
LEGITIMES = [
    "git -c safe.directory=* status",
    "python -m pytest tests/nr/x.py -q",
    "Get-Content docs/ROADMAP.md",
    "run action=run_job script=tools/x.py lane=veille online=true",
    "SELECT source FROM rag_fts WHERE rag_fts MATCH 'openhands'",
]

# Pieges MESURES le 2026-08-30 : le gate doit parler.
PIEGES = [
    ("LIKE sur rag_chunks", "SELECT * FROM rag_chunks WHERE text LIKE '%openhands%'"),
    ("expanduser en job", "os.path.expanduser('~/miniforge3/python.exe')"),
    ("find_spec sur un service", "importlib.util.find_spec('crawl4ai')"),
    ("$args reserve PowerShell", "$args = @('a'); & $PY @args"),
    ("job sans lane", "run action=run_job script=tools/lourd.py online=true"),
]


def _touches(cmd: str) -> list:
    return [m for p, m in G._COMPILED if p.search(cmd)]


def test_aucune_commande_ordinaire_ne_declenche_le_gate():
    """Le critere de survie d'un garde : le silence sur le travail normal."""
    bruyantes = [c for c in LEGITIMES if _touches(c)]
    assert not bruyantes, "faux positifs (un garde qui crie a faux se fait desarmer) : %s" % bruyantes


def test_chaque_piege_mesure_est_attrape():
    rates = [nom for nom, cmd in PIEGES if not _touches(cmd)]
    assert not rates, "pieges non vus : %s" % rates


def test_un_job_avec_lane_passe_mais_sans_lane_declenche():
    """La regle large criait sur TOUS les jobs : 1 faux positif sur 4, corrige le jour meme."""
    assert not _touches("run action=run_job script=tools/x.py lane=veille")
    assert _touches("run action=run_job script=tools/x.py online=true")


def test_les_messages_nomment_la_FORME_QUI_MARCHE():
    """Un nudge qui dit seulement « c'est faux » n'apprend rien : il doit donner la sortie."""
    for nom, cmd in PIEGES:
        for msg in _touches(cmd):
            assert len(msg) > 80, "%s : message trop court pour etre utile" % nom
            assert any(k in msg for k in ("rag_fts", "services.toml", "lane", "$arguments",
                                          "docker-compose", "SKILL", "PRODUIT")), \
                "%s : le message ne nomme aucune forme correcte" % nom


def test_le_gate_reste_un_nudge_non_bloquant():
    """Il informe, il n'interdit pas : bloquer sur une heuristique paralyserait le travail."""
    texte = (ROOT / "tools" / "hook_capability_gate.py").read_text(encoding="utf-8",
                                                                  errors="replace")
    assert "nudge" in texte.lower()
