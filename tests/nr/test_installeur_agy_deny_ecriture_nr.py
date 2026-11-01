"""NR -- l'installeur pose chez AGY le deny de l'ECRITURE native, prouve en reel le 24/10.

Decision owner « mesurer puis restreindre ». Essai 395e465f3 : sous deny command(*), le write_file natif d'AGY ecrivait
encore hors du hub. Essai 3ece1d452 : avec deny write_file(*) et edit_file(*), l'ecriture native est refusee
(« Matches user-configured deny rule »), governed_edit (MCP du hub) passe et la lecture native reste permise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_connect_clients as C  # noqa: E402


def test_le_profil_agy_n_ecrit_que_dans_les_worktrees_de_tache():
    # 30/10 (decision owner, remplace celle du 24/10) : AGY tourne DANS son worktree de tache (3db296d96) ; le refus
    # global d'ecriture native l'empechait d'ecrire son travail (« ecriture bloquee... permissions natives »), et
    # governed_edit ecrit dans le depot PRINCIPAL, hors worktree. Ecriture native bornee aux worktrees de tache ;
    # command(*) reste refuse ; aucune ecriture accordee ailleurs.
    new, _ = C.govern_config("agy", json.dumps({"theme": "dark"}))
    p = json.loads(new)["permissions"]
    assert "command(*)" in p["deny"]
    assert "write_file(*)" not in p["deny"] and "edit_file(*)" not in p["deny"]
    ecritures = [r for r in p["allow"] if r.startswith(("write_file(", "edit_file("))]
    assert ecritures and all("nokido_worktrees" in r and "taches" in r for r in ecritures), ecritures


def test_la_lecture_native_et_le_hub_restent_permis():
    new, _ = C.govern_config("agy", json.dumps({}))
    p = json.loads(new)["permissions"]
    assert not any(r.startswith("read_file") for r in p["deny"])
    assert "mcp(laforge-sovereign-hub/*)" in p["allow"]


def test_lecture_accordee_aux_seuls_worktrees():
    # 30/10 (accord owner) : en --print, agy REFUSE toute lecture qui demanderait une permission (stderr : « headless
    # mode cannot prompt ... auto-denied. Add an allow-rule ... read_file(<target>) ») -- 5 taches de code mortes.
    # Contrat : LECTURE seule, bornee a nokido_worktrees ; jamais d'ecriture ni le depot principal.
    new, _ = C.govern_config("agy", json.dumps({}))
    p = json.loads(new)["permissions"]
    lectures = [r for r in p["allow"] if r.startswith("read_file(")]
    assert sum("nokido_worktrees" in r for r in lectures) == 1, lectures
    assert not any(r.startswith("command") for r in p["allow"])
    # ecriture : uniquement les worktrees de tache (decision owner 30/10)
    assert all("taches" in r for r in p["allow"] if r.startswith(("write_file", "edit_file")))
    assert not any(r.rstrip(")").rstrip("\\*/").endswith("Nokido") for r in lectures)


def test_regles_heritees_lisibles_fichier_par_fichier():
    # 30/10 : GEMINI.md (worktree ET ~/.gemini global, pose par forge_client_bootstrap) importe en ABSOLU
    # Nokido/RULES_SHARED.md -- hors worktree, lecture refusee au DEMARRAGE d'agy (6 taches mortes). Contrat : ces
    # fichiers-la, nommes un par un, en lecture ; jamais un joker sur le depot principal.
    new, _ = C.govern_config("agy", json.dumps({}))
    lectures = [r for r in json.loads(new)["permissions"]["allow"] if r.startswith("read_file(")]
    hors_wt = [r for r in lectures if "nokido_worktrees" not in r]
    assert any(r.endswith("RULES_SHARED.md)") for r in hors_wt), hors_wt
    assert all("*" not in r for r in hors_wt), hors_wt
