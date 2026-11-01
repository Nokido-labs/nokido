"""NR -- chantier identites, phase 1 (GO owner 22/10) : inventaire MESURE des identites par canal et provenance.

Owner 22/10 : « chaque canal et chaque provenance doivent avoir leur identite et donc leur token, conforme RFC,
observabilite parfaite ». Defauts mesures le meme jour : boite agt_claude partagee Desktop/CLI (3 messages perdus),
CLAUDE_HEADLESS jamais authentifie (401 a chaque connexion, mailbox CLAUDE partagee). L'instrument croise registre,
coffre (booleen, jamais une valeur) et journal MCP ; il OBSERVE (observer avant d'enforcer) et DIT ce qu'il n'a pas lu.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_identites_audit as A  # noqa: E402

REGISTRE = {"agents": {
    "CLAUDE": {"ring": 1, "mailbox": "CLAUDE", "channel": "STDIO_CLAUDE"},
    "CLAUDE_HEADLESS": {"ring": 1, "mailbox": "CLAUDE", "channel": "HTTP_DIRECT"},
    "TRAY": {"ring": 2, "mailbox": "TRAY", "channel": "HTTP_DIRECT"},
    "PORTAIL": {"ring": 0, "mailbox": "PORTAIL", "jeton_direct": False},
}}


def _l(canal, outil, agent, ring, statut):
    return ('2026-10-22T13:58:17 | NetworkChannel.%s:%s | {"direction": "Direction.IN", "trace_id": "x", '
            '"agent": "%s", "ring": "%s", "in": "{\\"jsonrpc\\" | %s' % (canal, outil, agent, ring, statut))


JOURNAL = [
    _l("STDIO_CLAUDE", "run", "CLAUDE", 1, "OK"),
    _l("HTTP_DIRECT", "run", "CLAUDE", 1, "OK"),
    _l("HTTP_DIRECT", "UNAUTHORIZED", "CLAUDE_HEADLESS", -1, "ERR:401"),
    _l("HTTP_DIRECT", "UNAUTHORIZED", "CLAUDE_HEADLESS", -1, "ERR:401"),
    _l("HTTP_DIRECT", "hub", "TRAY", 3, "OK"),
    _l("HTTP_DIRECT", "hub", "INCONNU_X", 4, "OK"),
    "ligne illisible sans separateur",
]


def _audit(coffre=None):
    coffre = coffre or {"CLAUDE": True, "CLAUDE_HEADLESS": True, "TRAY": False}
    return A.auditer(REGISTRE, JOURNAL, lambda nom: coffre.get(nom))


def test_boite_partagee_par_deux_identites():
    r = _audit()
    assert r["boites_partagees"] == {"CLAUDE": ["CLAUDE", "CLAUDE_HEADLESS"]}


def test_identite_vue_sur_plusieurs_canaux_signale_des_provenances_melangees():
    r = _audit()
    assert r["identites_multi_canaux"] == {"CLAUDE": ["HTTP_DIRECT", "STDIO_CLAUDE"]}


def test_identite_jamais_authentifiee():
    r = _audit()
    assert r["jamais_authentifiees"] == ["CLAUDE_HEADLESS"]
    assert r["par_identite"]["CLAUDE_HEADLESS"]["refus_401"] == 2


def test_jeton_absent_au_coffre_et_inconnu_distingues():
    r = _audit({"CLAUDE": True, "CLAUDE_HEADLESS": None, "TRAY": False})
    assert r["sans_jeton_au_coffre"] == ["TRAY"]
    assert r["jeton_illisible"] == ["CLAUDE_HEADLESS"]   # UNKNOWN n'est pas NO


def test_identite_par_delegation_seulement_n_a_pas_de_jeton_attendu():
    assert "PORTAIL" not in _audit()["sans_jeton_au_coffre"]


def test_identite_vue_hors_registre_et_ring_contredit():
    r = _audit()
    assert r["hors_registre"] == ["INCONNU_X"]
    assert r["rings_contredits"] == {"TRAY": {"registre": 2, "observes": [3]}}


def test_les_lignes_illisibles_sont_comptees_pas_ignorees():
    assert _audit()["lignes_illisibles"] == 1


def test_le_point_d_entree_cli_rend_un_rapport_json(tmp_path):
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps(REGISTRE), encoding="utf-8")
    jour = tmp_path / "audit.log"
    jour.write_text("\n".join(JOURNAL) + "\n", encoding="utf-8")
    sortie = tmp_path / "r.json"
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_identites_audit.py"), "--registre", str(reg),
                        "--journal", str(jour), "--sans-coffre", "--sortie", str(sortie)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    assert p.returncode == 0, p.stderr
    r = json.loads(sortie.read_text(encoding="utf-8"))
    assert r["jamais_authentifiees"] == ["CLAUDE_HEADLESS"] and r["coffre"] == "NON_LU"
