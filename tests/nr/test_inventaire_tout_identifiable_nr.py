# -*- coding: utf-8 -*-
"""NR (owner 19/10 : « deux processus Python d'identite illisible, ce n'est pas acceptable, TOUT doit etre
identifiable dans Nokido ») -- l'inventaire identifie chaque processus d'execution par l'organe qui SAIT, et ne se
laisse pas tromper par un pid RECYCLE.

Mesure 19/10 : 365 cmdline illisibles sur 372 processus depuis un compte client ; ma sonde psutil a rendu « deux python
non identifiables » alors que le corps a des registres : superviseur (pid -> service), fiches de jobs
(sandbox/jobs/*.json : pid + started), battements (*.heartbeat : pid + ts), parente. tools/forge_process_inventory ne
consultait que le superviseur et le parent direct. PIEGE paye le meme soir : le pid 1988 (cree 21:50) « matchait »
job_2f64b597eeb7 -- un job du 10/09, termine : pid RECYCLE (l'egalite de pid ment, constitution). Contrat de
`identifier_processus(vivants, pid_service, jobs, battements, maintenant)` :
  1. cascade de PREUVES : superviseur -> job -> battement -> parente (ancetre identifie, plusieurs niveaux) ;
  2. une fiche de job n'identifie un pid que si le job a demarre a moins de 120 s de la creation du processus ; un
     battement, que s'il est FRAIS (<= 900 s) et posterieur a la creation -- sinon pid recycle, preuve ecartee ;
  3. chaque processus d'execution (python, opencode, deno, node, llama, ollama, qdrant...) recoit une identite et sa
     preuve, ou figure dans `non_identifies` avec ses attributs lisibles (nom, ppid, nom du parent) ;
  4. un processus hors runtimes (svchost...) n'est pas exige.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_process_inventory as inv  # noqa: E402

T = 1_000_000.0
VIVANTS = {
    100: {"nom": "python.exe", "ppid": 1, "cree": T - 3600},          # service supervise
    101: {"nom": "python.exe", "ppid": 100, "cree": T - 3000},        # enfant
    102: {"nom": "cmd.exe", "ppid": 101, "cree": T - 2000},
    103: {"nom": "python.exe", "ppid": 102, "cree": T - 1000},        # descendant au 3e niveau
    200: {"nom": "python.exe", "ppid": 50, "cree": T - 600},          # job run_job (demarre 5 s avant)
    201: {"nom": "python.exe", "ppid": 51, "cree": T - 600},          # pid RECYCLE : la fiche date de 40 jours
    300: {"nom": "python.exe", "ppid": 60, "cree": T - 500},          # organe a battement frais
    301: {"nom": "python.exe", "ppid": 61, "cree": T - 500},          # battement PERIME
    400: {"nom": "opencode.exe", "ppid": 70, "cree": T - 100},        # personne ne le revendique
    500: {"nom": "svchost.exe", "ppid": 4, "cree": T - 9000},
}
JOBS = {200: {"identite": "job_abc (tools/ci_local.py)", "debut": T - 605},
        201: {"identite": "job_vieux (tools/ci_local.py)", "debut": T - 40 * 86400}}
BATTEMENTS = {300: {"identite": "cardiac_node.heartbeat", "ts": T - 30},
              301: {"identite": "vieux.heartbeat", "ts": T - 7200}}


def _identifier():
    return inv.identifier_processus(VIVANTS, {100: "NokidoX"}, JOBS, BATTEMENTS, maintenant=T)


def test_cascade_de_preuves():
    ids, _ = _identifier()
    assert ids[100] == {"identite": "NokidoX", "preuve": "superviseur"}
    assert ids[200]["preuve"] == "job" and "job_abc" in ids[200]["identite"]
    assert ids[300]["preuve"] == "battement" and "cardiac_node" in ids[300]["identite"]


def test_un_pid_recycle_ou_un_battement_perime_n_identifie_pas():
    ids, non = _identifier()
    assert 201 not in ids and 301 not in ids
    assert {201, 301} <= {n["pid"] for n in non}


def test_la_parente_remonte_plusieurs_niveaux():
    ids, _ = _identifier()
    assert ids[103]["preuve"] == "parente" and "NokidoX" in ids[103]["identite"]
    assert ids[101]["preuve"] == "parente"


def test_les_non_identifies_sont_listes_avec_leurs_attributs():
    ids, non = _identifier()
    assert 400 not in ids
    n400 = [n for n in non if n["pid"] == 400][0]
    assert n400["nom"] == "opencode.exe" and n400["ppid"] == 70


def test_le_superviseur_et_les_clients_sont_nommes():
    """Mesure 19/10 22:41 (inventaire reel) : 94 runtimes identifies, 4 non -- dont deno.exe :8765 enfant de nssm.exe
    (le SUPERVISEUR LaForge-Master, absent de son propre statut) et un python enfant de bash.exe (Monitor du client
    Claude Code, hors corps). Le nom du parent est une preuve ; l'inconnu reste inconnu."""
    vivants = {10: {"nom": "deno.exe", "ppid": 9, "cree": T}, 9: {"nom": "nssm.exe", "ppid": 1, "cree": T},
               20: {"nom": "python.exe", "ppid": 19, "cree": T}, 19: {"nom": "bash.exe", "ppid": 1, "cree": T},
               30: {"nom": "python.exe", "ppid": 29, "cree": T}}
    ids, non = inv.identifier_processus(vivants, {}, {}, {}, maintenant=T)
    assert ids[10]["preuve"] == "parent" and "superviseur" in ids[10]["identite"]
    assert ids[20]["preuve"] == "parent" and "client" in ids[20]["identite"]
    assert [n["pid"] for n in non] == [30]


def test_collect_ne_cite_plus_en_inconnu_un_port_identifie(monkeypatch):
    """Inventaire reel 19/10 22:42 : `inconnus` (par port) citait encore :8791, :8793, :4096 et :8765, pourtant
    identifies par la cascade. Un port n'est inconnu que si son processus n'a AUCUNE identite."""
    monkeypatch.setattr(inv, "_declares", lambda *a, **k: {"NokidoX": {"status": "running", "pid": 100}})
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_vivants", lambda: ({100: {"nom": "python.exe", "ppid": 1, "cree": T, "rss_mo": 1, "cmd": None},
                                                    101: {"nom": "python.exe", "ppid": 100, "cree": T, "rss_mo": 1, "cmd": None},
                                                    102: {"nom": "python.exe", "ppid": 101, "cree": T, "rss_mo": 1, "cmd": None},
                                                    400: {"nom": "opencode.exe", "ppid": 70, "cree": T, "rss_mo": 1, "cmd": None}}, 4))
    monkeypatch.setattr(inv, "_ports", lambda: {8791: 102, 4096: 400})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: {})
    r = inv.collect()
    assert [i["port"] for i in r["inconnus"]] == [4096], r["inconnus"]


def test_un_processus_systeme_n_est_pas_exige():
    ids, non = _identifier()
    assert 500 not in ids and all(n["pid"] != 500 for n in non)
