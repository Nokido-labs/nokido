"""Le garde doit viser la COMMANDE `env`, jamais l'EXTENSION `.env`.

Mesure 2026-07-24 : `\\benv\\b` faisait bloquer toute mention d'un chemin
`Nokido.env` sous le motif « dump secret/PAT » — lire ou corriger un commentaire
dans ce fichier devenait impossible, alors qu'aucun secret n'etait dumpe.

Un garde-fou peut etre BON et son diagnostic FAUX : on corrige le diagnostic, on ne
retire pas le garde. La protection REELLE (regle « lecture secret », qui exige un
verbe cat/type/more/head/tail/get-content) doit rester intacte.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_tool_gate as tg  # noqa: E402


def _regle(motif: str):
    for rx, label, *_kinds in tg._DENY:  # (motif, libelle, portees) depuis l'ajout des portees
        if label == motif:
            return rx
    raise AssertionError(f"regle '{motif}' introuvable")


@pytest.mark.parametrize("texte", ["env ", "printenv ", "gh auth token", "git remote -v",
                                   "git remote get-url origin"])
def test_les_vrais_dumps_restent_bloques(texte):
    assert _regle("dump secret/PAT").search(texte), texte


@pytest.mark.parametrize("texte", [
    "LaForge/Nokido.env ",
    "editer Nokido.env",
    "C:/Users/x/Script python IA/LaForge/Nokido.env",
    "corriger le commentaire de Nokido.env",
])
def test_une_simple_mention_de_fichier_nest_PAS_un_dump(texte):
    assert not _regle("dump secret/PAT").search(texte), texte


@pytest.mark.parametrize("texte", ["cat Nokido.env", "type .env", "Get-Content secrets.env",
                                   "more id_rsa", "tail credentials.json"])
def test_la_protection_reelle_est_intacte(texte):
    """C'est CETTE regle qui protege : elle exige un verbe de lecture."""
    assert _regle("lecture secret").search(texte), texte


@pytest.mark.parametrize("texte", [
    "/bin/cat .env", "type C:\\x\\Nokido.env", "cat.exe id_rsa", "Get-Content x.key",
])
def test_le_verbe_reste_attrape_en_chemin_ou_avec_extension(texte):
    assert _regle("lecture secret").search(texte), texte


@pytest.mark.parametrize("texte", [
    # Mesure 2026-09-28 : sans bornes de mot, « cat » DANS un mot francais puis un nom
    # en `_token` sur la meme ligne refusait une ecriture de prose (fiche memoire).
    "groupe NOUVELLES, categorie ; tests voisins : test_capability_tokens hermetique",
    "la verification du jeton lit forge_auth_tokens",
    "mod = types.ModuleType('x') ; from forge_auth_tokens import login_agent",
    "un detail sur le module forge_secret_egress_gate",
])
def test_un_verbe_DANS_un_mot_n_est_pas_une_lecture(texte):
    assert not _regle("lecture secret").search(texte), texte
