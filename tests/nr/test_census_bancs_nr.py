"""NR -- les bancs du census (owner 23/10, GO : force sur tous les LLM joignables + effort Claude haiku/sonnet/opus).

Aucun banc n'est LANCE ici : le fournisseur est factice. Juges DETERMINISTES uniquement (execution de tests caches hors
ligne, reponse exacte, egalite JSON). Garde-fous : PAUSE_S, 429 = INDISPONIBLE nomme (jamais echec du modele), cout reel
cumule par cible avec arret au budget, dry-run sans aucun appel, aucune donnee du projet ni secret dans les prompts.
Rapport : sandbox/workspace/rapport_bancs_census_20261023.md
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as C  # noqa: E402
import forge_free_tier_census_bancs as D  # noqa: E402

# Solutions de reference : prouvent que les tests caches sont CORRECTS (un banc faux accuserait le modele).
REFERENCES = {
    "somme_pairs": "def somme_pairs(liste):\n    return sum(x for x in liste if x % 2 == 0)",
    "inverser_mots": "def inverser_mots(s):\n    return ' '.join(reversed(s.split(' ')))",
    "est_palindrome": "def est_palindrome(s):\n    t = [c.lower() for c in s if c.isalnum()]\n    return t == t[::-1]",
    "fibonacci": "def fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a",
    "compter_voyelles": "def compter_voyelles(s):\n    return sum(1 for c in s.lower() if c in 'aeiou')",
    "fusionner_tries": "def fusionner_tries(a, b):\n    return sorted(a + b)",
    "premiers_jusqua": "def premiers_jusqua(n):\n    return [k for k in range(2, n + 1) if all(k % d for d in range(2, int(k ** .5) + 1))]",
    "pgcd": "def pgcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a",
    "aplatir": "def aplatir(l):\n    r = []\n    for x in l:\n        r += aplatir(x) if isinstance(x, list) else [x]\n    return r",
    "anagrammes": "def anagrammes(a, b):\n    n = lambda s: sorted(s.lower().replace(' ', ''))\n    return n(a) == n(b)",
    "somme_chiffres": "def somme_chiffres(n):\n    return sum(int(c) for c in str(n))",
    "compresser": "def compresser(s):\n    import itertools\n    return ''.join(k + str(len(list(g))) for k, g in itertools.groupby(s))",
}


# ---------------------------------------------------------------- les items -------------------------------------------
def test_tailles_des_bancs_conformes_au_plan():
    assert len(D.CODE) == 18 and len(D.RAISONNEMENT) == 15 and len(D.OUTILS) == 10 and len(D.VISION) == 8
    assert len(D.EFFORT) == 6
    assert sorted(t["taille"] for t in D.EFFORT) == ["L", "L", "M", "M", "S", "S"]
    assert C.BANCS["raisonnement"]["items"] == 15 and C.BANCS["effort"]["items"] == 6
    assert C.BANCS["effort"]["repetitions"] == 3 and len(C.BANCS["effort"]["niveaux"]) == 3


@pytest.mark.parametrize("item", D.CODE, ids=lambda i: i["id"])
def test_tests_caches_de_code_acceptent_la_reference(item):
    assert C.juge_code(item, "```python\n%s\n```" % REFERENCES[item["fonction"]]) is True


def test_juge_code_refuse_faux_boucle_infinie_et_absent():
    item = D.CODE[0]
    assert C.juge_code(item, "def somme_pairs(liste):\n    return sum(liste)") is False
    assert C.juge_code(item, "def somme_pairs(liste):\n    while True:\n        pass") is False
    assert C.juge_code(item, "je ne sais pas") is False
    assert C.juge_code(item, "def autre(x):\n    return 1") is False


def test_juge_code_n_ecrit_ni_ne_lit_hors_du_bac(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert C.juge_code(D.CODE[7], "```python\n%s\n```" % REFERENCES["pgcd"]) is True
    assert list(tmp_path.iterdir()) == []


def test_juge_exact():
    r = D.RAISONNEMENT[0]
    assert r["reponse"] == "165"
    assert C.juge_exact(r, "Calcul...\nReponse finale: 165") is True
    assert C.juge_exact(r, "Reponse finale : **165** minutes") is True
    assert C.juge_exact(r, "Reponse finale: 1650") is False
    assert C.juge_exact(r, "Reponse finale: 164") is False
    assert C.juge_exact(r, "") is False
    chloe = D.RAISONNEMENT[4]
    assert C.juge_exact(chloe, "Reponse finale: Chlo\u00e9") is True
    assert C.juge_exact(chloe, "Chloe est la plus petite. Reponse finale: Bob") is False


def test_juge_outils_egalite_json_nom_et_arguments():
    it = D.OUTILS[1]
    ok = [{"name": "add", "arguments": {"a": 17, "b": 25}}]
    assert C.juge_outils(it, ok) is True
    assert C.juge_outils(it, [{"name": "add", "arguments": json.dumps({"b": 25, "a": 17})}]) is True
    assert C.juge_outils(it, [{"name": "add", "arguments": {"a": 17, "b": 26}}]) is False
    assert C.juge_outils(it, [{"name": "add", "arguments": {"a": 17, "b": 25, "c": 1}}]) is False
    assert C.juge_outils(it, [{"name": "set_timer", "arguments": {"a": 17, "b": 25}}]) is False
    assert C.juge_outils(it, ok + ok) is False
    assert C.juge_outils(it, []) is False and C.juge_outils(it, None) is False
    assert C.juge_outils(it, [{"name": "add", "arguments": "pas du json"}]) is False


def test_vision_images_synthetiques_pil():
    for it in D.VISION:
        png = D.image_vision(it)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert D.image_vision(it) == png
    assert D.image_vision(D.VISION[0]) != D.image_vision(D.VISION[2])


def test_aucune_donnee_du_projet_ni_secret_dans_les_prompts():
    prompts = [i["prompt"] for b in (D.CODE, D.RAISONNEMENT, D.OUTILS, D.VISION, D.EFFORT) for i in b]
    prompts += [json.dumps(D.OUTILS_SCHEMAS)]
    interdit = re.compile(r"nokido|laforge|forge_|[A-Z]:[/\\]|/Users/|sk-[A-Za-z0-9]|api[_-]?key|token|secret|password", re.I)
    for p in prompts:
        assert not interdit.search(p), p


# ---------------------------------------------------------------- le lanceur ------------------------------------------
def _parfait(appels=None):
    """Fournisseur factice qui REPOND JUSTE a tout, d'apres la requete."""
    def appel(cible, modele, req):
        if appels is not None:
            appels.append((cible, modele, req["banc"], req["item_id"], req.get("effort")))
        b = req["banc"]
        if b == "code":
            it = next(i for i in D.CODE if i["id"] == req["item_id"])
            return {"texte": REFERENCES[it["fonction"]], "cout_usd": 0.01}
        if b == "outils":
            it = next(i for i in D.OUTILS if i["id"] == req["item_id"])
            return {"texte": "", "tool_calls": [it["attendu"]], "cout_usd": 0.01}
        src = {"raisonnement": D.RAISONNEMENT, "vision": D.VISION, "effort": D.EFFORT}[b]
        it = next(i for i in src if i["id"] == req["item_id"])
        return {"texte": "Reponse finale: " + it["reponse"], "cout_usd": 0.01}
    return appel


