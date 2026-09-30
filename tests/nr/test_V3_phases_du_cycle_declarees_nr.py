"""Non-régression V3 : la carte dit OÙ vit un module, pas QUAND il parle.

Item de veille V3 (`google-deepmind/concordia`, `concordia/typing/`) : « un
module `typing` qui EST le contrat entre les parties — classes de base
abstraites, spécification d'action, et surtout un **cycle de vie explicite en
PHASES** (`PRE_ACT`, `POST_ACT`, `PRE_OBSERVE`, `POST_OBSERVE`, `update`)
auquel tout composant se raccorde ».

⚠️ CE QU'ON NE FAIT PAS, ET POURQUOI. On n'ajoute pas de hiérarchie de classes
abstraites à laquelle il faudrait ensuite raccorder 985 modules. Trois entrées
de cette même roadmap ont été rejetées pour exactement ce motif — « l'organe de
plus que la directive du 2026-09-07 refuse » — et la discipline arrêtée le
2026-09-05 est explicite : on n'ajoute plus de système parallèle, on identifie
la brique qui porte DÉJÀ une part du contrat et on l'étend si sa responsabilité
le permet.

Cette brique existe : `forge_organ_agents.WIRING_PROBES`. Quatre sondes
`(fichier, motif)`, vérifiées **dans les deux sens** par
`test_organ_registre_nr` — un câblage déclaré fait dont la sonde ne mord plus
est une régression, un câblage déclaré à faire dont la sonde mord est un
registre périmé. C'est l'inspectabilité que V3 réclame… à une dimension près.

CE QUI MANQUE, ET QUE CE FICHIER VERROUILLE : une sonde dit **qu'un** câblage
existe, jamais **quand** il intervient. Deux câblages du même organe, l'un
avant l'action et l'autre après, sont aujourd'hui indiscernables dans le
registre. D'où une PHASE déclarée par sonde, et surtout la question que
personne ne pouvait poser : **quelles phases du cycle n'ont aucun câblage ?**

⚠️ Une phase sans câblage n'est PAS une phase saine, et une phase non déclarée
n'est pas une phase absente. Trois états, comme partout ailleurs ici — sinon un
trou de câblage se lirait comme une étape qui n'a rien à faire.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _mod():
    import forge_organ_agents  # type: ignore

    return forge_organ_agents


# ── 1. Le vocabulaire des phases existe et il est fermé ───────────────────────

def test_les_phases_du_cycle_sont_declarees():
    m = _mod()
    phases = getattr(m, "PHASES", None)
    assert phases, (
        "aucun cycle de vie declare : la carte dit OU vit un module, rien ne dit "
        "QUAND il parle"
    )
    assert set(phases) >= {"PRE_ACT", "POST_ACT", "PRE_OBSERVE", "POST_OBSERVE",
                           "UPDATE"}, phases


def test_une_phase_inventee_est_refusee():
    """Un vocabulaire ouvert n'est pas un contrat : si chaque sonde peut nommer
    sa phase librement, deux câblages de la même étape porteront deux mots
    différents et l'agrégat ne voudra plus rien dire."""
    m = _mod()
    assert callable(getattr(m, "phases", None))
    r = m.phases({"sonde_bidon": ("PHASE_QUI_N_EXISTE_PAS", "x.py", "y")})
    assert "sonde_bidon" in r["sondes_a_phase_INVALIDE"], r


# ── 2. Chaque câblage déclare sa phase, ou le dit ─────────────────────────────

def test_chaque_cablage_du_registre_porte_une_phase():
    m = _mod()
    r = m.phases()
    assert r["sondes_SANS_phase"] == [], (
        "des cablages du registre ne declarent pas leur phase : %s"
        % r["sondes_SANS_phase"]
    )
    assert r["sondes_totales"] >= 4, r


def test_les_sondes_restent_utilisables_par_le_registre_existant():
    """La brique étendue doit continuer de servir ce qui s'en servait. Le
    registre est lu dans les deux sens par `test_organ_registre_nr` : casser sa
    forme transformerait un garde utile en faux positif permanent."""
    m = _mod()
    for cle, valeur in m.WIRING_PROBES.items():
        assert isinstance(valeur, tuple) and len(valeur) >= 2, (cle, valeur)
        fichier, motif = valeur[-2], valeur[-1]
        assert isinstance(fichier, str) and fichier.endswith(".py"), (cle, fichier)
        assert isinstance(motif, str) and motif, (cle, motif)
        assert callable(getattr(m, "probe", None))
        etat = m.probe(cle)
        assert isinstance(etat, dict), (cle, etat)


# ── 3. Une phase sans câblage se DIT ──────────────────────────────────────────

def test_une_phase_sans_aucun_cablage_est_nommee_pas_tue():
    """Le chiffre que V3 rend possible : quelles étapes du cycle ne sont
    surveillées par rien ? Les taire les ferait passer pour des étapes qui
    n'ont rien à faire."""
    m = _mod()
    r = m.phases()
    assert "phases_SANS_cablage_observe" in r, r
    # au moins une phase du vocabulaire n'a aucune sonde — sinon le registre
    # couvrirait tout le cycle, ce que la mesure du 2026-09-12 contredit
    assert isinstance(r["phases_SANS_cablage_observe"], list), r
    for p in r["phases_SANS_cablage_observe"]:
        assert p in m.PHASES, p
    assert set(r["par_phase"]) == set(m.PHASES), (
        "toutes les phases doivent apparaitre dans l'agregat, y compris vides : "
        "une phase absente de la table se lit comme une phase inexistante"
    )
