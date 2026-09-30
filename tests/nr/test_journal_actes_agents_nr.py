"""NR -- ce qu'un agent EXECUTE par le hub est lisible apres coup (journal des actes).

MESURE du 2026-09-25 : OPENCODE (ring 3) a appele `run` a 12:04:05 et 12:11:35 ; l'audit MCP
n'en garde que `"in": "{\\"method\\": \\"tool...` -- net_log coupe la charge a 200 caracteres
(l'enveloppe JSON-RPC, AVANT les arguments), puis forge_mcp_security.audit coupe chaque valeur a
80 et la ligne a 120. execution_traces herite de la meme coupe. La commande exacte d'un agent
etait donc ILLISIBLE partout. Le format de l'audit (lu par 4 consommateurs) ne change pas : un
journal des ACTES, au meme point de passage, garde l'essentiel lisible -- caviarde, borne, et la
troncature DITE.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_network_logger as nl  # noqa: E402

# Forme REELLE (motif Groq : gsk_ + 50 car. et plus). Mesure 2026-09-25 : une clef hors forme (36 car.)
# ne declenche aucun motif et fait croire a une fuite -- ou a une protection -- qui n'existe pas.
CLE_GROQ_FORME_REELLE = "gsk_" + "Zq3kT8vLm2Xp9Rw4Yb6Nc1Hd5Fg7Js0Ae2Ui8Qo4Pe6Wr1Ty3Uh9Ij"


@pytest.fixture
def journal(monkeypatch, tmp_path):
    chemin = tmp_path / "actes_agents.jsonl"
    monkeypatch.setattr(nl, "_JOURNAL_ACTES", chemin, raising=False)
    monkeypatch.setattr(nl, "_get_audit", lambda: None)  # jamais le vrai mcp_audit.log
    return chemin


def _appel(outil: str, arguments: dict) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                       "params": {"name": outil, "arguments": arguments}})


def _lignes(chemin: Path) -> list[dict]:
    return [json.loads(l) for l in chemin.read_text(encoding="utf-8").splitlines()] if chemin.exists() else []


def test_un_run_d_agent_est_lisible(journal):
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.IN, tool="run", agent="OPENCODE",
               ring=3, payload_in=_appel("run", {"action": "shell", "code": "whoami"}))
    [acte] = _lignes(journal)
    assert (acte["agent"], acte["ring"], acte["outil"], acte["action"]) == ("OPENCODE", 3, "run", "shell")
    assert "whoami" in acte["extrait"]


def test_une_ecriture_gouvernee_dit_le_chemin(journal):
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.IN, tool="governed_edit", agent="OPENCODE",
               ring=3, payload_in=_appel("governed_edit", {"path": "sandbox/essai.txt", "content": "test"}))
    [acte] = _lignes(journal)
    assert "sandbox/essai.txt" in acte["extrait"]


def test_les_secrets_sont_caviardes(journal):
    cle = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.IN, tool="run", agent="OPENCODE", ring=3,
               payload_in=_appel("run", {"action": "shell", "code": "set GROQ_API_KEY=" + cle}))
    [acte] = _lignes(journal)
    assert cle not in json.dumps(acte)


def test_la_troncature_est_dite(journal):
    code = "echo x\n" * 2000
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.IN, tool="run", agent="OPENCODE", ring=3,
               payload_in=_appel("run", {"action": "python", "code": code}))
    [acte] = _lignes(journal)
    assert len(acte["extrait"]) <= nl.EXTRAIT_ACTE_MAX
    assert acte["longueur_totale"] > nl.EXTRAIT_ACTE_MAX and acte["tronque"] is True


def test_charge_coupee_en_amont_ou_arguments_nus(journal):
    """MESURE runtime 2026-09-25 (hub relance) : une entree CLAUDE `run` sortait avec un extrait
    `{}`. Les appelants REELS ne passent jamais l'enveloppe complete : le serveur stdio
    (log_stdio_in) passe les arguments NUS coupes a 400 car., le hub HTTP l'enveloppe JSON-RPC
    coupee a 800 -- une commande longue arrive en JSON INCOMPLET. Le journal ne doit ni rendre
    `{}` ni perdre l'action : il garde le texte recu, caviarde, et DIT qu'il n'a pas pu l'analyser."""
    nl.log_stdio_in("run", "CLAUDE", 1, {"action": "shell", "code": "dir"})
    longue = "print('x')\n" * 100
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.IN, tool="run", agent="OPENCODE", ring=3,
               payload_in=_appel("run", {"action": "python", "code": longue})[:800])
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.IN, tool="run", agent="CLAUDE", ring=1,
               payload_in=str({"action": "python", "code": "print(1)"}))
    nus, coupee, repr_py = _lignes(journal)
    assert "dir" in nus["extrait"] and nus["action"] == "shell"
    assert "print('x')" in coupee["extrait"] and coupee["action"] == "python"
    assert coupee["forme"] == "TEXTE_NON_ANALYSABLE"
    assert "print(1)" in repr_py["extrait"] and repr_py["action"] == "python"


def test_la_reponse_du_hub_est_lisible(journal):
    """MESURE 2026-09-25 : OPENCODE appelle `run` shell whoami a 13:47:39, le hub repond en 48,5 ms
    -- et le TEXTE de sa reponse n'est lisible nulle part (audit coupe a 120 car., journal des actes
    limite a l'appel). L'owner demandait « commande + reponse ». La reponse d'un outil qui AGIT
    s'ecrit, caviardee et bornee, a cote de l'appel."""
    cle = CLE_GROQ_FORME_REELLE
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.OUT, tool="run", agent="OPENCODE", ring=3,
               latency_ms=48.5, status="OK", payload_in=json.dumps({"action": "shell", "commands": ["whoami"]}),
               payload_out="RBAC: ring 3 ne peut pas executer shell -- " + cle)
    [rep] = _lignes(journal)
    assert (rep["sens"], rep["agent"], rep["outil"], rep["latence_ms"]) == ("REPONSE", "OPENCODE", "run", 48.5)
    assert "RBAC: ring 3" in rep["reponse"] and cle not in json.dumps(rep)


def test_l_apercu_d_audit_ne_porte_pas_de_clef(journal, monkeypatch):
    """MESURE 2026-09-25 : `redact_for_log` n'applique que les motifs d'INFRASTRUCTURE (IP, chemins,
    base64...) ; une clef `gsk_` a la forme reelle le traversait intacte. `net_log` s'en servait pour
    les apercus in/out de mcp_audit.log comme pour le journal des actes."""
    vus = []
    monkeypatch.setattr(nl, "_get_audit", lambda: (lambda cle_outil, args, statut: vus.append(args)))
    cle = CLE_GROQ_FORME_REELLE
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.IN, tool="run", agent="OPENCODE", ring=3,
               payload_in=_appel("run", {"action": "shell", "code": "set K=" + cle}))
    assert vus and cle not in json.dumps(vus)
    assert cle not in json.dumps(_lignes(journal))


def test_l_historique_et_le_flux_sse_ne_portent_pas_de_clef(journal, monkeypatch):
    """MESURE 2026-09-25 : l'evenement que `net_log` range dans `_HISTORY` (servi par
    `net_history` -> web_hub app.py:1548/1703) et diffuse en SSE portait `payload_in[:500]` BRUT."""
    monkeypatch.setattr(nl, "_HISTORY", [], raising=False)
    cle = CLE_GROQ_FORME_REELLE
    ev = nl.net_log(nl.NetworkChannel.CLOUD, nl.Direction.OUT, tool="ask", agent="CLAUDE", ring=1,
                    payload_in="message avec " + cle, payload_out="reponse " + cle)
    assert cle not in json.dumps(ev) and cle not in json.dumps(nl.net_history(5))
    # Clef A CHEVAL sur la borne de 500 car. : couper avant de caviarder en laisserait un morceau
    # trop court pour son motif -- donc en clair.
    ev = nl.net_log(nl.NetworkChannel.CLOUD, nl.Direction.OUT, tool="ask", agent="CLAUDE", ring=1,
                    payload_in="x " * 240 + cle)
    assert cle[:20] not in json.dumps(ev)


def test_une_lecture_ne_charge_pas_le_journal(journal):
    nl.net_log(nl.NetworkChannel.HTTP_DIRECT, nl.Direction.IN, tool="read", agent="OPENCODE", ring=3,
               payload_in=_appel("read", {"action": "file", "path": "README.md"}))
    assert _lignes(journal) == []