UNITES = {"cli:claude": ["sonnet"], "cli:vibe": ["vibe"], "swarm:forge_agent_proxy": ["groq"],
          "swarm:free_tier": ["groq:m"]}


def _rien(_s):
    return None


@pytest.fixture(autouse=True)
def _refs_items_durs():
    from tests.nr.test_census_bancs_suites_nr import REF_DURS   # references des items durs c13-c18 (import tardif)
    REFERENCES.update(REF_DURS)


@pytest.fixture(autouse=True)
def _census_isole(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "SORTIE", tmp_path / "census_isole.json")   # la passe en ligne consigne : jamais le vrai census


@pytest.fixture
def sans_pause(monkeypatch):
    monkeypatch.setattr(C, "PAUSE_S", 1.5)


def test_lancer_juge_chaque_banc_et_note_la_force(sans_pause):
    r = C.lancer_bancs(["swarm:free_tier"], ["code", "raisonnement", "outils", "vision"], _parfait(),
                       unites=UNITES, sleep=_rien)
    u = r["cibles"]["swarm:free_tier"]["unites"]["groq:m"]
    for banc, n in (("code", 18), ("raisonnement", 15), ("outils", 10), ("vision", 8)):
        assert u["bancs"][banc]["echantillon"] == n and u["bancs"][banc]["valeur"] == 1.0, banc
        assert u["bancs"][banc]["juge"] == "deterministe"
    assert r["cibles"]["swarm:free_tier"]["appels"] == 51


