"""NR (owner 1/11, « réparer + NR ») : trois rouges publics de la v0.20.17, chacun avec sa réparation.

1. Parcours paquet Windows : pip a cherché nokido-agent==0.20.17 deux minutes après la publication, avant que l'index
   ne la serve (« Could not find a version that satisfies the requirement »). Une propagation n'est pas une panne :
   l'étape paquet_install réessaie sur CE seul motif, et jamais sur un autre échec.
2. SourceForge : la clé lue était la bonne (empreinte affichée = SHA256:xfbUmhWh…) mais le push a rendu « Could not
   read from remote repository » sans aucune trace d'authentification dans le journal : ILLISIBLE. Une sonde ssh -T
   avant le push DIT si l'authentification passe (utilisateur ou chemin faux) ou non (clé non enregistrée).
3. Hugging Face : whoami-v2 n'a rendu aucun compte, puis git a demandé un identifiant. Le jeton est nettoyé
   (\\r\\n venus de Windows), le code HTTP de whoami est affiché (jamais le jeton), et un compte illisible ARRÊTE
   l'étape avant tout clone ou push.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
MIROIRS = RACINE / ".github" / "workflows" / "miroirs-publics.yml"

NON_SERVIE = ("ERROR: Could not find a version that satisfies the requirement nokido-agent==0.20.17 "
              "(from versions: 0.20.15, 0.20.16)\nERROR: No matching distribution found for nokido-agent==0.20.17")


def _acceptance():
    spec = importlib.util.spec_from_file_location("acceptance_propagation_nr",
                                                  RACINE / "tools" / "forge_install_acceptance.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.R.clear()
    m.R["paquet_venv"] = {"etat": "PASS"}
    return m


def _faux_pip(echecs: int, sortie_echec: str, journal: list):
    def faux(cmd, timeout=600):
        cmd = [str(c) for c in cmd]
        if "pip" in cmd:
            journal.append(cmd)
            return (1, sortie_echec) if len(journal) <= echecs else (0, "Successfully installed nokido-agent")
        return 0, "0.20.17"
    return faux


def test_paquet_install_reessaie_tant_que_l_index_ne_sert_pas_la_version(monkeypatch):
    m = _acceptance()
    journal: list = []
    attentes: list = []
    monkeypatch.setattr(m, "_sh_p", _faux_pip(2, NON_SERVIE, journal))
    monkeypatch.setattr(m.time, "sleep", attentes.append)
    m._p_install()
    assert m.R["paquet_install"]["etat"] == "PASS", m.R["paquet_install"]
    assert len(journal) == 3 and len(attentes) == 2


def test_paquet_install_ne_reessaie_pas_un_autre_echec(monkeypatch):
    m = _acceptance()
    journal: list = []
    attentes: list = []
    monkeypatch.setattr(m, "_sh_p", _faux_pip(9, "ERROR: Failed building wheel for truc", journal))
    monkeypatch.setattr(m.time, "sleep", attentes.append)
    m._p_install()
    assert m.R["paquet_install"]["etat"] == "FAIL"
    assert len(journal) == 1 and not attentes


def test_paquet_install_finit_par_echouer_si_la_version_ne_vient_jamais(monkeypatch):
    m = _acceptance()
    journal: list = []
    monkeypatch.setattr(m, "_sh_p", _faux_pip(99, NON_SERVIE, journal))
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    m._p_install()
    assert m.R["paquet_install"]["etat"] == "FAIL"
    assert 2 <= len(journal) <= 10, "réessai borné"


def _etape(debut: str) -> str:
    t = MIROIRS.read_text(encoding="utf-8")
    i = t.index("- name: %s" % debut)
    j = t.find("\n      - name:", i + 1)
    return t[i:j if j > 0 else len(t)]


def test_sourceforge_sonde_l_authentification_avant_le_push():
    e = _etape("SourceForge")
    assert "ssh -T" in e or "ssh -vv -T" in e, "sonde d'authentification absente"
    assert e.index("-T") < e.index("git -C src.git push"), "la sonde doit précéder le push"
    assert "Authenticated" in e and "Permission denied" in e, "la sonde doit DIRE l'issue de l'authentification"


def test_hugging_face_nettoie_le_jeton_dit_le_code_http_et_s_arrete_si_compte_illisible():
    e = _etape("Space Hugging Face")
    assert "tr -d '\\r\\n'" in e, "jeton non nettoyé des fins de ligne Windows"
    assert "%{http_code}" in e, "code HTTP de whoami non affiché"
    garde = e.index('if [ -z "$HF_USER" ]')
    assert garde < e.index("git -c http.extraHeader"), "un compte illisible doit arrêter AVANT clone/push"
    assert "echo hf >> manquants" in e[garde:garde + 400]
