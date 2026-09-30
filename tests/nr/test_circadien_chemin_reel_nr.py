"""NR — le circadien qui TOURNE est celui du superviseur TypeScript.

Deux NR gardent deja `forge_circadian` (Python) : `test_circadian_postcondition_nr`
protege « une phase en echec conserve la dette », `test_npsc_circadien_nr` protege
la conformite du programme. Mais `fire_phase` n'est appele NULLE PART en Python —
mesure du 2026-09-20, ses seules autres occurrences sont des commentaires citant un
test. L'appelant reel est `supervisor.ts circadianLoop`, arme par `superviseBoucle`.

Les contrats ci-dessous sont donc deja arretes par le depot ; ce fichier les porte
sur le chemin QUI S'EXECUTE. C'est la lecon « un NR emprunte le chemin reel, pas
seulement la fonction » — ici la divergence n'est pas un drapeau CLI mais un LANGAGE.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SUPERVISEUR = RACINE / "proxy_deno" / "core" / "supervisor.ts"
SERVICES = RACINE / "proxy_deno" / "core" / "services.toml"


def _source_superviseur() -> str:
    if not SUPERVISEUR.exists():
        pytest.skip(f"superviseur absent : {SUPERVISEUR}")
    return SUPERVISEUR.read_text(encoding="utf-8", errors="replace")


def _corps_de_fire_phase(src: str) -> str:
    """Le corps de `firePhase`, borne a la declaration suivante.

    On ne lit pas tout le fichier : un test qui cherche un motif dans 3 128 lignes
    finit par le trouver ailleurs et rend un faux vert.
    """
    debut = re.search(r"async function firePhase\b", src)
    assert debut, "firePhase introuvable dans supervisor.ts — le NR ne sait plus quoi garder"
    suite = re.search(r"\n(?:async )?function \w+", src[debut.end():])
    fin = debut.end() + (suite.start() if suite else 4000)
    return src[debut.start():fin]


def test_tout_service_reveille_par_une_phase_est_declare():
    """Une phase qui reveille un service inconnu tire dans le vide.

    `firePhase` enregistre bien `error: "unknown service"`, mais ce resultat n'est
    lu par personne : la reference morte est donc INVISIBLE a l'execution. Elle
    doit etre attrapee ici, ou nulle part.
    """
    src = _source_superviseur()
    programme = re.search(
        r"const PHASE_PROGRAM: Record<Phase, PhaseAction\[\]> = \{(.+?)\n\};",
        src,
        re.S,
    )
    assert programme, "PHASE_PROGRAM introuvable — la forme du superviseur a change"
    cites = sorted(set(re.findall(r'service:\s*"([^"]+)"', programme.group(1))))
    assert cites, "aucun service cite par PHASE_PROGRAM : le NR ne mesurerait rien"

    if not SERVICES.exists():
        pytest.skip(f"SSoT des services absent : {SERVICES}")
    declares = set(re.findall(r'name\s*=\s*"([^"]+)"', SERVICES.read_text(encoding="utf-8", errors="replace")))
    assert declares, "services.toml lu mais AUCUN nom trouve — lecture suspecte, pas SSoT vide"

    morts = [s for s in cites if s not in declares]
    assert not morts, (
        f"{len(morts)}/{len(cites)} service(s) reveille(s) par une phase et ABSENT(s) "
        f"de services.toml : {morts}. Le rythme les appelle chaque jour sans effet."
    )


def test_une_phase_n_est_soldee_qu_au_vu_de_ses_resultats():
    """`REQUESTED != ACHIEVED` — mesure du 2026-09-20.

    `circadianLastFired.set(phase, ...)` etait pose HORS de toute condition : la
    phase se marquait accomplie que ses actions reussissent, echouent, ou ciblent un
    service inconnu. Consequence mesuree le meme jour : 7 des 9 entrees du programme
    visaient des services `disabled` ou absents, et les SIX phases affichaient malgre
    tout une dette inferieure a 28 h. `sleepDebt` (> 48 h) ne pouvait donc jamais se
    declencher : l'instrument rendait « sain » PARCE QU'il ne regardait pas l'echec.

    Le contrat lui-meme n'est pas neuf — `test_une_phase_en_echec_conserve_la_dette`
    l'arrete deja cote Python. Ce test le porte sur le chemin qui s'execute.
    """
    corps = _corps_de_fire_phase(_source_superviseur())

    solde = re.search(r"circadianLastFired\.set\(\s*phase", corps)
    assert solde, "le solde de la phase a disparu de firePhase — contrat a re-etablir avant tout"

    avant = corps[: solde.start()]
    # Le corps doit CONSULTER ses resultats avant de solder. On ne prescrit pas la
    # forme (some/every/filter/find/length) : on exige qu'une lecture ait lieu.
    consulte = re.search(r"results\s*\.\s*(some|every|filter|find|length)\b", avant)
    assert consulte, (
        "firePhase solde la phase sans lire `results` : une phase dont TOUTES les "
        "actions echouent est marquee accomplie, la dette reste a zero, et sleepDebt "
        "ne se declenche jamais. Conditionner le solde au vu des resultats."
    )
