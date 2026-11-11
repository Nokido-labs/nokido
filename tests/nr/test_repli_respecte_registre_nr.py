"""NR -- 7/11 : le repli d'une instance OpenCode respecte le registre partage des surfaces.

Passe par le vrai _delegate_to_opencode et capture le modele remis a _config_opencode_instance.
Avant le correctif, un Ollama Cloud epuise etait choisi quand meme : echec QUOTA sur chaque tache.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    sys.path.insert(0, str(_p))

import forge_provider_catalogue as C  # noqa: E402
import forge_task_executor as T  # noqa: E402


class _ModeleCapture(Exception):
    def __init__(self, modele):
        super().__init__(modele)
        self.modele = modele


def _modele_de_repli(monkeypatch, tmp_path, cfg, epuise):
    def _capture(_inst, modele):
        raise _ModeleCapture(modele)

    for nom in ("_avec_carte_attention", "_resoudre_pointeurs_consigne"):
        monkeypatch.setattr(T, nom, lambda texte: texte)
    monkeypatch.setattr(T, "precharger_corps_consigne", lambda texte, workdir=None: texte)
    monkeypatch.setattr(T, "_instances_opencode", lambda: {"OPENCODE_X": cfg})
    monkeypatch.setattr(T, "_workdir_opencode", lambda _inst: tmp_path)
    monkeypatch.setattr(T, "_WORKDIR_TACHE", {})
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda _inst: "j")
    monkeypatch.setattr(T, "_modele_de_la_tache", lambda _desc, defaut: defaut)
    monkeypatch.setattr(T, "_REPLI_EN_COURS", {"t1"})
    monkeypatch.setattr(T, "_config_opencode_instance", _capture)
    monkeypatch.setattr(T, "surface_est_indisponible",
                        lambda surface, *a, **k: "quota mensuel epuise" if epuise and surface == "OLLAMA_CLOUD" else None)
    monkeypatch.setattr(C, "palier_ollama_cloud", lambda _oc: "FREE")
    tache = {"id": "t1", "description": "consigne", "agent": "OPENCODE_X"}
    with pytest.raises(_ModeleCapture) as capture:
        T._delegate_to_opencode(tache, "jeton", instance="OPENCODE_X", _etat_avant=("x", set()))
    return capture.value.modele


def test_epuise_prend_repli_modele(monkeypatch, tmp_path):
    cfg = {"modele": "groq/a", "repli_ollama_cloud": "oc", "repli_modele": "groq/b"}
    assert _modele_de_repli(monkeypatch, tmp_path, cfg, epuise=True) == "groq/b"


def test_epuise_sans_repli_modele_prend_le_local(monkeypatch, tmp_path):
    # Owner 8/11 (GPU sature) : le palier local n'existe plus que sur opt-in (45f056fd2) ; sans lui, aucun repli.
    monkeypatch.setenv("LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE", "1")
    cfg = {"modele": "groq/a", "repli_ollama_cloud": "oc"}
    assert _modele_de_repli(monkeypatch, tmp_path, cfg, epuise=True) == T.REPLI_LOCAL_OPENCODE


def test_epuise_sans_opt_in_ne_replie_pas_en_local(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE", raising=False)
    cfg = {"modele": "groq/a", "repli_ollama_cloud": "oc"}
    assert _modele_de_repli(monkeypatch, tmp_path, cfg, epuise=True) != T.REPLI_LOCAL_OPENCODE


def test_disponible_prend_ollama_cloud(monkeypatch, tmp_path):
    cfg = {"modele": "groq/a", "repli_ollama_cloud": "oc", "repli_modele": "groq/b"}
    assert _modele_de_repli(monkeypatch, tmp_path, cfg, epuise=False) == "ollama_cloud/oc"


def test_aucun_repli_configure_n_invente_rien(monkeypatch, tmp_path):
    assert _modele_de_repli(monkeypatch, tmp_path, {"modele": "groq/a"}, epuise=False) == ""
