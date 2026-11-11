# -*- coding: utf-8 -*-
"""NR (owner 3/11 « tu echoues constamment sur les delegations, regarde comment omniroute gere ca » + « LM Studio et
OpenCode ne les oublie pas ») : pre-vol de disponibilite et palier local, a la maniere d'OmniRoute.

Mesure du soir : Codex « You've hit your usage limit ... try again at Nov 17th, 2026 1:38 PM » (2 taches brulees) ;
Ollama Cloud « reached your monthly usage limit » (tous les replis OpenCode morts) ; l'indisponibilite vivait dans la
memoire de CHAQUE executeur (_SURFACES_INDISPONIBLES), invisible des autres ; _ORDRE_REPLI ignorait les OpenCode ; aucun
palier local. OmniRoute : quota epuise -> cible ecartee jusqu'a sa remise a zero, chaine abonnement -> gratuit -> local.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as T  # noqa: E402

CODEX = ("ERROR: You’ve hit your usage limit. To continue using Codex and get access to GPT-5.3-Codex, start a free "
         "trial of Plus today (https://chatgpt.com/explore/plus), or try again at Nov 17th, 2026 1:38 PM.")
OLLAMA = ('error.error="AI_APICallError: you (naarobb) have reached your monthly usage limit, upgrade for higher limits"')


@pytest.mark.parametrize("texte, attendu", [(CODEX, True), (OLLAMA, True), ("Free usage limit reached", True),
                                            ("quota exceeded (journal OpenCode)", True),
                                            ("AssertionError: assert 2 == 3", False), ("", False)])
def test_un_quota_epuise_est_reconnu(texte, attendu):
    assert T._est_quota_epuise(texte) is attendu


def test_echeance_lue_dans_le_message():
    maintenant = datetime(2026, 11, 3, 21, 0).timestamp()
    assert T.echeance_quota(CODEX, maintenant) == datetime(2026, 11, 17, 13, 38).timestamp()
    assert T.echeance_quota(OLLAMA, maintenant) == datetime(2026, 12, 1, 0, 0).timestamp()      # mensuel
    assert T.echeance_quota("quota exceeded", maintenant) == maintenant + T.INDISPO_DEFAUT_S        # inconnu : borne


@pytest.fixture
def registre(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "_FICHIER_INDISPO", tmp_path / "surfaces_indisponibles.json")
    monkeypatch.setattr(T, "_SURFACES_INDISPONIBLES", {})
    return tmp_path


def test_l_indisponibilite_est_partagee_entre_processus_et_expire(registre, monkeypatch):
    t0 = time.time()
    T.marquer_surface_indisponible("CODEX", "usage limit", jusqu_a=t0 + 100)
    monkeypatch.setattr(T, "_SURFACES_INDISPONIBLES", {})           # « autre processus » : memoire vide
    assert T.surface_indisponible("CODEX", t0 + 10)
    assert T.surface_indisponible("CODEX", t0 + 200) is None        # remise a zero passee
    assert T.surface_indisponible("MISTRAL", t0 + 10) is None


def test_registre_illisible_ne_bloque_personne(registre):
    T._FICHIER_INDISPO.write_text("{pas du json", encoding="utf-8")
    assert T.surface_indisponible("CODEX") is None


def test_un_echec_de_quota_marque_la_surface_jusqu_a_l_echeance(registre):
    assert T._noter_indisponibilite("CODEX", "RIEN PRODUIT", CODEX) is True
    motif = T.surface_indisponible("CODEX", datetime(2026, 11, 10).timestamp())
    assert motif and "usage limit" in motif.lower()
    assert T.surface_indisponible("CODEX", datetime(2026, 11, 18).timestamp()) is None


def test_un_quota_ollama_cloud_marque_le_fournisseur_pas_l_instance(registre):
    T._noter_indisponibilite("OPENCODE_NEMOTRON", "RIEN PRODUIT", OLLAMA)
    assert T.surface_indisponible("OLLAMA_CLOUD", datetime(2026, 11, 20).timestamp())
    # l'instance garde son principal et son repli LOCAL : seul le FOURNISSEUR epuise est ecarte
    assert T.surface_indisponible("OPENCODE_NEMOTRON", datetime(2026, 11, 20).timestamp()) is None


def test_un_echec_ordinaire_ne_marque_rien(registre):
    assert T._noter_indisponibilite("MISTRAL", "ERR_TEST_FAIL", "FAILED tests/nr/x.py::test_y") is False
    assert T.surface_indisponible("MISTRAL") is None


def test_candidat_ecarte_s_il_est_indisponible(registre, monkeypatch):
    for f in ("_executeur_bat",):
        monkeypatch.setattr(T, f, lambda a: True)
    monkeypatch.setattr(T, "_executeur_suspendu", lambda a: False)
    monkeypatch.setattr(T, "_opencode_hors_quota", lambda a: None)
    monkeypatch.setattr(T, "statut_coupe_circuit", lambda a: ("CLOSED", ""))
    assert T._candidat_eligible("MISTRAL") is True
    T.marquer_surface_indisponible("MISTRAL", "usage limit", jusqu_a=time.time() + 100)
    assert T._candidat_eligible("MISTRAL") is False


# --- palier local LM Studio --------------------------------------------------------------------------------------
def test_repli_local_en_direct_quand_ollama_cloud_est_epuise(registre, monkeypatch):
    """Owner 3/11 « opencode est un CLI seul, pourquoi passer par LM Studio, tu peux l'avoir en direct » : le palier local
    est l'Ollama LOCAL du corps (:11434, supervise, sans cle), qwen3:8b (outils) ; LM Studio reste possible par config.
    Owner 8/11 (GPU sature par ce repli silencieux) : le palier local n'existe plus que sur opt-in explicite ; sans lui,
    aucun repli (tests/nr/test_repli_local_opencode_gpu_nr.py)."""
    monkeypatch.setenv("LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE", "1")
    inst = {"repli_ollama_cloud": "gpt-oss:120b"}
    assert T._repli_du(inst) == "ollama_cloud/gpt-oss:120b"
    T.marquer_surface_indisponible("OLLAMA_CLOUD", "monthly usage limit", jusqu_a=time.time() + 100)
    assert T._repli_du(inst) == T.REPLI_LOCAL_OPENCODE == "ollama/qwen3:8b"


def test_config_opencode_pour_lm_studio():
    cfg = T._config_opencode_instance("OPENCODE_GLM", "lmstudio/qwen3-8b")
    p = cfg["provider"]["lmstudio"]
    assert "127.0.0.1:1234" in p["options"]["baseURL"] and p["options"]["apiKey"] == "{env:LMSTUDIO_TOKEN}"
    assert "qwen3-8b" in p["models"] and cfg["model"] == "lmstudio/qwen3-8b"


def test_la_cle_lm_studio_est_injectee_comme_les_autres():
    assert T._CLE_PAR_FOURNISSEUR.get("lmstudio") == "LMSTUDIO_TOKEN"


def test_la_chaine_de_repli_inclut_les_opencode():
    for a in ("OPENCODE_GLM", "OPENCODE_DEFAUT2", "OPENCODE_GPTOSS"):
        assert a in T._ORDRE_REPLI_DEFAUT
