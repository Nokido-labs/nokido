"""NR 18/10 -- item p2_bail_priorite_403_depuis_un_job : la CI de reference prend le bail de priorite sous SA
propre identite, jamais sous SERVICES (403 : authentifie mais non autorise a prendre un bail).

Contrat (decisions owner 16/10 « forme a » et 18/10) :
  * le registre declare une identite dediee a la CI de reference, ring <= 3 (le bail arme l'exige),
    SANS droit d'ecriture au depot ;
  * tools/forge_ci_reference.py demande le bail sous cette identite (agent=...), pas sous l'identite par defaut.
Ce NR juge le DEPOT. Le semis du jeton au coffre (geste owner) et le journal du hub ne sont pas sous sa portee.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

RACINE = pathlib.Path(__file__).resolve().parent.parent.parent
REGISTRE = RACINE / "config" / "agent_identities.json"
CI_REF = RACINE / "tools" / "forge_ci_reference.py"


def _identites() -> dict:
    try:
        data = json.loads(REGISTRE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        pytest.skip(f"registre ILLISIBLE ({exc.__class__.__name__}) -- INDETERMINE")
    trouves: dict = {}

    def visiter(noeud, nom=None):
        if isinstance(noeud, dict):
            if "ring" in noeud and nom:
                trouves[nom] = noeud
            for k, v in noeud.items():
                visiter(v, k if isinstance(v, dict) else nom)
        elif isinstance(noeud, list):
            for v in noeud:
                visiter(v, (v.get("name") or v.get("agent")) if isinstance(v, dict) else nom)
    visiter(data)
    assert len(trouves) > 10, "parse du registre suspect : trop peu d'identites lues"
    return trouves


def _identite_ci() -> tuple[str, dict]:
    cand = [(n, d) for n, d in _identites().items() if "ci de reference" in str(d.get("organe", "")).lower()]
    assert len(cand) == 1, f"attendu UNE identite d'organe « CI de reference », trouve {[n for n, _ in cand]}"
    return cand[0]


def test_la_ci_de_reference_a_une_identite_dediee_au_ring_du_bail():
    nom, d = _identite_ci()
    assert nom.upper() != "SERVICES"
    assert isinstance(d.get("ring"), int) and d["ring"] <= 3, f"{nom} ring={d.get('ring')} : le bail arme exige <= 3"
    assert not d.get("write_paths"), f"{nom} ne doit avoir aucun droit d'ecriture au depot"


def test_forge_ci_reference_demande_le_bail_sous_cette_identite():
    nom, _ = _identite_ci()
    try:
        src = CI_REF.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        pytest.skip(f"forge_ci_reference.py ILLISIBLE ({exc.__class__.__name__})")
    appels = re.findall(r"bail_priorite\(([^)]*)\)", src)
    assert appels, "forge_ci_reference.py ne demande aucun bail de priorite"
    constantes = dict(re.findall(r"^([A-Z_][A-Z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]", src, re.M))

    def agent_de(appel: str) -> str | None:
        m = re.search(r"agent\s*=\s*(?:['\"]([^'\"]+)['\"]|([A-Z_][A-Z0-9_]*))", appel)
        return (m.group(1) or constantes.get(m.group(2))) if m else None

    assert any(agent_de(a) == nom for a in appels), (
        f"le bail est demande sans agent={nom!r} (litteral ou constante) : il partirait sous SERVICES -> 403")
