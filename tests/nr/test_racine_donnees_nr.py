"""NR -- la racine des DONNEES quitte site-packages quand Nokido est installe (chantier 3, GO owner du 13/10).

MESURE QUI L'A DECLENCHE. Parcours paquet 3 OS du 13/10 : installe par pip, Nokido ecrivait RAG, data, logs,
runtime et sandbox dans le dossier du paquet ; `pip uninstall` les laissait derriere lui (etape desinstallation
FAIL sur les trois systemes), et une mise a jour pouvait les ecraser.

Ce qui est verrouille : le clone ne change PAS (poste de developpement) ; installe, la racine est le dossier de
donnees standard de chaque systeme ; `NOKIDO_DATA_DIR` l'emporte ; la base RAG par defaut suit la racine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_db_path as D  # noqa: E402

INSTALLE = Path("/venv/lib/python3.12/site-packages/nokido_agent")


@pytest.fixture(autouse=True)
def _sans_surcharge(monkeypatch):
    for v in ("NOKIDO_DATA_DIR", "LAFORGE_DATA_DIR", "LAFORGE_DB"):
        monkeypatch.delenv(v, raising=False)


def test_le_clone_garde_sa_racine():
    assert D.racine_donnees() == D._ROOT


@pytest.mark.parametrize("plateforme, attendu", [
    ("win32", Path("/la/Nokido")),
    ("darwin", Path("/maison/Library/Application Support/Nokido")),
    ("linux", Path("/xdg/nokido")),
])
def test_installe_la_racine_est_le_dossier_de_donnees_utilisateur(monkeypatch, plateforme, attendu):
    monkeypatch.setattr(D, "_ROOT", INSTALLE)
    monkeypatch.setattr(sys, "platform", plateforme)
    monkeypatch.setenv("LOCALAPPDATA", "/la")
    monkeypatch.setenv("XDG_DATA_HOME", "/xdg")
    monkeypatch.setattr(Path, "home", lambda: Path("/maison"))
    assert D.racine_donnees() == attendu
    assert "site-packages" not in Path(D.db_path()).parts


def test_nokido_data_dir_l_emporte(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "_ROOT", INSTALLE)
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    assert D.racine_donnees() == tmp_path
    assert Path(D.db_path()) == (tmp_path / "RAG" / "embeddings.db").resolve()


def test_dist_packages_compte_aussi_comme_installe():
    assert D._installe(Path("/usr/lib/python3/dist-packages/nokido_agent"))
    assert not D._installe(ROOT)


# --- Redirection a la source (decision owner du 13/10 : 853 modules ecrivent sous leur racine de code) -------


def _paquet(tmp_path, monkeypatch):
    code = tmp_path / "venv" / "site-packages" / "nokido_agent"
    code.mkdir(parents=True)
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path / "donnees"))
    return code


def test_installe_les_ecritures_traversent_le_lien_jusqu_aux_donnees(tmp_path, monkeypatch):
    code = _paquet(tmp_path, monkeypatch)
    etats = D.rediriger_donnees(code)
    assert all(etats[n] == "CREE" for n in D.DOSSIERS_DE_DONNEES), etats
    (code / "logs" / "hub.log").write_text("x", encoding="utf-8")     # un ecrivain qui ignore tout du lien
    assert (tmp_path / "donnees" / "logs" / "hub.log").is_file()
    assert (tmp_path / "donnees" / D.MARQUEUR_DONNEES).is_file()
    assert D.rediriger_donnees(code)["logs"] == "LIE"                   # 2e import : rien a refaire


def test_un_dossier_reel_d_une_installation_anterieure_n_est_jamais_deplace(tmp_path, monkeypatch):
    code = _paquet(tmp_path, monkeypatch)
    (code / "RAG").mkdir()
    (code / "RAG" / "embeddings.db").write_bytes(b"base anterieure")
    assert D.rediriger_donnees(code)["RAG"] == "DEJA_REEL"
    assert (code / "RAG" / "embeddings.db").read_bytes() == b"base anterieure"


def test_desinstaller_retire_les_liens_pas_les_donnees_sauf_purge(tmp_path, monkeypatch):
    code = _paquet(tmp_path, monkeypatch)
    D.rediriger_donnees(code)
    (code / "data" / "machine_vault.dat").write_bytes(b"coffre")
    fait = D.retirer_donnees(code)
    assert fait["data"] == "LIEN_RETIRE" and not (code / "data").exists()
    assert (tmp_path / "donnees" / "data" / "machine_vault.dat").is_file()   # garde par defaut
    D.rediriger_donnees(code)
    assert D.retirer_donnees(code, purger=True)["purge"] == "EFFACEE"
    assert not (tmp_path / "donnees").exists()


def test_purge_refusee_sur_une_racine_sans_marqueur(tmp_path, monkeypatch):
    """NOKIDO_DATA_DIR peut viser le HOME par erreur : sans marqueur Nokido, rien n'est efface."""
    code = _paquet(tmp_path, monkeypatch)
    etranger = tmp_path / "home_de_quelqu_un"
    (etranger / "photos").mkdir(parents=True)
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(etranger))
    assert D.retirer_donnees(code, purger=True)["purge"].startswith("REFUSEE")
    assert (etranger / "photos").is_dir()


def test_le_clone_n_est_jamais_redirige_ni_desinstalle():
    assert D.rediriger_donnees(ROOT) == {"mode": "CLONE"}
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import forge_composants as F

    assert F.desinstaller(purger=True) == 2        # chemin REEL : le poste de developpement n'est pas touche


def test_supprimer_le_venv_n_efface_pas_les_donnees(tmp_path, monkeypatch):
    """Qui efface son venv par `shutil.rmtree` ne doit pas emporter ses donnees a travers le lien (mesure 13/10,
    Python 3.12 : la jonction n'est pas suivie)."""
    code = _paquet(tmp_path, monkeypatch)
    D.rediriger_donnees(code)
    (code / "RAG" / "embeddings.db").write_bytes(b"base")
    import shutil

    shutil.rmtree(tmp_path / "venv")
    assert (tmp_path / "donnees" / "RAG" / "embeddings.db").read_bytes() == b"base"


def test_le_doctor_dit_ou_vivent_les_donnees_et_avertit_d_une_installation_anterieure():
    """Mise a jour depuis 0.20.10 : ses dossiers restent DANS le paquet (DEJA_REEL, jamais deplaces en silence) --
    le doctor est le seul endroit ou l'utilisateur peut l'apprendre."""
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import nokido_doctor as N

    assert N.etat_donnees() == {"mode": "CLONE"}          # chemin REEL : le depot est un clone
    texte = N.rendre_donnees({"mode": "INSTALLE", "racine": "/la/Nokido", "RAG": "DEJA_REEL", "logs": "LIE",
                              "data": "ECHEC:PermissionError"})
    assert "/la/Nokido" in texte and "AVERTISSEMENT" in texte and "RAG" in texte
    assert "ECHEC de redirection : data (ECHEC:PermissionError)" in texte
    assert "AVERTISSEMENT" not in N.rendre_donnees({"mode": "INSTALLE", "racine": "/la/Nokido", "RAG": "LIE"})


def test_le_paquet_installe_redirige_des_son_import():
    source = (ROOT / "nokido_agent" / "__init__.py").read_text(encoding="utf-8")
    assert "from nokido_agent.app.forge_db_path import rediriger_donnees" in source
    assert "ETAT_DONNEES = _rediriger()" in source
