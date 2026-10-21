"""NR 18/10 -- decision owner sur `circadien_tire_dans_le_vide` (choix multiple, 18/10) :

  * rallumer NokidoIngestDaemon et NokidoMemoryConsolidator (services permanents) ;
  * garder NokidoNightTrainer / NokidoOfflineTrainer / NokidoSelfPatcher eteints, MAIS le corps doit
    savoir les LANCER quand sa phase le demande.

Cause instruite le 02/10 (AGY, verifiee sur pieces) : `firePhase` (proxy_deno/core/supervisor.ts) ne trouve
pas les services `disabled` dans `states` et rend « abstention disabled par politique » -- le programme
circadien tire dans le vide. Le reveil a la demande EXISTE pourtant : `etatALaDemande(name, ...)`, utilise
par /supervisor/service/start et /supervisor/llm/activate. Il manque seulement a `firePhase`.

Ce NR juge la COHERENCE DECLARATIVE du depot (meme forme que test_deps_on_demand_ont_un_rallumeur_vivant_nr),
pas la machine a l'instant t. NokidoWatchdog n'est PAS ici : c'est un service NSSM standalone, coupe du
superviseur le 2026-06-02 pour une dependance circulaire -- son reveil ne passe pas par `firePhase`.
"""
from __future__ import annotations

import pathlib
import re

import pytest

RACINE = pathlib.Path(__file__).resolve().parent.parent.parent
TOML = RACINE / "proxy_deno" / "core" / "services.toml"
SUP = RACINE / "proxy_deno" / "core" / "supervisor.ts"

PERMANENTS = ("NokidoIngestDaemon", "NokidoMemoryConsolidator")
A_LA_DEMANDE = ("NokidoNightTrainer", "NokidoOfflineTrainer", "NokidoSelfPatcher")


def _lire(chemin: pathlib.Path) -> str:
    try:
        return chemin.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        pytest.skip(f"{chemin.name} ILLISIBLE ({exc.__class__.__name__}) -- INDETERMINE, pas un vert")


def _disabled(nom: str) -> bool | None:
    for bloc in _lire(TOML).split("[[service]]")[1:]:
        if re.search(r'^name\s*=\s*"%s"' % re.escape(nom), bloc, re.M):
            m = re.search(r"^disabled\s*=\s*(true|false)", bloc, re.M)
            return bool(m and m.group(1) == "true")
    return None


def _corps_fire_phase() -> str:
    src = _lire(SUP)
    debut = src.find("async function firePhase(")
    assert debut >= 0, "firePhase introuvable dans supervisor.ts -- le NR doit suivre le renommage"
    fin = src.find("\nasync function ", debut + 10)
    return src[debut:fin if fin > 0 else debut + 8000]


@pytest.mark.parametrize("nom", PERMANENTS)
def test_les_organes_rallumes_par_l_owner_ne_sont_plus_disabled(nom):
    etat = _disabled(nom)
    assert etat is not None, f"{nom} n'est plus declare dans services.toml"
    assert etat is False, f"{nom} est encore disabled=true alors que l'owner a decide de le rallumer (18/10)"


@pytest.mark.parametrize("nom", A_LA_DEMANDE)
def test_les_organes_a_la_demande_restent_declares_et_eteints(nom):
    """Instrument d'abord : un nom disparu rendrait le test suivant vert sur une absence."""
    assert _disabled(nom) is True, f"{nom} doit rester declare ET disabled (decision owner 18/10)"
    assert '"%s"' % nom in _lire(SUP), f"{nom} n'est plus vise par le PHASE_PROGRAM du superviseur"


def test_fire_phase_reveille_les_organes_a_la_demande():
    corps = _corps_fire_phase()
    assert "etatALaDemande(" in corps, (
        "firePhase ne reutilise pas le reveil a la demande (etatALaDemande) : une phase qui vise un "
        "service disabled tire encore dans le vide")
    src = _lire(SUP)
    m = re.search(r"CIRCADIAN_REVEIL_A_LA_DEMANDE\s*=\s*new Set\(\s*\[([^\]]*)\]", src)
    assert m, "la liste BLANCHE des organes reveillables par le circadien (CIRCADIAN_REVEIL_A_LA_DEMANDE) manque"
    declares = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert set(A_LA_DEMANDE) <= declares, f"liste blanche incomplete : manque {set(A_LA_DEMANDE) - declares}"
    assert "NokidoWatchdog" not in declares, "NokidoWatchdog est NSSM : le reveiller ici recreerait la boucle du 02/06"
    assert "CIRCADIAN_REVEIL_A_LA_DEMANDE.has(" in corps, "firePhase doit consulter la liste blanche, pas tout reveiller"
