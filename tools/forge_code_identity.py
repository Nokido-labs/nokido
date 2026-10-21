"""forge_code_identity.py — identité du CODE RÉELLEMENT CHARGÉ par un process vivant.

Défaut mesuré le 2026-08-02 : après un revert sur DISQUE de `forge_docker_keeper`,
le keeper publiait toujours `daemon_up: true` — il exécutait l'ANCIEN code, chargé
en mémoire à son démarrage, et sondait un daemon que le revert venait d'abandonner.
Rien dans son battement ne permettait de le voir. « J'ai reverté » et « le service
exécute le revert » sont deux faits distincts ; sans ce module, seul le premier est
observable, et un service qui tourne un code périmé reste indétectable.

Contrat : `fields(__file__)` rend les champs à fusionner dans un heartbeat.
    code_sha      sha256[:12] du fichier tel que lu au PREMIER appel (≈ démarrage)
    code_sha_now  le même, relu à CHAQUE battement
    code_stale    True si le disque a divergé depuis le démarrage,
                  False si identique,
                  None si ILLISIBLE (absent, ACL, verrou).

`None` et non `False` quand on ne peut pas voir : un capteur qui rend `False` pour
« pas de dérive » ET pour « accès refusé » fabrique des faux négatifs indétectables
(RULES_SHARED — trois états : vrai · faux · illisible). Le consommateur qui alerte
doit donc tester `is True`, jamais la véracité brute.

Appelé depuis le premier battement, `fields()` fige la référence à cet instant. Un
keeper qui veut la figer plus tôt appelle `snapshot(__file__)` dans son `main()`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

__FORGE_COLOR__ = "immunitaire/proprioception-du-code"

# {chemin résolu -> sha au démarrage (None = illisible à ce moment-là)}
_AU_DEMARRAGE: dict[str, str | None] = {}


def _sha(chemin: Path) -> str | None:
    """sha256 tronqué du fichier, ou None si ILLISIBLE — jamais une chaîne vide."""
    try:
        return hashlib.sha256(chemin.read_bytes()).hexdigest()[:12]
    except OSError:
        return None


def snapshot(module_file: str) -> str | None:
    """Fige la référence pour ce fichier (idempotent) et la rend."""
    cle = str(Path(module_file).resolve())
    if cle not in _AU_DEMARRAGE:
        _AU_DEMARRAGE[cle] = _sha(Path(cle))
    return _AU_DEMARRAGE[cle]


def fields(module_file: str) -> dict:
    """Champs d'identité du code à fusionner dans un heartbeat."""
    chemin = Path(module_file).resolve()
    au_demarrage = snapshot(str(chemin))
    maintenant = _sha(chemin)
    stale: bool | None
    if au_demarrage is None or maintenant is None:
        stale = None  # illisible : ne PAS répondre « pas de dérive »
    else:
        stale = maintenant != au_demarrage
    return {
        "code_sha": au_demarrage,
        "code_sha_now": maintenant,
        "code_stale": stale,
    }


def drifted(module_file: str) -> bool:
    """True UNIQUEMENT sur une dérive prouvée (illisible → False, pas d'alerte à l'aveugle)."""
    return fields(module_file)["code_stale"] is True


def fichiers_du_depot(modules, racine) -> list:
    """Fichiers des modules CHARGÉS qui vivent sous `racine` (ordre conservé, sans doublon).

    16/10 : un process long (le tray) importe paresseusement d'autres modules du dépôt ; suivre son seul fichier
    raterait leur dérive. On suit donc ce qu'il a RÉELLEMENT chargé (`sys.modules`), rien de deviné."""
    base = Path(racine).resolve()
    out = []
    for m in modules:
        f = getattr(m, "__file__", None)
        if not f:
            continue
        chemin = Path(f).resolve()
        if chemin.is_relative_to(base) and str(chemin) not in out:
            out.append(str(chemin))
    return out


def perimes(fichiers) -> list:
    """Noms des fichiers dont le contenu a DÉRIVÉ depuis leur premier relevé (relevé posé au premier passage)."""
    out = []
    for f in fichiers:
        snapshot(f)
        if drifted(f):
            out.append(Path(f).name)
    return out
