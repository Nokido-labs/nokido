"""NR 31/10 (point 3, feu vert owner) -- la curation et la plasticite hebbienne entrent dans le sommeil profond.

Etude AGY 8c421e6a8 : forge_skill_curator et forge_hebbian_linker tournaient sur une Cadence fixe de 6 h, HORS du
programme de sommeil (seule la consolidation memoire y etait, en NREM1). Depuis 965926f41 le sommeil est tire sur
inactivite mesuree : y placer ces consolidations, c'est les faire tourner quand le corps est au repos. Meme patron que
NokidoMemoryConsolidator (l'action relance le service, qui consolide a son demarrage). Chaque service cite doit EXISTER.
"""
from __future__ import annotations

import re
from pathlib import Path

from nokido_agent.app import forge_circadian as C

RACINE = Path(__file__).resolve().parents[2]


def _services_declares():
    toml = (RACINE / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8")
    return set(re.findall(r'^name\s*=\s*"([^"]+)"', toml, re.M))


def test_curation_et_hebbien_en_sommeil_profond():
    services = {a.service for a in C.PHASE_PROGRAM[C.Phase.NREM3]}
    assert {"NokidoSkillCurator", "NokidoHebbian"} <= services


def test_aucune_phase_ne_relance_un_service_fantome():
    declares = _services_declares()
    for phase, actions in C.PHASE_PROGRAM.items():
        for a in actions:
            if a.service:
                assert a.service in declares, "%s : service %s absent de services.toml" % (phase.value, a.service)
