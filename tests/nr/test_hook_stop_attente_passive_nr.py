"""NR -- un tour ne se termine plus sur une ATTENTE PASSIVE (consigne owner 09/10, 13/10, 14/10 ; 3e recidive).

Les cas « bloque » sont les fins de tour REELLES de la nuit du 13 au 14/10, recopiees mot pour mot dans leur partie
fautive. Les cas « laisse passer » sont des rendus de main legitimes : geste owner, decision qui lui revient,
question posee. Le dernier test passe par le point d'entree REEL (`__main__`, stdin JSON, transcript sur disque).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import hook_stop_attente_passive as H  # noqa: E402

FAUTIFS = [
    "Le parcours paquet complet (`job_41abcef736dd`) tourne toujours ; je reprends dès son verdict.",
    "La mesure locale tourne encore (je serai prévenu à la fin). Voici le point sur ce qui dépend de toi.",
    "En attendant le verdict, rien d'autre à signaler.",
]
LEGITIMES = [
    "Le job tourne toujours. Il te reste à coller le secret puis cliquer « Add webhook ».",
    "La CI tourne encore ; le choix entre les deux options te revient.",
    "Le job tourne toujours. Je l'applique ?",
    "Lot clos, commits 21e1f907b et ca3e85314 ; aucun job en cours.",
]


@pytest.mark.parametrize("texte", FAUTIFS)
def test_une_attente_passive_bloque_la_fin_du_tour(texte):
    raison = H.decider(texte, deja_relance=False)
    assert raison and "backlog" in raison


@pytest.mark.parametrize("texte", LEGITIMES)
def test_un_rendu_de_main_legitime_passe(texte):
    assert H.decider(texte, deja_relance=False) is None


def test_jamais_de_boucle_une_seule_relance():
    assert H.decider(FAUTIFS[0], deja_relance=True) is None


def _transcript(tmp_path, owner, agent):
    lignes = [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": owner}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": agent}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
    ]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
    return p


def test_point_d_entree_reel_bloque_et_journalise(tmp_path, monkeypatch):
    t = _transcript(tmp_path, "ok fait, vérifie", FAUTIFS[0])
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "hook_stop_attente_passive.py")],
                       input=json.dumps({"transcript_path": str(t), "stop_hook_active": False}),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert r.returncode == 0
    assert json.loads(r.stdout)["decision"] == "block"


def test_la_raison_arrive_intacte_quel_que_soit_l_encodage_du_tube(tmp_path):
    """Mesure du 14/10, premier tir reel : « » arrivaient en U+FFFD. Sous Windows, stdout d'un tube est en cp1252 ;
    Claude Code lit de l'UTF-8. On lit donc les OCTETS : un JSON en ASCII pur passe quel que soit l'encodage."""
    t = _transcript(tmp_path, "ok fait, vérifie", FAUTIFS[0])
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "hook_stop_attente_passive.py")],
                       input=json.dumps({"transcript_path": str(t), "stop_hook_active": False}).encode("utf-8"),
                       capture_output=True, timeout=30)
    assert r.returncode == 0
    brut = r.stdout.decode("ascii")             # UnicodeDecodeError = un octet non ASCII est parti dans le tube
    assert "«" in json.loads(brut)["reason"]


def test_l_ancien_tour_ne_contamine_pas_le_dernier(tmp_path):
    """Une parole de l'owner en BLOCS remet le compteur a zero : seul le dernier message de l'agent est juge."""
    lignes = [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": FAUTIFS[0]}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "continue"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": LEGITIMES[3]}]}},
    ]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
    assert H.decider(H.dernier_message(p), deja_relance=False) is None
