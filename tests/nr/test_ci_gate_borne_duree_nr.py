"""Non-regression : un gate de CI a une BORNE de duree, et la dit.

DEFAUT MESURE le 2026-09-08, en instruisant « la CI est failed sur GitHub ».

Ce n'etait PAS un echec : les cinq derniers runs sont `cancelled`, pas `failure`,
et `cancelled` ne veut pas dire la meme chose. Le job `gates` demarre a 21:09:01 et
s'arrete a 21:29:02 -- vingt minutes PILE, soit le `timeout-minutes: 20` declare
dans `.github/workflows/ci-selfhosted.yml`. Une BORNE atteinte, presentee comme une
annulation.

⚠ CORRECTION DU 2026-09-09 -- MA PREMIERE MESURE ETAIT FAUSSE, et le dire fait
partie du test. J'ai d'abord attribue les 18 minutes a `pip-audit`. La ligne
`→ OK (rc=0, 1120.5 s)` est en realite celle de **`pytest (suite pure)`** ;
`pip-audit` finit en `UNKNOWN` presque aussitot, faute d'egress. Mon extraction par
regex avait lu des EN-TETES DE FIXTURE comme des en-tetes de gate : les blocs
`── pip-audit ──` apparaissent DANS la sortie de pytest, parce qu'un NR teste la
classification de ce gate. Meme defaut que « un instrument ne lit jamais son propre
vocabulaire », applique au JOURNAL.

Ce que la mesure dit vraiment : CI totale 22,0 min AVANT la borne, 22,3 min APRES --
donc la borne n'a rien change au budget, et ne pouvait pas. Le budget est mange par
la suite pure (18,7 min) contre 20 min autorisees par le workflow.

Le defaut general reste VRAI et vaut d'etre verrouille : **`_run` n'avait AUCUNE
borne de duree**. Un gate pouvait donc pendre jusqu'a ce qu'une borne EXTERNE le
coupe -- et une borne externe ne dit rien, elle annule. Une borne interne, elle,
NOMME ce qui s'est passe. C'est une dette comblee, PREVENTIVE : elle ne corrige pas
le depassement observe, elle empeche la prochaine attente sans fin.

INVARIANTS :
  - un depassement de borne vaut **NON MESURE**, jamais ECHEC : un gate coupe n'a
    pas trouve de probleme, il n'a pas fini de regarder. Les confondre enverrait
    chercher un bug qui n'existe pas.
  - la borne DIT combien : le motif porte la valeur, pas seulement le fait.
  - un gate qui finit avant sa borne n'est pas affecte.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (via ci_local._run) (l.54)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "tools", RACINE / "app"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import ci_local as ci  # noqa: E402


def test_un_gate_qui_depasse_sa_borne_est_NON_MESURE(monkeypatch, capsys):
    """Chemin REEL : un vrai sous-processus qui dort plus que sa borne."""
    monkeypatch.setattr(ci, "_INCONCLUS", [])
    nom, ok = ci._run("gate_qui_pend",
                      [sys.executable, "-c", "import time; time.sleep(30)"],
                      blocking=True, timeout_s=1.5)
    sortie = capsys.readouterr().out
    assert ok is True, ("un depassement de borne a ete compte comme un ECHEC du code : "
                        "il envoie chercher un bug qui n'existe pas")
    assert ci._INCONCLUS and ci._INCONCLUS[-1][0] == "gate_qui_pend", (
        f"le gate coupe n'est pas declare non mesure : {ci._INCONCLUS}")
    assert "UNKNOWN" in sortie, f"le verdict ne dit pas l'absence de mesure : {sortie!r}"


def test_la_borne_DIT_COMBIEN(monkeypatch, capsys):
    """Une borne doit dire combien, pas seulement « trop »."""
    monkeypatch.setattr(ci, "_INCONCLUS", [])
    ci._run("gate_qui_pend2", [sys.executable, "-c", "import time; time.sleep(30)"],
            blocking=False, timeout_s=1.5)
    sortie = capsys.readouterr().out
    assert "1" in sortie and "borne" in sortie.lower(), (
        f"le motif ne nomme pas la borne atteinte : {sortie!r}")


def test_un_gate_RAPIDE_n_est_pas_affecte(monkeypatch, capsys):
    monkeypatch.setattr(ci, "_INCONCLUS", [])
    nom, ok = ci._run("gate_rapide", [sys.executable, "-c", "print('fini')"],
                      blocking=True, timeout_s=60)
    sortie = capsys.readouterr().out
    assert ok is True and not ci._INCONCLUS, (
        "un gate termine dans les temps a ete declare non mesure")
    assert "OK (rc=0" in sortie, f"verdict inattendu : {sortie!r}"


def test_le_gate_pip_audit_PORTE_une_borne():
    """Le gate qui a fait deborder le budget doit desormais etre borne, sinon la
    correction ne tient qu'a la memoire de celui qui l'a ecrite."""
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    i = src.find('_run("pip-audit"')
    assert i > 0, "le gate pip-audit a change de forme : relire ce test avant de le croire"
    bloc = src[i:i + 900]
    assert "timeout_s" in bloc, (
        "pip-audit n'a pas de borne : il peut a nouveau consommer 18 min des 20 du "
        "budget GitHub et faire annuler le run")
