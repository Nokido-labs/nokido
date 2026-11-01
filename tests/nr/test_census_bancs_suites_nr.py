"""NR -- suites de la premiere mesure reelle des bancs (24/10) : persistance au census, chemins relatifs a la racine,
banc code plus dur (juge toujours deterministe), vibe INDISPONIBLE nomme, unite locale ollama 7b au plan.
Rapport : sandbox/workspace/rapport_suites_bancs_20261024.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as C  # noqa: E402
import forge_free_tier_census_bancs as D  # noqa: E402
from tests.nr.test_census_bancs_nr import UNITES, _parfait, _rien  # noqa: E402

REF_DURS = {
    "fusionner_intervalles": "def fusionner_intervalles(iv):\n    r = []\n    for a, b in sorted(iv):\n"
                             "        if r and a <= r[-1][1]:\n            r[-1][1] = max(r[-1][1], b)\n"
                             "        else:\n            r.append([a, b])\n    return r",
    "plus_longue_sans_repetition": "def plus_longue_sans_repetition(s):\n    vu, d, m = {}, 0, 0\n"
                                   "    for i, c in enumerate(s):\n        if c in vu and vu[c] >= d:\n"
                                   "            d = vu[c] + 1\n        vu[c] = i\n        m = max(m, i - d + 1)\n    return m",
    "somme_max_contigue": "def somme_max_contigue(l):\n    m = c = l[0]\n    for x in l[1:]:\n"
                          "        c = max(x, c + x)\n        m = max(m, c)\n    return m",
    "parentheses_valides": "def parentheses_valides(s):\n    p, o = [], {')': '(', ']': '[', '}': '{'}\n"
                           "    for c in s:\n        if c in '([{':\n            p.append(c)\n"
                           "        elif c in o:\n            if not p or p.pop() != o[c]:\n                return False\n"
                           "    return not p",
    "evaluer_rpn": "def evaluer_rpn(t):\n    p = []\n    for x in t:\n        if x in ('+', '-', '*', '/'):\n"
                   "            b, a = p.pop(), p.pop()\n            p.append(a + b if x == '+' else a - b if x == '-' "
                   "else a * b if x == '*' else int(a / b))\n        else:\n            p.append(int(x))\n    return p[0]",
    "longueur_sous_suite_croissante": "def longueur_sous_suite_croissante(l):\n    import bisect\n    t = []\n"
                                      "    for x in l:\n        i = bisect.bisect_left(t, x)\n"
                                      "        if i == len(t):\n            t.append(x)\n        else:\n            t[i] = x\n    return len(t)",
}


@pytest.fixture(autouse=True)
def _isole(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "SORTIE", tmp_path / "census_test.json")
    monkeypatch.setattr(C, "PAUSE_S", 0)


# ---------------------------------------------------------------- (3) banc code plus dur -----------------------------
def test_banc_code_compte_des_items_durs_et_les_taille_au_plan():
    assert len(D.CODE) == 18 and C.BANCS["code"]["items"] == 18
    assert [i["id"] for i in D.CODE][-6:] == ["c13", "c14", "c15", "c16", "c17", "c18"]


@pytest.mark.parametrize("item", D.CODE[12:], ids=lambda i: i["id"])
def test_items_durs_acceptent_la_reference(item):
    assert C.juge_code(item, "```python\n%s\n```" % REF_DURS[item["fonction"]]) is True


@pytest.mark.parametrize("item", D.CODE[12:], ids=lambda i: i["id"])
def test_items_durs_refusent_la_solution_naive(item):
    naive = {
        "fusionner_intervalles": "def fusionner_intervalles(iv):\n    return [list(x) for x in iv]",
        "plus_longue_sans_repetition": "def plus_longue_sans_repetition(s):\n    return len(set(s))",
        "somme_max_contigue": "def somme_max_contigue(l):\n    return sum(x for x in l if x > 0)",
        "parentheses_valides": "def parentheses_valides(s):\n    return s.count('(') == s.count(')')",
        "evaluer_rpn": "def evaluer_rpn(t):\n    return int(t[0])",
        "longueur_sous_suite_croissante": "def longueur_sous_suite_croissante(l):\n    d = [1] * len(l)\n"
                                          "    for i in range(len(l)):\n        for j in range(i):\n"
                                          "            if l[j] < l[i]:\n                d[i] = max(d[i], d[j] + 1)\n    return max(d) if d else 0",
    }[item["fonction"]]
    assert C.juge_code(item, naive) is False


def test_la_solution_quadratique_echoue_sur_la_complexite():
    item = next(i for i in D.CODE if i["fonction"] == "longueur_sous_suite_croissante")
    assert any(len(t[0][0]) >= 20000 for t in item["tests"])


def test_les_items_durs_n_ont_ni_donnee_projet_ni_secret():
    import re
    interdit = re.compile(r"nokido|laforge|forge_|[A-Z]:[/\\]|/Users/|sk-[A-Za-z0-9]|api[_-]?key|token|secret|password", re.I)
    assert not any(interdit.search(i["prompt"]) for i in D.CODE[12:])


# ---------------------------------------------------------------- (2) chemins relatifs ---------------------------------
def test_resoudre_chemin_relatif_contre_la_racine_du_depot(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    assert C.resoudre_chemin("sandbox/workspace/x.json") == tmp_path / "sandbox" / "workspace" / "x.json"
    absolu = tmp_path / "ailleurs" / "y.json"
    assert C.resoudre_chemin(str(absolu)) == absolu


def test_main_bancs_sortie_relative_independante_du_cwd(monkeypatch, tmp_path):
    racine, autre = tmp_path / "racine", tmp_path / "cwd"
    racine.mkdir()
    autre.mkdir()
    monkeypatch.setattr(C, "ROOT", racine)
    monkeypatch.chdir(autre)
    code = C.main_bancs(["--dimensions", "swarm:free_tier", "--bancs", "outils", "--sortie", "sandbox/workspace/r.json"],
                        appel=_parfait(), unites=UNITES, sleep=_rien)
    assert code == 0
    assert (racine / "sandbox" / "workspace" / "r.json").exists()
    assert not (autre / "sandbox").exists()


# ---------------------------------------------------------------- (1) persistance --------------------------------------
def _doc_mesure():
    return C.lancer_bancs(["swarm:free_tier", "cli:claude"], ["code"], _parfait(), unites=UNITES, sleep=_rien)


def test_consigner_fichier_resultats_ecrit_les_fiches_au_registre(tmp_path):
    f = tmp_path / "res.json"
    f.write_text(json.dumps(_doc_mesure(), default=str), encoding="utf-8")
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"verdicts": {"groq:m": {"joignable": True, "echecs_consecutifs": 0}}}), encoding="utf-8")
    n = C.consigner_fichier_resultats(f, reg)
    out = json.loads(reg.read_text(encoding="utf-8"))["verdicts"]
    assert n == 2
    assert out["groq:m"]["joignable"] is True
    assert out["groq:m"]["dimensions"]["force"]["code"]["valeur"] == 1.0
    assert out["cli:claude:sonnet"]["dimensions"]["force"]["code"]["etat"] == "OBSERVE"


def test_consigner_fichier_illisible_ne_touche_pas_au_registre(tmp_path):
    reg = tmp_path / "reg.json"
    reg.write_text('{"verdicts": {}}', encoding="utf-8")
    f = tmp_path / "res.json"
    f.write_text("pas du json", encoding="utf-8")
    assert C.consigner_fichier_resultats(f, reg) == 0
    assert reg.read_text(encoding="utf-8") == '{"verdicts": {}}'


def test_commande_consigner_sur_un_fichier_existant(tmp_path, capsys):
    f = tmp_path / "res.json"
    f.write_text(json.dumps(_doc_mesure(), default=str), encoding="utf-8")
    assert C.main_consigner([str(f)]) == 0
    out = json.loads(C.SORTIE.read_text(encoding="utf-8"))["verdicts"]
    assert out["groq:m"]["dimensions"]["force"]["code"]["valeur"] == 1.0
    assert C.main_consigner([str(tmp_path / "absent.json")]) != 0


def test_passe_en_ligne_consigne_a_la_fin(tmp_path):
    code = C.main_bancs(["--dimensions", "swarm:free_tier", "--bancs", "code", "--sortie", str(tmp_path / "s.json")],
                        appel=_parfait(), unites=UNITES, sleep=_rien)
    assert code == 0
    out = json.loads(C.SORTIE.read_text(encoding="utf-8"))["verdicts"]
    assert out["groq:m"]["dimensions"]["force"]["code"]["valeur"] == 1.0


def test_dry_run_ne_consigne_rien(tmp_path):
    C.main_bancs(["--dimensions", "swarm:free_tier", "--bancs", "code", "--dry-run"], unites=UNITES)
    assert not C.SORTIE.exists()


# ---------------------------------------------------------------- (4) vibe ------------------------------------------------
def test_binaire_vibe_comme_l_executeur(monkeypatch, tmp_path):
    exe = tmp_path / "vibe.exe"
    exe.write_text("x", encoding="utf-8")
    monkeypatch.setenv("LAFORGE_VIBE_BIN", str(exe))
    assert C._binaire_vibe() == str(exe)
    monkeypatch.delenv("LAFORGE_VIBE_BIN")
    monkeypatch.setenv("LAFORGE_AGENT_HOME", str(tmp_path))
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    (tmp_path / ".local" / "bin" / "vibe.exe").write_text("x", encoding="utf-8")
    assert C._binaire_vibe() == str(tmp_path / ".local" / "bin" / "vibe.exe")


def test_binaire_vibe_absent_rend_none(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_VIBE_BIN", raising=False)
    monkeypatch.setenv("LAFORGE_AGENT_HOME", str(tmp_path))
    import shutil
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    assert C._binaire_vibe() is None


def test_vibe_sans_binaire_est_indisponible_nomme_jamais_erreur(monkeypatch):
    monkeypatch.setattr(C, "_binaire_vibe", lambda: None)
    doc = C.lancer_bancs(["cli:vibe"], ["code"], C.appel_reel, unites={"cli:vibe": ["vibe"]}, sleep=_rien)
    u = doc["cibles"]["cli:vibe"]["unites"]["vibe"]
    assert u["etat"] == "INDISPONIBLE"
    assert "vibe" in u["motif"].lower() and "introuvable" in u["motif"].lower()
    assert u["bancs"]["code"]["echantillon"] == 0 and u["bancs"]["code"]["erreurs"] == 0


# ---------------------------------------------------------------- (5) unite locale 7b ------------------------------------
def test_unite_locale_ollama_7b_au_plan():
    assert C.surface_cible("local:ollama")["etat"] == "DISPONIBLE"
    assert C.unites_de("local:ollama") == ["qwen2.5-coder:7b"]
    plan = C.plan_bancs(["local:ollama"], ["code", "outils"])
    p = plan["cibles"]["local:ollama"]
    assert p["unites"] == ["qwen2.5-coder:7b"] and p["appels"] == 18 + 10
    assert p["cout_usd_estime"] == 0.0


def test_unite_locale_est_lancee_par_appel_reel(monkeypatch):
    vus = []
    monkeypatch.setattr(C, "_appel_ollama", lambda modele, req: vus.append(modele) or {"texte": "", "tool_calls": [], "cout_usd": 0.0})
    C.appel_reel("local:ollama", "qwen2.5-coder:7b", {"prompt": "x"})
    assert vus == ["qwen2.5-coder:7b"]


def test_la_table_de_paliers_n_est_pas_modifiee_en_attendant_la_mesure():
    import forge_palier_effort as P
    assert P.modele_de("opencode", "S") == "qwen2.5-coder:7b"
