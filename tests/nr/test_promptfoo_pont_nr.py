"""NR du pont Promptfoo -> Nokido (decision owner 15/10 : matrice etendue d'abord, Promptfoo ensuite).

Sans reseau, sans npm, sans cle : chaque collaborateur est injecte."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_promptfoo_pont as pont  # noqa: E402

MATRICE = {
    "mesure_le": "2026-10-15T12:00:00",
    "familles": {
        "gpt-oss": [
            {"fournisseur": "groq", "modele": "openai/gpt-oss-20b", "etat": "JOIGNABLE",
             "competence": {"mesurees": 4}},
            {"fournisseur": "openrouter", "modele": "openai/gpt-oss-120b", "etat": "SANS_SOLDE"},
            {"fournisseur": "nvidia", "modele": "openai/gpt-oss-20b", "etat": "JOIGNABLE",
             "competence": {"mesurees": 0}},
        ],
        "qwen": [
            {"fournisseur": "groq", "modele": "qwen/qwen3-32b", "etat": "JOIGNABLE"},
            {"fournisseur": "groq", "modele": "openai/gpt-oss-20b", "etat": "JOIGNABLE"},
        ],
    },
}


def test_seules_les_voies_utilisables_entrent():
    voies = pont.voies_utilisables(MATRICE)
    assert voies == [("groq", "openai/gpt-oss-20b"), ("groq", "qwen/qwen3-32b")]


def test_la_config_ne_porte_aucune_cle_et_ne_lit_pas_le_coffre(monkeypatch):
    def interdit(*_a, **_k):
        raise AssertionError("la config ne doit jamais lire le coffre")
    monkeypatch.setattr(pont, "_get_secret", interdit)
    taches = (("calcul", "17*23 ?", lambda t: t == "391"),)
    c = pont.construire_config(MATRICE, taches=taches, pont=Path("C:/x/pont.py"), python_exe="py")
    assert [p["label"] for p in c["providers"]] == ["groq:openai/gpt-oss-20b", "groq:qwen/qwen3-32b"]
    assert all(set(p["config"]) == {"fournisseur", "modele", "pythonExecutable"} for p in c["providers"])
    assert c["tests"][0]["vars"] == {"prompt": "17*23 ?", "tache": "calcul"}
    assert c["tests"][0]["assert"][0] == {"type": "python", "value": "file://C:/x/pont.py"}
    assert "apiKey" not in json.dumps(c)


def _cat(monkeypatch):
    faux = SimpleNamespace(FOURNISSEURS=[("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1/models")],
                           TACHES_COMPETENCE=(("calcul", "17*23 ?", lambda t: t.strip() == "391"),),
                           generer_texte=None)
    monkeypatch.setattr(pont, "_catalogue", lambda: faux)
    return faux


def test_call_api_rend_la_sortie_et_la_cle_reste_dans_le_processus(monkeypatch):
    _cat(monkeypatch)
    vu = {}

    def gen(url, cle, modele, prompt):
        vu.update(url=url, cle=cle, modele=modele)
        return 200, "391", 12.0
    r = pont.call_api("17*23 ?", {"config": {"fournisseur": "groq", "modele": "m"}}, {},
                      gen_fn=gen, get_secret=lambda k: "s3cr3t" if k == "GROQ_API_KEY" else "")
    assert r == {"output": "391"}
    assert vu["cle"] == "s3cr3t" and vu["modele"] == "m"


def test_un_echec_de_transport_est_une_erreur_jamais_une_sortie(monkeypatch):
    _cat(monkeypatch)
    r = pont.call_api("p", {"config": {"fournisseur": "groq", "modele": "m"}}, {},
                      gen_fn=lambda *a: (402, "Insufficient credits", 5.0), get_secret=lambda k: "s")
    assert "error" in r and "output" not in r and "402" in r["error"]


def test_voie_inconnue_ou_cle_absente_sont_dites(monkeypatch):
    _cat(monkeypatch)
    assert "voie inconnue" in pont.call_api("p", {"config": {"fournisseur": "zz", "modele": "m"}}, {})["error"]
    r = pont.call_api("p", {"config": {"fournisseur": "groq", "modele": "m"}}, {}, get_secret=lambda k: "")
    assert "cle absente" in r["error"]


def test_l_assertion_est_le_correcteur_deterministe(monkeypatch):
    _cat(monkeypatch)
    assert pont.get_assert("391", {"vars": {"tache": "calcul"}})["pass"] is True
    assert pont.get_assert("390", {"vars": {"tache": "calcul"}})["pass"] is False
    inconnue = pont.get_assert("391", {"vars": {"tache": "nulle_part"}})
    assert inconnue["pass"] is False and "inconnue" in inconnue["reason"]


def test_le_provisionnement_est_local_et_epingle(tmp_path):
    appels = []

    def executer(cmd, **_k):
        appels.append(cmd)
        sortie = pont.PIN + "\n" if "--version" in cmd else ""
        return SimpleNamespace(returncode=0, stdout=sortie, stderr="")
    r = pont.provisionner(tmp_path / "pf", executer=executer)
    assert r["ok"] is True
    install = appels[0]
    assert "--prefix" in install and str(tmp_path / "pf") in install
    assert "promptfoo@" + pont.PIN in install and "-g" not in install and "--global" not in install


def test_une_version_divergente_n_est_pas_un_succes(tmp_path):
    def executer(cmd, **_k):
        return SimpleNamespace(returncode=0, stdout="0.1.0" if "--version" in cmd else "", stderr="")
    assert pont.provisionner(tmp_path / "pf", executer=executer)["ok"] is False


def test_evaluer_sans_promptfoo_dit_inconnu(monkeypatch, tmp_path):
    monkeypatch.setattr(pont, "binaire", lambda *a: tmp_path / "absent")
    r = pont.evaluer(tmp_path / "c.json")
    assert r["ok"] is False and "INCONNU" in r["raison"]


def test_evaluer_coupe_la_telemetrie(monkeypatch, tmp_path):
    b = tmp_path / "promptfoo.cmd"
    b.write_text("")
    monkeypatch.setattr(pont, "binaire", lambda *a: b)
    vu = {}

    def executer(cmd, **k):
        vu.update(cmd=cmd, env=k["env"])
        return SimpleNamespace(returncode=100, stdout="fin", stderr="")
    r = pont.evaluer(tmp_path / "c.json", executer=executer)
    assert r["ok"] is True and r["rc"] == 100
    assert vu["env"]["PROMPTFOO_DISABLE_TELEMETRY"] == "1" and vu["env"]["PROMPTFOO_DISABLE_UPDATE"] == "1"
    assert vu["cmd"][1:3] == ["eval", "-c"]
