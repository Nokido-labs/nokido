"""NR — un identifiant d'agent designe UN SEUL acteur. Sinon le ring est tirable.

MESURE DU 2026-09-20 sur `config/agent_identities.json` (schema_version 3,
146 identites, 77 acteurs) :

    LAFORGE_CLI   actor=LAFORGE   ring=1   aliases: ['NOKIDO_CLI', 'agt_nokido_cli',
                                                     'nokido_cli', 'agt_laforge_cli',
                                                     'laforge_cli']
    NOKIDO_CLI    actor=NOKIDO    ring=4   aliases: ['agt_nokido_cli', 'nokido_cli']

`nokido_cli` et `agt_nokido_cli` sont revendiques par les DEUX entrees -- l'une
en RING 1 (privilegie), l'autre en RING 4. La resolution depend alors de l'ordre
de parcours du dictionnaire : un appelant se presentant comme `nokido_cli` PEUT
etre resolu vers le ring 1. C'est une ELEVATION DE PRIVILEGE latente, pas une
coquille.

RFC 6749 §2.2 : le client identifier est « a unique string representing the
registration information ». Deux enregistrements ne peuvent pas se partager un
identifiant -- c'est la condition meme pour qu'il identifie quelque chose.

⚠️ CE QUI N EST **PAS** UN DEFAUT, et que j'ai accuse a tort DEUX FOIS avant de
lire la structure : `AGY` / `GEMINI` / `ANTIGRAVITY` partagent des alias, et
c'est VOULU. Les trois portent `actor = ANTIGRAVITY`, et le registre le declare
en toutes lettres -- « IDENTIFIANT VIVANT. AGY = GEMINI = ANTIGRAVITY : un seul
acteur, plusieurs noms, TOUS actifs ». Le registre modelise deja la distinction
que les RFC imposent : l'ACTEUR (l'entite) n'est pas l'IDENTITE (le nom sous
lequel elle se presente). 8 des 10 « collisions » que j'avais comptees
s'evaporent des qu'on compare par `actor` -- le champ UNIVERSEL (146/146) -- au
lieu de `canonical` (4/146 seulement).

LE CRITERE EST DONC : un alias peut designer une autre identite DU MEME ACTEUR
(c'est le multi-nom legitime), jamais celle d'un acteur DIFFERENT.

PORTEE DITE : ce NR garde l'UNICITE inter-acteurs dans le registre. Il ne juge
ni les rings, ni les surfaces, ni la resolution runtime.
"""
from __future__ import annotations

import json
import pathlib

import pytest

_RACINE = pathlib.Path(__file__).resolve().parent.parent.parent
_REGISTRE = _RACINE / "config" / "agent_identities.json"


def _agents() -> dict:
    try:
        brut = json.loads(_REGISTRE.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError:
        pytest.skip("agent_identities.json ABSENT -- INDETERMINE, pas 'vide'")
    except OSError as exc:
        pytest.skip(f"agent_identities.json ILLISIBLE ({exc.__class__.__name__})")
    agents = brut.get("agents") or {}
    if not agents:
        pytest.skip("aucune entree `agents` -- schema a revoir, pas un vert")
    return agents


def test_le_registre_est_lisible_et_substantiel():
    """Garde l'instrument d'abord : un parse muet rendrait tout le reste vert."""
    a = _agents()
    assert len(a) > 100, f"seulement {len(a)} identites parsees -- le parse ment"


def test_chaque_identite_declare_son_ACTEUR():
    """`actor` est le champ qui porte la distinction acteur/identite.

    Sans lui, impossible de savoir si deux noms designent la meme entite -- et
    c'est exactement ce qui m'a fait accuser le registre a tort.
    """
    manquants = [n for n, m in _agents().items()
                 if isinstance(m, dict) and not m.get("actor")]
    assert not manquants, f"identites sans `actor` : {manquants[:10]}"


def test_aucun_alias_ne_designe_l_identite_d_un_AUTRE_acteur():
    """LE COEUR. RFC 6749 §2.2 : un identifiant designe UN enregistrement.

    Un alias partage entre deux acteurs rend la resolution dependante de l'ordre
    de parcours -- et quand les rings different, c'est une elevation de privilege.
    """
    agents = _agents()
    canon = {k.lower(): k for k in agents}
    fautes = []
    for nom, meta in agents.items():
        if not isinstance(meta, dict):
            continue
        for a in (meta.get("aliases") or []):
            cible = canon.get(str(a).lower())
            if not cible or cible == nom:
                continue
            if meta.get("actor") != agents[cible].get("actor"):
                fautes.append(
                    "%s (acteur %s, ring %s) revendique %r qui est l'identite de "
                    "%s (acteur %s, ring %s)"
                    % (nom, meta.get("actor"), meta.get("ring"), a,
                       cible, agents[cible].get("actor"), agents[cible].get("ring")))
    assert not fautes, "identifiant(s) ambigu(s) :\n  - " + "\n  - ".join(fautes)


def test_aucun_alias_n_est_revendique_par_deux_ACTEURS():
    """Le symetrique : deux entrees peuvent partager un alias SI elles ont le
    meme acteur (multi-nom legitime d'AGY/GEMINI/ANTIGRAVITY)."""
    agents = _agents()
    par_alias: dict[str, set] = {}
    for nom, meta in agents.items():
        if not isinstance(meta, dict):
            continue
        for a in (meta.get("aliases") or []):
            par_alias.setdefault(str(a).lower(), set()).add(meta.get("actor"))
    fautes = [f"{a!r} revendique par les acteurs {sorted(x for x in acts if x)}"
              for a, acts in par_alias.items() if len(acts) > 1]
    assert not fautes, "alias inter-acteurs :\n  - " + "\n  - ".join(fautes)


def test_le_multi_nom_d_un_MEME_acteur_reste_autorise():
    """GARDE ANTI-SUR-CORRECTION.

    Sans ce test, « nettoyer » le registre en supprimant tous les alias
    partages casserait AGY/GEMINI/ANTIGRAVITY -- que le registre declare
    explicitement comme UN SEUL acteur a plusieurs noms VIVANTS.
    """
    agents = _agents()
    trio = [n for n in ("AGY", "GEMINI", "ANTIGRAVITY") if n in agents]
    if len(trio) < 2:
        pytest.skip("le trio AGY/GEMINI/ANTIGRAVITY n'est plus au registre")
    acteurs = {agents[n].get("actor") for n in trio}
    assert len(acteurs) == 1, (
        f"AGY/GEMINI/ANTIGRAVITY ne partagent plus un acteur unique : {acteurs} -- "
        "le multi-nom legitime a ete casse")
