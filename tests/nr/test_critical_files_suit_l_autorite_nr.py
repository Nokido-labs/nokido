"""NR — la liste de protection doit suivre l'AUTORITE, pas l'anciennete.

MESURE DU 2026-09-12. `CRITICAL_FILES` protege `app/forge_rbac.py`
(`get_rbac`, 15 170 o, modifie le 2026-08-24) mais PAS
`app/forge_mcp_rbac.py` (`check_tool_capability`, 7 919 o, modifie le
2026-09-12) — or c'est le SECOND que le dispatch MCP consulte pour autoriser
chaque tool. Deux fichiers aux noms voisins, deux autorites reelles, une seule
protegee : la protection est restee sur l'ancien.

Meme constat pour la chaine d'arret : `app/forge_opsec.py` porte l'etat de
l'interrupteur humain (8 consommateurs) et `app/forge_corrigibility.py` le
garde qui le consulte au dispatch ; ni l'un ni l'autre n'etait couvert. Et
`tools/forge_governed_edit.py` — l'ecrivain qui APPLIQUE `CRITICAL_FILES` —
ne l'etait pas non plus.

CE QUE CE TEST NE DEMONTRE PAS :
  - il ne prouve AUCUNE independance. La derogation `allow_critical` reste
    accessible au ring <= 1, donc au client. Etre dans `CRITICAL_FILES`
    impose un geste EXPLICITE et TRACE, cela ne cree pas de frontiere.
  - il ne dit rien de l'etat runtime : le hub tourne sur le code charge a son
    demarrage. Ce test atteste la SOURCE.
  - il n'affirme pas que la liste soit complete : il verrouille ce qui a ete
    MESURE comme cable. Un nouveau module de decision devra y etre ajoute a
    la main — c'est le prix de ne pas deviner une autorite depuis un nom.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

S = pytest.importorskip("nokido_agent.app.forge_mcp_security")

# (chemin, pourquoi il porte une autorite) — chaque ligne est une MESURE du jour.
AUTORITES_MESUREES = (
    ("app/forge_mcp_rbac.py",
     "check_tool_capability : la decision d'autorisation par tool, cablee au "
     "dispatch (forge_mcp_registry)"),
    ("app/forge_opsec.py",
     "porte l'etat de l'off-switch humain ; 8 consommateurs le lisent"),
    ("app/forge_corrigibility.py",
     "corrigibility_gate : consulte l'off-switch au dispatch et refuse les "
     "tools mutants"),
    ("tools/forge_governed_edit.py",
     "governed_write : l'ecrivain qui APPLIQUE CRITICAL_FILES"),
)


@pytest.mark.parametrize("rel,motif", AUTORITES_MESUREES)
def test_un_module_qui_decide_est_protege(rel, motif):
    assert (RACINE / rel).is_file(), (
        "%s absent : verifier la mesure avant de conclure" % rel)
    assert S._is_critical(rel), (
        "%s n'est pas dans CRITICAL_FILES alors qu'il porte une autorite "
        "(%s). Une protection qui ne suit pas l'autorite protege le passe."
        % (rel, motif))


def test_le_couple_homonyme_rbac_est_couvert_des_deux_cotes():
    """Le piege precis du 2026-09-12 : deux noms voisins, une seule protection."""
    for rel in ("app/forge_rbac.py", "app/forge_mcp_rbac.py"):
        assert (RACINE / rel).is_file(), "%s absent" % rel
        assert S._is_critical(rel), (
            "%s non protege — les deux modules RBAC existent et sont tous deux "
            "importes ; proteger l'un et pas l'autre laisse l'autorite reelle "
            "a decouvert" % rel)


def test_la_protection_reste_exacte_et_ne_deborde_pas():
    """Controle POSITIF : `_is_critical` matche par endswith.

    Sans ce controle, on pourrait rendre le test precedent vert en ajoutant une
    entree trop large (par ex. `rbac.py`) qui protegerait aussi des modules
    ordinaires — une ACL elargie deguisee en correctif.
    """
    temoins = ("tools/forge_effect_surface.py", "app/forge_rag_engine.py",
               "tools/forge_module_census.py")
    for rel in temoins:
        assert not S._is_critical(rel), (
            "%s est devenu CRITICAL : la liste a ete elargie au-dela de "
            "l'autorite mesuree" % rel)


def test_la_liste_appliquee_par_l_ecrivain_est_la_meme_source():
    """Un repli fail-closed duplique la liste dans governed_write : le verifier.

    Ce repli n'agit que si l'import de `_is_critical` casse. Il ne doit pas
    diverger au point de laisser passer une autorite que la liste principale
    protege.
    """
    src = (RACINE / "tools" / "forge_governed_edit.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.find("fail-closed sur la liste connue")
    assert i != -1, "le repli fail-closed de governed_write a disparu"
    bloc = src[i: i + 1200]
    # `+` exigeait un caractere AVANT le point : l'entree ".env" n'etait donc
    # jamais vue, et le test rapportait un trou qui n'existait pas. Defaut
    # d'INSTRUMENT, corrige le 2026-09-12.
    replis = set(re.findall(r'"([^"]*\.(?:py|env))"', bloc))
    assert replis, "repli introuvable dans le bloc"
    manquants = [c for c in S.CRITICAL_FILES
                 if c.lower() not in {r.lower() for r in replis}]
    assert not manquants, (
        "le repli fail-closed de governed_write ne couvre pas %s : si l'import "
        "de _is_critical casse, ces fichiers deviennent ecrivables" % (manquants,))
