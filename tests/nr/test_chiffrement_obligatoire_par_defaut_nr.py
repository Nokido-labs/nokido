"""NR -- le chiffrement at-rest est OBLIGATOIRE PAR DEFAUT a l'installation (decision owner du 2026-10-20).

« Ne me fais pas une version publique au rabais » : VeraCrypt (Windows, macOS) ou cryptsetup/LUKS (Linux) est exige
par le profil d'installation `complet`. Sans lui, l'installation s'ARRETE en le disant, sauf refus EXPLICITE et
CONSIGNE (`--sans-chiffrement`) : un refus est une decision de l'utilisateur, il est ecrit (date, compte, motif) et
le bilan le DIT a chaque passage, jamais il ne disparait. Avant : `chiffrement_at_rest` etait OPTIONNEL
(app/forge_install_prerequis.py), aucune etape de la recette ne le mesurait.

Ce qui est garde :
  * le registre classe `chiffrement_at_rest` REQUIS ; absent sans refus = bloquant du bilan `complet` ;
  * un refus consigne leve le blocage et reste visible (`refus_consignes`), le profil `dev` n'est pas touche ;
  * `nokido-composants` refuse de poser quoi que ce soit sans chiffrement ni refus, nomme `--sans-chiffrement`,
    et consigne le refus quand on le lui donne ; la desinstallation n'est jamais bloquee ;
  * la recette d'installation a une etape `chiffrement`.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _charger(rel, nom):
    spec = importlib.util.spec_from_file_location(nom, RACINE / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def prerequis(tmp_path, monkeypatch):
    m = _charger("app/forge_install_prerequis.py", "prerequis_chiffrement_nr")
    monkeypatch.setattr(m, "FICHIER_REFUS_CHIFFREMENT", tmp_path / "refus_chiffrement.json")
    reel = m.verifier

    def sans_chiffrement(inclure_optionnels=True):
        lignes = reel(inclure_optionnels)
        for l in lignes:
            if l["cle"] == "chiffrement_at_rest":
                l["etat"] = m.ABSENT
        return lignes
    monkeypatch.setattr(m, "verifier", sans_chiffrement)
    return m


def _entree(m):
    tout = m.PREREQUIS.values() if isinstance(m.PREREQUIS, dict) else m.PREREQUIS
    return next(e for e in tout if e["cle"] == "chiffrement_at_rest")


def test_le_registre_exige_le_chiffrement(prerequis):
    assert _entree(prerequis)["niveau"] == prerequis.REQUIS


def test_sans_chiffrement_ni_refus_le_bilan_complet_bloque(prerequis):
    b = prerequis.bilan(profil="complet")
    assert "chiffrement_at_rest" in b["bloquants"]
    assert b["refus_consignes"] == []
    assert "chiffrement_at_rest" not in prerequis.bilan(profil="dev")["bloquants"], "le profil dev n'est pas touche"


def test_un_refus_consigne_leve_le_blocage_et_reste_dit(prerequis):
    chemin = prerequis.consigner_refus_chiffrement("banc de test")
    assert Path(chemin) == prerequis.FICHIER_REFUS_CHIFFREMENT
    fiche = json.loads(Path(chemin).read_text(encoding="utf-8"))
    assert fiche["motif"] == "banc de test" and fiche.get("date") and fiche.get("compte")
    assert prerequis.refus_chiffrement()["motif"] == "banc de test"
    b = prerequis.bilan(profil="complet")
    assert "chiffrement_at_rest" not in b["bloquants"]
    assert b["refus_consignes"] == ["chiffrement_at_rest"], "un refus ne disparait jamais du bilan"


@pytest.fixture
def composants(monkeypatch):
    m = _charger("tools/forge_composants.py", "composants_chiffrement_nr")
    etat = {"poses": 0, "consignes": [], "present": False, "refus": None}

    def poseur():
        etat["poses"] += 1
        return True, "ok"
    monkeypatch.setattr(m, "COMPOSANTS", ("factice",))
    monkeypatch.setattr(m, "POSEURS", {"factice": poseur})
    monkeypatch.setattr(m, "chiffrement_present", lambda: etat["present"])
    monkeypatch.setattr(m, "refus_chiffrement", lambda: etat["refus"])
    monkeypatch.setattr(m, "consigner_refus_chiffrement", lambda motif: etat["consignes"].append(motif) or "f")
    return m, etat


def test_composants_refuse_sans_chiffrement_et_nomme_le_drapeau(composants, capsys):
    m, etat = composants
    rc = m.main(["--composant", "factice"])
    sortie = capsys.readouterr()
    assert rc == 2 and etat["poses"] == 0
    assert "--sans-chiffrement" in sortie.out + sortie.err
    assert etat["consignes"] == []


def test_composants_consigne_le_refus_explicite_puis_installe(composants):
    m, etat = composants
    assert m.main(["--composant", "factice", "--sans-chiffrement"]) == 0
    assert etat["poses"] == 1 and len(etat["consignes"]) == 1


def test_composants_installe_avec_chiffrement_ou_refus_deja_consigne(composants, capsys):
    m, etat = composants
    etat["present"] = True
    assert m.main(["--composant", "factice"]) == 0 and etat["consignes"] == []
    etat["present"], etat["refus"] = False, {"motif": "plus tot", "date": "2026-10-20"}
    assert m.main(["--composant", "factice"]) == 0 and etat["poses"] == 2
    assert "refus" in capsys.readouterr().out.lower(), "un refus deja consigne est rappele, pas tu"


def test_la_desinstallation_n_est_jamais_bloquee(composants, monkeypatch):
    m, etat = composants
    monkeypatch.setattr(m, "desinstaller", lambda purger: 0)
    assert m.main(["--desinstaller"]) == 0 and etat["consignes"] == []


def test_la_recette_mesure_le_chiffrement():
    src = (RACINE / "tools" / "forge_install_acceptance.py").read_text(encoding="utf-8")
    assert '@etape("chiffrement"' in src
