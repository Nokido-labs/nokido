"""NR : introspect voit le corps, organe du module, service qui le porte, réflexes câblés.

Demande de l'owner 2026-11-05. Ce qu'il ne peut pas lire reste ILLISIBLE et se nomme dans non_consulte : sous le compte
du hub, ~/.claude/settings.json ne se lit pas, et « aucun réflexe » y serait un mensonge.
"""
import importlib.util
import json
import pathlib

import pytest

_CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "app" / "forge_introspect.py"
_spec = importlib.util.spec_from_file_location("fi_corps_nr", _CHEMIN)
fi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fi)

CENSUS = {"forge_x.py": "Memoire", "hook_garde.py": "Immunite"}
SERVICES = {"forge_x": ["NokidoX"], "forge_y": ["NokidoY"]}
HOOKS = {"hook_garde": [{"evenement": "PreToolUse", "filtre": "Bash"}], "forge_x": [{"evenement": "Stop", "filtre": ""}]}


def _corps(graines, query="question", census=CENSUS, services=SERVICES, hooks=HOOKS):
    nc = []
    return fi._corps(graines, query, nc, census=lambda _n: census, services=lambda _n: services,
                     reflexes=lambda _n: hooks), nc


def _ligne(res, module):
    return next(m for m in res["modules"] if m["module"] == module)


def test_module_rend_organe_service_reflexes():
    res, _ = _corps(["forge_x"])
    assert _ligne(res, "forge_x") == {"module": "forge_x", "organe": "Memoire", "services": ["NokidoX"],
                                      "reflexes": [{"evenement": "Stop", "filtre": ""}]}


def test_module_hors_census_n_est_pas_illisible():
    res, _ = _corps(["forge_z"])
    ligne = _ligne(res, "forge_z")
    assert ligne["organe"] == "non classe" and ligne["services"] == [] and ligne["reflexes"] == []


def test_census_illisible_ne_se_lit_pas_non_classe():
    res, _ = _corps(["forge_x"], census=None)
    assert _ligne(res, "forge_x")["organe"] == "ILLISIBLE"


def test_services_illisibles_ne_se_lisent_pas_vide():
    res, _ = _corps(["forge_x"], services=None)
    assert _ligne(res, "forge_x")["services"] == "ILLISIBLE"


def test_reflexes_illisibles_ne_se_lisent_pas_vide():
    res, _ = _corps(["forge_x"], hooks=None)
    assert _ligne(res, "forge_x")["reflexes"] == "ILLISIBLE"


def test_question_qui_nomme_un_hook_le_decrit():
    res, _ = _corps([], query="pourquoi hook_garde refuse")
    assert _ligne(res, "hook_garde")["reflexes"] == [{"evenement": "PreToolUse", "filtre": "Bash"}]


def test_question_qui_nomme_un_service_le_decrit():
    res, _ = _corps([], query="etat de NokidoY")
    assert _ligne(res, "forge_y")["services"] == ["NokidoY"]


def test_ensemble_toujours_compte():
    res, _ = _corps([])
    assert res["ensemble"] == {"reflexes_cables": 2, "services_portant_un_module": 2}


@pytest.mark.parametrize("mot", ["reflexes", "réflexes", "hooks", "gardes"])
def test_question_sur_les_reflexes_les_liste(mot):
    res, _ = _corps([], query=f"quels {mot} sont en place")
    assert res["reflexes_cables"] == ["forge_x", "hook_garde"]


def test_question_ordinaire_ne_liste_pas_tout():
    res, _ = _corps(["forge_x"])
    assert "reflexes_cables" not in res


def test_liste_bornee_et_dit_le_reste():
    res, _ = _corps([], query="quels hooks", hooks={f"h{i:03}": [] for i in range(80)})
    assert len(res["reflexes_cables"]) == fi._CORPS_LISTE_MAX and res["reflexes_non_listes"] == 80 - fi._CORPS_LISTE_MAX


def test_modules_bornes():
    res, _ = _corps([f"forge_{i}" for i in range(9)])
    assert len(res["modules"]) == 5


def test_lecture_census_absent_se_nomme(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "_CENSUS", tmp_path / "absent.json")
    nc = []
    assert fi._corps_census(nc) is None
    assert nc and "census" in nc[0]["organe"]


def test_lecture_census_reel_forme(tmp_path, monkeypatch):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"module_organ": CENSUS}), encoding="utf-8")
    monkeypatch.setattr(fi, "_CENSUS", f)
    assert fi._corps_census([]) == CENSUS


def test_lecture_services_extrait_le_module(tmp_path, monkeypatch):
    f = tmp_path / "s.toml"
    f.write_text('[[service]]\nname = "NokidoX"\nargs = ["tools/forge_x.py", "--daemon"]\n'
                 '[[service]]\nname = "SansScript"\ncmd = "a.exe"\n', encoding="utf-8")
    monkeypatch.setattr(fi, "_SERVICES_TOML", f)
    assert fi._corps_services([]) == {"forge_x": ["NokidoX"]}


