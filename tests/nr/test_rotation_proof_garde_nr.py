"""NR — l'outil de preuve de rotation refuse plutot que de simuler.

Le cliquet `test_aucun_module_nouveau_sans_test` a attrape `forge_rotation_proof`
au sha 2c5ab5799 : cree sans NR. Il avait raison, et sa consigne est precise --
« ecrire un test qui verifie son EFFET (pas son import) ».

L'EFFET de cet outil n'est pas de rotationner : c'est de REFUSER de conclure
quand il ne peut pas prouver. Trois refus le portent, et ce sont eux qu'on
eprouve ici :

  1. si le nom de preuve est adopte par du code reel, la rotation cesserait
     d'etre sans consequence -> il refuse AVANT d'ecrire quoi que ce soit ;
  2. si la phase B tourne sans attestation de phase A, une mesure d'APRES ne
     prouve rien (on ignore ce qui etait attendu) -> elle refuse ;
  3. l'affichage ne sort JAMAIS une valeur, seulement des empreintes.

AUCUNE CLE N'EST CREEE NI LUE. Le coffre n'est pas touche : les trois tests
substituent l'attestation vers `tmp_path` ou lisent du texte.
"""
import importlib
import inspect

import pytest

OUTIL = "nokido_agent.tools.forge_rotation_proof"


@pytest.fixture(name="proof")
def _fx_proof():
    return importlib.import_module(OUTIL)


def test_le_garde_REFUSE_si_le_nom_de_preuve_est_adopte(proof, monkeypatch, tmp_path):
    """Un garde verifie UNE FOIS, le jour ou on l'ecrit, ne garde rien.

    Si `NOKIDO_ROTATION_PROOF_KEY` se mettait a etre lu en production, la
    rotation de preuve cesserait d'etre inoffensive. Le garde re-verifie donc a
    CHAQUE execution -- on lui fabrique un faux depot ou le nom est reclame.
    """
    faux = tmp_path / "app"
    faux.mkdir()
    (faux / "un_module.py").write_text(
        "CLE = '%s'\n" % proof.NOM, encoding="utf-8")
    (tmp_path / "tools").mkdir()
    monkeypatch.setattr(proof, "RACINE", tmp_path, raising=True)
    with pytest.raises(SystemExit) as exc:
        proof._garde_nom_libre()
    assert "un_module.py" in str(exc.value), (
        "le refus doit NOMMER le reclamant : « refuse » sans dire qui oblige a "
        "re-chercher. Recu : %r" % str(exc.value)[:160]
    )


def test_le_garde_LAISSE_PASSER_quand_le_nom_est_libre(proof, monkeypatch, tmp_path):
    """La symetrie : un garde qui refuse toujours ne garde pas, il bloque."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "app" / "innocent.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(proof, "RACINE", tmp_path, raising=True)
    proof._garde_nom_libre()          # ne doit rien lever


def test_la_phase_B_REFUSE_sans_attestation_de_phase_A(proof, monkeypatch, tmp_path):
    """Sans le verdict d'AVANT, une mesure d'APRES ne prouve rien : on ignore
    ce qui etait attendu. Le refus vaut mieux qu'un verdict inventé."""
    monkeypatch.setattr(proof, "ATTESTATION", tmp_path / "absente.json",
                        raising=True)
    with pytest.raises(SystemExit) as exc:
        proof.apres_restart()
    assert "attestation" in str(exc.value).lower()


def test_aucune_sortie_ne_peut_porter_une_VALEUR(proof):
    """Contrat de l'outil : seules des EMPREINTES circulent.

    Verifie par le garde d'egress lui-meme, applique a la source de cet outil --
    ce qui le fait dependre d'un instrument deja eprouve des deux cotes plutot
    que d'une relecture a l'oeil.
    """
    gate = importlib.import_module("nokido_agent.tools.forge_secret_egress_gate")
    src = inspect.getsource(proof)
    assert gate.analyser_source(src) == [], (
        "un chemin d'emission de valeur existe dans l'outil de preuve"
    )
