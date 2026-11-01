"""NR -- la recette PROVISIONNE le chiffrement at-rest sur un runner CI avant de consigner un refus (P0 owner 20/10).

`P0_veracrypt_obligatoire_par_defaut_20261020`, reste mesure le 21/10 : decision owner (choix multiple ~16 h 15)
« Provisionner, sinon refus dit ». Aujourd'hui l'etape `paquet_composants` sonde `chiffrement_present()` puis passe
DIRECTEMENT `--sans-chiffrement --motif-refus "non provisionne"` : le refus est dit, mais rien n'a ete tente, donc
« non provisionnable » n'est jamais prouve (une impossibilite s'enonce APRES mesure).

Contrats :
  1. provisionner_chiffrement(systeme, executer=subprocess.run, env=os.environ) rend {tente, rc, raison} ;
     HORS CI (ni CI ni GITHUB_ACTIONS a « true ») : AUCUNE commande, raison `hors_ci` -- jamais d'installation de
     logiciel sur un poste ;
  2. en CI : Windows -> `choco install veracrypt -y --no-progress` ; Darwin -> `brew install --cask veracrypt` ;
     Linux -> `sudo apt-get install -y cryptsetup` ; `tente` = la commande jouee (texte), `rc` = son code ;
  3. une commande qui leve (absente, timeout) rend rc None et raison `ILLISIBLE:<Exception>` -- jamais un succes ;
  4. arguments_chiffrement_recette(present, systeme, provision=None) : present -> [] ; absent APRES tentative -> le
     motif cite la tentative (« provisionnement tente : <cmd> rc=<n> ») ; sans tentative, le motif ancien reste ;
  5. l'etape `paquet_composants` (chemin reel) : chiffrement absent -> provisionner -> RESONDER ; present apres
     provisionnement -> aucun refus passe a `nokido-composants`, et le detail dit « provisionne ».
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_install_acceptance as A  # noqa: E402


class _Rc:
    def __init__(self, rc):
        self.returncode, self.stdout, self.stderr = rc, "", ""


def _enregistreur(rc=0, leve=None):
    vus = []

    def executer(cmd, **kw):
        vus.append(cmd if isinstance(cmd, str) else " ".join(cmd))
        if leve:
            raise leve
        return _Rc(rc)
    return vus, executer


def test_hors_ci_aucune_installation():
    vus, ex = _enregistreur()
    p = A.provisionner_chiffrement("Windows", executer=ex, env={})
    assert vus == [] and p["tente"] == "" and p["rc"] is None and p["raison"] == "hors_ci"
    p2 = A.provisionner_chiffrement("Linux", executer=ex, env={"CI": "false"})
    assert vus == [] and p2["raison"] == "hors_ci"


def test_en_ci_la_bonne_commande_par_systeme():
    for systeme, attendu in (("Windows", "choco install veracrypt -y --no-progress"),
                             ("Darwin", "brew install --cask veracrypt"),
                             ("Linux", "sudo apt-get install -y cryptsetup")):
        vus, ex = _enregistreur(rc=0)
        p = A.provisionner_chiffrement(systeme, executer=ex, env={"GITHUB_ACTIONS": "true"})
        assert vus == [attendu], (systeme, vus)
        assert p["tente"] == attendu and p["rc"] == 0


def test_commande_qui_leve_est_illisible_jamais_un_succes():
    vus, ex = _enregistreur(leve=FileNotFoundError("choco"))
    p = A.provisionner_chiffrement("Windows", executer=ex, env={"CI": "true"})
    assert p["rc"] is None and p["raison"].startswith("ILLISIBLE:FileNotFoundError")


def test_le_refus_cite_la_tentative():
    assert A.arguments_chiffrement_recette(True, "Windows", provision={"tente": "x", "rc": 0}) == []
    r = A.arguments_chiffrement_recette(False, "Windows",
                                        provision={"tente": "choco install veracrypt -y --no-progress", "rc": 1,
                                                   "raison": ""})
    assert r[:2] == ["--sans-chiffrement", "--motif-refus"]
    assert "provisionnement tente : choco install veracrypt -y --no-progress rc=1" in r[2]
    ancien = A.arguments_chiffrement_recette(False, "Linux")
    assert "non provisionne" in ancien[2]


def test_l_etape_provisionne_puis_resonde(monkeypatch):
    sondes = iter([False, True])

    class _Comp:
        @staticmethod
        def chiffrement_present():
            return next(sondes)

    appels = []
    monkeypatch.setattr(A, "R", {"paquet_install": {"etat": "PASS"}})
    monkeypatch.setattr(A, "composants", lambda: _Comp)
    monkeypatch.setattr(A, "provisionner_chiffrement",
                        lambda systeme, **kw: {"tente": "choco install veracrypt -y --no-progress", "rc": 0,
                                               "raison": ""})
    monkeypatch.setattr(A, "_bin", lambda n: n)
    monkeypatch.setattr(A, "_sh_p", lambda cmd, timeout=0: (appels.append(cmd) or (0, "ok")))
    A._p_composants()
    assert "--sans-chiffrement" not in appels[0]
    assert A.R["paquet_composants"]["etat"] == "PASS"
    assert "provisionne" in A.R["paquet_composants"]["detail"]