def test_lecture_services_casse_se_nomme(tmp_path, monkeypatch):
    f = tmp_path / "s.toml"
    f.write_text("[[service\n", encoding="utf-8")
    monkeypatch.setattr(fi, "_SERVICES_TOML", f)
    nc = []
    assert fi._corps_services(nc) is None and "services" in nc[0]["organe"]


def _faux_hic(inventaire, hooks):
    return type("H", (), {
        "_inventaire_settings": staticmethod(lambda _chemins=None: inventaire),
        "_iter_hook_commands": staticmethod(lambda s: s["c"]),
        "_targets_from_command": staticmethod(lambda c: c.split()),
    })


def test_lecture_reflexes_settings_illisible_se_nomme(tmp_path, monkeypatch):
    lu = tmp_path / "s.json"
    lu.write_text(json.dumps({"c": [["PreToolUse", "Bash", "C:/py/python.exe C:/t/hook_garde.py"]]}), encoding="utf-8")
    monkeypatch.setattr(fi, "_hook_integrity", lambda: _faux_hic([(str(lu), "lu"), ("X:/owner.json", "illisible: refus")], {}))
    nc = []
    assert fi._corps_reflexes(nc) == {"hook_garde": [{"evenement": "PreToolUse", "filtre": "Bash"}]}
    assert any("X:/owner.json" in n["organe"] and "refus" in n["raison"] for n in nc)


def test_lecture_reflexes_aucun_settings_lu_vaut_illisible(monkeypatch):
    monkeypatch.setattr(fi, "_hook_integrity", lambda: _faux_hic([("X:/owner.json", "illisible: refus")], {}))
    assert fi._corps_reflexes([]) is None


def test_lecture_reflexes_module_absent_se_nomme(monkeypatch):
    def casse():
        raise ImportError("x")

    monkeypatch.setattr(fi, "_hook_integrity", casse)
    nc = []
    assert fi._corps_reflexes(nc) is None and nc


def _partiel(graines, query="question"):
    """Comme sous un compte de service : les réflexes de l'owner n'ont pas pu être lus."""
    nc = []

    def lecture(n):
        n.append({"organe": "reflexes de X:/owner.json", "raison": "absent pour ce compte"})
        return dict(HOOKS)

    return fi._corps(graines, query, nc, census=lambda _n: CENSUS, services=lambda _n: SERVICES, reflexes=lecture)


def test_lecture_partielle_le_compte_se_dit_partiel():
    assert _partiel([])["ensemble"]["reflexes_partiels"] is True


def test_lecture_complete_ne_se_dit_pas_partielle():
    res, _ = _corps([])
    assert "reflexes_partiels" not in res["ensemble"]


def test_lecture_partielle_un_module_sans_cablage_vu_n_est_pas_sans_reflexe():
    assert _ligne(_partiel(["forge_y"]), "forge_y")["reflexes"] == "ILLISIBLE"


def test_lecture_partielle_un_cablage_vu_reste_rendu():
    assert _ligne(_partiel(["forge_x"]), "forge_x")["reflexes"] == [{"evenement": "Stop", "filtre": ""}]


def test_question_qui_nomme_un_module_du_census_le_decrit():
    res, _ = _corps([], query="que fait forge_seul ici", census={"forge_seul.py": "Memoire"})
    assert _ligne(res, "forge_seul")["organe"] == "Memoire"


def _introspect_trouve(monkeypatch, budget):
    """Un symbole, un module et une procédure existent : seul le budget peut les retirer."""
    monkeypatch.setattr(fi, "_code", lambda *a, **k: [{"symbole": "s", "definitions": [{"file": "app/forge_x.py"}]}])
    monkeypatch.setattr(fi, "_succes", lambda *a, **k: [{"etat": "PROUVE"}])
    monkeypatch.setattr(fi, "_perimetre", lambda p: [])
    for nom in ("_litteraux", "_veille", "_enquetes"):
        monkeypatch.setattr(fi, nom, lambda *a, **k: [])
    monkeypatch.setattr(fi, "_modules", lambda *a, **k: [{"module": "forge_x"}])
    monkeypatch.setattr(fi, "_voisinage", lambda *a, **k: {})
    monkeypatch.setattr(fi, "_corps_census", lambda _n: CENSUS)
    monkeypatch.setattr(fi, "_corps_services", lambda _n: SERVICES)
    monkeypatch.setattr(fi, "_corps_reflexes", lambda _n: HOOKS)
    return fi.introspect("question", budget_tokens=budget, jit=object())


def test_budget_court_ne_fabrique_pas_une_absence(monkeypatch):
    res = _introspect_trouve(monkeypatch, 10)
    assert res["symboles_trouves"] == [] and res["budget"]["retire"]["symboles_trouves"] == 1
    assert "n'existe" not in res["verdict"] and "budget" in res["verdict"]


def test_budget_court_garde_la_recommandation_des_procedures(monkeypatch):
    res = _introspect_trouve(monkeypatch, 10)
    assert res["procedures_connues"] == [] and "1 procedure" in res["recommandation"]


