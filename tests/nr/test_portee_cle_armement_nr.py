"""NR - la cle d'armement porte une PORTEE : `l1` n'ouvre que les reglages L1 (owner 15/10).

Mesure du 15/10, avant le 1er essai RSI : la porte du juge (`evolution_autorisee`) est lue aussi
par submit_candidate_to_judge (qui ecrit un candidat de CODE dans l'arbre vivant), par la boucle
de mutation gardee et par le merge gate. Une cle sans portee armait tout cela pour un essai qui ne
devait toucher qu'un reglage. Decision owner : « L1 seul ». Vide ou contenu inconnu = rien.
Frein, cle et verrou humain sont simules : aucun fichier de sandbox/ n'est touche.
"""
import sys
import types

import pytest

from nokido_agent.app import forge_mutation_judge as juge
from nokido_agent.app import forge_proposal_applier as app


@pytest.fixture
def cle(monkeypatch, tmp_path):
    opsec = types.ModuleType("nokido_agent.app.forge_opsec")
    opsec.human_lock_state = lambda: ("LIBRE", "")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_opsec", opsec)
    monkeypatch.setattr(juge, "_FREIN_EVOLUTION", tmp_path / "evolution.halt")
    monkeypatch.setattr(juge, "_CLE_ARMEMENT", tmp_path / "evolution.armed")
    for v in ("LAFORGE_EVOLUTION_ARMED", "LAFORGE_APPLIER_ARMED"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path / "evolution.armed"


def test_cle_l1_ouvre_le_l1_et_ferme_le_code(cle):
    cle.write_text("l1\n", encoding="utf-8")
    assert juge.evolution_autorisee(portee="L1")["autorisee"] is True
    r = juge.evolution_autorisee()  # defaut = mutation de code
    assert r["autorisee"] is False and r["etat"] == "DESARMEE" and "portee L1" in r["motif"]
    assert app.portee_armement() == "L1" and app.arme() is True
    assert app.porte_evolution()["autorisee"] is True  # applicateur et controleur demandent L1


def test_cle_tout_ouvre_tout(cle):
    cle.write_text("TOUT", encoding="utf-8")
    assert juge.evolution_autorisee()["autorisee"] is True
    assert app.portee_armement() == "TOUT"


@pytest.mark.parametrize("contenu", ["", "owner", "oui", "l1 tout"])
def test_cle_vide_ou_inconnue_n_arme_rien(cle, contenu):
    cle.write_text(contenu, encoding="utf-8")
    r = juge.evolution_autorisee(portee="L1")
    assert r["autorisee"] is False and r["etat"] == "INCONNU" and "non reconnu" in r["motif"]
    assert app.portee_armement() is None and app.arme() is False


def test_cle_utf16_de_powershell_lue(cle):
    cle.write_bytes("l1\r\n".encode("utf-16"))  # Out-File de PowerShell 5.1 : BOM + UTF-16
    assert juge.portee_cle() == "L1"


def test_juge_variable_et_cle_l1_la_plus_restrictive_gagne(cle, monkeypatch):
    """Debat tour 3, Q3 (15/10) : la variable (TOUT) n'ecrase plus une cle `l1` -- cote JUGE (code)."""
    cle.write_text("l1", encoding="utf-8")
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    r = juge.evolution_autorisee()  # mutation de code
    assert r["autorisee"] is False and r["etat"] == "DESARMEE", r
    assert "plus restrictive" in r["motif"] and "LAFORGE_EVOLUTION_ARMED" in r["motif"], r
    r1 = juge.evolution_autorisee(portee="L1")
    assert r1["autorisee"] is True and "plus restrictive" in r1["motif"], r1


@pytest.mark.parametrize("contenu", ["", "owner"])
def test_juge_variable_et_cle_inconnue_ferme(cle, monkeypatch, contenu):
    cle.write_text(contenu, encoding="utf-8")
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    r = juge.evolution_autorisee(portee="L1")
    assert r["autorisee"] is False and r["etat"] == "INCONNU" and "plus restrictive" in r["motif"], r


def test_juge_variable_seule_ou_cle_tout_arme_sans_motif(cle, monkeypatch):
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    assert juge.evolution_autorisee() == {"autorisee": True, "etat": "ARMEE", "motif": ""}
    cle.write_text("tout", encoding="utf-8")
    assert juge.evolution_autorisee() == {"autorisee": True, "etat": "ARMEE", "motif": ""}


def test_applicateur_aligne_sur_le_juge(cle, monkeypatch):
    """Decision owner Q3 du 15/10 (« aligner + exempter RAM ») : cote APPLICATEUR aussi, entre la
    variable et la cle, la portee la plus restrictive gagne ; cle vide ou inconnue = rien."""
    monkeypatch.setenv("LAFORGE_APPLIER_ARMED", "1")
    assert app.portee_armement() == "TOUT"                     # variable seule
    cle.write_text("tout", encoding="utf-8")
    assert app.portee_armement() == "TOUT"
    cle.write_text("l1", encoding="utf-8")
    assert app.portee_armement() == "L1"                       # la plus restrictive gagne
    cle.write_text("n'importe quoi", encoding="utf-8")
    assert app.portee_armement() is None


def test_appliquer_l1_et_variable_exempte_les_seuls_reflexes_ram(cle, monkeypatch):
    """Sous L1, les types de `REFLEXES_RAM` s'executent si la variable les arme ; un type de reflexe
    hors liste reste en plan (une liste BLANCHE : l'inattendu ne passe pas par defaut)."""
    cle.write_text("l1", encoding="utf-8")
    monkeypatch.setenv("LAFORGE_APPLIER_ARMED", "1")
    plan = [{"id": "ram", "etage": "REFLEXE", "action": {"type": "reclaim_cache", "needed_gb": 1}},
            {"id": "neuf", "etage": "REFLEXE", "action": {"type": "type_de_reflexe_futur"}}]
    monkeypatch.setattr(app, "plan", lambda: plan)
    monkeypatch.setattr(app, "reprendre_orphelins_l1", lambda: [])
    monkeypatch.setattr(app, "FENETRE_S", 0)
    monkeypatch.setattr(app, "_sante_globale", lambda: 100.0)
    monkeypatch.setattr(app, "_observable", lambda a: {"valeur_go": None, "source": "aucune"})
    monkeypatch.setattr(app, "_marquer", lambda *a, **k: None)     # jamais le magasin reel
    executes = []
    monkeypatch.setattr(app, "_executer", lambda a: executes.append(a["type"]) or {"ok": True})
    r = app.appliquer()
    assert r["portee"] == "L1"
    assert executes == ["reclaim_cache"]
    assert [h["id"] for h in r["hors_portee"]] == ["neuf"]


def test_le_frein_gagne_sur_une_cle_l1(cle):
    cle.write_text("l1", encoding="utf-8")
    (cle.parent / "evolution.halt").write_text("essai", encoding="utf-8")
    assert juge.evolution_autorisee(portee="L1")["etat"] == "HALTED"
    assert app.portee_armement() is None


def test_appliquer_cle_l1_laisse_les_reflexes_en_plan(cle, monkeypatch):
    cle.write_text("l1", encoding="utf-8")
    plan = [{"id": "p1", "etage": "REFLEXE", "action": {"type": "reclaim_cache"}},
            {"id": "p2", "etage": "REFLEXE",
             "action": {"type": "set_param", "param": "embed.batch_size", "valeur": 40}}]
    monkeypatch.setattr(app, "plan", lambda: plan)
    monkeypatch.setattr(app, "reprendre_orphelins_l1", lambda: [])
    vus = []
    monkeypatch.setattr(app, "_appliquer_set_param",
                        lambda x: vus.append(x["id"]) or {"id": x["id"], "fait": True})

    def _interdit(*a, **k):
        raise AssertionError("un reflexe hors portee a ete execute")

    monkeypatch.setattr(app, "_executer", _interdit)
    r = app.appliquer()
    assert r["portee"] == "L1" and r["dry_run"] is False
    assert vus == ["p2"]
    assert [h["id"] for h in r["hors_portee"]] == ["p1"]


def test_submit_candidate_refuse_sous_cle_l1(cle, monkeypatch):
    """Le chemin qui ecrit du CODE dans l'arbre vivant reste ferme sous une cle L1."""
    from nokido_agent.app import forge_autonomous_loops as loops

    cle.write_text("l1", encoding="utf-8")
    notes = []
    monkeypatch.setattr(loops, "record_evolution_experience",
                        lambda d: notes.append(d) or "exp-test")
    r = loops.submit_candidate_to_judge("ref", "app/forge_x.py", "print('x')\n")
    assert r["status"] == "HALTED" and r["porte"]["etat"] == "DESARMEE"
    assert notes and notes[0]["verdict"] == "HALTED"
