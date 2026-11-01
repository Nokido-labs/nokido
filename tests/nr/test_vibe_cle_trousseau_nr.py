"""NR -- voie HYBRIDE de la cle Mistral de Vibe (decision owner 24/10) : un `vibe` lance A LA MAIN lit le trousseau
Windows (2e source de son /status). La cle vient du coffre ; le trousseau est PAR UTILISATEUR, d'ou le refus hors
compte owner ; elle passe par stdin a l'interpreteur de Vibe, jamais en argument ; aucune valeur dans la sortie.
Service/utilisateur MESURES dans le paquet installe : vibe/utils/keyring.py:15 et :320 (Vibe 3.0.1)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_provision_clients as P  # noqa: E402

FAUX = "faux-secret-mistral-0000"


class _Appels:
    def __init__(self, sortie="", rc=0):
        self.vus, self.sortie, self.rc = [], sortie, rc

    def __call__(self, args, entree):
        self.vus.append((args, entree))
        return subprocess.CompletedProcess(args, self.rc, stdout=self.sortie, stderr="")


def _vibe_py(tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("")
    return py


def test_service_et_utilisateur_sont_ceux_que_vibe_lit():
    assert P._VIBE_KEYRING == ("ai.mistral.vibe", "MISTRAL_API_KEY")


def test_hors_compte_owner_refus_et_rien_appele(tmp_path):
    a = _Appels()
    out = "\n".join(P._vibe_keyring(est_owner=False, lire_secret=lambda k: FAUX, executer=a, py=_vibe_py(tmp_path)))
    assert "REFUS" in out and not a.vus


def test_pose_par_stdin_jamais_en_argument_ni_en_sortie(tmp_path):
    a = _Appels()
    out = "\n".join(P._vibe_keyring(est_owner=True, lire_secret=lambda k: FAUX, executer=a, py=_vibe_py(tmp_path)))
    (args, entree), = a.vus
    assert entree == FAUX
    assert FAUX not in " ".join(map(str, args))
    assert "ai.mistral.vibe" in args and "MISTRAL_API_KEY" in args
    assert FAUX not in out and "posee" in out


def test_verification_booleenne_sans_valeur(tmp_path):
    a = _Appels(sortie="EGAL\n")
    out = "\n".join(P._vibe_keyring(verifier=True, est_owner=True, lire_secret=lambda k: FAUX, executer=a,
                                    py=_vibe_py(tmp_path)))
    assert "EGAL" in out and FAUX not in out


def test_cle_absente_du_coffre_rien_pose(tmp_path):
    a = _Appels()
    out = "\n".join(P._vibe_keyring(est_owner=True, lire_secret=lambda k: None, executer=a, py=_vibe_py(tmp_path)))
    assert "absente" in out and not a.vus