def test_lancer_distingue_une_mauvaise_reponse_d_une_bonne(sans_pause):
    def moitie(cible, modele, req):
        ok = int(req["item_id"][1:]) % 2 == 0
        it = next(i for i in D.RAISONNEMENT if i["id"] == req["item_id"])
        return {"texte": "Reponse finale: " + (it["reponse"] if ok else "xx"), "cout_usd": 0.0}
    r = C.lancer_bancs(["swarm:free_tier"], ["raisonnement"], moitie, unites=UNITES, sleep=_rien)
    b = r["cibles"]["swarm:free_tier"]["unites"]["groq:m"]["bancs"]["raisonnement"]
    assert b["echantillon"] == 15 and b["reussis"] == 7 and b["valeur"] == pytest.approx(7 / 15)


def test_pause_s_respectee_entre_deux_appels_de_la_meme_cible(monkeypatch):
    monkeypatch.setattr(C, "PAUSE_S", 2.25)
    pauses = []
    C.lancer_bancs(["swarm:free_tier"], ["outils"], _parfait(), unites=UNITES, sleep=pauses.append)
    assert pauses and all(p == 2.25 for p in pauses)
    assert len(pauses) == 9


def test_429_est_indisponible_nomme_jamais_un_echec_du_modele(sans_pause):
    n = {"k": 0}

    def limite(cible, modele, req):
        n["k"] += 1
        if n["k"] > 3:
            raise C.Limite429("HTTP 429 retry-after=30")
        return _parfait()(cible, modele, req)
    r = C.lancer_bancs(["swarm:free_tier"], ["raisonnement"], limite, unites=UNITES, sleep=_rien)
    u = r["cibles"]["swarm:free_tier"]["unites"]["groq:m"]
    assert u["etat"] == "INDISPONIBLE" and "429" in u["motif"]
    b = u["bancs"]["raisonnement"]
    assert b["echantillon"] == 3 and b["reussis"] == 3 and b["valeur"] == 1.0
    assert n["k"] == 4


def test_429_des_le_premier_appel_ne_donne_aucune_force(sans_pause):
    def toujours(cible, modele, req):
        raise C.Limite429("HTTP 429")
    r = C.lancer_bancs(["cli:claude"], ["code"], toujours, unites=UNITES, sleep=_rien)
    u = r["cibles"]["cli:claude"]["unites"]["sonnet"]
    assert u["etat"] == "INDISPONIBLE" and u["bancs"]["code"]["valeur"] is None and u["bancs"]["code"]["echantillon"] == 0


def test_budget_atteint_arrete_la_cible_sur_le_cout_reel_cumule(sans_pause):
    appels = []
    r = C.lancer_bancs(["cli:claude"], ["code", "raisonnement"], _parfait(appels), budgets={"cli:claude": 0.05},
                       unites=UNITES, sleep=_rien)
    c = r["cibles"]["cli:claude"]
    assert c["etat"] == "BUDGET_ATTEINT"
    assert len(appels) == 5 and c["cout_usd"] == pytest.approx(0.05)
    assert c["budget_usd"] == 0.05


def test_budget_est_par_cible_une_autre_cible_continue(sans_pause):
    appels = []
    r = C.lancer_bancs(["cli:claude", "swarm:free_tier"], ["outils"], _parfait(appels),
                       budgets={"cli:claude": 0.02}, unites=UNITES, sleep=_rien)
    assert r["cibles"]["cli:claude"]["appels"] == 2
    assert r["cibles"]["swarm:free_tier"]["appels"] == 10 and r["cibles"]["swarm:free_tier"]["etat"] == "OK"


def test_cout_inconnu_n_est_jamais_compte_zero(sans_pause):
    def sans_cout(cible, modele, req):
        it = next(i for i in D.RAISONNEMENT if i["id"] == req["item_id"])
        return {"texte": "Reponse finale: " + it["reponse"], "cout_usd": None}
    r = C.lancer_bancs(["cli:vibe"], ["raisonnement"], sans_cout, unites=UNITES, sleep=_rien)
    c = r["cibles"]["cli:vibe"]
    assert c["cout_usd"] is None and c["appels_cout_inconnu"] == 15


