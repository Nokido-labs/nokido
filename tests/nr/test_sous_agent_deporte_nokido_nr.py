# -*- coding: utf-8 -*-
"""NR — un sous-agent se déporte en JOB DÉTACHÉ Nokido, jamais en sous-agent Claude.

__FORGE_COLOR__ = "immunitaire/guard : non-regression du deport des sous-agents"

RÈGLE OWNER DU 2026-09-06, sans exception : « systématiquement les sous-agents doivent
être détachés dans Nokido ». Un sous-agent Claude facture un modèle pour un travail que le
corps sait faire seul (`run action=run_job`), et rend une réponse à interpréter là où un
job rend un fichier -- le `.rc`.

CE QUI A ETE PAYE LE JOUR MEME. Le gate ne captait QUE les sous-types de recon (`explore`,
`general-purpose`, `plan`) et laissait passer « les sous-agents specialises ». Un
`Agent(subagent_type="general-purpose")` lance pour une simple attente de CI suivie d'un
push a ete refuse ; relance en `subagent_type="claude"`, il est PASSE. Meme travail, meme
cout cloud, etiquette differente.

**Un garde qu'on franchit en renommant son intention ne garde rien.** C'est tout l'objet
de ce fichier : verifier qu'AUCUN sous-type, connu ou invente, ne rouvre l'echappatoire.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

GATE = ROOT / "tools" / "forge_tool_gate.py"


def _decider(sous_type):
    import forge_tool_gate as g

    args = {"subagent_type": sous_type} if sous_type is not None else {}
    return g.decide("claude_code", "CLAUDE", "Agent", args)


@pytest.mark.parametrize("sous_type", [
    "general-purpose",   # capté par l'ancienne règle
    "explore", "plan",   # idem
    "claude",            # L'ÉCHAPPATOIRE EMPRUNTÉE le 2026-09-06
    "claude-code-guide", "statusline-setup",
    "un-type-invente-demain",   # un nom neuf ne doit pas rouvrir la porte
    "", None,                    # défaut / absent
])
def test_aucun_sous_type_ne_passe_en_natif(sous_type):
    """La liste blanche a ete supprimee : il n'y a plus de sous-type « non-recon »."""
    d = _decider(sous_type)
    assert d.get("action") != "native", (
        f"sous_type={sous_type!r} repasse en natif -- l'echappatoire est rouverte : {d}")
    assert d.get("action") == "block", d
    assert d.get("enforce") == "hard", "un refus mou se contourne par insistance"


def test_le_refus_dit_QUOI_FAIRE_a_la_place():
    """Un refus qui n'indique pas la forme correcte se fait contourner, pas respecter."""
    raison = str(_decider("claude").get("reason", ""))
    assert "run_job" in raison, "le refus doit nommer le mecanisme de remplacement"
    assert "forge_job_watch_notify" in raison, (
        "il doit aussi dire comment etre NOTIFIE, sinon on retombe sur du polling manuel")


def test_la_cible_du_deport_est_le_hub():
    d = _decider("claude")
    assert "run_job" in str(d.get("target") or ""), d


def test_la_regle_reste_ecrite_dans_le_code():
    """Une regle sans sa raison se fait supprimer par le prochain agent qu'elle gene."""
    src = GATE.read_text(encoding="utf-8")
    assert "2026-09-06" in src, "la date de la decision owner doit rester citee"
    assert "renommant son intention" in src, (
        "le motif de l'echappatoire doit rester ecrit, c'est lui qui justifie la severite")


def test_la_regle_est_aussi_dans_le_socle_partage():
    """RULES_SHARED est lu par TOUS les clients, y compris ceux sans hooks."""
    socle = (ROOT / "RULES_SHARED.md").read_text(encoding="utf-8", errors="replace")
    assert "JAMAIS un sous-agent Claude" in socle
    assert "run_job" in socle