def test_budget_large_sans_verdict_quand_on_a_trouve(monkeypatch):
    assert "verdict" not in _introspect_trouve(monkeypatch, 4000)


def test_rien_trouve_garde_le_verdict_d_absence(monkeypatch):
    for nom in ("_code", "_litteraux", "_veille", "_enquetes", "_succes", "_modules"):
        monkeypatch.setattr(fi, nom, lambda *a, **k: [])
    monkeypatch.setattr(fi, "_voisinage", lambda *a, **k: {})
    monkeypatch.setattr(fi, "_corps_census", lambda _n: CENSUS)
    monkeypatch.setattr(fi, "_corps_services", lambda _n: SERVICES)
    monkeypatch.setattr(fi, "_corps_reflexes", lambda _n: HOOKS)
    assert "PAS une preuve" in fi.introspect("question", budget_tokens=10, jit=object())["verdict"]


def _introspect_isole(monkeypatch, budget=4000):
    for nom in ("_code", "_litteraux", "_veille", "_enquetes", "_succes"):
        monkeypatch.setattr(fi, nom, lambda *a, **k: [])
    monkeypatch.setattr(fi, "_modules", lambda *a, **k: [{"module": "forge_x"}])
    monkeypatch.setattr(fi, "_voisinage", lambda *a, **k: {})
    monkeypatch.setattr(fi, "_corps_census", lambda _n: CENSUS)
    monkeypatch.setattr(fi, "_corps_services", lambda _n: SERVICES)
    monkeypatch.setattr(fi, "_corps_reflexes", lambda _n: HOOKS)
    return fi.introspect("question", budget_tokens=budget, jit=object())


def test_introspect_rend_le_corps(monkeypatch):
    res = _introspect_isole(monkeypatch)
    assert _ligne(res["corps"], "forge_x")["organe"] == "Memoire"


def test_budget_court_sacrifie_le_corps_et_le_dit(monkeypatch):
    res = _introspect_isole(monkeypatch, budget=10)
    assert res["corps"] == {} and res["budget"]["retire"]["corps"] == 1


def _settings_avec_un_hook(profil, script):
    dossier = profil / ".claude"
    dossier.mkdir(parents=True)
    (dossier / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "python C:/x/tools/%s.py" % script}]},
    ]}}), encoding="utf-8")


def test_reflexes_lus_dans_le_profil_de_l_owner_pas_celui_du_compte(tmp_path, monkeypatch):
    """Constat 5/11 : sous SYSTEM, le hub cherchait systemprofile/.claude et perdait les hooks de l'owner."""
    owner, compte = tmp_path / "owner", tmp_path / "systemprofile"
    compte.mkdir()
    _settings_avec_un_hook(owner, "hook_de_l_owner_nr")
    monkeypatch.setenv("LAFORGE_OWNER_HOME", str(owner))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda _c: compte))
    nc = []
    reflexes = fi._corps_reflexes(nc)
    assert "hook_de_l_owner_nr" in reflexes
    assert not [n for n in nc if str(compte) in n["organe"]]


def test_profil_owner_sans_settings_reste_nomme(tmp_path, monkeypatch):
    owner = tmp_path / "owner"
    owner.mkdir()
    monkeypatch.setenv("LAFORGE_OWNER_HOME", str(owner))
    nc = []
    fi._corps_reflexes(nc)
    assert [n for n in nc if str(owner) in n["organe"]]


def _introspect_a_budget_serre(monkeypatch, retrait=20, enquetes=()):
    """Rejoue introspect a la taille mesuree moins `retrait` : seule la marge saute."""
    noms = ["forge_a", "forge_b", "forge_c", "forge_d"]
    res = _introspect_isole(monkeypatch)
    monkeypatch.setattr(fi, "_modules", lambda *a, **k: [{"module": n} for n in noms])
    monkeypatch.setattr(fi, "_enquetes", lambda *a, **k: [dict(e) for e in enquetes])
    plein = fi.introspect("question", budget_tokens=100000, jit=object())
    assert len(plein["corps"]["modules"]) == len(noms), res
    return fi.introspect("question", budget_tokens=plein["budget"]["estime"] - retrait, jit=object())


def test_budget_serre_retire_le_corps_module_par_module(monkeypatch):
    """Constat 5/11 : a budget 1000, `corps` tombait en entier avant toute autre section."""
    res = _introspect_a_budget_serre(monkeypatch)
    assert res["budget"]["retire"]["corps"] >= 1
    assert 0 < len(res["corps"]["modules"]) < 4
    assert res["corps"]["modules"][0]["module"] == "forge_a"


def test_les_enquetes_tombent_avant_le_corps(monkeypatch):
    enquetes = [{"id": "e%d" % i, "conclusion": "x" * 200} for i in range(3)]
    res = _introspect_a_budget_serre(monkeypatch, retrait=5, enquetes=enquetes)
    assert res["budget"]["retire"].get("enquetes_anterieures", 0) >= 1
    assert "corps" not in res["budget"]["retire"]
