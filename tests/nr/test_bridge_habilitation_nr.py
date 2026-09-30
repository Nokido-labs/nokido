"""L'emetteur d'habilitation ne fabrique que des jetons BORNES, et ne les montre pas.

POURQUOI CE FICHIER EXISTE. Il a ete reclame par un cliquet, pas par une bonne
intention : `test_nr_coverage_ratchet_nr` a fait ROUGIR la CI en constatant que
`tools/forge_bridge_habilitation.py` avait ete livre sans aucun test. Le module
etait ecrit, relu, commente -- et rien ne le PROUVAIT.

CE QU'IL PROTEGE. L'emetteur est la main de l'operateur : lui a le droit de lire le
coffre, la passerelle non. C'est la seule raison d'etre de la separation en deux
fichiers. Trois proprietes doivent donc tenir, et aucune n'est evidente a la
relecture :

  1. il n'emet PAS pour un depot que la passerelle refuserait -- un jeton mort a la
     naissance ne provoque pas un refus clair, il provoque un doute ;
  2. il n'IMPRIME jamais la valeur emise. Une sortie de job est relue, archivee,
     parfois recopiee dans une conversation ; seules des metadonnees en sortent ;
  3. ce qu'il signe, la passerelle le RECONNAIT. Emetteur et verificateur qui
     divergent, c'est une cle valide que personne n'accepte.

Hermetique : le coffre est remplace par un double, et le fichier de sortie est
redirige vers un repertoire temporaire -- sans quoi ce test ECRASERAIT
l'habilitation reellement en service.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import time

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
CHEMIN = RACINE / "tools" / "forge_bridge_habilitation.py"
CLEF_FACTICE = "0" * 64


def _charger(chemin: pathlib.Path, nom: str):
    if not chemin.exists():
        pytest.fail("%s introuvable" % chemin)
    spec = importlib.util.spec_from_file_location(nom, chemin)
    if spec is None or spec.loader is None:
        pytest.fail("%s illisible par l'importeur" % chemin)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        pytest.fail("%s ne s'importe pas : %s: %s" % (nom, type(exc).__name__, exc))
    return module


@pytest.fixture()
def outil(tmp_path, monkeypatch):
    """L'emetteur reel, avec un coffre DOUBLE et une sortie DETOURNEE.

    Le detournement n'est pas un confort : sans lui, un simple `pytest` ecraserait
    `sandbox/bridge_habilitation.json`, c'est-a-dire l'habilitation en service.
    """
    module = _charger(CHEMIN, "forge_bridge_habilitation")
    ecrits = {}

    def _coffre_double():
        def get_secret(cle):
            if cle in ecrits:
                return ecrits[cle]
            return CLEF_FACTICE if cle == module.CLEF else None

        def set_secret(cle, valeur):
            ecrits[cle] = valeur
            return True

        return get_secret, set_secret

    monkeypatch.setattr(module, "_coffre", _coffre_double)
    monkeypatch.setattr(module, "SORTIE", tmp_path / "habilitation.json")
    module._ecrits = ecrits
    return module


def _sortie(outil) -> dict:
    return json.loads(outil.SORTIE.read_text(encoding="utf-8"))


# ------------------------------------------------------- moindre privilege

def test_un_depot_hors_liste_blanche_n_est_PAS_emis(outil, capsys):
    rc = outil.main(["--sujet", "essai", "--ressource", "autre/projet"])
    assert rc != 0, "un jeton a ete emis pour un depot que la passerelle refuse"
    assert not outil.SORTIE.exists(), "un jeton mort a tout de meme ete ecrit"
    assert "REFUS" in capsys.readouterr().out


def test_un_mode_de_rejeu_inconnu_est_refuse(outil):
    with pytest.raises(SystemExit):
        outil.main(["--sujet", "essai", "--rejeu", "eternel"])


def test_une_habilitation_sans_destinataire_est_refusee(outil, capsys):
    rc = outil.main([])
    assert rc != 0
    assert "sujet" in capsys.readouterr().out.lower(), (
        "le refus doit DIRE pourquoi : une habilitation anonyme ne s'audite ni ne "
        "se revoque")
    assert not outil.SORTIE.exists()


@pytest.mark.parametrize("jours", [0, -1, 366, 4000])
def test_une_duree_hors_bornes_est_refusee(outil, jours):
    rc = outil.main(["--sujet", "essai", "--ttl-jours", str(jours)])
    assert rc != 0, "duree %r acceptee" % jours
    assert not outil.SORTIE.exists()


def test_sans_clef_au_coffre_rien_n_est_emis(outil, monkeypatch, capsys):
    monkeypatch.setattr(outil, "_coffre",
                        lambda: ((lambda _c: None), (lambda _c, _v: True)))
    rc = outil.main(["--sujet", "essai"])
    assert rc != 0
    assert "clef" in capsys.readouterr().out.lower()
    assert not outil.SORTIE.exists()


# ------------------------------------------------- la valeur ne sort jamais

def test_la_valeur_emise_n_est_JAMAIS_imprimee(outil, capsys):
    rc = outil.main(["--sujet", "action-essai", "--ttl-jours", "7"])
    assert rc == 0
    sortie = capsys.readouterr().out
    valeur = _sortie(outil)["habilitation"]
    assert valeur not in sortie, "la valeur de l'habilitation a ete IMPRIMEE"
    for morceau in (valeur[:24], valeur[-24:]):
        assert morceau not in sortie, "un fragment de la valeur a ete imprime"
    assert CLEF_FACTICE not in sortie, "la clef de signature a ete imprimee"
    # ce qui DOIT sortir : de quoi auditer et revoquer, rien de plus
    for attendu in ("jti", "expire", "empreinte", "action-essai"):
        assert attendu in sortie.lower(), "metadonnee %r absente de la sortie" % attendu


def test_la_valeur_n_est_pas_un_argument_de_ligne_de_commande():
    """Les arguments des scripts privilegies sont journalises en clair."""
    source = CHEMIN.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"add_argument\(\s*[\"']--([a-z-]+)", source):
        nom = m.group(1)
        assert not any(x in nom for x in ("token", "secret", "key")), \
            "l'outil accepte un secret en argument : --%s" % nom


def test_la_frappe_de_clef_n_ecrase_pas_une_clef_existante(outil, capsys):
    """Remplacer la clef invaliderait TOUTES les habilitations en circulation."""
    outil._ecrits[outil.CLEF] = "clef-deja-en-service"
    rc = outil.main(["--frapper-la-clef"])
    assert rc == 0
    assert outil._ecrits[outil.CLEF] == "clef-deja-en-service", "la clef a ete ecrasee"
    assert "deja" in capsys.readouterr().out.lower()


# --------------------------------------- coherence avec le verificateur

def test_ce_qui_est_EMIS_est_reconnu_par_la_passerelle(outil, monkeypatch):
    """Emetteur et verificateur qui divergent : une cle valide que nul n'accepte."""
    rc = outil.main(["--sujet", "action-essai", "--ttl-jours", "30",
                     "--rejeu", "multi"])
    assert rc == 0
    emis = _sortie(outil)

    pont = _charger(RACINE / "tools" / "forge_github_bridge.py", "forge_github_bridge")
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", CLEF_FACTICE)
    vues = []

    def _faux(chemin, methode="GET"):
        vues.append(chemin)
        return 200, {"full_name": emis["resource"], "private": True,
                     "permissions": {"pull": True}}

    monkeypatch.setattr(pont, "_appel_github", _faux)
    ok, res = pont.traiter("repo_info", {"repo": emis["resource"]},
                           emis["habilitation"])
    assert ok is True, "la passerelle REFUSE ce que l'emetteur a signe : %r" % (res,)
    assert len(vues) == 1


def test_l_habilitation_emise_porte_ses_bornes(outil):
    outil.main(["--sujet", "action-essai", "--ttl-jours", "30", "--rejeu", "multi"])
    emis = _sortie(outil)
    assert emis["sub"] == "action-essai"
    assert emis["resource"] == "Nokido-labs/nokido"
    assert emis["replay"] == "multi"
    assert emis["jti"].startswith("bridge-"), "le jti doit etre tracable a l'emission"
    reste = emis["exp"] - time.time()
    assert 29 * 86400 < reste <= 30 * 86400, "expiration hors de la duree demandee"
