"""NR -- l'applicateur de verification de roadmap cherche une cle dans TOUTES ses zones de vie.

Constat du dry-run du 7/11 (cbd873331 99) : il ne lisait que `architecture_rules` et sautait comme « absent » des cles
vivant dans `roadmap` et `active_bugs` (clos=1 au lieu des entrees attendues). Regles verifiees ici :
- la cle est cherchee dans architecture_rules, roadmap, active_bugs, et ecrite dans la zone ou elle vit ;
- une cle presente dans plusieurs zones est signalee et sautee, sans deviner ;
- une cle absente le dit en nommant les zones cherchees ;
- une valeur JSON (`{"intent":"ROADMAP_ITEM","etat":...}`) garde un JSON valide : seul le champ `etat` est mis a jour ;
- la cloture reste exigeant une preuve, le dry-run reste le defaut, `--exclure` est respecte.

Tableau noir JETABLE (bb._DB redirige sous tmp_path) ; rapport lu par une doublure de `git show`.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import forge_roadmap_verif_appliquer as ap  # noqa: E402

DATE = "2026-11-07"
PREUVE_CLE = "CURRENT_preuve_nr"  # cle existante (architecture_rules) : preuve de remplacement, sans git


@pytest.fixture
def bb(tmp_path, monkeypatch):
    """Module blackboard reel, pointe sur une base jetable ; journal d'intention neutralise."""
    sys.path[:0] = [str(ROOT / "app"), str(ROOT)]
    import forge_swarm_blackboard as bb_mod  # noqa: PLC0415

    monkeypatch.setattr(bb_mod, "_DB", tmp_path / "swarm_nr.db")
    # connexion ecrivain persistante : elle ne doit pas pointer une base d'un autre test
    monkeypatch.setattr(bb_mod, "_writer_conn", None)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_intention_journal", None)
    bb_mod.init_db()
    yield bb_mod
    if bb_mod._writer_conn is not None:
        bb_mod._writer_conn.close()
        bb_mod._writer_conn = None


def _semer(bb_mod, zone, key, value, category="roadmap"):
    c = sqlite3.connect(str(bb_mod._DB))
    c.execute("INSERT INTO swarm_blackboard(zone,key,value,category,trust,worker_id,updated_at) "
              "VALUES(?,?,?,?,?,?,?)", (zone, key, value, category, 0.5, "nr", time.time()))
    c.commit()
    c.close()


def _lire(bb_mod, zone):
    return {r["key"]: str(r["value"]) for r in bb_mod.read_zone(zone, limit=500)}


def _rapport(monkeypatch, entrees):
    """Doublure de `git show sha:chemin` : rend le rapport ; le reste de _git est reel."""
    reel = ap._git

    def faux(*a):
        if a and a[0] == "show":
            class R:
                returncode = 0
                stdout = json.dumps(entrees)
            return R()
        return reel(*a)

    monkeypatch.setattr(ap, "_git", faux)


def _lancer(extra):
    return ap.main(["HEAD", "lot_nr", "--date", DATE, "--fichier-date", "20261107", *extra])


def test_cle_en_zone_roadmap_est_trouvee_et_ecrite_dans_roadmap(bb, monkeypatch, capsys):
    _semer(bb, "architecture_rules", PREUVE_CLE, "regle", category="roadmap")
    _semer(bb, "roadmap", "ITEM_TEXTE_NR", "texte d'origine")
    _rapport(monkeypatch, [{"key": "ITEM_TEXTE_NR", "verdict": "FAIT", "preuves": ["remplace par " + PREUVE_CLE]}])

    assert _lancer(["--apply"]) == 0

    sortie = capsys.readouterr().out
    assert "absent du tableau noir" not in sortie
    apres = _lire(bb, "roadmap")["ITEM_TEXTE_NR"]
    assert apres.startswith("[CLOS %s :" % DATE)
    assert apres.endswith("texte d'origine")
    assert "ITEM_TEXTE_NR" not in _lire(bb, "architecture_rules")


