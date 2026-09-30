# -*- coding: utf-8 -*-
"""NR — le dispatcher Go ecoute la boucle locale, et son build est reproductible.

Audit securite du 2026-09-18, finding #10. Mesure sur la table des sockets
VIVANTE, pas sur la declaration de service :

    TCP    0.0.0.0:8779    LISTENING
    TCP    [::]:8779       LISTENING

IPv4 ET IPv6. Ce service etait le SEUL de la flotte a ecouter au-dela de la
boucle locale, alors que les vingt autres y sont confines. Rien dans sa
declaration ne demandait cette exposition : elle venait d'un HOTE OMIS.

En Go, `":8779"` signifie toutes les interfaces. L'omission est le piege --
la chaine se relit comme « le port 8779 » et ne dit pas « depuis n'importe ou ».

CE QUE CE NR TESTE, ET POURQUOI PAS LE BINAIRE. `forge_dispatcher.exe` est un
ARTEFACT : il peut etre plus vieux que la source, et le tester reviendrait a
mesurer la date de la derniere compilation. On verrouille donc la SOURCE, qui
est ce que le depot gouverne. Le binaire en service reste a rebatir -- geste
owner, puisqu'il faut arreter le service pour remplacer un fichier verrouille.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/reseau : le dispatcher Go reste sur la boucle locale"

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

SRC = RACINE / "go_services" / "forge_dispatcher" / "main.go"
BUILD = RACINE / "go_services" / "forge_dispatcher" / "build.bat"


def _lignes_de_code(chemin: Path) -> list:
    """Lignes hors commentaire. Un commentaire qui DECRIT le defaut ne doit pas
    le declencher -- motif paye huit fois dans ce depot le 2026-09-18."""
    out = []
    for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        nu = ligne.strip()
        if nu.startswith("//") or nu.startswith("REM ") or not nu:
            continue
        out.append(ligne)
    return out


def test_l_hote_d_ecoute_est_EXPLICITE_et_local():
    code = "\n".join(_lignes_de_code(SRC))
    m = re.search(r'defaultPort\s*=\s*"([^"]+)"', code)
    assert m, "la constante de port a disparu : relire ce NR"
    valeur = m.group(1)
    assert valeur.startswith(("127.0.0.1:", "localhost:", "[::1]:")), (
        f'le dispatcher ecoute "{valeur}" — un hote omis signifie TOUTES les '
        "interfaces en Go"
    )


def test_MORSURE_un_hote_omis_serait_DETECTE():
    """CONTROLE NEGATIF — sans lui, un test qui accepte tout passerait au vert."""
    for fautif in (":8779", ":0", ":8080"):
        assert not fautif.startswith(("127.0.0.1:", "localhost:", "[::1]:")), (
            f"le controle laisserait passer {fautif!r}"
        )


def test_aucune_autre_ecoute_ouverte_dans_la_source():
    """Un second `ListenAndServe` avec un hote vide rouvrirait le trou ailleurs."""
    code = "\n".join(_lignes_de_code(SRC))
    ouvertes = re.findall(r'(?:ListenAndServe|net\.Listen)\(\s*"(:[0-9]+)"', code)
    assert not ouvertes, f"ecoute(s) sur toutes les interfaces : {ouvertes}"


def test_le_script_de_build_porte_ses_deux_drapeaux():
    """Le build echouait sous tout compte non proprietaire du depot.

    Deux causes MESUREES le meme jour, chacune avec son drapeau :
      - le tamponnage VCS de Go appelle git, qui rend « dubious ownership » ;
      - les comptes de service ont HOME=C:/Users/Default, donc %LocalAppData%
        n'existe pas et Go refuse de construire faute de cache.

    Un script de build qui ne tourne que sous un compte n'est pas reproductible.
    """
    code = "\n".join(_lignes_de_code(BUILD))
    assert "-buildvcs=false" in code, (
        "sans ce drapeau, le build meurt en exit 128 sous un compte non proprietaire"
    )
    assert "GOCACHE" in code, (
        "sans cache defini, le build meurt : %LocalAppData% n'existe pas pour les "
        "comptes de service"
    )
