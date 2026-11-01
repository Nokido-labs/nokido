"""NR 29/10 soir (owner « go » : banc DLP en generateur local) -- le banc `redaction_dlp` s'arretait en PRE_FLIGHT_REFUSE x3 :
le pare-feu refuse, a bon droit, d'envoyer SON PROPRE code (motifs de secrets) a un generateur cloud. Un banc peut
declarer `generateur_local` : l'adresse doit etre LOCALE (sinon refus, rien n'est appele) ; alors le pre_flight cloud
n'est pas appele (rien ne sort) et le generateur cloud jamais."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)]

import forge_banc_amelioration as B  # noqa: E402


def _banc(base):
    return {"perimetre": ["app/f.py"], "fonctions": [], "juge": {"commande": "x", "metrique": "m", "sens": "max",
                                                                   "empreintes": []},
            "garde_tests": [], "axes": [], "budget_iterations": 1,
            "generateur_local": {"base": base, "modele": "qwen2.5-coder:7b"}}


def _deps(appels):
    def copier(racine, dest):
        (Path(dest) / "app").mkdir(parents=True, exist_ok=True)
        (Path(dest) / "app" / "f.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    def interdit(nom):
        def _f(*a, **k):
            appels.append(nom)
            raise AssertionError("%s ne doit pas etre appele" % nom)
        return _f

    def local(prompt, cfg):
        appels.append("local:%s" % cfg["modele"])
        return "rien a proposer", "local:%s" % cfg["modele"]

    import shutil
    return B.Deps(copier, interdit("generer_cloud"), interdit("appliquer"), interdit("garde"), interdit("juge"),
                  interdit("thymus"), interdit("pre_flight"), lambda r, d: shutil.rmtree(d, ignore_errors=True),
                  generer_local=local)


def test_generateur_local_sans_pre_flight_ni_cloud(tmp_path):
    appels = []
    r = B.iteration("dlp", _banc("http://127.0.0.1:11434"), 0, tmp_path, tmp_path / "reg", _deps(appels),
                    tmp_path / "copies", 0.87)
    assert appels == ["local:qwen2.5-coder:7b"] and r["verdict"] == "SANS_BLOC"


def test_adresse_non_locale_refusee_rien_appele(tmp_path):
    appels = []
    r = B.iteration("dlp", _banc("https://ollama.com"), 0, tmp_path, tmp_path / "reg", _deps(appels),
                    tmp_path / "copies", 0.87)
    assert appels == [] and r["verdict"] == "GENERATEUR_LOCAL_REFUSE"