def test_non_supporte_est_unknown_pas_zero(sans_pause):
    def sans_image(cible, modele, req):
        if req["banc"] == "vision":
            raise C.NonSupporte("pas d'image en CLI headless")
        return _parfait()(cible, modele, req)
    r = C.lancer_bancs(["cli:vibe"], ["vision", "outils"], sans_image, unites=UNITES, sleep=_rien)
    u = r["cibles"]["cli:vibe"]["unites"]["vibe"]["bancs"]
    assert u["vision"]["valeur"] is None and u["vision"]["etat"] == "UNKNOWN" and "image" in u["vision"]["motif"]
    assert u["vision"]["echantillon"] == 0
    assert u["outils"]["valeur"] == 1.0


def test_erreur_reseau_hors_denominateur(sans_pause):
    def casse(cible, modele, req):
        if req["item_id"] == "r01":
            raise OSError("reseau")
        return _parfait()(cible, modele, req)
    r = C.lancer_bancs(["swarm:free_tier"], ["raisonnement"], casse, unites=UNITES, sleep=_rien)
    b = r["cibles"]["swarm:free_tier"]["unites"]["groq:m"]["bancs"]["raisonnement"]
    assert b["erreurs"] == 1 and b["echantillon"] == 14 and b["valeur"] == 1.0


def test_voix_reste_unknown_assume_sans_appel(sans_pause):
    appels = []
    r = C.lancer_bancs(["swarm:free_tier"], ["voix"], _parfait(appels), unites=UNITES, sleep=_rien)
    assert appels == []
    b = r["cibles"]["swarm:free_tier"]["unites"]["groq:m"]["bancs"]["voix"]
    assert b["etat"] == "UNKNOWN" and b["valeur"] is None


def test_effort_6_taches_x_3_efforts_x_3_repetitions_par_modele_claude(sans_pause):
    appels = []
    unites = {**UNITES, "cli:claude": ["haiku", "sonnet", "opus"]}
    r = C.lancer_bancs(["cli:claude"], ["effort"], _parfait(appels), unites=unites, sleep=_rien)
    assert len(appels) == 3 * 54
    for m in ("haiku", "sonnet", "opus"):
        pm = [a for a in appels if a[1] == m]
        assert len(pm) == 54 and {a[4] for a in pm} == {"low", "medium", "high"}
        e = r["cibles"]["cli:claude"]["unites"][m]["effort"]
        assert e["etat"] == "OBSERVE" and set(e["niveaux"]) == {"low", "medium", "high"}
        assert all(v["n"] == 18 and v["taux_reussite"] == 1.0 for v in e["niveaux"].values())


def test_effort_unknown_assume_pour_vibe_et_proxy(sans_pause):
    appels = []
    r = C.lancer_bancs(["cli:vibe", "swarm:forge_agent_proxy"], ["effort"], _parfait(appels), unites=UNITES, sleep=_rien)
    assert appels == []
    for cible, m in (("cli:vibe", "vibe"), ("swarm:forge_agent_proxy", "groq")):
        assert r["cibles"][cible]["unites"][m]["effort"]["etat"] == "UNKNOWN"


def test_cible_indisponible_ou_inconnue_jamais_appelee(sans_pause):
    appels = []
    r = C.lancer_bancs(["cli:agy", "cli:codex", "cli:telepathie"], ["code"], _parfait(appels), unites=UNITES, sleep=_rien)
    assert appels == []
    assert r["cibles"]["cli:agy"]["etat"] == "INDISPONIBLE" and r["cibles"]["cli:agy"]["motif"]
    assert r["cibles"]["cli:codex"]["etat"] == "INDISPONIBLE"
    assert r["cibles"]["cli:telepathie"]["etat"] == "INCONNUE"


def test_requete_ne_porte_que_le_banc(sans_pause):
    vus = []

    def espion(cible, modele, req):
        vus.append(req)
        return {"texte": "", "tool_calls": [], "cout_usd": 0.0}
    C.lancer_bancs(["swarm:free_tier"], ["outils", "vision"], espion, unites=UNITES, sleep=_rien)
    assert {k for r in vus for k in r} <= {"banc", "item_id", "prompt", "tools", "image", "effort", "max_tokens"}
    assert all(r["image"][:4] == b"\x89PNG" for r in vus if r["banc"] == "vision")
    assert all(r["tools"] for r in vus if r["banc"] == "outils")