def test_cle_active_bugs_json_met_a_jour_etat_et_reste_du_json_valide(bb, monkeypatch):
    _semer(bb, "architecture_rules", PREUVE_CLE, "regle", category="roadmap")
    valeur = json.dumps({"intent": "ROADMAP_ITEM", "etat": "OUVERT"}, ensure_ascii=False)
    _semer(bb, "active_bugs", "BUG_JSON_NR", valeur, category="roadmap")
    _rapport(monkeypatch, [{"key": "BUG_JSON_NR", "verdict": "PARTIEL", "reste": "encore un test",
                            "preuves": []}])

    assert _lancer(["--apply"]) == 0

    apres = _lire(bb, "active_bugs")["BUG_JSON_NR"]
    objet = json.loads(apres)  # JSON valide, aucun texte devant
    assert objet["intent"] == "ROADMAP_ITEM"
    # Le marqueur reste un MOT que le lecteur du SSoT comprend ; la preuve vit a cote, jamais dans `etat`.
    assert objet["etat"] == "PARTIEL"
    assert objet["verification"].startswith("[PARTIEL %s :" % DATE)


def test_lire_zones_voit_architecture_rules_hors_categorie_roadmap_et_au_dela_de_500():
    class Faux:
        def __init__(self):
            self.appels = []

        def read_zone(self, zone, **kw):
            self.appels.append((zone, kw))
            return []

    f = Faux()
    ap.lire_zones(f)
    assert all("category" not in kw for _, kw in f.appels)
    assert all(kw.get("limit", 0) >= 5000 for _, kw in f.appels)


def test_cle_dans_deux_zones_est_sautee_sans_deviner(bb, monkeypatch, capsys):
    _semer(bb, "architecture_rules", PREUVE_CLE, "regle", category="roadmap")
    _semer(bb, "roadmap", "DOUBLE_NR", "A")
    _semer(bb, "active_bugs", "DOUBLE_NR", "B")
    _rapport(monkeypatch, [{"key": "DOUBLE_NR", "verdict": "FAIT", "preuves": ["remplace par " + PREUVE_CLE]}])

    assert _lancer(["--apply"]) == 0

    sortie = capsys.readouterr().out
    assert "DOUBLE_NR" in sortie and "plusieurs zones" in sortie
    assert _lire(bb, "roadmap")["DOUBLE_NR"] == "A"
    assert _lire(bb, "active_bugs")["DOUBLE_NR"] == "B"


def test_cle_absente_nomme_les_trois_zones_cherchees(bb, monkeypatch, capsys):
    _semer(bb, "architecture_rules", PREUVE_CLE, "regle", category="roadmap")
    _rapport(monkeypatch, [{"key": "FANTOME_NR", "verdict": "FAIT", "preuves": ["remplace par " + PREUVE_CLE]}])

    assert _lancer(["--apply"]) == 0

    sortie = capsys.readouterr().out
    assert "FANTOME_NR" in sortie and "absent du tableau noir" in sortie
    for zone in ("architecture_rules", "roadmap", "active_bugs"):
        assert zone in sortie


def test_sans_apply_rien_n_est_ecrit(bb, monkeypatch):
    _semer(bb, "architecture_rules", PREUVE_CLE, "regle", category="roadmap")
    _semer(bb, "roadmap", "ITEM_SEC_NR", "intact")
    _rapport(monkeypatch, [{"key": "ITEM_SEC_NR", "verdict": "FAIT", "preuves": ["remplace par " + PREUVE_CLE]}])

    assert _lancer([]) == 0

    assert _lire(bb, "roadmap")["ITEM_SEC_NR"] == "intact"


def test_exclure_et_cloture_sans_preuve_restent_inchanges(bb, monkeypatch):
    _semer(bb, "architecture_rules", PREUVE_CLE, "regle", category="roadmap")
    _semer(bb, "roadmap", "EXCLU_NR", "x")
    _semer(bb, "roadmap", "SANS_PREUVE_NR", "y")
    _rapport(monkeypatch, [
        {"key": "EXCLU_NR", "verdict": "FAIT", "preuves": ["remplace par " + PREUVE_CLE]},
        {"key": "SANS_PREUVE_NR", "verdict": "FAIT", "preuves": []},
    ])

    assert _lancer(["--apply", "--exclure", "EXCLU_NR"]) == 0

    roadmap = _lire(bb, "roadmap")
    assert roadmap["EXCLU_NR"] == "x"
    assert roadmap["SANS_PREUVE_NR"].startswith("[VERIF_A_FAIRE %s" % DATE)
