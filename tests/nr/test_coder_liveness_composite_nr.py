# -*- coding: utf-8 -*-
"""NR — A0-2 : la liveness du coder repose sur des preuves SEPAREES.

DEFAUT MESURE LE 2026-09-05. `llamacpp_native_status()` sondait par PowerShell, or
`_powershell` rend `rc=-1` depuis le compte du hub : la sonde tombait TOUJOURS sur
son defaut `{running: False, port_listening: False, ram_gb: 0, pid: 0}` —
indistinguable d'un coder mort. Elle n'a donc jamais rien mesure dans ce contexte,
et `arbitrer_pression` lisait « pas de coder » a chaque appel.

Deux confusions s'y ajoutaient :

- `running` designe l'etat du SERVICE NSSM, pas celui du coder. Sous le compte
  sandbox, `Get-Service` se voit REFUSER l'acces et `-ErrorAction SilentlyContinue`
  avalait le refus : RUNNING, STOPPED et INVISIBLE-PAR-ACL s'ecrasaient en un seul
  `False`. Mesure : « service INTROUVABLE » depuis le sandbox, `Stopped` depuis
  SYSTEM — la sonde rendait un resultat DEPENDANT DU COMPTE sans le dire.
- l'appelant compensait par `running or port_listening`, c'est-a-dire un OR entre
  une preuve de GESTION et une preuve de TRANSPORT, pour en tirer une conclusion
  qu'aucune des deux ne portait.

Le contrat tenu ici : PROCESS / PORT / HTTP / SERVICE sont etablis SEPAREMENT,
aucune preuve ne se deduit d'une autre, et le verdict n'est `VIVANT` que si la
combinaison requise est demontree — sinon `INCERTAIN`, avec sa raison.

Portee du risque, mesuree : `coder_up` n'autorise qu'une chose dans
`arbitrer_pression` — la branche `yield_coder`. Un faux negatif ne provoque donc
aucune eviction abusive : il EMPECHE une eviction legitime, et l'embedder affame
n'est jamais servi. C'est pourquoi `INCERTAIN` doit se lire `False` cote `coder_up`.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

rm = pytest.importorskip("forge_resource_manager")


def _monter(monkeypatch, service, port, pid, process, ram, http):
    monkeypatch.setattr(rm, "_preuve_service_coder", lambda: (service, ""))
    monkeypatch.setattr(rm, "_preuve_port_coder", lambda: (port, pid))
    monkeypatch.setattr(rm, "_preuve_process_coder", lambda *_a: (process, ram))
    monkeypatch.setattr(rm, "_sonde_http_coder", lambda: http)


def test_port_et_process_etablissent_vivant(monkeypatch):
    _monter(monkeypatch, "STOPPED", "OUI", 42, "OUI", 4.65, "OUI")
    s = rm.llamacpp_native_status()
    assert s["verdict"] == "VIVANT"
    assert s["ram_gb"] == 4.65 and s["pid"] == 42


def test_service_stopped_ne_tue_pas_un_coder_qui_sert(monkeypatch):
    """Le reveil on-demand lance le binaire HORS supervision : c'est le cas NOMINAL."""
    _monter(monkeypatch, "STOPPED", "OUI", 42, "OUI", 4.65, "INCONNU")
    assert rm.llamacpp_native_status()["verdict"] == "VIVANT"


def test_service_inconnu_ne_determine_pas_le_verdict(monkeypatch):
    """AccessDenied sur le service ne doit ni tuer ni ressusciter le coder."""
    _monter(monkeypatch, "INCONNU", "NON", 0, "NON", 0.0, "INCONNU")
    s = rm.llamacpp_native_status()
    assert s["verdict"] == "MORT", "port NON + process NON suffisent a conclure"
    _monter(monkeypatch, "INCONNU", "OUI", 7, "OUI", 1.0, "INCONNU")
    assert rm.llamacpp_native_status()["verdict"] == "VIVANT"


def test_preuves_partielles_donnent_incertain(monkeypatch):
    """Le cas dangereux : le port repond mais le porteur est illisible."""
    _monter(monkeypatch, "INCONNU", "OUI", 0, "INCONNU", 0.0, "INCONNU")
    s = rm.llamacpp_native_status()
    assert s["verdict"] == "INCERTAIN"
    assert "port=OUI" in s["raison"] and "process=INCONNU" in s["raison"]


def test_port_inconnu_n_est_jamais_une_mort(monkeypatch):
    """Enumeration refusee != aucun port. UNKNOWN n'est pas NO."""
    _monter(monkeypatch, "INCONNU", "INCONNU", 0, "INCONNU", 0.0, "INCONNU")
    assert rm.llamacpp_native_status()["verdict"] == "INCERTAIN"


def test_running_garde_le_sens_du_service(monkeypatch):
    """`running` ne doit PAS devenir un alias de `verdict` : deux questions distinctes."""
    _monter(monkeypatch, "STOPPED", "OUI", 42, "OUI", 4.65, "OUI")
    s = rm.llamacpp_native_status()
    assert s["running"] is False and s["verdict"] == "VIVANT"
    _monter(monkeypatch, "RUNNING", "NON", 0, "NON", 0.0, "INCONNU")
    s = rm.llamacpp_native_status()
    assert s["running"] is True and s["verdict"] == "MORT"


def test_chaque_preuve_est_rendue_separement(monkeypatch):
    _monter(monkeypatch, "STOPPED", "OUI", 42, "OUI", 4.65, "OUI")
    s = rm.llamacpp_native_status()
    for clef in ("service", "port", "process", "http", "verdict", "raison"):
        assert clef in s, "preuve %s absente : le contrat A0-2 n'est plus tenu" % clef


def test_la_sonde_ne_passe_plus_par_powershell():
    """La sonde tombait toujours sur son defaut, PowerShell rendant rc=-1 ici.

    Verifie par AST les APPELS, jamais le texte : une premiere version cherchait la
    chaine dans la source et se declenchait sur le COMMENTAIRE qui explique
    justement pourquoi ce chemin est abandonne — vert avant l'explication, rouge
    apres, sans qu'une ligne de comportement change. C'est le piege de l'instrument
    qui mesure son propre vocabulaire, deja paye le 2026-09-04.
    """
    import ast
    import inspect
    import textwrap

    arbre = ast.parse(textwrap.dedent(inspect.getsource(rm.llamacpp_native_status)))
    appels = {getattr(n.func, "id", "") or getattr(n.func, "attr", "")
              for n in ast.walk(arbre) if isinstance(n, ast.Call)}
    assert "_powershell" not in appels, \
        "la sonde rappelle PowerShell, indisponible depuis le compte du hub"
    assert {"_preuve_port_coder", "_preuve_process_coder"} <= appels, \
        "les preuves independantes ne sont plus appelees"
