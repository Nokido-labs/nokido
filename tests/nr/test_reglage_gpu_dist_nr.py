"""NR -- reglage GPU automatique a la DISTRIBUTION (29/10) : env dans le services.toml INSTALLE, num_gpu sur les fiches.

Fixtures seulement : faux services.toml en tmp_path, faux Ollama (/api/show, /api/create). Rien de reel.
"""
from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]

TOML = '''[[service]]
name = "Autre"
env = { A = "1" }

[[service]]
name = "NokidoOllama"
port = 11434
env = { OLLAMA_MODELS = "x", OLLAMA_KEEP_ALIVE = "30s" }
# commentaire
'''

PROP_IGPU = {"env": {"OLLAMA_IGPU_ENABLE": "1", "OLLAMA_GPU_OVERHEAD": "1073741824", "OLLAMA_MAX_LOADED_MODELS": "1"},
             "num_gpu_par_modele": {"qwen2.5-coder:1.5b": 0, "laforge-qwen": 0},
             "motifs": ["iGPU reserve 8 Go : OLLAMA_IGPU_ENABLE=1"]}


def _mod():
    spec = importlib.util.spec_from_file_location("composants_gpu_nr", RACINE / "tools" / "forge_composants.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FauxOllama:
    def __init__(self, fiches):
        self.fiches = fiches  # nom -> texte "parameters" ; None = illisible
        self.creations = []

    def __call__(self, chemin, charge):
        if chemin == "/api/show":
            t = self.fiches.get(charge["model"])
            if t is None:
                raise OSError("illisible")
            return {"parameters": t, "modelfile": "FROM x"}
        if chemin == "/api/create":
            self.creations.append(charge)
            self.fiches[charge["model"]] = "\n".join(
                "%-20s %s" % (k, json.dumps(v) if isinstance(v, str) else v) for k, v in charge["parameters"].items())
            return {"status": "success"}
        raise AssertionError(chemin)


def _fiches():
    return {"qwen2.5-coder:1.5b": "", "laforge-qwen": 'stop                 "### Instruction:"\ntemperature          0.2\ntop_p                0.9'}


def _poser(tmp_path, prop, http):
    st = tmp_path / "services.toml"
    st.write_text(TOML, encoding="utf-8")
    m = _mod()
    r = m.appliquer_reglage_gpu(prop, st, http, tmp_path / "journal")
    return m, st, r


def _env(st, nom="NokidoOllama"):
    return next(s for s in tomllib.loads(st.read_text(encoding="utf-8"))["service"] if s["name"] == nom)["env"]


def test_igpu_ecrit_cle_et_recree_fiches_avec_parametres_conserves(tmp_path):
    http = FauxOllama(_fiches())
    m, st, r = _poser(tmp_path, PROP_IGPU, http)
    env = _env(st)
    assert env["OLLAMA_IGPU_ENABLE"] == "1" and env["OLLAMA_MODELS"] == "x"
    assert _env(st, "Autre") == {"A": "1"}
    lf = next(c for c in http.creations if c["model"] == "laforge-qwen")
    assert lf["from"] == "laforge-qwen"
    assert lf["parameters"] == {"stop": "### Instruction:", "temperature": 0.2, "top_p": 0.9, "num_gpu": 0}
    assert len(http.creations) == 2
    assert list((tmp_path / "journal").glob("fiche_avant_*.json"))  # sauvegarde de la fiche d'avant
    assert "iGPU reserve" in " ".join(r["motifs"])


def test_idempotence(tmp_path):
    http = FauxOllama(_fiches())
    m, st, _ = _poser(tmp_path, PROP_IGPU, http)
    avant = st.read_text(encoding="utf-8")
    n = len(http.creations)
    r = m.appliquer_reglage_gpu(PROP_IGPU, st, http, tmp_path / "journal")
    assert st.read_text(encoding="utf-8") == avant and len(http.creations) == n
    assert r["inchange"]


def test_gpu_dedie_aucune_cle_igpu_motif_dit(tmp_path):
    prop = {"env": {"OLLAMA_GPU_OVERHEAD": "1073741824", "OLLAMA_MAX_LOADED_MODELS": "1"}, "num_gpu_par_modele": {},
            "motifs": ["GPU dedie : pas d'OLLAMA_IGPU_ENABLE"]}
    http = FauxOllama(_fiches())
    m, st, r = _poser(tmp_path, prop, http)
    assert "OLLAMA_IGPU_ENABLE" not in st.read_text(encoding="utf-8")
    assert http.creations == [] and "GPU dedie" in " ".join(r["motifs"])


def test_inconnu_ou_vide_rien(tmp_path):
    prop = {"env": {}, "num_gpu_par_modele": {}, "motifs": ["GPU X : type inconnu -> aucun reglage"]}
    http = FauxOllama(_fiches())
    m, st, r = _poser(tmp_path, prop, http)
    assert st.read_text(encoding="utf-8") == TOML and http.creations == []
    assert "inconnu" in " ".join(r["motifs"])


def test_fiche_illisible_aucun_changement_de_fiche_motif(tmp_path):
    http = FauxOllama({"qwen2.5-coder:1.5b": None, "laforge-qwen": None})
    m, st, r = _poser(tmp_path, PROP_IGPU, http)
    assert http.creations == []
    assert "illisible" in " ".join(r["motifs"])


def test_refuse_dans_un_clone_de_dev(tmp_path):
    m = _mod()
    dev = RACINE / "proxy_deno" / "core" / "services.toml"
    with pytest.raises(ValueError):
        m.appliquer_reglage_gpu(PROP_IGPU, dev, FauxOllama(_fiches()), tmp_path)


def test_recette_verifie_proposition_fiches_et_vulkan(tmp_path):
    http = FauxOllama(_fiches())
    m, st, _ = _poser(tmp_path, PROP_IGPU, http)
    ok = m.verifier_reglage_gpu(PROP_IGPU, st, http, "load_backend: loaded Vulkan backend ... library=Vulkan")
    assert ok["etat"] == "PASS", ok
    # (c) iGPU active mais pas de Vulkan dans le journal -> ROUGE
    assert m.verifier_reglage_gpu(PROP_IGPU, st, http, "library=cpu")["etat"] == "FAIL"
    # (b) fiche sans num_gpu -> ROUGE
    http.fiches["laforge-qwen"] = "temperature 0.2"
    assert m.verifier_reglage_gpu(PROP_IGPU, st, http, "library=Vulkan")["etat"] == "FAIL"
    # (a) cle absente du services.toml -> ROUGE
    st.write_text(TOML, encoding="utf-8")
    assert m.verifier_reglage_gpu(PROP_IGPU, st, http, "library=Vulkan")["etat"] == "FAIL"
