"""NR — reprise par surface du cliquet de mutation (owner 15/10 : « les accelerations CI oui »).

Une surface dont l'empreinte (module, suite, moteur, conftest, plafond, interpreteur) n'a pas
bouge reprend son resultat au lieu de muter (~5 min par CI) ; toute modification la fait
rejouer ; une surface non propre n'est jamais reprise ; un resultat en erreur n'est jamais
memorise ; `--ecrire-socle` et `--sans-reprise` mesurent toujours.
Le moteur de mutation est simule : aucun mutant reel, aucun fichier ecrit hors tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture
def banc(tmp_path, monkeypatch):
    import forge_mutation_ratchet as R
    from nokido_agent.tools import forge_mutation_test as M

    monkeypatch.setattr(sys, "path", list(sys.path))  # mesurer() insere ROOT : on restaure
    (tmp_path / "tools").mkdir()
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tools" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "nr" / "test_mod_nr.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tmp_path / "tools" / "forge_mutation_test.py").write_text("# moteur\n", encoding="utf-8")
    monkeypatch.setattr(R, "ROOT", str(tmp_path))
    monkeypatch.setattr(R, "SURFACES", [("tools/mod.py", "tests/nr/test_mod_nr.py", 4)])
    monkeypatch.setenv("LAFORGE_MUTATION_REPRISE_FICHIER", str(tmp_path / "reprise.json"))
    monkeypatch.delenv("LAFORGE_MUTATION_REPRISE", raising=False)
    appels: list = []
    propre = {"ok": True}
    monkeypatch.setattr(M, "_git_propre",
                        lambda module: (propre["ok"], "" if propre["ok"] else "modifie"))
    monkeypatch.setattr(M, "executer", lambda module, test, cap: appels.append(module) or
                        {"mutants": 4, "tues": 3, "score": 75, "survivants": [{"genre": "comparaison"}]})
    return R, tmp_path, appels, propre


def test_surface_inchangee_reprise_sans_muter(banc):
    R, _tmp, appels, _ = banc
    a = R.mesurer(reprise=True)
    b = R.mesurer(reprise=True)
    assert appels == ["tools/mod.py"]
    assert a["par_cle"] == b["par_cle"] == {"tools/mod.py|comparaison": 1}
    assert a["surfaces"][0]["repris"] is False and b["surfaces"][0]["repris"] is True


@pytest.mark.parametrize("rel", ["tools/mod.py", "tests/nr/test_mod_nr.py", "tools/forge_mutation_test.py"])
def test_une_modification_fait_rejouer(banc, rel):
    R, tmp, appels, _ = banc
    R.mesurer(reprise=True)
    p = tmp / rel
    p.write_text(p.read_text(encoding="utf-8") + "# change\n", encoding="utf-8")
    r = R.mesurer(reprise=True)
    assert len(appels) == 2 and r["surfaces"][0]["repris"] is False


def test_reprise_perimee_au_dela_de_7_jours(banc):
    R, tmp, appels, _ = banc
    R.mesurer(reprise=True)
    f = tmp / "reprise.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["surfaces"]["tools/mod.py"]["ts"] -= R.REPRISE_AGE_MAX_S + 1
    f.write_text(json.dumps(d), encoding="utf-8")
    R.mesurer(reprise=True)
    assert len(appels) == 2


def test_surface_non_propre_jamais_reprise(banc):
    R, _tmp, appels, propre = banc
    R.mesurer(reprise=True)
    propre["ok"] = False
    r = R.mesurer(reprise=True)
    assert "erreur" in r["surfaces"][0] and len(appels) == 1


def test_sans_reprise_mute_toujours(banc):
    R, _tmp, appels, _ = banc
    R.mesurer(reprise=True)
    R.mesurer(reprise=False)
    assert len(appels) == 2


def test_resultat_en_erreur_jamais_memorise(banc, monkeypatch):
    R, _tmp, appels, _ = banc
    from nokido_agent.tools import forge_mutation_test as M

    monkeypatch.setattr(M, "executer", lambda m, t, c: appels.append(m) or {"erreur": "suite deja rouge"})
    R.mesurer(reprise=True)
    R.mesurer(reprise=True)
    assert len(appels) == 2


def test_chemin_reel_check_dit_la_reprise_et_le_socle_mesure_toujours(banc, monkeypatch, capsys):
    R, tmp, appels, _ = banc
    socle = tmp / "socle.json"
    socle.write_text(json.dumps({"par_cle": {"tools/mod.py|comparaison": 1}}), encoding="utf-8")
    monkeypatch.setattr(R, "SOCLE", str(socle))
    monkeypatch.setattr(sys, "argv", ["forge_mutation_ratchet.py", "--check"])
    assert R.main() == 0
    assert R.main() == 0
    assert "[repris : surface inchangee]" in capsys.readouterr().out and len(appels) == 1
    monkeypatch.setattr(sys, "argv", ["forge_mutation_ratchet.py", "--ecrire-socle"])
    R.main()
    assert len(appels) == 2  # le socle se mesure toujours, jamais sur une reprise


def test_la_reprise_vit_dans_l_arbre_principal(monkeypatch):
    import forge_mutation_ratchet as R

    monkeypatch.delenv("LAFORGE_MUTATION_REPRISE_FICHIER", raising=False)
    chemin = Path(R._fichier_reprise())
    assert chemin.name == "mutation_ratchet_reprise.json" and chemin.parent.name == "sandbox"