# ---------------------------------------------------------------- dry-run et CLI --------------------------------------
def test_dry_run_chiffre_sans_aucun_appel(capsys):
    def interdit(*a, **k):
        raise AssertionError("appel pendant un dry-run")
    code = C.main_bancs(["--dimensions", "cli:claude,cli:vibe,swarm:free_tier,cli:agy", "--bancs",
                         "code,raisonnement,effort", "--dry-run"], appel=interdit, unites=UNITES)
    out = capsys.readouterr().out
    assert code == 0
    assert "cli:claude" in out and "cli:vibe" in out and "swarm:free_tier" in out
    assert "INDISPONIBLE" in out and "quota epuise" in out
    plan = C.plan_bancs(["cli:claude"], ["code", "raisonnement", "effort"], unites={"cli:claude": ["haiku", "sonnet", "opus"]})
    p = plan["cibles"]["cli:claude"]
    assert p["appels"] == 3 * (18 + 15 + 54)
    assert p["cout_usd_estime"] > 0 and p["nature"] == "ESTIMATION"


def test_plan_palier_gratuit_zero_dollar_vibe_cout_inconnu():
    plan = C.plan_bancs(["swarm:free_tier", "cli:vibe"], ["code"], unites=UNITES)
    assert plan["cibles"]["swarm:free_tier"]["cout_usd_estime"] == 0.0
    assert plan["cibles"]["cli:vibe"]["cout_usd_estime"] is None
    assert plan["cibles"]["swarm:free_tier"]["appels"] == 18


def test_plan_signale_un_budget_inferieur_a_l_estimation():
    plan = C.plan_bancs(["cli:claude"], ["effort"], unites={"cli:claude": ["opus"]}, budgets={"cli:claude": 1.0})
    assert plan["cibles"]["cli:claude"]["budget_depasse_par_estimation"] is True


def test_main_ecrit_la_sortie_json_et_respecte_le_budget(tmp_path, capsys):
    sortie = tmp_path / "bancs.json"
    code = C.main_bancs(["--dimensions", "cli:claude,swarm:free_tier", "--bancs", "outils", "--sortie", str(sortie),
                         "--budget", "cli:claude=0.03"], appel=_parfait(), unites=UNITES, sleep=_rien)
    assert code == 0
    doc = json.loads(sortie.read_text(encoding="utf-8"))
    assert doc["cibles"]["cli:claude"]["etat"] == "BUDGET_ATTEINT"
    assert doc["cibles"]["swarm:free_tier"]["unites"]["groq:m"]["bancs"]["outils"]["valeur"] == 1.0
    assert doc["commande"] and doc["mesure_le"]


def test_main_sans_sortie_refuse_un_lancement_reel(capsys):
    code = C.main_bancs(["--dimensions", "swarm:free_tier", "--bancs", "outils"], appel=_parfait(), unites=UNITES)
    assert code != 0
    assert "--sortie" in capsys.readouterr().out


def test_main_bancs_inconnu_ou_budget_mal_forme_refuse(capsys):
    assert C.main_bancs(["--dimensions", "swarm:free_tier", "--bancs", "telepathie", "--dry-run"], unites=UNITES) != 0
    assert C.main_bancs(["--dimensions", "swarm:free_tier", "--bancs", "code", "--dry-run", "--budget", "x"],
                        unites=UNITES) != 0


def test_fiches_dimensions_issues_des_mesures(sans_pause):
    r = C.lancer_bancs(["swarm:free_tier"], ["code", "effort"], _parfait(), unites=UNITES, sleep=_rien)
    f = r["cibles"]["swarm:free_tier"]["unites"]["groq:m"]["fiche"]
    assert f["force"]["code"]["etat"] == "OBSERVE" and f["force"]["code"]["valeur"] == 1.0
    assert f["force"]["vision"]["etat"] == "UNKNOWN"
    assert f["effort"]["etat"] == "OBSERVE"


def test_le_point_d_entree_du_module_route_vers_les_bancs(monkeypatch):
    vu = {}

    def faux(argv, **k):
        vu["argv"] = argv
        return 0
    monkeypatch.setattr(C, "main_bancs", faux)
    monkeypatch.setattr(sys, "argv", ["x", "--dimensions", "cli:claude", "--bancs", "code", "--dry-run"])
    assert C.main() == 0 and vu["argv"][:2] == ["--dimensions", "cli:claude"]


def test_dimensions_seul_reste_la_lecture_du_registre(monkeypatch):
    lu = {}

    def faux(bancs):
        lu["ok"] = True
        return 0
    monkeypatch.setattr(C, "_afficher_dimensions", faux)
    monkeypatch.setattr(sys, "argv", ["x", "--dimensions"])
    assert C.main() == 0 and lu["ok"]


def test_ci_pure_tests_inscrit():
    assert "tests/nr/test_census_bancs_nr.py" in (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
